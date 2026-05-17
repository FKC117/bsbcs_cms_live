import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0069_corporateeventregistration_corporateeventattendee'),
    ]

    operations = [
        migrations.AddField(
            model_name='corporateeventattendee',
            name='participant',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='corporate_attendee', to='registration.participant'),
        ),
    ]
