from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0065_event_registration_audience'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='images/profiles/'),
        ),
    ]
