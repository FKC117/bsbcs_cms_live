import os
import sys

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'conference.settings')

import django

django.setup()

from registration.models import PaymentStatus
from registration.pdf_utils import generate_invoice

qs = PaymentStatus.objects.filter(status='completed').exclude(participant__isnull=True).order_by('-updated_at')[:5]
print('found', qs.count())
if qs.exists():
    p = qs[0]
    print('participant', getattr(p.participant, 'name', None), getattr(p.participant, 'email', None), 'event', getattr(p.event, 'name', None), 'amount', p.amount)
    path = generate_invoice(p.participant, p.event, p)
    print('invoice_path', path)
    print('exists', os.path.exists(path))
    print('qr_code_field', p.qr_code.name if p.qr_code else None)
    if p.qr_code:
        try:
            print('qr_code_exists', os.path.exists(p.qr_code.path))
        except Exception as e:
            print('qr_code path error', e)
