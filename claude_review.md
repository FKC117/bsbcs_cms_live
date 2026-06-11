# Django Performance Fix Plan — BSBCS Conference Platform

## Overview

This plan covers all identified performance bottlenecks, grouped by priority. Each fix includes the affected file(s), the problem, the exact change needed, and an effort estimate.

---

## Priority 1 — Critical (Fix First)

These cause the most visible slowdowns under normal load.

---

### Fix 1: Add Database Connection Pooling

**File:** `conference/settings.py`  
**Problem:** No `CONN_MAX_AGE` is set. Django opens and closes a new MySQL connection on every single HTTP request. Under concurrent load this creates a flood of connection handshakes.  
**Effort:** 5 minutes

```python
# In DATABASES['default'], add:
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DATABASE_NAME'),
        'USER': config('DATABASE_USER'),
        'PASSWORD': config('DATABASE_PASSWORD'),
        'HOST': config('DATABASE_HOST'),
        'PORT': config('DATABASE_PORT'),
        'CONN_MAX_AGE': 60,          # Reuse connections for 60 seconds
        'CONN_HEALTH_CHECKS': True,  # Django 4.1+ — safe with mod_wsgi
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}
```

---

### Fix 2: Add Redis Cache Backend

**File:** `conference/settings.py`  
**Problem:** No `CACHES` setting is configured. Redis is already running for Celery but is unused as a cache. Every lookup that could be cached (user profiles, session data, repeated queries) hits MySQL directly instead.  
**Effort:** 10 minutes

```python
# Add this block to settings.py
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': config('CELERY_BROKER_URL', default='redis://localhost:6379/0'),
        'OPTIONS': {
            'db': '1',  # Use a separate Redis DB from Celery (which uses 0)
        },
        'KEY_PREFIX': 'bsbcs',
        'TIMEOUT': 300,  # 5 minutes default TTL
    }
}
```

Install the Redis client if not already present:
```bash
pip install django-redis
```

Then update the backend to:
```python
'BACKEND': 'django_redis.cache.RedisCache',
```

---

### Fix 3: Denormalize BulkEmail Count Properties

**File:** `registration/models.py`  
**Problem:** `recipient_count`, `sent_count`, `failed_count`, and `pending_count` are `@property` methods that each fire a `COUNT(*)` query on every access. In an admin list showing 20 campaigns, this produces 80 COUNT queries per page load.  
**Effort:** 1–2 hours

**Step 1 — Add cached integer fields to BulkEmail:**
```python
class BulkEmail(models.Model):
    # ... existing fields ...
    recipient_count_cache = models.PositiveIntegerField(default=0, editable=False)
    sent_count_cache = models.PositiveIntegerField(default=0, editable=False)
    failed_count_cache = models.PositiveIntegerField(default=0, editable=False)
    pending_count_cache = models.PositiveIntegerField(default=0, editable=False)
```

**Step 2 — Add a refresh method:**
```python
def refresh_recipient_counts(self):
    from django.db.models import Count
    counts = self.recipients.values('status').annotate(n=Count('id'))
    tally = {row['status']: row['n'] for row in counts}
    self.recipient_count_cache = sum(tally.values())
    self.sent_count_cache = tally.get('sent', 0)
    self.failed_count_cache = tally.get('failed', 0)
    self.pending_count_cache = tally.get('pending', 0)
    self.save(update_fields=[
        'recipient_count_cache', 'sent_count_cache',
        'failed_count_cache', 'pending_count_cache', 'updated_at',
    ])
```

**Step 3 — Call `refresh_recipient_counts()` in `bulk_email_services.py`** after each send loop completes, instead of relying on the property.

**Step 4 — Run the migration:**
```bash
python manage.py makemigrations
python manage.py migrate
```

---

### Fix 4: Fix N+1 in `prepare_bulk_email_recipients`

**File:** `registration/bulk_email_services.py`  
**Problem:** `upsert_bulk_email_recipient()` calls `bulk_email_identity_for_email()` per row, which fires two DB queries (User + UserProfile lookup) per recipient. For a campaign to 1,000 users that's 2,000 extra queries.  
**Effort:** 1 hour

```python
def prepare_bulk_email_recipients(bulk_email):
    added = 0

    if bulk_email.audience_type == BulkEmail.AUDIENCE_ACTIVE_USERS:
        users = list(User.objects.filter(is_active=True).exclude(email=''))

        # Pre-fetch all relevant profiles in ONE query
        emails = [u.email.strip().lower() for u in users]
        profiles = {
            p.email.strip().lower(): p
            for p in UserProfile.objects.filter(email__in=emails)
        }

        for user in users:
            email_key = user.email.strip().lower()
            profile = profiles.get(email_key)
            added += int(upsert_bulk_email_recipient(
                bulk_email,
                user.email,
                name=profile.name if profile and profile.name else user.get_full_name() or user.username,
                source_type=BulkEmailRecipient.SOURCE_USER,
                user=user,
                user_profile=profile,
            ))
    # ... apply same pattern to other audience_type branches ...
```

---

### Fix 5: Fix N+1 in Participant List Context

**File:** `registration/views.py`  
**Problem:** `apply_public_participant_display()` is called inside a paginated loop, firing up to 4 extra queries per participant (previous department, previous org, member lookup, specialties). This is ~48 queries per page.  
**Effort:** 2–3 hours

**Step 1 — Pre-fetch in the queryset before pagination:**
```python
participants = Participant.objects.filter(event=event, approved=True) \
    .select_related('user', 'member') \
    .prefetch_related('member__specialties')
```

**Step 2 — Batch "previous participant" lookups:**
```python
# Collect all emails first
emails = [p.email for p in page_obj.object_list if p.email]

# Fetch all previous participants for those emails in one query
previous_map = {
    p.email: p
    for p in Participant.objects.filter(
        email__in=emails,
        approved=True,
    ).exclude(event=event).select_related('department', 'organization')
    .order_by('email', '-event__start_date')
    .distinct('email')  # or use a subquery for MySQL compatibility
}

# Then use the map inside the loop — no DB calls
for participant in page_obj.object_list:
    previous = previous_map.get(participant.email)
    # apply display logic using `previous` directly
```

> **Note:** MySQL does not support `DISTINCT ON`. Use a subquery or `itertools.groupby` on the pre-fetched list as an alternative.

---

## Priority 2 — High Impact

---

### Fix 6: Remove `builtins.print` Monkey-Patch

**File:** `conference/settings.py`  
**Problem:** Every `print()` call anywhere — including in Celery workers, third-party libraries, and Django internals — now creates a new logger instance and routes through your custom handler. This is unnecessary overhead in production.  
**Effort:** 30 minutes

**Step 1 — Remove the monkey-patch from `settings.py`:**
```python
# DELETE this entire block from settings.py:
import builtins
original_print = builtins.print

def logged_print(*args, **kwargs):
    ...

builtins.print = logged_print
```

**Step 2 — Replace all `print()` calls in your own code with proper logging:**
```python
# At the top of each module:
import logging
logger = logging.getLogger(__name__)

# Replace:
print(f"Registration kit created for {instance.participant.name}")

# With:
logger.info("Registration kit created for %s - %s",
            instance.participant.name, instance.event.name)
```

Files that need this change: `signals.py`, any other file using `print()` for status output.

---

### Fix 7: Fix `signals.py` — Inverted Logic and Wrong Variable

**File:** `registration/signals.py`  
**Problem:** Two bugs in one signal: (1) `created` refers to whether the `PaymentStatus` was just created, not the `RegistrationKit`. (2) `print()` fires on every save. The log messages are reversed.  
**Effort:** 10 minutes

```python
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import PaymentStatus, RegistrationKit

logger = logging.getLogger(__name__)

@receiver(post_save, sender=PaymentStatus)
def create_registration_kit(sender, instance, created, **kwargs):
    if instance.status == 'completed':
        kit, kit_created = RegistrationKit.objects.get_or_create(
            event=instance.event,
            payment_status=instance,
            defaults={'status': 'not_issued'}
        )
        if kit_created:
            logger.info(
                "Registration kit created for %s - %s",
                instance.participant.name, instance.event.name
            )
        else:
            logger.debug(
                "Registration kit already exists for %s - %s",
                instance.participant.name, instance.event.name
            )
```

---

### Fix 8: Fix `PaymentStatus.save()` — Repeated DELETE on Every Save

**File:** `registration/models.py`  
**Problem:** Every call to `.save()` on a PaymentStatus fires a `DELETE` query when status is `'paid'` or `'completed'`, even if the status hasn't changed (e.g. when saving just to attach an invoice or QR code).  
**Effort:** 30 minutes

Use a `pre_save` signal to capture the old status and only delete reminders on actual transition:

```python
from django.db.models.signals import pre_save
from django.dispatch import receiver

@receiver(pre_save, sender=PaymentStatus)
def clear_payment_reminders_on_completion(sender, instance, **kwargs):
    if not instance.pk:
        return  # New instance, nothing to compare against
    try:
        old = PaymentStatus.objects.get(pk=instance.pk)
    except PaymentStatus.DoesNotExist:
        return
    old_terminal = old.status in ('paid', 'completed')
    new_terminal = instance.status in ('paid', 'completed')
    if not old_terminal and new_terminal:
        PendingPaymentReminder.objects.filter(payment_status=instance).delete()
```

Remove the equivalent logic from `PaymentStatus.save()`.

---

### Fix 9: Replace Schema Introspection in `participant_email_log_table_ready()`

**File:** `registration/tasks.py`  
**Problem:** `connection.introspection.table_names()` fetches the full database schema on every call. This runs potentially dozens of times during a bulk send campaign.  
**Effort:** 15 minutes

```python
# Replace the function entirely with a module-level cached check:
_email_log_table_ready = None

def participant_email_log_table_ready():
    global _email_log_table_ready
    if _email_log_table_ready is None:
        try:
            ParticipantEmailLog.objects.exists()
            _email_log_table_ready = True
        except Exception:
            _email_log_table_ready = False
    return _email_log_table_ready
```

This runs at most once per worker process lifetime instead of once per email send.

---

### Fix 10: Admin — Replace 4 Separate COUNT Queries with One Aggregation

**File:** `registration/admin.py` (`send_corporate_invoice_email` action)  
**Problem:** Four separate `.count()` calls against the same queryset — one query each for total, approved, denied, and pending.  
**Effort:** 15 minutes

```python
from django.db.models import Count

# Replace:
total_count    = attendees.count()
approved_count = attendees.filter(review_status='approved').count()
denied_count   = attendees.filter(review_status='denied').count()
pending_count  = attendees.filter(review_status='pending').count()

# With:
counts = attendees.values('review_status').annotate(n=Count('id'))
tally = {row['review_status']: row['n'] for row in counts}
total_count    = sum(tally.values())
approved_count = tally.get('approved', 0)
denied_count   = tally.get('denied', 0)
pending_count  = tally.get('pending', 0)
```

---

### Fix 11: Admin — Use `get_queryset` with Annotations for `get_used_count` / `get_remaining_count`

**File:** `registration/admin.py` (`CorporateEventComplementaryQuotaAdmin`)  
**Problem:** `get_used_count` and `get_remaining_count` appear in `list_display`. Each fires a DB query per row. In a list of 30 rows that's 60 queries per page load.  
**Effort:** 30 minutes

```python
class CorporateEventComplementaryQuotaAdmin(admin.ModelAdmin):
    list_display = (..., 'used_count_display', 'remaining_count_display')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            used_count_ann=Count('usages'),  # adjust related name as appropriate
        )

    @admin.display(description='Used', ordering='used_count_ann')
    def used_count_display(self, obj):
        return obj.used_count_ann

    @admin.display(description='Remaining')
    def remaining_count_display(self, obj):
        return obj.total_quota - obj.used_count_ann
```

---

## Priority 3 — Medium / Security

---

### Fix 12: Add Functional Email Index for Case-Insensitive Lookups

**File:** New migration in `registration/migrations/`  
**Problem:** `email__iexact` lookups appear throughout the codebase. MySQL cannot use a B-tree index for `LOWER()` comparisons unless a functional index exists.  
**Effort:** 20 minutes

Option A — Normalise emails to lowercase on save (recommended):
```python
# In UserProfile.save():
def save(self, *args, **kwargs):
    if self.email:
        self.email = self.email.strip().lower()
    super().save(*args, **kwargs)
# Then switch all email__iexact to email__exact in queries
```

Option B — Add a functional index via a raw migration:
```python
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [('registration', '0XXX_previous')]

    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX reg_userprofile_email_lower ON registration_userprofile ((LOWER(email)));",
            reverse_sql="DROP INDEX reg_userprofile_email_lower ON registration_userprofile;",
        ),
    ]
```

---

### Fix 13: Cache the `approved_user_required` Decorator Check

**File:** `registration/decorators.py`  
**Problem:** Every request to a decorated view fires `Participant.objects.filter(email=..., approved=True).exists()`. Approval status rarely changes.  
**Effort:** 30 minutes

```python
from django.core.cache import cache
from django.contrib.auth.decorators import user_passes_test
from .models import Participant

def _is_approved(user):
    cache_key = f'approved_user_{user.pk}'
    result = cache.get(cache_key)
    if result is None:
        result = Participant.objects.filter(
            email=user.email, approved=True
        ).exists()
        cache.set(cache_key, result, timeout=300)  # Cache for 5 minutes
    return result

def approved_user_required(function=None):
    actual_decorator = user_passes_test(
        _is_approved,
        login_url='/login/',
        redirect_field_name=None,
    )
    if function:
        return actual_decorator(function)
    return actual_decorator
```

Invalidate the cache key in the signal or admin action that changes approval status:
```python
cache.delete(f'approved_user_{participant.user.pk}')
```

---

### Fix 14: Enable HTTPS Security Settings in Production

**File:** `conference/settings.py`  
**Problem:** `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, and all HSTS settings are commented out. The site handles payments — these must be enabled.  
**Effort:** 10 minutes

```python
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000        # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
```

---

### Fix 15: Split `models.py` into Domain Modules

**File:** `registration/models.py` (1,779 lines)  
**Problem:** Single monolith with repeated imports and mixed domains. Slows development and increases circular import risk as the project grows.  
**Effort:** Half a day (non-urgent, do last)

Proposed structure:
```
registration/
  models/
    __init__.py       ← re-exports everything for backward compatibility
    events.py         ← Event, TimeSlot, Schedule
    participants.py   ← Participant, UserProfile, Department
    payments.py       ← PaymentStatus, RegistrationKit, PendingPaymentReminder
    email.py          ← BulkEmail, BulkEmailRecipient, BulkEmailSendLog, BulkEmailsReporting
    corporate.py      ← CorporateAccount, CorporateAccountRequest, CorporateEventComplementaryQuota
    program.py        ← ProgramSession, ProgramItem, ProgramPerson
```

The `__init__.py` keeps all existing imports working with no changes elsewhere:
```python
from .events import Event, TimeSlot
from .participants import Participant, UserProfile
from .payments import PaymentStatus, RegistrationKit
# ... etc
```

---

## Implementation Order

| Step | Fix | Effort | Impact |
|------|-----|--------|--------|
| 1 | Add `CONN_MAX_AGE` to settings | 5 min | High |
| 2 | Add Redis cache backend | 10 min | High |
| 3 | Fix `signals.py` logic + logging | 10 min | Medium |
| 4 | Replace schema introspection in tasks | 15 min | Medium |
| 5 | Collapse 4 COUNT queries in admin | 15 min | Medium |
| 6 | Remove `builtins.print` monkey-patch | 30 min | Medium |
| 7 | Fix `PaymentStatus.save()` repeated DELETE | 30 min | High |
| 8 | Add email index / normalise emails | 20 min | High |
| 9 | Admin annotation for quota counts | 30 min | High |
| 10 | Cache `approved_user_required` | 30 min | Medium |
| 11 | Denormalize BulkEmail count fields | 2 hr | Critical |
| 12 | Fix N+1 in bulk email recipient loop | 1 hr | Critical |
| 13 | Fix N+1 in participant list context | 3 hr | Critical |
| 14 | Enable HTTPS security settings | 10 min | Security |
| 15 | Split `models.py` into modules | 4 hr | Maintainability |

---

## Recommended Tooling

Add `django-debug-toolbar` to your development environment. It shows the exact number of queries, their duration, and which code triggered them — making it much easier to verify these fixes are working.

```bash
pip install django-debug-toolbar
```

```python
# In settings.py, inside DEBUG block:
if DEBUG:
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
    INTERNAL_IPS = ['127.0.0.1']
```
