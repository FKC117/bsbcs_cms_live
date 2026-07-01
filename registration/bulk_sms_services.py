import json
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from .forms import DEFAULT_COUNTRY, normalize_phone_number
from .models import (
    AbstractSubmission,
    BulkSMS,
    BulkSMSRecipient,
    BulkSMSSendLog,
    CorporateAccount,
    CorporateAccountRequest,
    Participant,
    PaymentStatus,
    PhoneGroup,
    UserProfile,
)
from .sms import send_bulk_sms


User = get_user_model()
DEFAULT_BULK_SMS_DELAY_SECONDS = 0.25


def _campaign_stop_status(bulk_sms):
    has_activity = bulk_sms.recipients.filter(
        status__in=[BulkSMSRecipient.STATUS_SENT, BulkSMSRecipient.STATUS_FAILED]
    ).exists()
    return BulkSMS.STATUS_PARTIAL if has_activity else BulkSMS.STATUS_RECIPIENTS_READY


def sync_bulk_sms_status(bulk_sms):
    pending_count = bulk_sms.recipients.filter(status=BulkSMSRecipient.STATUS_PENDING).count()
    sent_count = bulk_sms.recipients.filter(status=BulkSMSRecipient.STATUS_SENT).count()
    failed_count = bulk_sms.recipients.filter(status=BulkSMSRecipient.STATUS_FAILED).count()
    recipient_total = pending_count + sent_count + failed_count

    if bulk_sms.status == BulkSMS.STATUS_SENDING and (pending_count or failed_count):
        status = BulkSMS.STATUS_SENDING
    elif pending_count:
        if bulk_sms.status == BulkSMS.STATUS_PARTIAL:
            status = BulkSMS.STATUS_PARTIAL
        else:
            status = (
                BulkSMS.STATUS_SENDING
                if sent_count or failed_count or bulk_sms.status == BulkSMS.STATUS_SENDING
                else BulkSMS.STATUS_RECIPIENTS_READY
            )
    elif recipient_total and sent_count and not failed_count:
        status = BulkSMS.STATUS_SENT
    elif recipient_total and (sent_count or failed_count):
        status = BulkSMS.STATUS_PARTIAL
    else:
        status = BulkSMS.STATUS_DRAFT

    if bulk_sms.status != status:
        bulk_sms.status = status
        bulk_sms.save(update_fields=['status', 'updated_at'])

    return {
        'status': status,
        'pending': pending_count,
        'sent': sent_count,
        'failed': failed_count,
        'total': recipient_total,
    }


def bulk_sms_identity_for_phone(phone):
    if not phone:
        return {}
    profile = UserProfile.objects.filter(phone=phone).select_related('user').first()
    user = profile.user if profile and profile.user_id else None
    return {
        'user': user,
        'user_profile': profile,
        'name': profile.name if profile and profile.name else (user.get_full_name() or user.username if user else ''),
        'country': profile.country if profile and profile.country else DEFAULT_COUNTRY,
    }


def _normalize_sms_phone_or_none(phone, country):
    try:
        return normalize_phone_number(phone, country or DEFAULT_COUNTRY)
    except Exception:
        return None


def upsert_bulk_sms_recipient(bulk_sms, phone, *, country=DEFAULT_COUNTRY, raw_phone='', name='', source_type=BulkSMSRecipient.SOURCE_MANUAL, **links):
    normalized = _normalize_sms_phone_or_none(phone, country)
    if not normalized:
        return False

    identity = bulk_sms_identity_for_phone(normalized)
    defaults = {
        'raw_phone': raw_phone or phone,
        'country': country or identity.get('country') or DEFAULT_COUNTRY,
        'name': name or identity.get('name') or '',
        'source_type': source_type,
        'user': identity.get('user'),
        'user_profile': identity.get('user_profile'),
        **{key: value for key, value in links.items() if value is not None},
    }
    _, created = BulkSMSRecipient.objects.get_or_create(
        bulk_sms=bulk_sms,
        phone=normalized,
        defaults=defaults,
    )
    return created


def prepare_bulk_sms_recipients(bulk_sms):
    added = 0
    target_recipients = []

    def queue_target(phone, *, country=DEFAULT_COUNTRY, raw_phone='', name='', source_type=BulkSMSRecipient.SOURCE_MANUAL, **links):
        normalized = _normalize_sms_phone_or_none(phone, country)
        if not normalized:
            return
        target_recipients.append({
            'phone': normalized,
            'country': country or DEFAULT_COUNTRY,
            'raw_phone': raw_phone or phone,
            'name': name,
            'source_type': source_type,
            'links': links,
        })

    if bulk_sms.audience_type == BulkSMS.AUDIENCE_ACTIVE_USERS:
        profiles = UserProfile.objects.exclude(phone='').select_related('user')
        for profile in profiles:
            if profile.user_id and not profile.user.is_active:
                continue
            queue_target(
                profile.phone,
                country=profile.country or DEFAULT_COUNTRY,
                name=profile.name,
                source_type=BulkSMSRecipient.SOURCE_USER,
                user=profile.user,
                user_profile=profile,
            )
    elif bulk_sms.audience_type == BulkSMS.AUDIENCE_PHONE_GROUP:
        if not bulk_sms.phone_group:
            return 0
        for phone in bulk_sms.phone_group.parsed_phone_numbers():
            queue_target(
                phone,
                country=DEFAULT_COUNTRY,
                source_type=BulkSMSRecipient.SOURCE_PHONE_GROUP,
            )
    elif bulk_sms.audience_type == BulkSMS.AUDIENCE_EVENT_PARTICIPANTS and bulk_sms.event:
        participants = Participant.objects.filter(event=bulk_sms.event).exclude(phone='')
        for participant in participants:
            queue_target(
                participant.phone,
                country=participant.country or DEFAULT_COUNTRY,
                name=participant.name,
                source_type=BulkSMSRecipient.SOURCE_PARTICIPANT,
                participant=participant,
            )
    elif bulk_sms.audience_type == BulkSMS.AUDIENCE_EVENT_UNPAID and bulk_sms.event:
        payments = PaymentStatus.objects.filter(
            event=bulk_sms.event,
            status__in=['unpaid', 'pending', 'failed', 'initiated'],
            participant__isnull=False,
        ).select_related('participant')
        for payment in payments:
            participant = payment.participant
            if participant and participant.phone:
                queue_target(
                    participant.phone,
                    country=participant.country or DEFAULT_COUNTRY,
                    name=participant.name,
                    source_type=BulkSMSRecipient.SOURCE_PARTICIPANT,
                    participant=participant,
                )
    elif bulk_sms.audience_type == BulkSMS.AUDIENCE_MEMBERSHIP_UNPAID:
        from website.models import Member

        members = Member.objects.filter(
            approval_status='approved',
            is_active_member=False,
        ).select_related('user_profile', 'user_profile__user').order_by('-approved_at', '-updated_at')
        for member in members:
            profile = member.user_profile
            if not profile or not profile.phone:
                continue
            queue_target(
                profile.phone,
                country=profile.country or DEFAULT_COUNTRY,
                name=profile.name,
                source_type=BulkSMSRecipient.SOURCE_MEMBERSHIP,
                user=profile.user,
                user_profile=profile,
            )
    elif bulk_sms.audience_type == BulkSMS.AUDIENCE_ABSTRACT_SUBMITTERS and bulk_sms.event:
        abstracts = AbstractSubmission.objects.filter(event=bulk_sms.event).select_related('user')
        for abstract in abstracts:
            if not abstract.user_id:
                continue
            profile = UserProfile.objects.filter(user=abstract.user).first() or UserProfile.objects.filter(email__iexact=abstract.user.email).first()
            if not profile or not profile.phone:
                continue
            queue_target(
                profile.phone,
                country=profile.country or DEFAULT_COUNTRY,
                name=profile.name,
                source_type=BulkSMSRecipient.SOURCE_ABSTRACT,
                abstract_submission=abstract,
                user=abstract.user,
                user_profile=profile,
            )
    elif bulk_sms.audience_type == BulkSMS.AUDIENCE_CORPORATE_CONTACTS:
        accounts = CorporateAccount.objects.filter(status='approved').exclude(phone='')
        for account in accounts:
            queue_target(
                account.phone,
                country=DEFAULT_COUNTRY,
                name=account.contact_name,
                source_type=BulkSMSRecipient.SOURCE_CORPORATE,
                corporate_account=account,
            )
        requests = CorporateAccountRequest.objects.filter(status='approved').exclude(phone='')
        for account_request in requests:
            queue_target(
                account_request.phone,
                country=DEFAULT_COUNTRY,
                name=account_request.contact_name,
                source_type=BulkSMSRecipient.SOURCE_CORPORATE,
                corporate_request=account_request,
            )

    target_phones = {item['phone'] for item in target_recipients}
    stale_pending_ids = list(
        bulk_sms.recipients.filter(
            status=BulkSMSRecipient.STATUS_PENDING,
        ).exclude(
            source_type=BulkSMSRecipient.SOURCE_MANUAL,
        ).exclude(
            phone__in=target_phones,
        ).values_list('id', flat=True)
    )
    if stale_pending_ids:
        BulkSMSRecipient.objects.filter(id__in=stale_pending_ids).delete()

    for item in target_recipients:
        added += int(upsert_bulk_sms_recipient(
            bulk_sms,
            item['phone'],
            country=item['country'],
            raw_phone=item['raw_phone'],
            name=item['name'],
            source_type=item['source_type'],
            **item['links'],
        ))

    if bulk_sms.recipient_count:
        bulk_sms.status = BulkSMS.STATUS_RECIPIENTS_READY
        bulk_sms.save(update_fields=['status', 'updated_at'])
    return added


def _bulk_sms_result_message(result):
    response = result.get('response') if isinstance(result, dict) else None
    if isinstance(response, dict):
        return response.get('Text') or json.dumps(response, ensure_ascii=True)
    return result.get('message') if isinstance(result, dict) else ''


def send_pending_bulk_sms_recipients(bulk_sms_id, sent_by_user_id=None, recipient_statuses=None):
    from .tasks import send_pending_bulk_sms_campaign

    bulk_sms = BulkSMS.objects.filter(pk=bulk_sms_id).first()
    if not bulk_sms:
        return {'sent': 0, 'failed': 0, 'error': 'Campaign not found.'}

    sent_by = User.objects.filter(pk=sent_by_user_id).first() if sent_by_user_id else None
    if not sent_by:
        sent_by = User.objects.filter(is_superuser=True).order_by('id').first()
    if not sent_by:
        sent_by = User.objects.filter(is_staff=True).order_by('id').first()

    recipient_statuses = recipient_statuses or [BulkSMSRecipient.STATUS_PENDING]
    should_prepare_pending = BulkSMSRecipient.STATUS_PENDING in recipient_statuses
    if should_prepare_pending and not bulk_sms.recipients.filter(status=BulkSMSRecipient.STATUS_PENDING).exists():
        prepare_bulk_sms_recipients(bulk_sms)

    target_recipients = list(bulk_sms.recipients.filter(status__in=recipient_statuses).order_by('id'))
    chunk_size = max(int(getattr(settings, 'BULK_SMS_CHUNK_SIZE', 100) or 100), 1)
    current_chunk = target_recipients[:chunk_size]

    if not current_chunk:
        bulk_sms.status = _campaign_stop_status(bulk_sms)
        bulk_sms.save(update_fields=['status', 'updated_at'])
        sync_bulk_sms_status(bulk_sms)
        return {
            'sent': 0,
            'failed': 0,
            'campaign_id': bulk_sms.id,
            'next_task_id': None,
            'processed_in_chunk': 0,
            'chunk_size': chunk_size,
        }

    bulk_sms.status = BulkSMS.STATUS_SENDING
    bulk_sms.save(update_fields=['status', 'updated_at'])

    result = send_bulk_sms(
        [recipient.phone for recipient in current_chunk],
        bulk_sms.body,
        country=DEFAULT_COUNTRY,
        sms_type=bulk_sms.sms_type,
        context={
            'source': 'dashboard_bulk_sms_campaign',
            'bulk_sms_id': bulk_sms.id,
            'recipient_ids': [recipient.id for recipient in current_chunk],
        },
    )

    response = result.get('response') if isinstance(result, dict) else None
    provider_status = str(result.get('provider_status') or '') if isinstance(result, dict) else ''
    message_ids = []
    if isinstance(response, dict):
        message_ids = [item.strip() for item in str(response.get('Message_ID') or '').split(',') if item.strip()]

    sent = 0
    failed = 0
    now = timezone.now()
    message_text = _bulk_sms_result_message(result)
    send_ok = isinstance(result, dict) and result.get('status') == 'sent'

    for index, recipient in enumerate(current_chunk):
        provider_message_id = message_ids[index] if index < len(message_ids) else ''
        if send_ok:
            recipient.status = BulkSMSRecipient.STATUS_SENT
            recipient.error_message = ''
            recipient.provider_message_id = provider_message_id or None
            recipient.sent_at = now
            recipient.save(update_fields=['status', 'error_message', 'provider_message_id', 'sent_at'])
            BulkSMSSendLog.objects.create(
                bulk_sms=bulk_sms,
                recipient=recipient,
                phone=recipient.phone,
                status=BulkSMSRecipient.STATUS_SENT,
                message=message_text,
                provider_status=provider_status,
                provider_message_id=provider_message_id or None,
                sent_by=sent_by,
            )
            sent += 1
        else:
            error_text = message_text or (result.get('reason') if isinstance(result, dict) else 'SMS send failed.') or 'SMS send failed.'
            recipient.status = BulkSMSRecipient.STATUS_FAILED
            recipient.error_message = error_text
            recipient.save(update_fields=['status', 'error_message'])
            BulkSMSSendLog.objects.create(
                bulk_sms=bulk_sms,
                recipient=recipient,
                phone=recipient.phone,
                status=BulkSMSRecipient.STATUS_FAILED,
                message=error_text,
                provider_status=provider_status,
                sent_by=sent_by,
            )
            failed += 1

        remaining_delay = max(float(getattr(settings, 'BULK_SMS_DELAY_SECONDS', DEFAULT_BULK_SMS_DELAY_SECONDS) or 0), 0)
        while remaining_delay > 0:
            sleep_slice = min(0.5, remaining_delay)
            time.sleep(sleep_slice)
            remaining_delay -= sleep_slice
            bulk_sms.refresh_from_db(fields=['status'])
            if bulk_sms.status != BulkSMS.STATUS_SENDING:
                remaining_delay = 0
                break

    bulk_sms.refresh_from_db()
    remaining_recipients = bulk_sms.recipients.filter(status__in=recipient_statuses).exclude(pk__in=[recipient.id for recipient in current_chunk]).order_by('id')
    next_task_id = None
    if bulk_sms.status == BulkSMS.STATUS_SENDING and remaining_recipients.exists():
        next_task = send_pending_bulk_sms_campaign.delay(
            bulk_sms.id,
            sent_by.id if sent_by else None,
            recipient_statuses,
        )
        next_task_id = next_task.id
    elif bulk_sms.status == BulkSMS.STATUS_SENDING:
        bulk_sms.status = _campaign_stop_status(bulk_sms)
        bulk_sms.save(update_fields=['status', 'updated_at'])
    sync_bulk_sms_status(bulk_sms)

    return {
        'sent': sent,
        'failed': failed,
        'campaign_id': bulk_sms.id,
        'next_task_id': next_task_id,
        'processed_in_chunk': sent + failed,
        'chunk_size': chunk_size,
    }
