from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0099_chestcarddesign'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChestCard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('generated_pdf', models.FileField(blank=True, null=True, upload_to='chest_cards/generated_pdfs/')),
                ('generated_png', models.ImageField(blank=True, null=True, upload_to='chest_cards/generated_png/')),
                ('generated_at', models.DateTimeField(blank=True, null=True)),
                ('design_updated_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('generated', 'Generated'), ('outdated', 'Outdated'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('last_error', models.TextField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chest_cards', to='registration.event')),
                ('participant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='chest_card', to='registration.participant')),
                ('payment_status', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='chest_card', to='registration.paymentstatus')),
            ],
            options={
                'verbose_name': 'Chest card',
                'verbose_name_plural': 'Chest cards',
            },
        ),
    ]
