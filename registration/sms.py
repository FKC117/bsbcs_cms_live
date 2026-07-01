import json
import logging
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


def _mask_phone(phone):
    phone = (phone or '').strip()
    if len(phone) <= 7:
        return phone
    return f"{phone[:4]}***{phone[-3:]}"


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
        return max(int(getattr(settings, 'SMS_MASKING_CHAR_LIMIT', 100) or 100), 1)
    return max(int(getattr(settings, 'SMS_NON_MASKING_CHAR_LIMIT', 100) or 100), 1)


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


def send_sms(phone, message, *, country=DEFAULT_COUNTRY, context=None, sms_type=SMS_TYPE_NON_MASKING):
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

    payload = _build_payload(normalized_phone, message, sms_type=sms_type)
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
        logger.exception('SMS request failed. to=%s context=%s', _mask_phone(normalized_phone), context)
        return {'status': 'failed', 'reason': 'request_exception', 'phone': normalized_phone, 'message': str(exc)}

    provider_status = response_data.get('Status') if isinstance(response_data, dict) else None
    ok = response.ok and provider_status in SUCCESS_STATUSES
    log_method = logger.info if ok else logger.warning
    log_method(
        'SMS provider response. to=%s http_status=%s provider_status=%s response=%s context=%s',
        _mask_phone(normalized_phone),
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
    }


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
    return f"BSBCS: Your registration for {participant.event.name} {participant.event.year} has been submitted successfully. We will notify you after review."


def build_registration_approval_sms(participant):
    return f"BSBCS: Your registration for {participant.event.name} {participant.event.year} has been approved. Please complete payment from your account."


def build_registration_confirmation_sms(participant):
    return f"BSBCS: Your registration for {participant.event.name} {participant.event.year} is confirmed."


def build_abstract_submission_sms(participant):
    return f"BSBCS: Your abstract for {participant.event.name} {participant.event.year} has been submitted successfully."


def build_abstract_approval_sms(abstract, approval_type):
    return f"BSBCS: Your abstract for {abstract.event.name} {abstract.event.year} has been approved for {approval_type.lower()}."


def build_membership_submission_sms(member):
    return 'BSBCS: Your membership application has been submitted successfully. We will notify you after review.'


def build_membership_approval_sms(member):
    return 'BSBCS: Your membership application has been approved. Please log in to continue.'


def build_membership_rejection_sms(member):
    return 'BSBCS: Your membership application has been updated. Please check your email for details.'
