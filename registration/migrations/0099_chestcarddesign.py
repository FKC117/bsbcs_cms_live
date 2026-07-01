from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0098_event_executive_member_registration_fee'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChestCardDesign',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('design_mode', models.CharField(choices=[('overlay', 'Preprinted overlay'), ('html', 'HTML design')], default='html', max_length=20)),
                ('width_mm', models.DecimalField(decimal_places=2, default=105, max_digits=6)),
                ('height_mm', models.DecimalField(decimal_places=2, default=148, max_digits=6)),
                ('dpi', models.PositiveIntegerField(default=300)),
                ('badge_title', models.CharField(blank=True, help_text='Optional small heading like PARTICIPANT or DELEGATE.', max_length=120, null=True)),
                ('accent_color', models.CharField(default='#1769c2', max_length=20)),
                ('background_color', models.CharField(default='#f8fbff', max_length=20)),
                ('overlay_reference_image', models.ImageField(blank=True, help_text='Optional on-screen reference image for preprinted paper alignment.', null=True, upload_to='chest_cards/overlay_reference/')),
                ('html_background_image', models.ImageField(blank=True, null=True, upload_to='chest_cards/html_backgrounds/')),
                ('name_x_mm', models.DecimalField(decimal_places=2, default=15, max_digits=6)),
                ('name_y_mm', models.DecimalField(decimal_places=2, default=48, max_digits=6)),
                ('name_width_mm', models.DecimalField(decimal_places=2, default=75, max_digits=6)),
                ('name_height_mm', models.DecimalField(decimal_places=2, default=28, max_digits=6)),
                ('qr_x_mm', models.DecimalField(decimal_places=2, default=30, max_digits=6)),
                ('qr_y_mm', models.DecimalField(decimal_places=2, default=90, max_digits=6)),
                ('qr_size_mm', models.DecimalField(decimal_places=2, default=28, max_digits=6)),
                ('font_size_pt', models.PositiveIntegerField(default=28)),
                ('font_color', models.CharField(default='#0f172a', max_length=20)),
                ('text_align', models.CharField(choices=[('left', 'Left'), ('center', 'Center'), ('right', 'Right')], default='center', max_length=10)),
                ('show_event_name', models.BooleanField(default=True)),
                ('show_organization', models.BooleanField(default=True)),
                ('show_invoice_number', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='chest_card_design', to='registration.event')),
            ],
            options={
                'verbose_name': 'Chest card design',
                'verbose_name_plural': 'Chest card designs',
            },
        ),
    ]
