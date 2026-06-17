from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('registration', '0088_alter_bulkemail_audience_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='certificate',
            name='speaker_body',
            field=models.TextField(blank=True, help_text='Optional body text for speaker certificates. Supports {{ event_name }}, {{ event_date }}, and {{ event_location }}.', null=True),
        ),
        migrations.AddField(
            model_name='certificate',
            name='speaker_require_feedback',
            field=models.BooleanField(default=False, help_text='Require linked speaker feedback submission before speaker certificate generation.'),
        ),
        migrations.AddField(
            model_name='certificate',
            name='speaker_require_kit_issue',
            field=models.BooleanField(default=False, help_text='Require linked speaker registration kit issue before speaker certificate generation.'),
        ),
        migrations.AddField(
            model_name='certificate',
            name='speaker_title',
            field=models.CharField(blank=True, help_text='Optional title for speaker certificates. Defaults to Certificate of Appreciation.', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='certificate',
            name='speaker_upload_image',
            field=models.ImageField(blank=True, null=True, upload_to='media/event_images/'),
        ),
        migrations.CreateModel(
            name='SpeakerCertificate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('generated_file', models.ImageField(blank=True, null=True, upload_to='certificates/speakers/generated/')),
                ('issued_at', models.DateTimeField(auto_now_add=True)),
                ('emailed_at', models.DateTimeField(blank=True, null=True)),
                ('downloaded_at', models.DateTimeField(blank=True, null=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='speaker_certificates', to='registration.event')),
                ('issued_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='issued_speaker_certificates', to=settings.AUTH_USER_MODEL)),
                ('profile', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='speaker_certificates', to='registration.userprofile')),
                ('program_person', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='speaker_certificates', to='registration.programperson')),
            ],
            options={
                'ordering': ['-issued_at'],
                'unique_together': {('event', 'program_person')},
            },
        ),
    ]
