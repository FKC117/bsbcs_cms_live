from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0009_membershipbenefitmodal_show_on_homepage'),
    ]

    operations = [
        migrations.AddField(
            model_name='member',
            name='is_executive_member',
            field=models.BooleanField(default=False, help_text='Marks members who receive complimentary event registration as executive committee members.'),
        ),
    ]
