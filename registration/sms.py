import json
import logging
import re
from math import ceil
from typing import Iterable

import requests
from django.conf import settings
from django.core.exceptions import ValidationError

from .forms import DEFAULT_COUNTRY, is_sms_eligible_phone, normalize_phone_number


logger = logging.getLogger('sms')
SUCCESS_STATUSES = {'0', 0}
SMS_TYPE_MASKING = 'masking'
SMS_TYPE_NON_MASKING = 'non_masking'
SYSTEM_SMS_TEMPLATE_DEFAULTS = {
    'registration_submission': {'label': 'Registration submission', 'description': 'Sent right after a participant submits event registration.', 'available_variables': 'participant_name, event_name, event_year', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: Your registration for {{ event_name }} {{ event_year }} has been submitted successfully. We will notify you after review.'},
    'registration_approval': {'label': 'Registration approval / payment', 'description': 'Sent after admin approval when payment is still required.', 'available_variables': 'participant_name, event_name, event_year', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: Your registration for {{ event_name }} {{ event_year }} has been approved. Please check your email for the payment link and next steps.'},
    'registration_confirmation': {'label': 'Registration confirmation', 'description': 'Sent after admin free confirmation or completed confirmation flow.', 'available_variables': 'participant_name, event_name, event_year', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: Your registration for {{ event_name }} {{ event_year }} is confirmed successfully. Please check your email for details.'},
    'abstract_submission': {'label': 'Abstract submission', 'description': 'Sent right after abstract submission.', 'available_variables': 'participant_name, event_name, event_year, abstract_title', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: Your abstract has been submitted successfully for {{ event_name }} {{ event_year }}.'},
    'abstract_approval': {'label': 'Abstract approval', 'description': 'Sent after abstract approval decision.', 'available_variables': 'participant_name, event_name, event_year, approval_type, abstract_title', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: Your abstract has been approved for {{ approval_type }} in {{ event_name }} {{ event_year }}.'},
    'registration_payment_received': {'label': 'Registration payment received', 'description': 'Sent after event payment is completed.', 'available_variables': 'participant_name, event_name, event_year, transaction_reference', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: We received your payment (TRXID: {{ transaction_reference }}) for {{ event_name }} {{ event_year }}.'},
    'membership_submission': {'label': 'Membership submission', 'description': 'Sent after membership form submission.', 'available_variables': 'member_name', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: Your membership application has been submitted successfully. We will notify you after review.'},
    'membership_payment_received': {'label': 'Membership payment received', 'description': 'Sent after membership payment is completed.', 'available_variables': 'member_name, membership_type, transaction_reference', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: We received your membership payment (TRXID: {{ transaction_reference }}) for {{ membership_type }}.'},
    'membership_approval': {'label': 'Membership approval', 'description': 'Sent after membership approval.', 'available_variables': 'member_name', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: Your membership application has been approved. Please log in to continue.'},
    'membership_rejection': {'label': 'Membership rejection', 'description': 'Sent after membership rejection or update.', 'available_variables': 'member_name', 'sms_type': SMS_TYPE_MASKING, 'body': 'BSBCS: Your membership application has been updated. Please check your email for details.'},
}


def get_system_sms_template_defaults():
    return {key: value.copy() for key, value in SYSTEM_SMS_TEMPLATE_DEFAULTS.items()}


def ensure_system_sms_templates():
    from .models import SystemSMSTemplate

    for template_key, defaults in SYSTEM_SMS_TEMPLATE_DEFAULTS.items():
        SystemSMSTemplate.objects.get_or_create(
            template_key=template_key,
            defaults={
                'label': defaults['label'],
                'description': defaults['description'],
                'available_variables': defaults['available_variables'],
                'sms_type': defaults['sms_type'],
                'body': defaults['body'],
            },
        )


def _render_sms_template_text(body, context=None):
    context = context or {}

    def replace(match):
        key = (match.group(1) or '').strip()
        value = context.get(key, '')
        return '' if value is None else str(value)

    return re.sub(r'\{\{\s*([a-zA-Z0-9_]+)\s*\}\}', replace, body or '')


def get_system_sms_content(template_key, context=None):
    from .models import SystemSMSTemplate

    defaults = SYSTEM_SMS_TEMPLATE_DEFAULTS.get(template_key)
    if defaults is None:
        return {'body': '', 'sms_type': SMS_TYPE_MASKING, 'template': None, 'defaults': None}

    try:
        template = SystemSMSTemplate.objects.filter(template_key=template_key).first()
    except Exception:
        template = None

    body = template.body if template and template.body else defaults['body']
    sms_type = normalize_sms_type(template.sms_type if template and template.sms_type else defaults['sms_type'])
    return {'body': _render_sms_template_text(body, context=context), 'sms_type': SMS_TYPE_MASKING, 'fallback_sms_type': SMS_TYPE_NON_MASKING, 'template': template, 'defaults': defaults}


def _mask_phone(phone):
    phone = (phone or '').strip()
    if len(phone) <= 7:
        return phone
    return f"{phone[:4]}***{phone[-3:]}"


def _extract_provider_message_id(response_data):
    if not isinstance(response_data, dict):
        return ''
    return str(response_data.get('Message_ID') or response_data.get('messageid') or response_data.get('messageId') or '').strip()


def _record_system_sms_log(*, phone, country, message, context, result):
    template_key = (context or {}).get('system_sms_template_key') or (context or {}).get('template_key')
    if not template_key:
        return

    from .models import SystemSMSSendLog

    SystemSMSSendLog.objects.create(
        template_key=template_key,
        source=(context or {}).get('source') or '',
        phone=phone,
        country=country or '',
        sms_type=normalize_sms_type(result.get('sms_type')),
        fallback_from_sms_type=normalize_sms_type(result.get('fallback_from_sms_type')) if result.get('fallback_from_sms_type') else None,
        status=(result.get('status') or SystemSMSSendLog.STATUS_FAILED),
        message=message,
        provider_status='' if result.get('provider_status') is None else str(result.get('provider_status')),
        provider_message_id=_extract_provider_message_id(result.get('response')),
        event_id=(context or {}).get('event_id') or None,
        participant_id=(context or {}).get('participant_id') or None,
        user_profile_id=(context or {}).get('user_profile_id') or None,
    )


def _response_preview(value, *, limit=300):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=True)
    else:
        text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}..."


def normalize_sms_type(sms_type=None):
    return SMS_TYPE_MASKING if sms_type == SMS_TYPE_MASKING else SMS_TYPE_NON_MASKING


def resolve_sms_caller_id(sms_type=None):
    sms_type = normalize_sms_type(sms_type)
    if sms_type == SMS_TYPE_MASKING:
        return (getattr(settings, 'SMS_GATEWAY_MASKING_CALLER_ID', '') or getattr(settings, 'SMS_GATEWAY_CALLER_ID', '')).strip()
    return (getattr(settings, 'SMS_GATEWAY_NON_MASKING_CALLER_ID', '') or getattr(settings, 'SMS_GATEWAY_CALLER_ID', '')).strip()


def get_sms_segment_char_limit(sms_type=None):
    sms_type = normalize_sms_type(sms_type)
    if sms_type == SMS_TYPE_MASKING:
        return max(int(getattr(settings, 'SMS_MASKING_CHAR_LIMIT', 160) or 160), 1)
    return max(int(getattr(settings, 'SMS_NON_MASKING_CHAR_LIMIT', 160) or 160), 1)


def calculate_sms_segments(message, sms_type=None):
    normalized_message = '' if message is None else str(message)
    character_count = len(normalized_message)
    segment_char_limit = get_sms_segment_char_limit(sms_type)
    segment_count = int(ceil(character_count / segment_char_limit)) if character_count else 0
    return {
        'sms_type': normalize_sms_type(sms_type),
        'characters': character_count,
        'segment_char_limit': segment_char_limit,
        'segments': segment_count,
    }


def estimate_sms_units(message, recipient_count=0, sms_type=None):
    summary = calculate_sms_segments(message, sms_type=sms_type)
    summary['recipient_count'] = max(int(recipient_count or 0), 0)
    summary['estimated_total_units'] = summary['segments'] * summary['recipient_count']
    return summary


def resolve_sms_url(*, is_bulk=False):
    if is_bulk:
        return (getattr(settings, 'SMS_GATEWAY_BULK_URL', '') or getattr(settings, 'SMS_GATEWAY_URL', '')).strip()
    return (getattr(settings, 'SMS_GATEWAY_SINGLE_URL', '') or getattr(settings, 'SMS_GATEWAY_URL', '')).strip()


def _gateway_ready(sms_type=None, *, is_bulk=False):
    return all([
        resolve_sms_url(is_bulk=is_bulk),
        getattr(settings, 'SMS_GATEWAY_API_KEY', '').strip(),
        getattr(settings, 'SMS_GATEWAY_SECRET_KEY', '').strip(),
        resolve_sms_caller_id(sms_type),
    ])


def _normalize_destination(phone, country):
    try:
        normalized = normalize_phone_number(phone, country or DEFAULT_COUNTRY)
    except ValidationError as exc:
        return '', str(exc)

    if not is_sms_eligible_phone(country or DEFAULT_COUNTRY, normalized):
        return '', 'SMS is allowed only for valid Bangladesh mobile numbers.'
    return normalized, ''


def _gateway_auth_payload():
    return {
        'apikey': settings.SMS_GATEWAY_API_KEY,
        'secretkey': settings.SMS_GATEWAY_SECRET_KEY,
    }


def _gateway_auth_params():
    return {
        'apikey': settings.SMS_GATEWAY_API_KEY,
        'secretkey': settings.SMS_GATEWAY_SECRET_KEY,
    }


def _build_payload(to_user, message, *, sms_type=None):
    payload = {
        **_gateway_auth_payload(),
        'callerID': resolve_sms_caller_id(sms_type),
        'toUser': to_user,
        'messageContent': message,
    }
    sms_hash = getattr(settings, 'SMS_GATEWAY_HASH', '').strip()
    if sms_hash:
        payload['hash'] = sms_hash
    return payload


def _build_bulk_campaign_payload(phone_numbers, message, *, sms_type=None):
    payload = {
        **_gateway_auth_payload(),
        'content': [
            {
                'callerID': resolve_sms_caller_id(sms_type),
                'toUser': ','.join(phone_numbers),
                'messageContent': message,
            }
        ],
    }
    sms_hash = getattr(settings, 'SMS_GATEWAY_HASH', '').strip()
    if sms_hash:
        payload['hash'] = sms_hash
    return payload


def _perform_sms_get_request(url, *, params, context=None, log_label='SMS GET API'):
    context = context or {}
    if not url:
        return {'status': 'skipped', 'reason': 'gateway_not_configured'}

    try:
        response = requests.get(
            url,
            params=params,
            timeout=getattr(settings, 'SMS_REQUEST_TIMEOUT', 15),
        )
        try:
            response_data = response.json()
        except ValueError:
            response_data = response.text
    except requests.RequestException as exc:
        logger.exception('%s request failed. context=%s', log_label, context)
        return {'status': 'failed', 'reason': 'request_exception', 'message': str(exc)}

    provider_status = response_data.get('Status') if isinstance(response_data, dict) else None
    ok = response.ok and (provider_status in SUCCESS_STATUSES or provider_status is None)
    log_method = logger.info if ok else logger.warning
    log_method(
        '%s response. http_status=%s provider_status=%s response=%s context=%s',
        log_label,
        response.status_code,
        provider_status,
        _response_preview(response_data),
        context,
    )
    return {
        'status': 'ok' if ok else 'failed',
        'http_status': response.status_code,
        'provider_status': provider_status,
        'response': response_data,
        'url': url,
    }


def query_sms_status(message_id, *, context=None):
    message_id = (message_id or '').strip()
    if not message_id:
        return {'status': 'skipped', 'reason': 'missing_message_id'}
    return _perform_sms_get_request(
        getattr(settings, 'SMS_GATEWAY_DLR_URL', '').strip(),
        params={**_gateway_auth_params(), 'messageid': message_id},
        context=context,
        log_label='SMS status API',
    )


def query_sms_multi_status(message_ids, *, context=None):
    if isinstance(message_ids, str):
        values = [item.strip() for item in message_ids.replace('\n', ',').split(',') if item.strip()]
    else:
        values = [str(item).strip() for item in (message_ids or []) if str(item).strip()]
    if not values:
        return {'status': 'skipped', 'reason': 'missing_message_ids'}
    return _perform_sms_get_request(
        getattr(settings, 'SMS_GATEWAY_MULTI_STATUS_URL', '').strip(),
        params={**_gateway_auth_params(), 'messageids': ','.join(values)},
        context=context,
        log_label='SMS multi-status API',
    )


def query_sms_balance(*, context=None):
    client_id = getattr(settings, 'SMS_GATEWAY_CLIENT_ID', '').strip()
    if not client_id:
        return {'status': 'skipped', 'reason': 'missing_client_id'}
    return _perform_sms_get_request(
        getattr(settings, 'SMS_GATEWAY_BALANCE_URL', '').strip(),
        params={'client': client_id},
        context=context,
        log_label='SMS balance API',
    )


def send_sms(phone, message, *, country=DEFAULT_COUNTRY, context=None, sms_type=SMS_TYPE_NON_MASKING, fallback_sms_type=None):
    context = context or {}
    message = (message or '').strip()
    if not message:
        logger.warning('SMS skipped because message body is empty. context=%s', context)
        return {'status': 'skipped', 'reason': 'empty_message'}

    normalized_phone, error = _normalize_destination(phone, country)
    if not normalized_phone:
        logger.info('SMS skipped because destination is not eligible. phone=%s country=%s reason=%s context=%s', _mask_phone(phone), country, error, context)
        return {'status': 'skipped', 'reason': 'ineligible_phone', 'message': error}

    if not getattr(settings, 'SMS_ENABLED', False):
        logger.info('SMS skipped because SMS is disabled. to=%s context=%s', _mask_phone(normalized_phone), context)
        return {'status': 'skipped', 'reason': 'disabled', 'phone': normalized_phone}

    if not _gateway_ready(sms_type, is_bulk=False):
        logger.warning('SMS skipped because gateway configuration is incomplete. to=%s context=%s', _mask_phone(normalized_phone), context)
        return {'status': 'skipped', 'reason': 'gateway_not_configured', 'phone': normalized_phone}

    attempted_sms_type = normalize_sms_type(sms_type)
    attempted_fallback_sms_type = normalize_sms_type(fallback_sms_type) if fallback_sms_type else None

    def _submit(current_sms_type):
        payload = _build_payload(normalized_phone, message, sms_type=current_sms_type)
        try:
            response = requests.post(
                resolve_sms_url(is_bulk=False),
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=getattr(settings, 'SMS_REQUEST_TIMEOUT', 15),
            )
            try:
                response_data = response.json()
            except ValueError:
                response_data = response.text
        except requests.RequestException as exc:
            logger.exception('SMS request failed. to=%s sms_type=%s context=%s', _mask_phone(normalized_phone), current_sms_type, context)
            return {'status': 'failed', 'reason': 'request_exception', 'phone': normalized_phone, 'message': str(exc), 'sms_type': current_sms_type}

        provider_status = response_data.get('Status') if isinstance(response_data, dict) else None
        ok = response.ok and provider_status in SUCCESS_STATUSES
        log_method = logger.info if ok else logger.warning
        log_method(
            'SMS provider response. to=%s sms_type=%s http_status=%s provider_status=%s response=%s context=%s',
            _mask_phone(normalized_phone),
            current_sms_type,
            response.status_code,
            provider_status,
            _response_preview(response_data),
            context,
        )
        return {
            'status': 'sent' if ok else 'failed',
            'phone': normalized_phone,
            'http_status': response.status_code,
            'provider_status': provider_status,
            'response': response_data,
            'sms_type': current_sms_type,
        }

    result = _submit(attempted_sms_type)
    if result.get('status') == 'sent' or not attempted_fallback_sms_type or attempted_fallback_sms_type == attempted_sms_type:
        _record_system_sms_log(phone=normalized_phone, country=country, message=message, context=context, result=result)
        return result

    logger.warning('SMS primary route failed; trying fallback sender. to=%s primary=%s fallback=%s context=%s', _mask_phone(normalized_phone), attempted_sms_type, attempted_fallback_sms_type, context)
    fallback_result = _submit(attempted_fallback_sms_type)
    fallback_result['fallback_from_sms_type'] = attempted_sms_type
    _record_system_sms_log(phone=normalized_phone, country=country, message=message, context=context, result=fallback_result)
    return fallback_result


def send_bulk_sms(phone_numbers: Iterable[str], message, *, country=DEFAULT_COUNTRY, context=None, sms_type=SMS_TYPE_NON_MASKING):
    context = context or {}
    normalized_numbers = []
    skipped_numbers = []
    seen = set()

    for phone in phone_numbers or []:
        normalized_phone, error = _normalize_destination(phone, country)
        if not normalized_phone:
            skipped_numbers.append({'phone': phone, 'reason': error})
            continue
        if normalized_phone in seen:
            continue
        seen.add(normalized_phone)
        normalized_numbers.append(normalized_phone)

    if not normalized_numbers:
        logger.info('Bulk SMS skipped because no eligible Bangladesh numbers were found. context=%s skipped=%s', context, skipped_numbers)
        return {'status': 'skipped', 'reason': 'no_eligible_numbers', 'skipped': skipped_numbers}

    if not getattr(settings, 'SMS_ENABLED', False):
        logger.info('Bulk SMS skipped because SMS is disabled. count=%s context=%s', len(normalized_numbers), context)
        return {'status': 'skipped', 'reason': 'disabled', 'numbers': normalized_numbers, 'skipped': skipped_numbers}

    if not _gateway_ready(sms_type, is_bulk=True):
        logger.warning('Bulk SMS skipped because gateway configuration is incomplete. count=%s context=%s', len(normalized_numbers), context)
        return {'status': 'skipped', 'reason': 'gateway_not_configured', 'numbers': normalized_numbers, 'skipped': skipped_numbers}

    message = (message or '').strip()
    payload = _build_bulk_campaign_payload(normalized_numbers, message, sms_type=sms_type)
    try:
        response = requests.post(
            resolve_sms_url(is_bulk=True),
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=getattr(settings, 'SMS_REQUEST_TIMEOUT', 15),
        )
        try:
            response_data = response.json()
        except ValueError:
            response_data = response.text
    except requests.RequestException as exc:
        logger.exception('Bulk SMS request failed. count=%s context=%s', len(normalized_numbers), context)
        return {'status': 'failed', 'reason': 'request_exception', 'numbers': normalized_numbers, 'skipped': skipped_numbers, 'message': str(exc)}

    provider_status = response_data.get('Status') if isinstance(response_data, dict) else None
    ok = response.ok and provider_status in SUCCESS_STATUSES
    log_method = logger.info if ok else logger.warning
    log_method(
        'Bulk SMS provider response. count=%s http_status=%s provider_status=%s response=%s context=%s',
        len(normalized_numbers),
        response.status_code,
        provider_status,
        _response_preview(response_data),
        context,
    )
    return {
        'status': 'sent' if ok else 'failed',
        'numbers': normalized_numbers,
        'skipped': skipped_numbers,
        'http_status': response.status_code,
        'provider_status': provider_status,
        'response': response_data,
    }


def build_registration_submission_sms(participant):
    return get_system_sms_content(
        'registration_submission',
        context={
            'participant_name': participant.name,
            'event_name': participant.event.name,
            'event_year': participant.event.year,
        },
    )['body']


def build_registration_approval_sms(participant):
    return get_system_sms_content(
        'registration_approval',
        context={
            'participant_name': participant.name,
            'event_name': participant.event.name,
            'event_year': participant.event.year,
        },
    )['body']


def build_registration_confirmation_sms(participant):
    return get_system_sms_content(
        'registration_confirmation',
        context={
            'participant_name': participant.name,
            'event_name': participant.event.name,
            'event_year': participant.event.year,
        },
    )['body']


def build_abstract_submission_sms(participant):
    latest_abstract = participant.abstractsubmission_set.order_by('-id').first()
    return get_system_sms_content(
        'abstract_submission',
        context={
            'participant_name': participant.name,
            'event_name': participant.event.name,
            'event_year': participant.event.year,
            'abstract_title': latest_abstract.title if latest_abstract else '',
        },
    )['body']


def build_abstract_approval_sms(abstract, approval_type):
    profile = getattr(abstract.user, 'userprofile', None)
    return get_system_sms_content(
        'abstract_approval',
        context={
            'participant_name': profile.name if profile else getattr(abstract.user, 'username', ''),
            'event_name': abstract.event.name if abstract.event else '',
            'event_year': abstract.event.year if abstract.event else '',
            'approval_type': approval_type,
            'abstract_title': abstract.title,
        },
    )['body']


def build_membership_submission_sms(member):
    return get_system_sms_content(
        'membership_submission',
        context={'member_name': member.user_profile.name if member.user_profile else ''},
    )['body']


def build_membership_approval_sms(member):
    return get_system_sms_content(
        'membership_approval',
        context={'member_name': member.user_profile.name if member.user_profile else ''},
    )['body']


def build_membership_rejection_sms(member):
    return get_system_sms_content(
        'membership_rejection',
        context={'member_name': member.user_profile.name if member.user_profile else ''},
    )['body']


def _payment_transaction_reference(record):
    return getattr(record, 'trxID', None) or getattr(record, 'transaction_id', None) or getattr(record, 'merchant_invoice_number', None) or 'N/A'


def queue_registration_payment_received_sms(payment_status, *, source='registration_payment_completed'):
    from .tasks import send_sms_task

    participant = payment_status.participant
    payload = get_system_sms_content(
        'registration_payment_received',
        context={
            'participant_name': participant.name,
            'event_name': payment_status.event.name,
            'event_year': payment_status.event.year,
            'transaction_reference': _payment_transaction_reference(payment_status),
            'system_sms_template_key': 'registration_payment_received',
        },
    )
    send_sms_task.delay(
        participant.phone,
        payload['body'],
        country=participant.country,
        context={
            'source': source,
            'participant_id': participant.id,
            'event_id': payment_status.event_id,
            'payment_status_id': payment_status.id,
            'transaction_reference': _payment_transaction_reference(payment_status),
        },
        sms_type=payload['sms_type'],
        fallback_sms_type=payload.get('fallback_sms_type'),
    )


def queue_membership_payment_received_sms(payment_record, *, source='membership_payment_completed'):
    from registration.tasks import send_sms_task

    profile = payment_record.user_profile
    payload = get_system_sms_content(
        'membership_payment_received',
        context={
            'member_name': profile.name,
            'membership_type': payment_record.membership_type.name if payment_record.membership_type else 'membership',
            'transaction_reference': _payment_transaction_reference(payment_record),
            'system_sms_template_key': 'membership_payment_received',
        },
    )
    send_sms_task.delay(
        profile.phone,
        payload['body'],
        country=profile.country,
        context={
            'source': source,
            'user_profile_id': profile.id,
            'membership_payment_id': payment_record.id,
            'transaction_reference': _payment_transaction_reference(payment_record),
        },
        sms_type=payload['sms_type'],
        fallback_sms_type=payload.get('fallback_sms_type'),
    )
