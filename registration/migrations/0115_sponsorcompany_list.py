from django.db import migrations


def seed_sponsor_companies(apps, schema_editor):
    Sponsor = apps.get_model('registration', 'Sponsor')
    SponsorCompany = apps.get_model('registration', 'SponsorCompany')
    FinanceSponsorshipIncome = apps.get_model('registration', 'FinanceSponsorshipIncome')

    created = {}
    for name in Sponsor.objects.order_by('name').values_list('name', flat=True):
        cleaned = (name or '').strip()
        if not cleaned:
            continue
        company, _ = SponsorCompany.objects.get_or_create(name=cleaned)
        created[cleaned.lower()] = company.pk

    for row in FinanceSponsorshipIncome.objects.all():
        cleaned = (row.company_name or '').strip()
        if not cleaned:
            continue
        company_pk = created.get(cleaned.lower())
        if not company_pk:
            company, _ = SponsorCompany.objects.get_or_create(name=cleaned)
            company_pk = company.pk
            created[cleaned.lower()] = company_pk
        row.sponsor_company_id = company_pk
        row.save(update_fields=['sponsor_company'])


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0118_sponsorcompany_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_sponsor_companies, migrations.RunPython.noop),
    ]
