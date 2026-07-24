from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0113_finance_control'),
    ]

    operations = [
        migrations.AddField(
            model_name='financecontrol',
            name='gateway_collection_account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='finance_control_gateway_collection_account', to='registration.financeaccount'),
        ),
    ]
