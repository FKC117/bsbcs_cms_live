import os

from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.db import connection
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from .bulk_email_services import send_pending_bulk_email_recipients
from .models import Participant, ParticipantEmailLog


@shared_task(bind=True)
def send_pending_bulk_email_campaign(self, bulk_email_id, sent_by_user_id=None):
    return send_pending_bulk_email_recipients(
        bulk_email_id=bulk_email_id,
        sent_by_user_id=sent_by_user_id,
    )


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
    email = EmailMultiAlternatives(
        'Your BSBCS profile and login account',
        text_content,
        settings.DEFAULT_FROM_EMAIL or os.getenv('EMAIL_HOST_USER'),
        [participant.email],
    )
    email.attach_alternative(html_content, 'text/html')
    email.send()
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
        email = EmailMultiAlternatives(
            subject,
            text_content,
            settings.DEFAULT_FROM_EMAIL or os.getenv('EMAIL_HOST_USER'),
            [participant.email],
        )
        email.attach_alternative(html_content, 'text/html')
        email.send()
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
