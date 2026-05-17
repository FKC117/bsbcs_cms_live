import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0070_corporateeventattendee_participant'),
    ]

    operations = [
        migrations.CreateModel(
            name='CorporatePayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('status', models.CharField(choices=[('unpaid', 'Unpaid'), ('initiated', 'Initiated'), ('pending', 'Pending'), ('completed', 'Completed'), ('paid', 'Paid'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], default='unpaid', max_length=20)),
                ('merchant_invoice_number', models.CharField(max_length=255, unique=True)),
                ('transaction_id', models.CharField(blank=True, max_length=255, null=True)),
                ('trxID', models.CharField(blank=True, max_length=255, null=True)),
                ('invoice', models.FileField(blank=True, null=True, upload_to='media/corporate_invoices/')),
                ('email_sent', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('attendees', models.ManyToManyField(blank=True, related_name='corporate_payments', to='registration.corporateeventattendee')),
                ('corporate_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='corporate_payments', to='registration.corporateaccount')),
                ('corporate_registration', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='corporate_payments', to='registration.corporateeventregistration')),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='corporate_payments', to='registration.event')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
