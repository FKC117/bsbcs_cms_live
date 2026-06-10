import os
import sys
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'conference.settings')
import django

django.setup()

from registration.models import CorporateEventRegistration, CorporatePayment, CorporateEventAttendee

for reg_type in ['company_person', 'complementary', 'regular']:
    regs = CorporateEventRegistration.objects.filter(registration_type=reg_type)
    print(f'{reg_type} corporate registrations count=', regs.count())
    for reg in regs[:5]:
        print(' ', reg.id, reg.corporate_account.company_name, reg.event.name, 'attendees=', reg.attendees.count(), 'status=', reg.status)
        payments = CorporatePayment.objects.filter(corporate_registration=reg)
        print('    payments=', payments.count(), [p.status for p in payments])

# corporate payments overall
corp_payments = CorporatePayment.objects.filter(status__in=['completed', 'paid'])
print('corporate payments completed/paid=', corp_payments.count())
for payment in corp_payments[:5]:
    print(' ', payment.id, payment.corporate_account.company_name, payment.event.name, payment.status, payment.amount)
