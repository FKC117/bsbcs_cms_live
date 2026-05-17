import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0067_corporateaccountrequest'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CorporateAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('company_name', models.CharField(max_length=180)),
                ('contact_name', models.CharField(max_length=120)),
                ('contact_designation', models.CharField(blank=True, max_length=120, null=True)),
                ('email', models.EmailField(max_length=254)),
                ('phone', models.CharField(max_length=30)),
                ('status', models.CharField(choices=[('approved', 'Approved'), ('suspended', 'Suspended')], default='approved', max_length=20)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('source_request', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='corporate_account', to='registration.corporateaccountrequest')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='corporate_account', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['company_name'],
            },
        ),
    ]
