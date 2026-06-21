from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0091_thankyouemaillog'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='slug',
            field=models.SlugField(blank=True, max_length=250, unique=True),
        ),
    ]
