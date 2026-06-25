from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0095_speakeroutreachtemplatepreset'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(choices=[('approval', 'Approval emails'), ('registration', 'Registration emails'), ('membership', 'Membership emails'), ('bulk_email', 'Bulk emails'), ('thank_you', 'Thank-you emails'), ('invoice', 'Invoice emails'), ('program', 'Program emails'), ('speaker_certificate', 'Speaker certificate emails'), ('speaker_outreach', 'Speaker outreach emails'), ('corporate', 'Corporate emails'), ('system', 'System emails')], max_length=40)),
                ('subject', models.CharField(max_length=255)),
                ('recipients', models.JSONField(default=list)),
                ('recipient_count', models.PositiveIntegerField(default=1)),
                ('status', models.CharField(choices=[('sent', 'Sent'), ('failed', 'Failed')], default='sent', max_length=20)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('sent_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='email_audit_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-sent_at', '-id'],
                'verbose_name': 'Email audit log',
                'verbose_name_plural': 'Email audit logs',
            },
        ),
    ]
