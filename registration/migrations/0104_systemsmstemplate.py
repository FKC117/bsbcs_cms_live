from django.db import migrations, models


def seed_system_sms_templates(apps, schema_editor):
    SystemSMSTemplate = apps.get_model('registration', 'SystemSMSTemplate')
    defaults = {
        'registration_submission': {'label': 'Registration submission', 'description': 'Sent right after a participant submits event registration.', 'available_variables': 'participant_name, event_name, event_year', 'sms_type': 'masking', 'body': 'BSBCS: Your registration for {{ event_name }} {{ event_year }} has been submitted successfully. We will notify you after review.'},
        'registration_approval': {'label': 'Registration approval / payment', 'description': 'Sent after admin approval when payment is still required.', 'available_variables': 'participant_name, event_name, event_year', 'sms_type': 'masking', 'body': 'BSBCS: Your registration for {{ event_name }} {{ event_year }} has been approved. Please check your email for the payment link and next steps.'},
        'registration_confirmation': {'label': 'Registration confirmation', 'description': 'Sent after admin free confirmation or completed confirmation flow.', 'available_variables': 'participant_name, event_name, event_year', 'sms_type': 'masking', 'body': 'BSBCS: Your registration for {{ event_name }} {{ event_year }} is confirmed successfully. Please check your email for details.'},
        'abstract_submission': {'label': 'Abstract submission', 'description': 'Sent right after abstract submission.', 'available_variables': 'participant_name, event_name, event_year, abstract_title', 'sms_type': 'masking', 'body': 'BSBCS: Your abstract has been submitted successfully for {{ event_name }} {{ event_year }}.'},
        'abstract_approval': {'label': 'Abstract approval', 'description': 'Sent after abstract approval decision.', 'available_variables': 'participant_name, event_name, event_year, approval_type, abstract_title', 'sms_type': 'masking', 'body': 'BSBCS: Your abstract has been approved for {{ approval_type }} in {{ event_name }} {{ event_year }}.'},
        'registration_payment_received': {'label': 'Registration payment received', 'description': 'Sent after event payment is completed.', 'available_variables': 'participant_name, event_name, event_year, transaction_reference', 'sms_type': 'masking', 'body': 'BSBCS: We received your payment (TRXID: {{ transaction_reference }}) for {{ event_name }} {{ event_year }}.'},
        'membership_submission': {'label': 'Membership submission', 'description': 'Sent after membership form submission.', 'available_variables': 'member_name', 'sms_type': 'masking', 'body': 'BSBCS: Your membership application has been submitted successfully. We will notify you after review.'},
        'membership_payment_received': {'label': 'Membership payment received', 'description': 'Sent after membership payment is completed.', 'available_variables': 'member_name, membership_type, transaction_reference', 'sms_type': 'masking', 'body': 'BSBCS: We received your membership payment (TRXID: {{ transaction_reference }}) for {{ membership_type }}.'},
        'membership_approval': {'label': 'Membership approval', 'description': 'Sent after membership approval.', 'available_variables': 'member_name', 'sms_type': 'masking', 'body': 'BSBCS: Your membership application has been approved. Please log in to continue.'},
        'membership_rejection': {'label': 'Membership rejection', 'description': 'Sent after membership rejection or update.', 'available_variables': 'member_name', 'sms_type': 'masking', 'body': 'BSBCS: Your membership application has been updated. Please check your email for details.'},
    }
    for template_key, values in defaults.items():
        SystemSMSTemplate.objects.get_or_create(template_key=template_key, defaults=values)


class Migration(migrations.Migration):
    dependencies = [('registration', '0103_bulksms_sms_type')]
    operations = [
        migrations.CreateModel(
            name='SystemSMSTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('template_key', models.CharField(choices=[('registration_submission', 'Registration submission'), ('registration_approval', 'Registration approval / payment'), ('registration_confirmation', 'Registration confirmation'), ('abstract_submission', 'Abstract submission'), ('abstract_approval', 'Abstract approval'), ('registration_payment_received', 'Registration payment received'), ('membership_submission', 'Membership submission'), ('membership_payment_received', 'Membership payment received'), ('membership_approval', 'Membership approval'), ('membership_rejection', 'Membership rejection')], max_length=80, unique=True)),
                ('label', models.CharField(max_length=120)),
                ('description', models.TextField(blank=True, null=True)),
                ('available_variables', models.TextField(blank=True, null=True)),
                ('sms_type', models.CharField(choices=[('masking', 'Masking'), ('non_masking', 'Non-masking')], default='masking', max_length=20)),
                ('body', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'System SMS template', 'verbose_name_plural': 'System SMS templates', 'ordering': ['label']},
        ),
        migrations.RunPython(seed_system_sms_templates, migrations.RunPython.noop),
    ]
