import os
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    AbstractSubmission,
    BulkEmail,
    BulkEmailRecipient,
    BulkEmailsReporting,
    BulkEmailSendLog,
    CorporateAccount,
    CorporateAccountRequest,
    Participant,
    PaymentStatus,
    UserProfile,
)


User = get_user_model()
DEFAULT_BULK_EMAIL_DELAY_SECONDS = 0.25


def sync_bulk_email_status(bulk_email):
    pending_count = bulk_email.recipients.filter(status=BulkEmailRecipient.STATUS_PENDING).count()
    sent_count = bulk_email.recipients.filter(status=BulkEmailRecipient.STATUS_SENT).count()
    failed_count = bulk_email.recipients.filter(status=BulkEmailRecipient.STATUS_FAILED).count()
    recipient_total = pending_count + sent_count + failed_count

    if pending_count:
        status = (
            BulkEmail.STATUS_SENDING
            if sent_count or failed_count or bulk_email.status == BulkEmail.STATUS_SENDING
            else BulkEmail.STATUS_RECIPIENTS_READY
        )
    elif recipient_total and sent_count and not failed_count:
        status = BulkEmail.STATUS_SENT
    elif recipient_total and (sent_count or failed_count):
        status = BulkEmail.STATUS_PARTIAL
    else:
        status = BulkEmail.STATUS_DRAFT

    if bulk_email.status != status:
        bulk_email.status = status
        bulk_email.save(update_fields=['status', 'updated_at'])

    return {
        'status': status,
        'pending': pending_count,
        'sent': sent_count,
        'failed': failed_count,
        'total': recipient_total,
    }


def valid_bulk_email_or_none(email):
    if not email:
        return None
    normalized = email.strip()
    try:
        validate_email(normalized)
    except ValidationError:
        return None
    return normalized


def bulk_email_identity_for_email(email):
    normalized = valid_bulk_email_or_none(email)
    if not normalized:
        return {}
    user = User.objects.filter(email__iexact=normalized).first()
    profile = UserProfile.objects.filter(email__iexact=normalized).first()
    return {
        'user': user,
        'user_profile': profile,
        'name': (
            profile.name
            if profile and profile.name
            else user.get_full_name() or user.username
            if user
            else ''
        ),
    }


def upsert_bulk_email_recipient(bulk_email, email, name='', source_type=BulkEmailRecipient.SOURCE_MANUAL, **links):
    normalized = valid_bulk_email_or_none(email)
    if not normalized:
        return False

    identity = bulk_email_identity_for_email(normalized)
    defaults = {
        'name': name or identity.get('name') or '',
        'source_type': source_type,
        'user': identity.get('user'),
        'user_profile': identity.get('user_profile'),
        **{key: value for key, value in links.items() if value is not None},
    }
    _, created = BulkEmailRecipient.objects.get_or_create(
        bulk_email=bulk_email,
        email=normalized,
        defaults=defaults,
    )
    return created


def prepare_bulk_email_recipients(bulk_email):
    added = 0
    if bulk_email.audience_type == BulkEmail.AUDIENCE_ACTIVE_USERS:
        users = User.objects.filter(is_active=True).exclude(email='')
        for user in users:
            added += int(upsert_bulk_email_recipient(
                bulk_email,
                user.email,
                name=user.get_full_name() or user.username,
                source_type=BulkEmailRecipient.SOURCE_USER,
                user=user,
            ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_EMAIL_GROUP:
        if not bulk_email.email_group:
            return 0
        for email in bulk_email.email_group.parsed_emails():
            added += int(upsert_bulk_email_recipient(
                bulk_email,
                email,
                source_type=BulkEmailRecipient.SOURCE_EMAIL_GROUP,
            ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_EVENT_PARTICIPANTS and bulk_email.event:
        participants = Participant.objects.filter(event=bulk_email.event).exclude(email='')
        for participant in participants:
            added += int(upsert_bulk_email_recipient(
                bulk_email,
                participant.email,
                name=participant.name,
                source_type=BulkEmailRecipient.SOURCE_PARTICIPANT,
                participant=participant,
            ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_EVENT_UNPAID and bulk_email.event:
        payments = PaymentStatus.objects.filter(
            event=bulk_email.event,
            status__in=['unpaid', 'pending', 'failed', 'initiated'],
            participant__isnull=False,
        ).select_related('participant')
        for payment in payments:
            participant = payment.participant
            if participant:
                added += int(upsert_bulk_email_recipient(
                    bulk_email,
                    participant.email,
                    name=participant.name,
                    source_type=BulkEmailRecipient.SOURCE_PARTICIPANT,
                    participant=participant,
                ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_MEMBERSHIP_UNPAID:
        from website.models import MembershipPayment

        payments = MembershipPayment.objects.filter(
            user_profile__member__approval_status='approved',
        ).exclude(
            status='completed',
        ).select_related(
            'user_profile',
            'user_profile__user',
            'membership_type',
        ).order_by('-updated_at')
        for payment in payments:
            profile = payment.user_profile
            added += int(upsert_bulk_email_recipient(
                bulk_email,
                profile.email,
                name=profile.name,
                source_type=BulkEmailRecipient.SOURCE_MEMBERSHIP,
                user=profile.user,
                user_profile=profile,
            ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_ABSTRACT_SUBMITTERS and bulk_email.event:
        abstracts = AbstractSubmission.objects.filter(event=bulk_email.event).select_related('user')
        for abstract in abstracts:
            email = abstract.user.email if abstract.user_id else ''
            name = abstract.user.get_full_name() or abstract.user.username if abstract.user_id else ''
            added += int(upsert_bulk_email_recipient(
                bulk_email,
                email,
                name=name,
                source_type=BulkEmailRecipient.SOURCE_ABSTRACT,
                abstract_submission=abstract,
                user=abstract.user if abstract.user_id else None,
            ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_CORPORATE_CONTACTS:
        accounts = CorporateAccount.objects.filter(status='approved').exclude(email='')
        for account in accounts:
            added += int(upsert_bulk_email_recipient(
                bulk_email,
                account.email,
                name=account.contact_name,
                source_type=BulkEmailRecipient.SOURCE_CORPORATE,
                corporate_account=account,
            ))
        requests = CorporateAccountRequest.objects.filter(status='approved').exclude(email='')
        for account_request in requests:
            added += int(upsert_bulk_email_recipient(
                bulk_email,
                account_request.email,
                name=account_request.contact_name,
                source_type=BulkEmailRecipient.SOURCE_CORPORATE,
                corporate_request=account_request,
            ))

    if bulk_email.recipient_count:
        bulk_email.status = BulkEmail.STATUS_RECIPIENTS_READY
        bulk_email.save(update_fields=['status', 'updated_at'])
    return added


def _send_bulk_email_recipient_direct(bulk_email, recipient, sent_by=None):
    disconnect_markers = (
        'Connection unexpectedly closed',
        'Server not connected',
        'Connection reset',
        'Connection aborted',
        'Broken pipe',
    )
    last_error = ''

    for attempt in range(1, 4):
        email = EmailMessage(
            subject=bulk_email.subject,
            body=bulk_email.body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None) or os.getenv("EMAIL_HOST_USER"),
            to=[recipient.email],
        )
        if bulk_email.attachment:
            email.attach_file(bulk_email.attachment.path)

        try:
            email.send()
            break
        except Exception as exc:
            last_error = str(exc)
            is_disconnect = any(marker.lower() in last_error.lower() for marker in disconnect_markers)
            if attempt < 3 and is_disconnect:
                time.sleep(attempt * 2)
                continue

            recipient.status = BulkEmailRecipient.STATUS_FAILED
            recipient.error_message = last_error
            recipient.save(update_fields=['status', 'error_message'])
            BulkEmailSendLog.objects.create(
                bulk_email=bulk_email,
                recipient=recipient,
                email=recipient.email,
                status=BulkEmailRecipient.STATUS_FAILED,
                message=last_error,
                sent_by=sent_by,
            )
            sync_bulk_email_status(bulk_email)
            return False

    recipient.status = BulkEmailRecipient.STATUS_SENT
    recipient.error_message = ''
    recipient.sent_at = timezone.now()
    recipient.save(update_fields=['status', 'error_message', 'sent_at'])
    BulkEmailSendLog.objects.create(
        bulk_email=bulk_email,
        recipient=recipient,
        email=recipient.email,
        status=BulkEmailRecipient.STATUS_SENT,
        sent_by=sent_by,
    )
    sync_bulk_email_status(bulk_email)
    return True


def send_bulk_email_recipient(bulk_email, recipient, sent_by=None):
    try:
        from .tasks import send_bulk_email_recipient_task

        send_bulk_email_recipient_task.delay(
            bulk_email.id,
            recipient.id,
            sent_by_user_id=sent_by.id if sent_by else None,
        )
        return True
    except Exception as exc:
        recipient.status = BulkEmailRecipient.STATUS_FAILED
        recipient.error_message = str(exc)
        recipient.save(update_fields=['status', 'error_message'])
        BulkEmailSendLog.objects.create(
            bulk_email=bulk_email,
            recipient=recipient,
            email=recipient.email,
            status=BulkEmailRecipient.STATUS_FAILED,
            message=str(exc),
            sent_by=sent_by,
        )
        sync_bulk_email_status(bulk_email)
        return False


def send_pending_bulk_email_recipients(bulk_email_id, sent_by_user_id=None):
    bulk_email = BulkEmail.objects.filter(pk=bulk_email_id).first()
    if not bulk_email:
        return {'sent': 0, 'failed': 0, 'error': 'Campaign not found.'}

    sent_by = User.objects.filter(pk=sent_by_user_id).first() if sent_by_user_id else None
    if not sent_by:
        sent_by = User.objects.filter(is_superuser=True).order_by('id').first()
    if not sent_by:
        sent_by = User.objects.filter(is_staff=True).order_by('id').first()
    if not bulk_email.recipients.filter(status=BulkEmailRecipient.STATUS_PENDING).exists():
        prepare_bulk_email_recipients(bulk_email)

    pending_recipients = bulk_email.recipients.filter(status=BulkEmailRecipient.STATUS_PENDING)
    sent = 0
    failed = 0
    sent_emails = []
    bulk_email.status = BulkEmail.STATUS_SENDING
    bulk_email.save(update_fields=['status', 'updated_at'])

    for recipient in pending_recipients.iterator():
        if _send_bulk_email_recipient_direct(bulk_email, recipient, sent_by=sent_by):
            sent += 1
            sent_emails.append(recipient.email)
        else:
            failed += 1
        time.sleep(getattr(settings, 'BULK_EMAIL_DELAY_SECONDS', DEFAULT_BULK_EMAIL_DELAY_SECONDS))

    bulk_email.refresh_from_db()
    sync_bulk_email_status(bulk_email)

    if sent_emails:
        BulkEmailsReporting.objects.create(
            subject=bulk_email.subject,
            body=bulk_email.body,
            recipients=', '.join(sent_emails),
            attachment=bulk_email.attachment if bulk_email.attachment else None,
        )

    return {'sent': sent, 'failed': failed, 'campaign_id': bulk_email.id}
