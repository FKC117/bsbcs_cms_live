import os
import sys
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'conference.settings')
import django

django.setup()

from registration.models import PaymentStatus

types = ['regular', 'member', 'company_person', 'complementary']
for t in types:
    qs = PaymentStatus.objects.filter(participant__registration_type=t).select_related('participant', 'event')
    print(f'{t} count=', qs.count())
    if qs.exists():
        for p in qs[:5]:
            print(' ', p.participant.name, p.participant.email, p.status, p.amount, p.event.name, p.event.member_registration_enabled, p.event.company_person_registration_fee)
