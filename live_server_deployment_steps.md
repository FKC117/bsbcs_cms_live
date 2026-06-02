# BSBCS Live Server Deployment Steps

Use this checklist on the BSBCS live VM before deploying changes that include new migrations, certificate HTML-to-JPEG rendering, dashboard/admin workflow updates, or future async bulk email sending.

Run the steps in order. Do not skip backups.

Important live rule:

```bash
# Do not run this on live unless we deliberately decide otherwise:
python manage.py makemigrations
```

Migrations should already be committed from local development. On live we only inspect and apply them.

Live project path:

```bash
/var/www/html/conference
```

Virtualenv path:

```bash
/var/www/html/venv
```

## 1. Connect And Enter Project

```bash
ssh bsbcs@163.53.151.197
cd /var/www/html
source venv/bin/activate
cd conference
```

Confirm the environment:

```bash
which python
python --version
git status
```

Expected:

```bash
/var/www/html/venv/bin/python
```

## 2. Take Backups First

Database backup:

```bash
cd ~
mysqldump --no-tablespaces -u root1 -p bbcc_multi1 | gzip > backup_$(date +%F_%H-%M).sql.gz
ls -lh backup_*.sql.gz
```

Media backup:

```bash
tar -czf ~/media_backup_$(date +%F_%H-%M).tar.gz -C /var/www/html/conference media
ls -lh ~/media_backup_*.tar.gz
```

Return to project:

```bash
cd /var/www/html/conference
```

## 3. Pull Latest Code

```bash
git status
git pull origin main
```

If `git status` is not clean before pulling, stop and inspect the changed files.

If Git shows an `index.lock` error, it usually means another Git operation was interrupted. Stop there and check for a running Git process before removing the lock file.

## 4. Install Python Dependencies

Run this only if `requirements.txt` changed or we have added new packages.

```bash
pip install -r requirements.txt
```

For the current certificate browser requirement, no Python package is enough by itself. The server also needs an actual browser binary such as Google Chrome or Chromium.

Current known future dependencies:

```bash
pip install celery redis
```

Only install `celery redis` when the async bulk email worker code has been added and pushed. Installing them early is harmless, but they do nothing until the code and worker service exist.

## 5. Install Browser For HTML Certificate Rendering

The certificate renderer searches for:

- `google-chrome`
- `chromium`
- `chromium-browser`

Recommended production install: Google Chrome stable.

```bash
cd /tmp
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt update
sudo apt install -y ./google-chrome-stable_current_amd64.deb
```

Verify:

```bash
which google-chrome
google-chrome --version
```

Optional Apache user visibility check:

```bash
sudo -u www-data which google-chrome
```

Fallback if Chrome install is not possible:

```bash
sudo apt update
sudo apt install -y chromium-browser
which chromium-browser || which chromium
chromium-browser --version || chromium --version
```

On Ubuntu 24.04, Chromium may install through Snap. If Chromium gives permission/profile issues under Apache, prefer Google Chrome stable from the `.deb` package above.

Important: certificate HTML mode will fail with this message if no browser is installed:

```text
Chrome/Edge was not found on the server, so the HTML certificate cannot be rendered to JPEG.
```

## 6. Prepare Redis For Future Celery Bulk Email

Use this when async bulk email sending is implemented.

Install Redis:

```bash
sudo apt update
sudo apt install redis-server
sudo systemctl enable redis-server
sudo systemctl restart redis-server
sudo systemctl status redis-server --no-pager
```

Quick Redis check:

```bash
redis-cli ping
```

Expected:

```text
PONG
```

## 7. Check Django Before Migration

```bash
python manage.py check
```

If this fails, do not continue to migration.

## 8. Review Pending Migrations

Check registration migrations:

```bash
python manage.py showmigrations registration
```

Check website migrations:

```bash
python manage.py showmigrations website
```

Current registration migrations recently added in this development cycle:

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

If any expected migration is missing from the server after `git pull`, stop and check the repository before running `migrate`.

If live has many pending migrations, that is expected for this deployment. The important part is that they appear in the correct order and no old migration is unexpectedly missing.

## 9. Run Migrations

Run all pending migrations:

```bash
python manage.py migrate
```

Then confirm:

```bash
python manage.py showmigrations registration
python manage.py showmigrations website
```

All expected migrations should show `[X]`.

If migration fails with duplicate table or duplicate column errors, do not fake blindly. Stop and compare:

```bash
python manage.py showmigrations registration
python manage.py showmigrations website
```

Then inspect whether the database already has the table/column from an earlier manual/local import.

## 10. Collect Static Files

```bash
python manage.py collectstatic --noinput
```

If Tailwind/CSS was changed, build CSS locally first and commit the generated CSS before deploying. Do not rely on `cdn.tailwindcss.com` for production pages.

## 11. Restart Apache

```bash
sudo systemctl restart apache2
sudo systemctl status apache2 --no-pager
```

The `AH00558` ServerName warning is common and not usually a deployment blocker.

## 12. Celery Worker Service For Future Bulk Email

Only do this after Celery settings and tasks are added to the Django codebase.

Create a service file:

```bash
sudo nano /etc/systemd/system/bsbcs-celery.service
```

Suggested service:

```ini
[Unit]
Description=BSBCS Celery Worker
After=network.target redis-server.service

[Service]
Type=simple
User=bsbcs
Group=www-data
WorkingDirectory=/var/www/html/conference
EnvironmentFile=/var/www/html/conference/.env
ExecStart=/var/www/html/venv/bin/celery -A conference worker --loglevel=INFO
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable bsbcs-celery
sudo systemctl restart bsbcs-celery
sudo systemctl status bsbcs-celery --no-pager
```

Check logs:

```bash
sudo journalctl -u bsbcs-celery -n 100 --no-pager
```

## 13. Post-Deploy Smoke Tests

Open the site and verify:

- Homepage loads.
- Admin login works.
- Dashboard loads.
- Bulk Email Center loads.
- Program Session Builder loads.
- Certificate generation works for one test participant.
- Program person email summary page/action loads if recently changed.
- Bulk email campaign page loads and recipient pagination works.
- Media images still load.
- Membership modal settings still load.

Useful log checks:

```bash
tail -n 80 /var/www/html/conference/django.log
sudo tail -n 80 /var/log/apache2/error.log
```

## 14. Certificate HTML-To-JPEG Test

Before testing:

- Browser installed and visible through `which google-chrome` or `which chromium`.
- Certificate event has a certificate row.
- Certificate is set to HTML Design mode if using HTML certificate.
- Required logos/signatures are configured.

Then test through the browser using a normal participant certificate link.

If it fails, check:

```bash
tail -n 120 /var/www/html/conference/django.log
sudo tail -n 120 /var/log/apache2/error.log
```

## 15. Rollback Notes

If deployment breaks before migrations:

```bash
git log --oneline -5
git reset --hard <previous_commit_sha>
sudo systemctl restart apache2
```

If deployment breaks after migrations, do not blindly roll back code only. The database schema may already be changed. Restore from the SQL backup if needed:

```bash
gunzip < ~/backup_YYYY-MM-DD_HH-MM.sql.gz | mysql -u root1 -p bbcc_multi1
```

Restore media if needed:

```bash
tar -xzf ~/media_backup_YYYY-MM-DD_HH-MM.tar.gz -C /var/www/html/conference
```

Use rollback carefully on live. Prefer fixing forward if the migration completed successfully and the issue is template/view related.

## 16. Quick Deployment Command Order

Use this as the short version after reading the full guide:

```bash
ssh bsbcs@163.53.151.197
cd ~
mysqldump --no-tablespaces -u root1 -p bbcc_multi1 | gzip > backup_$(date +%F_%H-%M).sql.gz
tar -czf ~/media_backup_$(date +%F_%H-%M).tar.gz -C /var/www/html/conference media
cd /var/www/html
source venv/bin/activate
cd conference
git status
git pull origin main
python manage.py check
python manage.py showmigrations registration
python manage.py showmigrations website
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart apache2
sudo systemctl status apache2 --no-pager
tail -n 80 /var/www/html/conference/django.log
sudo tail -n 80 /var/log/apache2/error.log
```
