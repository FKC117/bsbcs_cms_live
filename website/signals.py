"""Django signals for the website app.

Handles post-save operations like sending approval/rejection emails
when a Member's approval_status changes.
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
from .models import Member
from registration.tasks import send_email_task, send_sms_task
from registration.models import EmailAuditLog
from registration.sms import build_membership_approval_sms, build_membership_rejection_sms, build_membership_submission_sms
import logging

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Member)
def pre_save_member(sender, instance, **kwargs):
    """
    Store the original approval_status and active status on the instance 
    to detect changes during post_save.
    """
    if not instance.id:
        instance._original_approval_status = None
        instance._original_active_status = False
    else:
        try:
            # We want a fresh copy from the DB to see the CURRENT state
            original = Member.objects.get(id=instance.id)
            instance._original_approval_status = original.approval_status
            instance._original_active_status = original.is_active_member
        except Member.DoesNotExist:
            instance._original_approval_status = None
            instance._original_active_status = False



@receiver(post_save, sender=Member)
def send_member_approval_email(sender, instance, created, update_fields, **kwargs):
    """Send approval/rejection email to user when Member approval_status changes.
    
    Listens for Member.post_save signal. If approval_status is approved or rejected,
    sends an appropriate email to the user's profile email address.
    
    Args:
        sender: The Member model class
        instance: The Member instance being saved
        created: Boolean indicating if this is a new instance
        update_fields: Set of field names being updated (None if all fields)
        **kwargs: Additional signal kwargs
    """
    
    # Only process if approval_status field was actually updated or update_fields is None (Admin save)
    # We check if it changed versus our pre_save tracker
    original_status = getattr(instance, '_original_approval_status', None)
    original_active_status = getattr(instance, '_original_active_status', False)

    if instance.user_profile and instance.is_active_member and not original_active_status:
        try:
            from .utils_membership import process_pending_event_intents
            process_pending_event_intents(instance)
        except Exception as e:
            logger.error(f"[MEMBER SIGNAL] Failed to process event intents for {instance}: {str(e)}", exc_info=True)

    if instance.approval_status == original_status:
        logger.info(f"[MEMBER SIGNAL] Member {instance} updated but status '{instance.approval_status}' hasn't changed. Skipping email.")
        return

    logger.info(f"[MEMBER SIGNAL] Member status change detected: {original_status} -> {instance.approval_status}")
    
    logger.info(f"[MEMBER SIGNAL] Member updated: {instance}, status={instance.approval_status}, update_fields={update_fields}")
    
    # Check if user_profile exists
    if not instance.user_profile:
        logger.warning(f"[MEMBER SIGNAL] Member {instance} has no user_profile, cannot send email")
        return

    user_email = instance.user_profile.email
    user_name = instance.user_profile.name
    
    # Only send emails for approved or rejected status
    if instance.approval_status == 'approved':
        # NEW CHECK: If member is already active (paid), skip the standard approval email 
        # (the invoice email will serve as their activation notification).
        if instance.is_active_member:
            logger.info(f"[MEMBER SIGNAL] Member {user_email} already active/paid, skipping approval email")
            return

        try:
            from .utils_membership import ensure_membership_payment_for_member
            payment = ensure_membership_payment_for_member(instance)
            if payment:
                logger.info(
                    "[MEMBER SIGNAL] Ensured membership payment row for %s: payment_id=%s",
                    user_email,
                    payment.id,
                )
            else:
                logger.info(
                    "[MEMBER SIGNAL] Membership payment row not created for %s. Membership type may be missing.",
                    user_email,
                )
        except Exception as e:
            logger.error(f"[MEMBER SIGNAL] Failed to ensure membership payment row for {user_email}: {str(e)}", exc_info=True)
            
        logger.info(f"[MEMBER SIGNAL] Processing approval for {user_email}")
        template_name = 'emails/member_approval_email.html'
        subject = f'Welcome to {settings.SITE_NAME} - Membership Approved!'
        site_url = getattr(settings, 'SITE_URL', 'https://bsbcs.info')
        from django.urls import reverse
        # Redirect to login first, then to the payment page via 'next' parameter
        pay_path = reverse('website:membership_payment_init')
        login_path = reverse('login')
        payment_url = f"{site_url}{login_path}?next={pay_path}"
        
        email_context = {
            'user_name': user_name,
            'site_name': getattr(settings, 'SITE_NAME', 'BSBCS'),
            'site_url': site_url,
            'payment_url': payment_url,
        }
        
    elif instance.approval_status == 'rejected':
        logger.info(f"[MEMBER SIGNAL] Processing rejection for {user_email}")
        template_name = 'emails/member_rejection_email.html'
        subject = f'{settings.SITE_NAME} - Membership Application Update'
        email_context = {
            'user_name': user_name,
            'rejection_reason': instance.rejection_reason or 'Not specified',
            'site_name': getattr(settings, 'SITE_NAME', 'BSBCS'),
            'support_email': getattr(settings, 'CONTACT_EMAIL', 'support@example.com'),
        }
    elif instance.approval_status == 'pending':
        logger.info(f"[MEMBER SIGNAL] Processing pending submission for {user_email}")
        send_sms_task.delay(
            instance.user_profile.phone,
            build_membership_submission_sms(instance),
            country=instance.user_profile.country,
            context={
                'source': 'membership_submission',
                'member_id': instance.id,
                'approval_status': instance.approval_status,
                'user_profile_id': instance.user_profile_id,
            },
        )
        return
    else:
        logger.info(f"[MEMBER SIGNAL] Member {instance} status is '{instance.approval_status}', no email to send")
        return
    
    # Send email
    try:
        logger.info(f"[MEMBER SIGNAL] Rendering template: {template_name}")
        html_message = render_to_string(template_name, email_context)
        plain_message = strip_tags(html_message)
        logger.info(f"[MEMBER SIGNAL] Template rendered successfully")
        
        logger.info(f"[MEMBER SIGNAL] Queueing {instance.approval_status} email to {user_email} via Celery")
        send_email_task.delay(
            subject=subject,
            body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            html_message=html_message,
            audit_category=EmailAuditLog.CATEGORY_MEMBERSHIP,
            audit_metadata={
                'member_id': instance.id,
                'approval_status': instance.approval_status,
                'user_profile_id': instance.user_profile_id,
            },
        )
        sms_message = (
            build_membership_approval_sms(instance)
            if instance.approval_status == 'approved'
            else build_membership_rejection_sms(instance)
        )
        send_sms_task.delay(
            instance.user_profile.phone,
            sms_message,
            country=instance.user_profile.country,
            context={
                'source': 'membership_status_change',
                'member_id': instance.id,
                'approval_status': instance.approval_status,
                'user_profile_id': instance.user_profile_id,
            },
        )
        logger.info(f"[MEMBER SIGNAL] Email task queued successfully for {user_email}")
    except Exception as e:
        logger.error(f"[MEMBER SIGNAL] Failed to queue email to {user_email}: {str(e)}", exc_info=True)
        # Print to console for debugging (no unicode to avoid cp1252 encoding issues on Windows)
        import traceback
        print("\n" + "="*60)
        print("!!! EMAIL SEND ERROR !!!")
        print("="*60)
        print(f"Error: {str(e)}")
        print(f"Template: {template_name}")
        print(f"Email: {user_email}")
        print("="*60)
        print(traceback.format_exc())
        print("="*60 + "\n")
