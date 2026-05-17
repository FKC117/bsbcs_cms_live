import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0068_corporateaccount'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CorporateEventRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('submission_mode', models.CharField(choices=[('manual', 'Manual entry'), ('csv', 'CSV upload')], default='manual', max_length=20)),
                ('status', models.CharField(choices=[('submitted', 'Submitted'), ('under_review', 'Under review'), ('approved', 'Approved'), ('partially_approved', 'Partially approved'), ('rejected', 'Rejected')], default='submitted', max_length=30)),
                ('total_attendees', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('corporate_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='event_registrations', to='registration.corporateaccount')),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='corporate_registrations', to='registration.event')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='CorporateEventAttendee',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('email', models.EmailField(max_length=254)),
                ('phone', models.CharField(max_length=30)),
                ('degree', models.CharField(blank=True, max_length=120, null=True)),
                ('organization', models.CharField(blank=True, max_length=180, null=True)),
                ('country', models.CharField(blank=True, max_length=100, null=True)),
                ('department', models.CharField(blank=True, max_length=120, null=True)),
                ('bmdc_registration_number', models.CharField(blank=True, max_length=80, null=True)),
                ('designation', models.CharField(blank=True, max_length=120, null=True)),
                ('notes', models.CharField(blank=True, max_length=255, null=True)),
                ('review_status', models.CharField(choices=[('pending', 'Pending review'), ('approved', 'Approved'), ('denied', 'Denied')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('matched_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='corporate_event_attendees', to=settings.AUTH_USER_MODEL)),
                ('registration', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendees', to='registration.corporateeventregistration')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
    ]
