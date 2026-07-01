from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0102_bulksms_phonegroup_bulksmsrecipient_bulksmssendlog'),
    ]

    operations = [
        migrations.AddField(
            model_name='bulksms',
            name='sms_type',
            field=models.CharField(choices=[('masking', 'Masking'), ('non_masking', 'Non-masking')], default='non_masking', max_length=20),
        ),
    ]
