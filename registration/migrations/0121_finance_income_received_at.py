from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0120_financeaccount_opening_balance_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='financeotherincome',
            name='received_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='financesponsorshipincome',
            name='received_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
