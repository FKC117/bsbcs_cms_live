from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0119_financeaccount_opening_balance_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='financeaccount',
            name='opening_balance_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Optional exact snapshot time for the opening balance. Movements posted after this moment are counted.',
                null=True,
            ),
        ),
    ]
