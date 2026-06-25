from django.contrib.auth import get_user_model


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
