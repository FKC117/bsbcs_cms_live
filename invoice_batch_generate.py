import os
import sys
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'conference.settings')
import django

django.setup()

from registration.models import PaymentStatus, CorporatePayment
from registration.pdf_utils import generate_invoice, generate_corporate_invoice
from website.utils_membership import generate_membership_invoice

results = []

# Regular participant invoice
regular = PaymentStatus.objects.filter(
    participant__registration_type='regular',
    status__in=['completed', 'paid']
).select_related('participant', 'event').order_by('-updated_at').first()
if regular:
    path = generate_invoice(regular.participant, regular.event, regular)
    results.append(('regular', regular.participant.name, regular.participant.email, path))
else:
    results.append(('regular', None, None, 'NOT_FOUND'))

# Member event registration invoice
member = PaymentStatus.objects.filter(
    participant__registration_type='member',
    status__in=['completed', 'paid']
).select_related('participant', 'event').order_by('-updated_at').first()
if member:
    path = generate_invoice(member.participant, member.event, member)
    results.append(('member', member.participant.name, member.participant.email, path))
else:
    results.append(('member', None, None, 'NOT_FOUND'))

# Company person registration invoice
company_person = PaymentStatus.objects.filter(
    participant__registration_type='company_person',
    status__in=['completed', 'paid']
).select_related('participant', 'event').order_by('-updated_at').first()
if company_person:
    path = generate_invoice(company_person.participant, company_person.event, company_person)
    results.append(('company_person', company_person.participant.name, company_person.participant.email, path))
else:
    results.append(('company_person', None, None, 'NOT_FOUND'))

# Complementary registration invoice
complementary = PaymentStatus.objects.filter(
    participant__registration_type='complementary',
    status__in=['completed', 'paid']
).select_related('participant', 'event').order_by('-updated_at').first()
if complementary:
    path = generate_invoice(complementary.participant, complementary.event, complementary)
    results.append(('complementary', complementary.participant.name, complementary.participant.email, path))
else:
    results.append(('complementary', None, None, 'NOT_FOUND'))

# Corporate attendee registration invoice
corporate_payment = CorporatePayment.objects.filter(
    status__in=['completed', 'paid']
).select_related('corporate_account', 'event').order_by('-updated_at').first()
if corporate_payment:
    path = generate_corporate_invoice(corporate_payment)
    results.append(('corporate', corporate_payment.corporate_account.company_name, None, path))
else:
    results.append(('corporate', None, None, 'NOT_FOUND'))

print('=== INVOICE GENERATION RESULTS ===')
for category, name, email, path in results:
    print(f'{category}: name={name or "-"} email={email or "-"} path={path}')

# Also print where each file is stored
for category, name, email, path in results:
    if path and path != 'NOT_FOUND':
        print(f'EXISTS {category}:', os.path.exists(path), '->', path)
