from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0106_eventdrivelink'),
    ]

    operations = [
        migrations.CreateModel(
            name='SystemSMSSendLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('template_key', models.CharField(blank=True, choices=[('registration_submission', 'Registration submission'), ('registration_approval', 'Registration approval / payment'), ('registration_confirmation', 'Registration confirmation'), ('abstract_submission', 'Abstract submission'), ('abstract_approval', 'Abstract approval'), ('registration_payment_received', 'Registration payment received'), ('membership_submission', 'Membership submission'), ('membership_payment_received', 'Membership payment received'), ('membership_approval', 'Membership approval'), ('membership_rejection', 'Membership rejection')], max_length=80, null=True)),
                ('source', models.CharField(blank=True, max_length=80, null=True)),
                ('phone', models.CharField(max_length=20)),
                ('country', models.CharField(blank=True, max_length=120, null=True)),
                ('sms_type', models.CharField(choices=[('masking', 'Masking'), ('non_masking', 'Non-masking')], default='masking', max_length=20)),
                ('fallback_from_sms_type', models.CharField(blank=True, choices=[('masking', 'Masking'), ('non_masking', 'Non-masking')], max_length=20, null=True)),
                ('status', models.CharField(choices=[('sent', 'Sent'), ('failed', 'Failed'), ('skipped', 'Skipped')], max_length=20)),
                ('message', models.TextField(blank=True, null=True)),
                ('provider_status', models.CharField(blank=True, max_length=50, null=True)),
                ('provider_message_id', models.CharField(blank=True, max_length=120, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='system_sms_logs', to='registration.event')),
                ('participant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='system_sms_logs', to='registration.participant')),
                ('user_profile', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='system_sms_logs', to='registration.userprofile')),
            ],
            options={
                'verbose_name': 'System SMS log',
                'verbose_name_plural': 'System SMS logs',
                'ordering': ['-created_at'],
            },
        ),
    ]
