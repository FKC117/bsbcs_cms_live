# BSBCS Beta Server Deployment Steps

Use this guide to deploy the current BSBCS project as a beta site on the same VM before pushing the same changes to the main live site.

The beta site must be isolated from the main site and from any other subdomain already running on the server.

Recommended beta setup:

```text
Main project:   /var/www/html/conference
Beta project:   /var/www/html/conference_beta
Main database:  bbcc_multi1
Beta database:  bbcc_multi1_beta
Main domain:    bsbcs.info
Beta domain:    beta.bsbcs.info
```

Do not run `makemigrations` on beta or live. Migrations should already be committed from local development.

## 1. Confirm Existing Sites First

Before creating the beta site, check the current Apache sites. This protects the main site and the other subdomain already running on the same VM.

```bash
ssh bsbcs@163.53.151.197
ls -la /etc/apache2/sites-available
ls -la /etc/apache2/sites-enabled
apachectl -S
```

Write down the existing `ServerName` and `ServerAlias` values. Do not overwrite an existing `.conf` file.

Use a new file for beta, for example:

```text
/etc/apache2/sites-available/bsbcs-beta.conf
```

## 2. Create DNS Record

In the domain DNS panel, create:

```text
Type: A
Host: beta
Value: 163.53.151.197
```

Wait until it resolves:

```bash
nslookup beta.bsbcs.info
```

If DNS is not ready, Apache can still be prepared, but browser testing should wait until DNS resolves.

## 3. Take Main Site Backups

Database backup:

```bash
cd ~
mysqldump --no-tablespaces -u root1 -p bbcc_multi1 | gzip > backup_before_beta_$(date +%F_%H-%M).sql.gz
ls -lh backup_before_beta_*.sql.gz
```

Media backup:

```bash
tar -czf ~/media_backup_before_beta_$(date +%F_%H-%M).tar.gz -C /var/www/html/conference media
ls -lh ~/media_backup_before_beta_*.tar.gz
```

## 4. Create Beta Database

Create a separate beta database:

```bash
mysql -u root1 -p
```

Inside MySQL:

```sql
CREATE DATABASE bbcc_multi1_beta CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
SHOW DATABASES LIKE 'bbcc_multi1%';
EXIT;
```

Import a copy of the main live database into beta:

```bash
gunzip -c ~/backup_before_beta_YYYY-MM-DD_HH-MM.sql.gz | mysql -u root1 -p bbcc_multi1_beta
```

Replace `YYYY-MM-DD_HH-MM` with the actual backup filename.

## 5. Create Beta Project Folder

Create a separate project folder:

```bash
cd /var/www/html
cp -a conference conference_beta
cd conference_beta
```

Check ownership:

```bash
ls -la /var/www/html
```

If needed:

```bash
sudo chown -R bsbcs:www-data /var/www/html/conference_beta
sudo find /var/www/html/conference_beta -type d -exec chmod 775 {} \;
sudo find /var/www/html/conference_beta -type f -exec chmod 664 {} \;
chmod +x /var/www/html/conference_beta/manage.py
```

## 6. Configure Beta Environment

Open the beta `.env`:

```bash
nano /var/www/html/conference_beta/.env
```

Change beta-specific values. The exact variable names depend on the current `.env`, but the important values are:

```text
DATABASE_NAME=bbcc_multi1_beta
ALLOWED_HOSTS=beta.bsbcs.info,163.53.151.197
CSRF_TRUSTED_ORIGINS=https://beta.bsbcs.info
```

If the project uses separate variables for DB user/password/host, keep those the same unless a separate DB user is created.

Strong beta safety recommendation:

```text
DEBUG=False
BETA_SITE=True
```

If we add a beta banner in code later, `BETA_SITE=True` can control it.

## 7. Email And Payment Safety

Beta should not accidentally send real bulk email or trigger real payment confusion.

Recommended beta behavior:

- Use test email addresses where possible.
- Do not run real bulk email campaigns from beta.
- Clearly label beta pages/admin notes as beta.
- If payment gateway supports sandbox mode, use sandbox credentials in beta `.env`.
- If sandbox is not available, use beta only for form/admin/payment-status workflow testing, not real customer payments.

If we later add Celery async email, beta should have its own worker name and logs.

## 8. Pull Latest Code Into Beta

If `conference_beta` is copied from `conference`, it includes the `.git` folder.

```bash
cd /var/www/html/conference_beta
git status
git pull origin main
```

If Git says the working tree is dirty, stop and inspect before pulling.

## 9. Activate Virtualenv

The beta can use the existing virtualenv:

```bash
cd /var/www/html
source venv/bin/activate
cd conference_beta
which python
python --version
```

Expected:

```text
/var/www/html/venv/bin/python
```

If `requirements.txt` changed:

```bash
pip install -r requirements.txt
```

## 10. Install Browser For Certificate HTML-To-JPEG

The certificate renderer searches for:

- `google-chrome`
- `chromium`
- `chromium-browser`

Recommended:

```bash
cd /tmp
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt update
sudo apt install -y ./google-chrome-stable_current_amd64.deb
which google-chrome
google-chrome --version
```

Optional Apache user check:

```bash
sudo -u www-data which google-chrome
```

If Chrome is already installed for the main site, do not reinstall it. Just verify `which google-chrome`.

## 11. Check And Run Beta Migrations

Run checks from the beta project folder:

```bash
cd /var/www/html/conference_beta
python manage.py check
```

Review migrations:

```bash
python manage.py showmigrations registration
python manage.py showmigrations website
```

Recently added registration migrations to expect:

```text
0072_certificate_design_mode_certificate_event_logo_and_more
0073_certificate_co_organizer_logo
0074_programperson_programsession_programsessionitem_and_more
0075_programsession_time_slot
0076_timeslot_label_timeslot_slot_type
0077_programtalkslot_programsessionitem_talk_slot
0078_programperson_profile
0079_programperson_events
0080_programpersonemaillog
0081_bulkemail_audience_type_bulkemail_created_by_and_more
```

Apply migrations to the beta database only:

```bash
python manage.py migrate
```

Confirm:

```bash
python manage.py showmigrations registration
python manage.py showmigrations website
```

All expected migrations should show `[X]`.

If duplicate table/column errors appear, stop. Do not fake migrations blindly.

## 12. Prepare Beta Static And Media

Because beta is a separate project folder, collect static into the beta `staticfiles` folder:

```bash
cd /var/www/html/conference_beta
python manage.py collectstatic --noinput
```

Media choices:

Option A: copy live media once for beta testing:

```bash
rsync -a /var/www/html/conference/media/ /var/www/html/conference_beta/media/
sudo chown -R bsbcs:www-data /var/www/html/conference_beta/media
```

Option B: keep beta media empty and upload test files manually.

Do not point beta uploads to the main live media folder if testing certificate/image upload workflows.

## 13. Create Apache Beta VirtualHost

Create a new Apache file:

```bash
sudo nano /etc/apache2/sites-available/bsbcs-beta.conf
```

Suggested config:

```apache
<VirtualHost *:80>
    ServerName beta.bsbcs.info

    ErrorLog ${APACHE_LOG_DIR}/bsbcs_beta_error.log
    CustomLog ${APACHE_LOG_DIR}/bsbcs_beta_access.log combined

    Alias /static/ /var/www/html/conference_beta/staticfiles/
    <Directory /var/www/html/conference_beta/staticfiles>
        Require all granted
    </Directory>

    Alias /media/ /var/www/html/conference_beta/media/
    <Directory /var/www/html/conference_beta/media>
        Require all granted
    </Directory>

    <Directory /var/www/html/conference_beta/conference>
        <Files wsgi.py>
            Require all granted
        </Files>
    </Directory>

    WSGIDaemonProcess bsbcs_beta python-home=/var/www/html/venv python-path=/var/www/html/conference_beta
    WSGIProcessGroup bsbcs_beta
    WSGIScriptAlias / /var/www/html/conference_beta/conference/wsgi.py
</VirtualHost>
```

Important:

- Use a unique `WSGIDaemonProcess` name such as `bsbcs_beta`.
- Do not reuse the main site's daemon process name.
- Do not edit the other subdomain's Apache file.

Enable the beta site:

```bash
sudo apachectl configtest
sudo a2ensite bsbcs-beta.conf
sudo systemctl reload apache2
sudo systemctl status apache2 --no-pager
```

## 14. Add HTTPS For Beta

If Certbot is installed:

```bash
sudo certbot --apache -d beta.bsbcs.info
```

Then verify:

```bash
sudo apachectl configtest
sudo systemctl reload apache2
```

If Certbot is not installed, configure HTTPS the same way the current main domain and existing subdomain are configured.

## 15. Beta Smoke Tests

Open:

```text
https://beta.bsbcs.info/
https://beta.bsbcs.info/admin/
https://beta.bsbcs.info/dashboard/
```

Test:

- Homepage loads.
- Admin login works.
- Dashboard loads.
- Program Session Builder loads.
- Program people can be added/removed for an event.
- Faculty/program summary email page/action loads.
- Bulk Email Center loads.
- Recipient rows and logs paginate.
- Membership flow loads.
- Event registration loads.
- Corporate dashboard loads.
- Certificate HTML-to-JPEG generation works.
- Media files load from beta media folder.

Check beta logs:

```bash
tail -n 100 /var/www/html/conference_beta/django.log
sudo tail -n 100 /var/log/apache2/bsbcs_beta_error.log
```

Also check Apache site mapping:

```bash
apachectl -S
```

Confirm `beta.bsbcs.info` points to `bsbcs-beta.conf`.

## 16. Beta Celery Notes For Future Async Bulk Email

Only use this after Celery code is implemented.

Install packages if not already in `requirements.txt`:

```bash
pip install celery redis
```

Install Redis:

```bash
sudo apt update
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl restart redis-server
redis-cli ping
```

Create a beta-specific worker service:

```bash
sudo nano /etc/systemd/system/bsbcs-beta-celery.service
```

Suggested service:

```ini
[Unit]
Description=BSBCS Beta Celery Worker
After=network.target redis-server.service

[Service]
Type=simple
User=bsbcs
Group=www-data
WorkingDirectory=/var/www/html/conference_beta
EnvironmentFile=/var/www/html/conference_beta/.env
ExecStart=/var/www/html/venv/bin/celery -A conference worker --loglevel=INFO --hostname=bsbcs_beta@%%h
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable bsbcs-beta-celery
sudo systemctl restart bsbcs-beta-celery
sudo systemctl status bsbcs-beta-celery --no-pager
```

## 17. Promote Beta To Main Site

Only promote after beta testing is approved.

Recommended promotion flow:

1. Take fresh main DB backup.
2. Take fresh main media backup.
3. Pull the same Git commit into `/var/www/html/conference`.
4. Run `python manage.py check`.
5. Review `showmigrations`.
6. Run `python manage.py migrate`.
7. Run `python manage.py collectstatic --noinput`.
8. Restart Apache.
9. Run live smoke tests.

Do not copy the beta database back to live unless we intentionally want beta test data to become live data. Usually we do not.

## 18. Remove Or Freeze Beta Later

After main live deployment succeeds, choose one:

Keep beta for future testing:

```bash
cd /var/www/html/conference_beta
git pull origin main
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl reload apache2
```

Or disable beta:

```bash
sudo a2dissite bsbcs-beta.conf
sudo systemctl reload apache2
```

Keep the beta database backup before deleting anything.
