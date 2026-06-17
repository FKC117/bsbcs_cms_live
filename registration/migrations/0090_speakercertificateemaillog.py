from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('registration', '0089_certificate_speaker_fields_speakercertificate'),
    ]

    operations = [
        migrations.CreateModel(
            name='SpeakerCertificateEmailLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('sent', 'Sent'), ('failed', 'Failed'), ('skipped', 'Skipped')], default='queued', max_length=20)),
                ('task_id', models.CharField(blank=True, max_length=255, null=True)),
                ('message', models.TextField(blank=True, null=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('certificate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_logs', to='registration.speakercertificate')),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='speaker_certificate_email_logs', to='registration.event')),
                ('person', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='speaker_certificate_email_logs', to='registration.programperson')),
                ('sent_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='speaker_certificate_email_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
