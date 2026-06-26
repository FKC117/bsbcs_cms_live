from io import BytesIO
import uuid

import qrcode
from django.conf import settings
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils.text import slugify


def registration_qr_payload(payment_status):
    site_url = getattr(settings, 'SITE_URL', 'https://bsbcs.info').rstrip('/')
    path = reverse('registration_qr_checkin', kwargs={'token': payment_status.qr_token})
    return f'{site_url}{path}'


def registration_qr_filename(payment_status):
    participant = payment_status.participant
    event_slug = slugify(f'{payment_status.event.name}-{payment_status.event.year}') or f'event-{payment_status.event_id}'
    event_prefix = event_slug[:32] or f'event-{payment_status.event_id}'
    participant_id = participant.id or 'participant'
    token_suffix = str(payment_status.qr_token).split('-')[0]
    return f'{event_prefix}/p{participant_id}_{token_suffix}.png'


def ensure_registration_qr(payment_status, force=False):
    if not payment_status.qr_token:
        payment_status.qr_token = uuid.uuid4()
        payment_status.save(update_fields=['qr_token', 'updated_at'])

    if payment_status.qr_code and not force:
        try:
            if payment_status.qr_code.storage.exists(payment_status.qr_code.name):
                return payment_status.qr_code.path
        except (NotImplementedError, ValueError):
            return payment_status.qr_code.name

    qr_image = qrcode.make(registration_qr_payload(payment_status))
    buffer = BytesIO()
    qr_image.save(buffer, format='PNG')
    payment_status.qr_code.save(
        registration_qr_filename(payment_status),
        ContentFile(buffer.getvalue()),
        save=False,
    )
    payment_status.save(update_fields=['qr_code', 'updated_at'])
    try:
        return payment_status.qr_code.path
    except NotImplementedError:
        return payment_status.qr_code.name
