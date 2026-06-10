import os
import sys
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'conference.settings')
import django

django.setup()

from registration.models import CorporateEventRegistration, CorporatePayment
from registration.pdf_utils import generate_corporate_invoice

for reg_type in ['company_person', 'complementary']:
    regs = CorporateEventRegistration.objects.filter(registration_type=reg_type)
    for reg in regs:
        payments = CorporatePayment.objects.filter(corporate_registration=reg)
        for payment in payments:
            path = generate_corporate_invoice(payment)
            print(f'{reg_type} corporate_payment id={payment.id} status={payment.status} amount={payment.amount} path={path} exists={os.path.exists(path)}')
