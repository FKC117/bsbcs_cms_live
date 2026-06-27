from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0097_email_quota_reservations'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='executive_member_registration_fee',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Optional executive committee member fee. Leave blank or set 0 for complimentary EC registration.', max_digits=10, null=True),
        ),
    ]
