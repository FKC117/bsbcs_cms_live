# Generated manually on 2026-07-24

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('registration', '0110_finance_approval_audit'),
    ]

    operations = [
        migrations.CreateModel(
            name='FinanceAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=180, unique=True)),
                ('code', models.CharField(blank=True, max_length=40, null=True, unique=True)),
                ('account_type', models.CharField(choices=[('bank', 'Bank account'), ('petty_cash', 'Petty cash'), ('bkash', 'bKash or mobile wallet'), ('fdr', 'FDR or term deposit'), ('other', 'Other account')], default='bank', max_length=20)),
                ('opening_balance', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('note', models.TextField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Finance account',
                'verbose_name_plural': 'Finance accounts',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='FinanceOtherIncome',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('income_type', models.CharField(choices=[('fdr_interest', 'FDR interest'), ('bank_interest', 'Bank interest'), ('donation', 'Donation'), ('misc', 'Misc income'), ('other', 'Other income')], default='other', max_length=30)),
                ('title', models.CharField(max_length=180)),
                ('source_name', models.CharField(blank=True, max_length=180, null=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('status', models.CharField(choices=[('expected', 'Expected'), ('received', 'Received'), ('cancelled', 'Cancelled')], default='received', max_length=20)),
                ('received_on', models.DateField(blank=True, null=True)),
                ('reference_number', models.CharField(blank=True, max_length=120, null=True)),
                ('proof_file', models.FileField(blank=True, null=True, upload_to='finance/other_income_proofs/')),
                ('note', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='finance_other_incomes', to='registration.event')),
                ('received_account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='other_income_rows', to='registration.financeaccount')),
            ],
            options={
                'verbose_name': 'Finance other income',
                'verbose_name_plural': 'Finance other incomes',
                'ordering': ['-received_on', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='FinanceTransfer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('transfer_date', models.DateField()),
                ('status', models.CharField(choices=[('posted', 'Posted'), ('cancelled', 'Cancelled')], default='posted', max_length=20)),
                ('reference_number', models.CharField(blank=True, max_length=120, null=True)),
                ('note', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='finance_transfers', to='registration.event')),
                ('from_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='outgoing_transfers', to='registration.financeaccount')),
                ('to_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='incoming_transfers', to='registration.financeaccount')),
            ],
            options={
                'verbose_name': 'Finance transfer',
                'verbose_name_plural': 'Finance transfers',
                'ordering': ['-transfer_date', '-created_at'],
            },
        ),
        migrations.AddField(
            model_name='financesponsorshipincome',
            name='received_account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sponsorship_income_rows', to='registration.financeaccount'),
        ),
        migrations.AddField(
            model_name='financevendorpayment',
            name='source_account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vendor_payments', to='registration.financeaccount'),
        ),
    ]
