# Local Celery And Redis Setup

Use this for testing async bulk email sending locally before deploying to beta/live.

## 1. Confirm Redis Is Running

From the project folder:

```powershell
..\venv\Scripts\python.exe -c "import redis; r=redis.Redis.from_url('redis://localhost:6379/0'); print(r.ping())"
```

Expected:

```text
True
```

If it fails, start your local Redis server first.

## 2. Environment Variables

The code has safe defaults:

```text
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
CELERY_TASK_ALWAYS_EAGER=False
```

You only need to add these to `.env` if you want to override the Redis database or run tasks synchronously during debugging.

For this local Windows shell, if `DEBUG=release` exists in the environment, override it before running Django/Celery:

```powershell
$env:DEBUG='true'
```

## 3. Start Django

Terminal 1:

```powershell
cd F:\deployed\bsbcs_live\bsbcs_cms_live
$env:DEBUG='true'
..\venv\Scripts\python.exe manage.py runserver
```

## 4. Start Celery Worker

Terminal 2:

```powershell
cd F:\deployed\bsbcs_live\bsbcs_cms_live
$env:DEBUG='true'
..\venv\Scripts\celery.exe -A conference worker -l info -P solo
```

`-P solo` is recommended on Windows local development.

## 5. Test Bulk Email Queue

1. Open `/dashboard/bulk-email-center/`.
2. Create or select a campaign.
3. Prepare recipients.
4. Click send pending.
5. The web page should respond immediately with a queued task message.
6. Watch the Celery terminal for send progress.
7. Refresh the campaign after the worker finishes to see sent/failed recipient rows and logs.

## 6. Useful Checks

Show Celery config:

```powershell
$env:DEBUG='true'
..\venv\Scripts\celery.exe -A conference report
```

Inspect registered tasks after the worker is running:

```powershell
$env:DEBUG='true'
..\venv\Scripts\celery.exe -A conference inspect registered
```

Expected task:

```text
registration.tasks.send_pending_bulk_email_campaign
```

## 7. Live Server Reminder

On live/beta, the worker should be a systemd service. Do not depend on a manual terminal worker there.

Use the deployment guides:

- `live_server_deployment_steps.md`
- `beta_server_deployment_steps.md`
