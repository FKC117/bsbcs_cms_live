from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0115_sponsorcompany_list'),
    ]

    operations = [
        migrations.AddField(
            model_name='financeaccount',
            name='opening_balance_date',
            field=models.DateField(
                blank=True,
                help_text='Optional snapshot date for the opening balance. When set, older transactions are not counted again.',
                null=True,
            ),
        ),
    ]
