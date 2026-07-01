from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0100_chestcard'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chestcard',
            name='generated_pdf',
            field=models.FileField(blank=True, max_length=255, null=True, upload_to='chest_cards/generated_pdfs/'),
        ),
        migrations.AlterField(
            model_name='chestcard',
            name='generated_png',
            field=models.ImageField(blank=True, max_length=255, null=True, upload_to='chest_cards/generated_png/'),
        ),
    ]
