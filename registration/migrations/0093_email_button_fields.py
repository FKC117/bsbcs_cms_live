from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0092_alter_event_slug'),
    ]

    operations = [
        migrations.AddField(
            model_name='bulkemail',
            name='button_text',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='bulkemail',
            name='button_url',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='bulkemailsreporting',
            name='button_text',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='bulkemailsreporting',
            name='button_url',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='event',
            name='email_button_text',
            field=models.CharField(blank=True, help_text='Optional thank-you email button text', max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='event',
            name='email_button_url',
            field=models.URLField(blank=True, help_text='Optional thank-you email button URL', max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='thankyouemail',
            name='button_text',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='thankyouemail',
            name='button_url',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
    ]
