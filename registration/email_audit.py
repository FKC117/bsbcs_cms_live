from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone


DEFAULT_BULK_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H = 400
DEFAULT_TOTAL_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H = 470
DEFAULT_EMAIL_QUOTA_WINDOW_HOURS = 24


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


def get_email_quota_limits():
    bulk_limit = int(getattr(settings, 'BULK_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H', DEFAULT_BULK_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H) or 0)
    total_limit = int(getattr(settings, 'TOTAL_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H', DEFAULT_TOTAL_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H) or 0)
    window_hours = int(getattr(settings, 'EMAIL_QUOTA_WINDOW_HOURS', DEFAULT_EMAIL_QUOTA_WINDOW_HOURS) or DEFAULT_EMAIL_QUOTA_WINDOW_HOURS)
    return {
        'bulk_limit': max(bulk_limit, 0),
        'total_limit': max(total_limit, 0),
        'reserved_non_bulk': max(total_limit - bulk_limit, 0),
        'window_hours': max(window_hours, 1),
    }


def get_email_quota_snapshot(*, now=None):
    from .models import EmailAuditLog

    limits = get_email_quota_limits()
    now = now or timezone.now()
    window_start = now - timedelta(hours=limits['window_hours'])
    audit_logs = EmailAuditLog.objects.filter(
        status=EmailAuditLog.STATUS_SENT,
        sent_at__gte=window_start,
    ).only('category', 'recipients', 'sent_at')

    total_seen = set()
    bulk_seen = set()
    non_bulk_seen = set()

    for log in audit_logs.iterator():
        recipients = normalize_email_recipients(log.recipients)
        for recipient in recipients:
            key = recipient.lower()
            total_seen.add(key)
            if log.category == EmailAuditLog.CATEGORY_BULK_EMAIL:
                bulk_seen.add(key)
            else:
                non_bulk_seen.add(key)

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
        'bulk_used': bulk_used,
        'non_bulk_used': non_bulk_used,
        'total_used': total_used,
        'bulk_remaining': max(limits['bulk_limit'] - bulk_used, 0),
        'non_bulk_remaining': max(limits['reserved_non_bulk'] - non_bulk_used, 0),
        'total_remaining': max(limits['total_limit'] - total_used, 0),
        'bulk_seen': bulk_seen,
        'total_seen': total_seen,
    }


def plan_bulk_email_send(recipients, *, quota_snapshot=None):
    quota_snapshot = quota_snapshot or get_email_quota_snapshot()
    remaining_bulk = quota_snapshot['bulk_remaining']
    remaining_total = quota_snapshot['total_remaining']
    bulk_seen = set(quota_snapshot['bulk_seen'])
    total_seen = set(quota_snapshot['total_seen'])

    allowed_recipient_ids = []
    blocked_recipient_ids = []

    for recipient in recipients:
        recipients_for_quota = normalize_email_recipients([getattr(recipient, 'email', '')])
        if not recipients_for_quota:
            allowed_recipient_ids.append(recipient.id)
            continue

        recipient_key = recipients_for_quota[0].lower()
        consumes_bulk = recipient_key not in bulk_seen
        consumes_total = recipient_key not in total_seen

        if consumes_bulk and remaining_bulk <= 0:
            blocked_recipient_ids.append(recipient.id)
            continue
        if consumes_total and remaining_total <= 0:
            blocked_recipient_ids.append(recipient.id)
            continue

        allowed_recipient_ids.append(recipient.id)
        if consumes_bulk:
            bulk_seen.add(recipient_key)
            remaining_bulk -= 1
        if consumes_total:
            total_seen.add(recipient_key)
            remaining_total -= 1

    return {
        'recipient_ids': allowed_recipient_ids,
        'allowed_count': len(allowed_recipient_ids),
        'blocked_count': len(blocked_recipient_ids),
        'blocked_recipient_ids': blocked_recipient_ids,
        'quota_snapshot': quota_snapshot,
        'bulk_remaining_after': max(remaining_bulk, 0),
        'total_remaining_after': max(remaining_total, 0),
    }


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
