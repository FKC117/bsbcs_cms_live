from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0093_email_button_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='SpeakerOutreachTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject', models.CharField(blank=True, max_length=255, null=True)),
                ('intro_body', models.TextField(blank=True, null=True)),
                ('closing_body', models.TextField(blank=True, null=True)),
                ('airfare_body', models.TextField(blank=True, help_text='Optional paragraph shown when return airfare support is offered.', null=True)),
                ('hotel_body', models.TextField(blank=True, help_text='Optional paragraph shown when hotel accommodation is offered.', null=True)),
                ('allowance_body', models.TextField(blank=True, help_text='Optional paragraph shown when honorarium or allowance is offered.', null=True)),
                ('local_transport_body', models.TextField(blank=True, help_text='Optional paragraph shown when local transport support is offered.', null=True)),
                ('special_support_body', models.TextField(blank=True, help_text='Optional paragraph shown when another special arrangement is offered.', null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='speaker_outreach_template', to='registration.event')),
            ],
            options={
                'verbose_name': 'Speaker outreach template',
                'verbose_name_plural': 'Speaker outreach templates',
            },
        ),
        migrations.CreateModel(
            name='SpeakerOutreachCoordination',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('offer_airfare', models.BooleanField(default=False)),
                ('offer_hotel', models.BooleanField(default=False)),
                ('offer_allowance', models.BooleanField(default=False)),
                ('offer_local_transport', models.BooleanField(default=False)),
                ('offer_special_support', models.BooleanField(default=False)),
                ('custom_notes', models.TextField(blank=True, null=True)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('sent', 'Sent')], default='draft', max_length=20)),
                ('send_count', models.PositiveIntegerField(default=0)),
                ('last_subject', models.CharField(blank=True, max_length=255, null=True)),
                ('last_body', models.TextField(blank=True, null=True)),
                ('last_sent_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='speaker_outreach_rows', to='registration.event')),
                ('last_sent_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='speaker_outreach_sent_rows', to='auth.user')),
                ('person', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='speaker_outreach_rows', to='registration.programperson')),
            ],
            options={
                'verbose_name': 'Speaker outreach coordination row',
                'verbose_name_plural': 'Speaker outreach coordination rows',
                'ordering': ['event__start_date', 'person__name'],
                'unique_together': {('event', 'person')},
            },
        ),
        migrations.CreateModel(
            name='SpeakerOutreachEmailLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('subject', models.CharField(max_length=255)),
                ('body', models.TextField()),
                ('offer_airfare', models.BooleanField(default=False)),
                ('offer_hotel', models.BooleanField(default=False)),
                ('offer_allowance', models.BooleanField(default=False)),
                ('offer_local_transport', models.BooleanField(default=False)),
                ('offer_special_support', models.BooleanField(default=False)),
                ('custom_notes', models.TextField(blank=True, null=True)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('sent', 'Sent'), ('failed', 'Failed'), ('skipped', 'Skipped')], default='queued', max_length=20)),
                ('task_id', models.CharField(blank=True, max_length=255, null=True)),
                ('message', models.TextField(blank=True, null=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('coordination', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='email_logs', to='registration.speakeroutreachcoordination')),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='speaker_outreach_email_logs', to='registration.event')),
                ('person', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='speaker_outreach_email_logs', to='registration.programperson')),
                ('sent_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='speaker_outreach_email_logs', to='auth.user')),
            ],
            options={
                'verbose_name': 'Speaker outreach email log',
                'verbose_name_plural': 'Speaker outreach email logs',
                'ordering': ['-created_at'],
            },
        ),
    ]
