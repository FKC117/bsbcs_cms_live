import os
import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.db import connection
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from .bulk_email_services import send_pending_bulk_email_recipients
from .bulk_sms_services import send_pending_bulk_sms_recipients
from .email_audit import consume_email_quota_reservations, record_email_audit, release_email_quota_reservations, reserve_email_quota
from .email_rendering import render_rich_email_html
from .models import EmailAuditLog, Participant, ParticipantEmailLog, SpeakerCertificate, SpeakerCertificateEmailLog, SpeakerOutreachCoordination, SpeakerOutreachEmailLog, ThankYouEmailLog
from .sms import (
    get_system_sms_content,
    send_sms,
)


speaker_certificate_celery_logger = logging.getLogger('speaker_certificate_celery')


def _send_email(
    subject,
    body,
    from_email,
    recipient_list,
    html_message=None,
    attachment_paths=None,
    cc=None,
    bcc=None,
    reply_to=None,
    headers=None,
    audit_category=None,
    audit_metadata=None,
    audit_sent_by_user_id=None,
):
    all_recipients = (recipient_list or []) + (cc or []) + (bcc or [])
    reservation_result = None

    if audit_category and all_recipients:
        reservation_result = reserve_email_quota(
            all_recipients,
            category=audit_category,
            metadata=audit_metadata,
        )
        normalized_count = len({recipient.lower() for recipient in reservation_result['allowed_recipients']})
        expected_count = len({(recipient or '').strip().lower() for recipient in all_recipients if (recipient or '').strip()})
        if normalized_count < expected_count:
            release_email_quota_reservations(reservation_result['reservation_key'])
            quota_snapshot = reservation_result['quota_snapshot']
            raise RuntimeError(
                f"24-hour email quota reached. Bulk used: {quota_snapshot['bulk_used']}/{quota_snapshot['bulk_limit']}, total used: {quota_snapshot['total_used']}/{quota_snapshot['total_limit']}."
            )

    if html_message:
        body_text = body or strip_tags(html_message)
        email = EmailMultiAlternatives(
            subject,
            body_text,
            from_email,
            recipient_list,
            cc=cc or [],
            bcc=bcc or [],
            reply_to=reply_to or [],
            headers=headers or {},
        )
        email.attach_alternative(html_message, 'text/html')
    else:
        email = EmailMessage(
            subject,
            body or '',
            from_email,
            recipient_list,
            cc=cc or [],
            bcc=bcc or [],
            reply_to=reply_to or [],
            headers=headers or {},
        )

    if attachment_paths:
        for attachment_path in attachment_paths:
            if attachment_path and os.path.exists(attachment_path):
                email.attach_file(attachment_path)

    try:
        result = email.send()
    except Exception:
        if reservation_result:
            release_email_quota_reservations(reservation_result['reservation_key'])
        raise

    if result and audit_category:
        record_email_audit(
            category=audit_category,
            subject=subject,
            recipients=all_recipients,
            metadata=audit_metadata,
            sent_by_user_id=audit_sent_by_user_id,
        )
        if reservation_result:
            consume_email_quota_reservations(
                reservation_result['reservation_key'],
                reservation_result['allowed_recipients'],
            )
    elif reservation_result:
        release_email_quota_reservations(reservation_result['reservation_key'])

    return result


@shared_task(bind=True)
def send_sms_task(self, phone, message, country='Bangladesh', context=None, sms_type='non_masking', fallback_sms_type=None):
    return send_sms(phone, message, country=country, context=context, sms_type=sms_type, fallback_sms_type=fallback_sms_type)


@shared_task(bind=True)
def send_pending_bulk_sms_campaign(self, bulk_sms_id, sent_by_user_id=None, recipient_statuses=None):
    return send_pending_bulk_sms_recipients(bulk_sms_id, sent_by_user_id=sent_by_user_id, recipient_statuses=recipient_statuses)


@shared_task(bind=True)
def send_email_task(
    self,
    subject,
    body,
    from_email,
    recipient_list,
    html_message=None,
    attachment_paths=None,
    cc=None,
    bcc=None,
    reply_to=None,
    headers=None,
    audit_category=None,
    audit_metadata=None,
    audit_sent_by_user_id=None,
):
    return _send_email(
        subject=subject,
        body=body,
        from_email=from_email,
        recipient_list=recipient_list,
        html_message=html_message,
        attachment_paths=attachment_paths,
        cc=cc,
        bcc=bcc,
        reply_to=reply_to,
        headers=headers,
        audit_category=audit_category,
        audit_metadata=audit_metadata,
        audit_sent_by_user_id=audit_sent_by_user_id,
    )


def thank_you_email_log_table_ready():
    try:
        return ThankYouEmailLog._meta.db_table in connection.introspection.table_names()
    except Exception:
        return False


def _update_thank_you_email_log(log_id, **fields):
    if not log_id or not thank_you_email_log_table_ready():
        return
    ThankYouEmailLog.objects.filter(pk=log_id).update(**fields, updated_at=timezone.now())


@shared_task(bind=True)
def send_thank_you_email_task(self, thank_you_email_id, log_id=None, sent_by_user_id=None, force_resend=False):
    from .models import ThankYouEmail

    try:
        thank_you_email = ThankYouEmail.objects.select_related(
            'registration_kit__event',
            'registration_kit__payment_status__participant'
        ).get(pk=thank_you_email_id)
    except ThankYouEmail.DoesNotExist:
        _update_thank_you_email_log(log_id, status=ThankYouEmailLog.STATUS_FAILED, message='Thank-you email record not found.')
        return {'status': 'missing'}

    if thank_you_email.registration_kit.status != 'issued':
        _update_thank_you_email_log(
            log_id,
            status=ThankYouEmailLog.STATUS_SKIPPED,
            message='Thank-you email skipped because the kit is no longer issued.',
        )
        return {'status': 'skipped'}

    if thank_you_email.email_sent and not force_resend:
        _update_thank_you_email_log(
            log_id,
            status=ThankYouEmailLog.STATUS_SKIPPED,
            message='Thank-you email skipped because it was already sent.',
        )
        return {'status': 'skipped'}

    participant = thank_you_email.registration_kit.payment_status.participant
    if not participant or not participant.email:
        _update_thank_you_email_log(log_id, status=ThankYouEmailLog.STATUS_FAILED, message='Recipient email is missing.')
        return {'status': 'missing_recipient'}

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or os.getenv('EMAIL_HOST_USER')
    try:
        html_message = render_rich_email_html(
            thank_you_email.subject,
            thank_you_email.body,
            button_text=thank_you_email.button_text,
            button_url=thank_you_email.button_url,
        )
        result = _send_email(
            subject=thank_you_email.subject,
            body=thank_you_email.body,
            from_email=from_email,
            recipient_list=[participant.email],
            html_message=html_message,
            audit_category=EmailAuditLog.CATEGORY_THANK_YOU,
            audit_metadata={
                'thank_you_email_id': thank_you_email.id,
                'event_id': thank_you_email.registration_kit.event_id,
                'participant_id': participant.id,
            },
            audit_sent_by_user_id=sent_by_user_id,
        )
    except Exception as exc:
        _update_thank_you_email_log(log_id, status=ThankYouEmailLog.STATUS_FAILED, message=str(exc))
        raise

    if result:
        sent_at = timezone.now()
        thank_you_email.email_sent = True
        thank_you_email.sent_at = sent_at
        thank_you_email.save(update_fields=['email_sent', 'sent_at'])
        _update_thank_you_email_log(
            log_id,
            status=ThankYouEmailLog.STATUS_SENT,
            sent_at=sent_at,
            message='Thank-you email resent successfully.' if force_resend else 'Thank-you email sent successfully.',
        )

    return {'status': 'sent' if result else 'failed', 'result': result}


@shared_task(bind=True)
def send_pending_bulk_email_campaign(self, bulk_email_id, sent_by_user_id=None, recipient_statuses=None):
    logging.getLogger('registration').info(
        "Celery received bulk email task: task_id=%s campaign_id=%s sent_by_user_id=%s recipient_statuses=%s",
        getattr(self.request, 'id', None),
        bulk_email_id,
        sent_by_user_id,
        recipient_statuses,
    )
    return send_pending_bulk_email_recipients(
        bulk_email_id=bulk_email_id,
        sent_by_user_id=sent_by_user_id,
        recipient_statuses=recipient_statuses,
    )


@shared_task(bind=True)
def send_bulk_email_recipient_task(self, bulk_email_id, recipient_id, sent_by_user_id=None):
    from .bulk_email_services import _send_bulk_email_recipient_direct
    from .models import BulkEmail, BulkEmailRecipient, User

    bulk_email = BulkEmail.objects.filter(pk=bulk_email_id).first()
    recipient = BulkEmailRecipient.objects.filter(pk=recipient_id).first()
    if not bulk_email or not recipient:
        return {
            'status': 'missing',
            'bulk_email_id': bulk_email_id,
            'recipient_id': recipient_id,
        }

    sent_by = User.objects.filter(pk=sent_by_user_id).first() if sent_by_user_id else None
    result = _send_bulk_email_recipient_direct(bulk_email, recipient, sent_by=sent_by)
    return {
        'status': 'sent' if result else 'failed',
        'bulk_email_id': bulk_email_id,
        'recipient_id': recipient_id,
    }


@shared_task(bind=True)
def send_manual_participant_account_email(self, participant_id, password):
    participant = Participant.objects.select_related('event', 'user').get(pk=participant_id)
    login_url = f"{settings.SITE_URL.rstrip('/')}{reverse('login')}"
    context = {
        'participant': participant,
        'event': participant.event,
        'username': participant.user.username,
        'password': password,
        'login_url': login_url,
    }
    html_content = render_to_string('emails/manual_participant_account_created.html', context)
    text_content = strip_tags(html_content)
    _send_email(
        subject='Your BSBCS profile and login account',
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL or os.getenv('EMAIL_HOST_USER'),
        recipient_list=[participant.email],
        html_message=html_content,
        audit_category=EmailAuditLog.CATEGORY_REGISTRATION,
        audit_metadata={
            'participant_id': participant.id,
            'event_id': participant.event_id,
            'source': 'manual_participant_account',
        },
    )
    return {'participant_id': participant.id, 'email': participant.email, 'status': 'sent'}


def participant_email_log_table_ready():
    try:
        return ParticipantEmailLog._meta.db_table in connection.introspection.table_names()
    except Exception:
        return False


def _update_participant_email_log(log_id, **fields):
    if not log_id or not participant_email_log_table_ready():
        return
    ParticipantEmailLog.objects.filter(pk=log_id).update(**fields, updated_at=timezone.now())


def speaker_certificate_email_log_table_ready():
    try:
        return SpeakerCertificateEmailLog._meta.db_table in connection.introspection.table_names()
    except Exception:
        return False


def _update_speaker_certificate_email_log(log_id, **fields):
    if not log_id or not speaker_certificate_email_log_table_ready():
        return
    SpeakerCertificateEmailLog.objects.filter(pk=log_id).update(**fields, updated_at=timezone.now())


@shared_task(bind=True)
def send_participant_approval_email(
    self,
    participant_id,
    email_type,
    log_id=None,
    sent_by_user_id=None,
    password=None,
    include_password=False,
    payment_url=None,
):
    participant = Participant.objects.select_related('event').get(pk=participant_id)
    event = participant.event
    sent_by = User.objects.filter(pk=sent_by_user_id).first() if sent_by_user_id else None

    if email_type == ParticipantEmailLog.TYPE_APPROVAL_PAYMENT:
        subject = f'Your Registration for {event.name} {event.year} is Approved!'
        if not payment_url:
            payment_url = reverse('registration:payment', kwargs={
                'event_id': event.id,
                'participant_id': participant.id,
            })
        context = {
            'participant': participant,
            'event': event,
            'payment_url': payment_url,
        }
        template_name = 'consolidated_email.html'
    elif email_type == ParticipantEmailLog.TYPE_FREE_CONFIRMATION:
        subject = f'Registration Confirmed for {event.name} {event.year}'
        context = {
            'participant': participant,
            'event': event,
        }
        template_name = 'free_event_confirmation_email.html'

        # Ensure a free-event invoice is generated and attached for free approvals.
        from .models import PaymentStatus
        from .pdf_utils import generate_invoice

        payment_status = PaymentStatus.objects.filter(participant=participant, event=event).first()
        invoice_path = None
        if payment_status:
            existing_invoice_path = None
            if payment_status.invoice:
                try:
                    existing_invoice_path = payment_status.invoice.path
                except Exception:
                    existing_invoice_path = None

            if existing_invoice_path and os.path.exists(existing_invoice_path):
                invoice_path = existing_invoice_path
            else:
                invoice_path = generate_invoice(participant, event, payment_status)
                relative_invoice_path = os.path.relpath(invoice_path, settings.MEDIA_ROOT).replace('\\', '/')
                payment_status.invoice = relative_invoice_path
                payment_status.save(update_fields=['invoice'])
    else:
        message = f'Unknown participant email type: {email_type}'
        _update_participant_email_log(
            log_id,
            status=ParticipantEmailLog.STATUS_FAILED,
            message=message,
            sent_by=sent_by,
        )
        raise ValueError(message)

    if include_password and password:
        context['password'] = password

    try:
        html_content = render_to_string(template_name, context)
        text_content = strip_tags(html_content)
        attachment_paths = []
        if email_type == ParticipantEmailLog.TYPE_FREE_CONFIRMATION and invoice_path and os.path.exists(invoice_path):
            attachment_paths.append(invoice_path)
        _send_email(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL or os.getenv('EMAIL_HOST_USER'),
            recipient_list=[participant.email],
            html_message=html_content,
            attachment_paths=attachment_paths,
            audit_category=(
                EmailAuditLog.CATEGORY_APPROVAL
                if email_type == ParticipantEmailLog.TYPE_APPROVAL_PAYMENT
                else EmailAuditLog.CATEGORY_REGISTRATION
            ),
            audit_metadata={
                'participant_id': participant.id,
                'event_id': event.id,
                'email_type': email_type,
            },
            audit_sent_by_user_id=sent_by_user_id,
        )
        sms_template_key = (
            'registration_approval'
            if email_type == ParticipantEmailLog.TYPE_APPROVAL_PAYMENT
            else 'registration_confirmation'
        )
        sms_payload = get_system_sms_content(
            sms_template_key,
            context={
                'participant_name': participant.name,
                'event_name': event.name,
                'event_year': event.year,
            },
        )
        send_sms(
            participant.phone,
            sms_payload['body'],
            country=participant.country,
            context={
                'source': 'participant_approval_email',
                'participant_id': participant.id,
                'event_id': event.id,
                'email_type': email_type,
            },
            sms_type=sms_payload['sms_type'],
            fallback_sms_type=sms_payload.get('fallback_sms_type'),
        )
        if email_type == ParticipantEmailLog.TYPE_FREE_CONFIRMATION and payment_status:
            payment_status.email_sent = True
            payment_status.save(update_fields=['email_sent'])
    except Exception as exc:
        _update_participant_email_log(
            log_id,
            status=ParticipantEmailLog.STATUS_FAILED,
            message=str(exc),
            sent_by=sent_by,
        )
        raise

    _update_participant_email_log(
        log_id,
        status=ParticipantEmailLog.STATUS_SENT,
        message='Email sent successfully.',
        sent_by=sent_by,
        sent_at=timezone.now(),
    )
    return {'participant_id': participant.id, 'email': participant.email, 'status': 'sent'}


@shared_task(bind=True)
def send_speaker_certificate_email(
    self,
    certificate_id,
    log_id=None,
    sent_by_user_id=None,
):
    speaker_certificate_celery_logger.info(
        "Speaker certificate email task started: certificate_id=%s log_id=%s sent_by_user_id=%s task_id=%s",
        certificate_id,
        log_id,
        sent_by_user_id,
        getattr(self.request, 'id', None),
    )
    certificate = SpeakerCertificate.objects.select_related('event', 'program_person', 'profile').get(pk=certificate_id)
    sent_by = User.objects.filter(pk=sent_by_user_id).first() if sent_by_user_id else None
    recipient_email = (certificate.profile.email if certificate.profile_id else '') or certificate.program_person.email

    if not recipient_email:
        message = 'No recipient email address available.'
        _update_speaker_certificate_email_log(
            log_id,
            status=SpeakerCertificateEmailLog.STATUS_FAILED,
            message=message,
            sent_by=sent_by,
        )
        speaker_certificate_celery_logger.warning(
            "Speaker certificate email task aborted: missing recipient certificate_id=%s person_id=%s event_id=%s",
            certificate.id,
            certificate.program_person_id,
            certificate.event_id,
        )
        raise ValueError(message)

    if not certificate.generated_file:
        message = 'Speaker certificate file is not available.'
        _update_speaker_certificate_email_log(
            log_id,
            status=SpeakerCertificateEmailLog.STATUS_FAILED,
            message=message,
            sent_by=sent_by,
        )
        speaker_certificate_celery_logger.warning(
            "Speaker certificate email task aborted: missing generated file certificate_id=%s person_id=%s event_id=%s",
            certificate.id,
            certificate.program_person_id,
            certificate.event_id,
        )
        raise ValueError(message)

    try:
        attachment_path = certificate.generated_file.path
    except Exception as exc:
        message = f'Could not resolve generated speaker certificate file: {exc}'
        _update_speaker_certificate_email_log(
            log_id,
            status=SpeakerCertificateEmailLog.STATUS_FAILED,
            message=message,
            sent_by=sent_by,
        )
        speaker_certificate_celery_logger.exception(
            "Speaker certificate email task could not resolve attachment path: certificate_id=%s person_id=%s event_id=%s",
            certificate.id,
            certificate.program_person_id,
            certificate.event_id,
        )
        raise ValueError(message)

    subject = f'Your Speaker Certificate for {certificate.event.name} {certificate.event.year}'
    context = {
        'certificate': certificate,
        'event': certificate.event,
        'person': certificate.program_person,
    }
    html_content = render_to_string('emails/speaker_certificate_email.html', context)
    text_content = strip_tags(html_content)

    try:
        speaker_certificate_celery_logger.info(
            "Speaker certificate email task sending: certificate_id=%s person_id=%s event_id=%s recipient=%s attachment=%s",
            certificate.id,
            certificate.program_person_id,
            certificate.event_id,
            recipient_email,
            attachment_path,
        )
        _send_email(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL or os.getenv('EMAIL_HOST_USER'),
            recipient_list=[recipient_email],
            html_message=html_content,
            attachment_paths=[attachment_path],
            audit_category=EmailAuditLog.CATEGORY_SPEAKER_CERTIFICATE,
            audit_metadata={
                'certificate_id': certificate.id,
                'event_id': certificate.event_id,
                'program_person_id': certificate.program_person_id,
            },
            audit_sent_by_user_id=sent_by_user_id,
        )
    except Exception as exc:
        _update_speaker_certificate_email_log(
            log_id,
            status=SpeakerCertificateEmailLog.STATUS_FAILED,
            message=str(exc),
            sent_by=sent_by,
        )
        speaker_certificate_celery_logger.exception(
            "Speaker certificate email task failed during send: certificate_id=%s person_id=%s event_id=%s recipient=%s",
            certificate.id,
            certificate.program_person_id,
            certificate.event_id,
            recipient_email,
        )
        raise

    sent_at = timezone.now()
    SpeakerCertificate.objects.filter(pk=certificate.pk).update(emailed_at=sent_at)
    _update_speaker_certificate_email_log(
        log_id,
        status=SpeakerCertificateEmailLog.STATUS_SENT,
        message='Speaker certificate email sent successfully.',
        sent_by=sent_by,
        sent_at=sent_at,
    )
    speaker_certificate_celery_logger.info(
        "Speaker certificate email task completed: certificate_id=%s person_id=%s event_id=%s recipient=%s sent_at=%s",
        certificate.id,
        certificate.program_person_id,
        certificate.event_id,
        recipient_email,
        sent_at.isoformat(),
    )
    return {'certificate_id': certificate.id, 'email': recipient_email, 'status': 'sent'}


def speaker_outreach_email_log_table_ready():
    try:
        return SpeakerOutreachEmailLog._meta.db_table in connection.introspection.table_names()
    except Exception:
        return False


def _update_speaker_outreach_email_log(log_id, **fields):
    if not log_id or not speaker_outreach_email_log_table_ready():
        return
    SpeakerOutreachEmailLog.objects.filter(pk=log_id).update(**fields, updated_at=timezone.now())


@shared_task(bind=True)
def send_speaker_outreach_email_task(self, log_id):
    try:
        log = SpeakerOutreachEmailLog.objects.select_related('coordination', 'event', 'person', 'sent_by').get(pk=log_id)
    except SpeakerOutreachEmailLog.DoesNotExist:
        return {'status': 'missing'}

    recipient_email = (log.email or '').strip()
    if not recipient_email:
        _update_speaker_outreach_email_log(log_id, status=SpeakerOutreachEmailLog.STATUS_FAILED, message='Recipient email is missing.')
        return {'status': 'missing_recipient'}

    html_message = render_rich_email_html(log.subject, log.body)
    try:
        _send_email(
            subject=log.subject,
            body=log.body,
            from_email=settings.DEFAULT_FROM_EMAIL or os.getenv('EMAIL_HOST_USER'),
            recipient_list=[recipient_email],
            html_message=html_message,
            audit_category=EmailAuditLog.CATEGORY_SPEAKER_OUTREACH,
            audit_metadata={
                'event_id': log.event_id,
                'program_person_id': log.person_id,
                'speaker_outreach_log_id': log.id,
            },
            audit_sent_by_user_id=log.sent_by_id,
        )
    except Exception as exc:
        _update_speaker_outreach_email_log(log_id, status=SpeakerOutreachEmailLog.STATUS_FAILED, message=str(exc))
        raise

    sent_at = timezone.now()
    _update_speaker_outreach_email_log(
        log_id,
        status=SpeakerOutreachEmailLog.STATUS_SENT,
        message='Speaker outreach email sent successfully.',
        sent_at=sent_at,
    )

    if log.coordination_id:
        SpeakerOutreachCoordination.objects.filter(pk=log.coordination_id).update(
            status=SpeakerOutreachCoordination.STATUS_SENT,
            send_count=(log.coordination.send_count if log.coordination else 0) + 1,
            last_subject=log.subject,
            last_body=log.body,
            last_sent_at=sent_at,
            last_sent_by_id=log.sent_by_id,
            updated_at=sent_at,
        )

    return {'status': 'sent', 'log_id': log_id, 'email': recipient_email}

