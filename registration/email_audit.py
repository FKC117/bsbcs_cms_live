from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone


DEFAULT_BULK_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H = 400
DEFAULT_TOTAL_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H = 470
DEFAULT_EMAIL_QUOTA_WINDOW_HOURS = 24
DEFAULT_EMAIL_QUOTA_RESERVATION_TTL_MINUTES = 90


def normalize_email_recipients(recipients):
    if not recipients:
        return []
    if isinstance(recipients, str):
        recipients = [recipients]

    normalized = []
    seen = set()
    for recipient in recipients:
        value = (recipient or '').strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized


def _resolve_recipient_entry(recipient):
    value = recipient
    if hasattr(recipient, 'email'):
        value = getattr(recipient, 'email', '')
    normalized = normalize_email_recipients([value])
    if not normalized:
        return {
            'item': recipient,
            'recipient_id': getattr(recipient, 'id', None),
            'email': '',
            'recipient_key': '',
        }
    return {
        'item': recipient,
        'recipient_id': getattr(recipient, 'id', None),
        'email': normalized[0],
        'recipient_key': normalized[0].lower(),
    }


def get_email_quota_limits():
    bulk_limit = int(getattr(settings, 'BULK_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H', DEFAULT_BULK_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H) or 0)
    total_limit = int(getattr(settings, 'TOTAL_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H', DEFAULT_TOTAL_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H) or 0)
    window_hours = int(getattr(settings, 'EMAIL_QUOTA_WINDOW_HOURS', DEFAULT_EMAIL_QUOTA_WINDOW_HOURS) or DEFAULT_EMAIL_QUOTA_WINDOW_HOURS)
    reservation_ttl_minutes = int(getattr(settings, 'EMAIL_QUOTA_RESERVATION_TTL_MINUTES', DEFAULT_EMAIL_QUOTA_RESERVATION_TTL_MINUTES) or DEFAULT_EMAIL_QUOTA_RESERVATION_TTL_MINUTES)
    return {
        'bulk_limit': max(bulk_limit, 0),
        'total_limit': max(total_limit, 0),
        'reserved_non_bulk': max(total_limit - bulk_limit, 0),
        'window_hours': max(window_hours, 1),
        'reservation_ttl_minutes': max(reservation_ttl_minutes, 1),
    }


def cleanup_expired_email_quota_reservations(*, now=None):
    from .models import EmailQuotaReservation

    now = now or timezone.now()
    EmailQuotaReservation.objects.filter(
        status=EmailQuotaReservation.STATUS_RESERVED,
        expires_at__lt=now,
    ).update(
        status=EmailQuotaReservation.STATUS_RELEASED,
        released_at=now,
    )


def get_email_quota_snapshot(*, now=None):
    from .models import EmailAuditLog, EmailQuotaReservation

    limits = get_email_quota_limits()
    now = now or timezone.now()
    cleanup_expired_email_quota_reservations(now=now)
    window_start = now - timedelta(hours=limits['window_hours'])

    audit_logs = EmailAuditLog.objects.filter(
        status=EmailAuditLog.STATUS_SENT,
        sent_at__gte=window_start,
    ).only('category', 'recipients', 'sent_at')

    total_sent_seen = set()
    bulk_sent_seen = set()
    non_bulk_sent_seen = set()

    for log in audit_logs.iterator():
        recipients = normalize_email_recipients(log.recipients)
        for recipient in recipients:
            key = recipient.lower()
            total_sent_seen.add(key)
            if log.category == EmailAuditLog.CATEGORY_BULK_EMAIL:
                bulk_sent_seen.add(key)
            else:
                non_bulk_sent_seen.add(key)

    reservations = EmailQuotaReservation.objects.filter(
        status=EmailQuotaReservation.STATUS_RESERVED,
        expires_at__gte=now,
    ).only('category', 'recipient_key', 'expires_at')

    total_reserved_seen = set()
    bulk_reserved_seen = set()
    non_bulk_reserved_seen = set()

    for reservation in reservations.iterator():
        key = (reservation.recipient_key or '').strip().lower()
        if not key:
            continue
        total_reserved_seen.add(key)
        if reservation.category == EmailAuditLog.CATEGORY_BULK_EMAIL:
            bulk_reserved_seen.add(key)
        else:
            non_bulk_reserved_seen.add(key)

    total_seen = total_sent_seen | total_reserved_seen
    bulk_seen = bulk_sent_seen | bulk_reserved_seen
    non_bulk_seen = non_bulk_sent_seen | non_bulk_reserved_seen

    total_used = len(total_seen)
    bulk_used = len(bulk_seen)
    non_bulk_used = len(non_bulk_seen)

    return {
        'window_start': window_start,
        'window_end': now,
        'window_hours': limits['window_hours'],
        'bulk_limit': limits['bulk_limit'],
        'total_limit': limits['total_limit'],
        'reserved_non_bulk': limits['reserved_non_bulk'],
        'reservation_ttl_minutes': limits['reservation_ttl_minutes'],
        'bulk_used': bulk_used,
        'non_bulk_used': non_bulk_used,
        'total_used': total_used,
        'bulk_remaining': max(limits['bulk_limit'] - bulk_used, 0),
        'non_bulk_remaining': max(limits['reserved_non_bulk'] - non_bulk_used, 0),
        'total_remaining': max(limits['total_limit'] - total_used, 0),
        'bulk_seen': bulk_seen,
        'total_seen': total_seen,
        'bulk_sent_seen': bulk_sent_seen,
        'total_sent_seen': total_sent_seen,
        'bulk_reserved_seen': bulk_reserved_seen,
        'total_reserved_seen': total_reserved_seen,
        'reserved_bulk_count': len(bulk_reserved_seen),
        'reserved_total_count': len(total_reserved_seen),
    }


def plan_email_send(recipients, *, category, quota_snapshot=None):
    from .models import EmailAuditLog

    quota_snapshot = quota_snapshot or get_email_quota_snapshot()
    remaining_bulk = quota_snapshot['bulk_remaining']
    remaining_total = quota_snapshot['total_remaining']
    bulk_seen = set(quota_snapshot['bulk_seen'])
    total_seen = set(quota_snapshot['total_seen'])

    allowed_entries = []
    blocked_entries = []

    for recipient in recipients:
        entry = _resolve_recipient_entry(recipient)
        recipient_key = entry['recipient_key']
        if not recipient_key:
            entry['requires_reservation'] = False
            allowed_entries.append(entry)
            continue

        consumes_total = recipient_key not in total_seen
        consumes_bulk = category == EmailAuditLog.CATEGORY_BULK_EMAIL and recipient_key not in bulk_seen

        if category == EmailAuditLog.CATEGORY_BULK_EMAIL and consumes_bulk and remaining_bulk <= 0:
            blocked_entries.append(entry)
            continue
        if consumes_total and remaining_total <= 0:
            blocked_entries.append(entry)
            continue

        entry['requires_reservation'] = consumes_total or consumes_bulk
        allowed_entries.append(entry)

        if consumes_bulk:
            bulk_seen.add(recipient_key)
            remaining_bulk -= 1
        if consumes_total:
            total_seen.add(recipient_key)
            remaining_total -= 1

    return {
        'allowed_entries': allowed_entries,
        'blocked_entries': blocked_entries,
        'allowed_count': len(allowed_entries),
        'blocked_count': len(blocked_entries),
        'allowed_recipient_ids': [entry['recipient_id'] for entry in allowed_entries if entry['recipient_id'] is not None],
        'blocked_recipient_ids': [entry['recipient_id'] for entry in blocked_entries if entry['recipient_id'] is not None],
        'quota_snapshot': quota_snapshot,
        'bulk_remaining_after': max(remaining_bulk, 0),
        'total_remaining_after': max(remaining_total, 0),
    }


def plan_bulk_email_send(recipients, *, quota_snapshot=None):
    from .models import EmailAuditLog

    plan = plan_email_send(
        recipients,
        category=EmailAuditLog.CATEGORY_BULK_EMAIL,
        quota_snapshot=quota_snapshot,
    )
    return {
        'recipient_ids': plan['allowed_recipient_ids'],
        'allowed_count': plan['allowed_count'],
        'blocked_count': plan['blocked_count'],
        'blocked_recipient_ids': plan['blocked_recipient_ids'],
        'quota_snapshot': plan['quota_snapshot'],
        'bulk_remaining_after': plan['bulk_remaining_after'],
        'total_remaining_after': plan['total_remaining_after'],
    }


def reserve_email_quota(recipients, *, category, reservation_key=None, metadata=None, max_allowed=None, now=None):
    from .models import EmailQuotaLock, EmailQuotaReservation

    recipient_list = list(recipients or [])
    reservation_key = reservation_key or f'quota-{uuid4().hex}'
    now = now or timezone.now()
    limits = get_email_quota_limits()
    expires_at = now + timedelta(minutes=limits['reservation_ttl_minutes'])

    with transaction.atomic():
        lock, _ = EmailQuotaLock.objects.get_or_create(key='global')
        EmailQuotaLock.objects.select_for_update().get(pk=lock.pk)
        cleanup_expired_email_quota_reservations(now=now)
        snapshot = get_email_quota_snapshot(now=now)
        plan = plan_email_send(recipient_list, category=category, quota_snapshot=snapshot)
        allowed_entries = plan['allowed_entries']
        if max_allowed is not None:
            allowed_entries = allowed_entries[:max(int(max_allowed), 0)]

        reservations = []
        reserved_recipient_keys = []
        for entry in allowed_entries:
            if not entry.get('requires_reservation') or not entry.get('recipient_key'):
                continue
            reservations.append(
                EmailQuotaReservation(
                    reservation_key=reservation_key,
                    category=category,
                    recipient_email=entry['email'],
                    recipient_key=entry['recipient_key'],
                    metadata=metadata or {},
                    status=EmailQuotaReservation.STATUS_RESERVED,
                    expires_at=expires_at,
                )
            )
            reserved_recipient_keys.append(entry['recipient_key'])
        if reservations:
            EmailQuotaReservation.objects.bulk_create(reservations)

    return {
        'reservation_key': reservation_key,
        'allowed_entries': allowed_entries,
        'allowed_count': len(allowed_entries),
        'blocked_count': plan['blocked_count'],
        'blocked_entries': plan['blocked_entries'],
        'allowed_recipient_ids': [entry['recipient_id'] for entry in allowed_entries if entry['recipient_id'] is not None],
        'allowed_recipients': [entry['email'] for entry in allowed_entries if entry.get('email')],
        'reserved_recipient_keys': reserved_recipient_keys,
        'quota_snapshot': plan['quota_snapshot'],
        'expires_at': expires_at,
    }


def consume_email_quota_reservations(reservation_key, recipients, *, now=None):
    from .models import EmailQuotaReservation

    recipient_keys = [_resolve_recipient_entry(recipient)['recipient_key'] for recipient in recipients or []]
    recipient_keys = [key for key in recipient_keys if key]
    if not reservation_key or not recipient_keys:
        return 0

    now = now or timezone.now()
    return EmailQuotaReservation.objects.filter(
        reservation_key=reservation_key,
        recipient_key__in=recipient_keys,
        status=EmailQuotaReservation.STATUS_RESERVED,
    ).update(
        status=EmailQuotaReservation.STATUS_CONSUMED,
        consumed_at=now,
    )


def release_email_quota_reservations(reservation_key, recipients=None, *, now=None):
    from .models import EmailQuotaReservation

    if not reservation_key:
        return 0

    filters = {
        'reservation_key': reservation_key,
        'status': EmailQuotaReservation.STATUS_RESERVED,
    }
    if recipients is not None:
        recipient_keys = [_resolve_recipient_entry(recipient)['recipient_key'] for recipient in recipients or []]
        recipient_keys = [key for key in recipient_keys if key]
        if not recipient_keys:
            return 0
        filters['recipient_key__in'] = recipient_keys

    now = now or timezone.now()
    return EmailQuotaReservation.objects.filter(**filters).update(
        status=EmailQuotaReservation.STATUS_RELEASED,
        released_at=now,
    )


def record_email_audit(
    *,
    category,
    subject,
    recipients,
    status='sent',
    metadata=None,
    sent_by_user_id=None,
):
    from .models import EmailAuditLog

    normalized_recipients = normalize_email_recipients(recipients)
    if not normalized_recipients:
        return None

    sent_by = None
    if sent_by_user_id:
        sent_by = get_user_model().objects.filter(pk=sent_by_user_id).first()

    return EmailAuditLog.objects.create(
        category=category,
        subject=(subject or '')[:255],
        recipients=normalized_recipients,
        recipient_count=len(normalized_recipients),
        status=status,
        metadata=metadata or {},
        sent_by=sent_by,
    )
