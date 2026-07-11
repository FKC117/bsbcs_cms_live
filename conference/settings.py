import django
from pathlib import Path
import os
from decouple import Config, RepositoryEnv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
config = Config(RepositoryEnv(str(BASE_DIR / '.env')))


def csv_config(name, default=''):
    raw_value = config(name, default=default)
    return [item.strip() for item in raw_value.split(',') if item.strip()]


def unique_list(items):
    seen = set()
    values = []
    for item in items:
        if item not in seen:
            values.append(item)
            seen.add(item)
    return values


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

SECRET_KEY = config('SECRET_KEY')


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

# Apache production hosts - include IP, primary domain, beta, and www variants.
DEFAULT_ALLOWED_HOSTS = [
    '163.53.151.197',
    'bsbcs.analyticabd.xyz',       # Direct IP access
    'bsbcs.info',           # Primary domain
    'www.bsbcs.info',       # www subdomain
    'beta.bsbcs.info',      # Beta subdomain
    'localhost',            # Local testing (optional, remove if not needed)
    '127.0.0.1',           # Loopback (optional, remove if not needed)
]
ALLOWED_HOSTS = unique_list(DEFAULT_ALLOWED_HOSTS + csv_config('ALLOWED_HOSTS'))

# CSRF Trusted Origins for HTTPS
DEFAULT_CSRF_TRUSTED_ORIGINS = [
    'https://bsbcs.info',
    'https://www.bsbcs.info',
    'https://beta.bsbcs.info',
    'https://bsbcs.analyticabd.xyz',
]
CSRF_TRUSTED_ORIGINS = unique_list(DEFAULT_CSRF_TRUSTED_ORIGINS + csv_config('CSRF_TRUSTED_ORIGINS'))

# Handle HTTPS proxy headers from Apache
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
import matplotlib
matplotlib.use('Agg')

# Application definition

INSTALLED_APPS = [
    'django.forms',
    'django.contrib.humanize',
    'django_admin_contexts',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_countries',
    'website',
    'registration.apps.RegistrationConfig',
    'import_export',
    'crispy_forms',
    'crispy_tailwind',
    'crispy_bootstrap5',
    'django_cleanup.apps.CleanupConfig',
    'django.contrib.sitemaps',
    
]
CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"

CRISPY_TEMPLATE_PACK = "tailwind"
# conference/settings.py (at the bottom or around line 66)
FORM_RENDERER = 'django.forms.renderers.TemplatesSetting'


MIDDLEWARE = [
    'conference.middleware.fix_brackets.SquareBracketMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'conference.middleware.debug_event_type.DebugEventMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'conference.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'templates'),
            os.path.join(os.path.dirname(django.__file__), 'forms', 'templates'),
        ],
        'OPTIONS': {
            'loaders': [
                ('django.template.loaders.cached.Loader', [
                    'django.template.loaders.filesystem.Loader',
                    'django.template.loaders.app_directories.Loader',
                ]),
            ],
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Add site-wide settings and navigation
                'website.context_processors.site_settings',
                # Add registration user_profile context
                'registration.context_processors.user_profile',
            ],
        },
    },
]


WSGI_APPLICATION = 'conference.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DATABASE_NAME'),
        'USER': config('DATABASE_USER'),
        'PASSWORD': config('DATABASE_PASSWORD'),
        'HOST': config('DATABASE_HOST'),
        'PORT': config('DATABASE_PORT'),
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Dhaka'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_URL = '/media/'

MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


#Chart Configuration
CHART_DIR = os.path.join(MEDIA_ROOT, 'charts')
os.makedirs(CHART_DIR, exist_ok=True)



# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com' #'mail.event.bsbcs.org'
EMAIL_PORT = 465 #587 for TLS
EMAIL_USE_SSL = True
EMAIL_USE_TLS = False
EMAIL_HOST_USER = config('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = config('EMAIL_HOST_USER', default='noreply@bsbcs.org')

# 24-hour recipient quota safeguards for Gmail-based sending.
BULK_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H = config('BULK_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H', default=400, cast=int)
TOTAL_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H = config('TOTAL_EMAIL_UNIQUE_RECIPIENT_LIMIT_24H', default=470, cast=int)
EMAIL_QUOTA_WINDOW_HOURS = config('EMAIL_QUOTA_WINDOW_HOURS', default=24, cast=int)
EMAIL_QUOTA_RESERVATION_TTL_MINUTES = config('EMAIL_QUOTA_RESERVATION_TTL_MINUTES', default=90, cast=int)
BULK_EMAIL_CHUNK_SIZE = config('BULK_EMAIL_CHUNK_SIZE', default=50, cast=int)
BULK_EMAIL_DELAY_SECONDS = config('BULK_EMAIL_DELAY_SECONDS', default=2.0, cast=float)

# Celery / Redis
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default=CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = config('CELERY_TASK_TIME_LIMIT', default=2700, cast=int)
CELERY_TASK_ALWAYS_EAGER = config('CELERY_TASK_ALWAYS_EAGER', default=False, cast=bool)

# Site Configuration
SITE_NAME = 'BSBCS'
SITE_URL = config('SITE_URL', default='http://127.0.0.1:8000' if DEBUG else 'https://bsbcs.info')
CONTACT_EMAIL = config('CONTACT_EMAIL', default='info.bsbcs@gmail.com')

SMS_ENABLED = config('SMS_ENABLED', default=False, cast=bool)
SMS_GATEWAY_URL = config('SMS_GATEWAY_URL', default='')
SMS_GATEWAY_SINGLE_URL = config('SMS_GATEWAY_SINGLE_URL', default=SMS_GATEWAY_URL)
SMS_GATEWAY_BULK_URL = config('SMS_GATEWAY_BULK_URL', default=SMS_GATEWAY_URL)
SMS_GATEWAY_DLR_URL = config('SMS_GATEWAY_DLR_URL', default='')
SMS_GATEWAY_MULTI_STATUS_URL = config('SMS_GATEWAY_MULTI_STATUS_URL', default='')
SMS_GATEWAY_BALANCE_URL = config('SMS_GATEWAY_BALANCE_URL', default='')
SMS_GATEWAY_CLIENT_ID = config('SMS_GATEWAY_CLIENT_ID', default='')
SMS_GATEWAY_API_KEY = config('SMS_GATEWAY_API_KEY', default='')
SMS_GATEWAY_SECRET_KEY = config('SMS_GATEWAY_SECRET_KEY', default='')
SMS_GATEWAY_CALLER_ID = config('SMS_GATEWAY_CALLER_ID', default='')
SMS_GATEWAY_MASKING_CALLER_ID = config('SMS_GATEWAY_MASKING_CALLER_ID', default=SMS_GATEWAY_CALLER_ID)
SMS_GATEWAY_NON_MASKING_CALLER_ID = config('SMS_GATEWAY_NON_MASKING_CALLER_ID', default=SMS_GATEWAY_CALLER_ID)
SMS_GATEWAY_HASH = config('SMS_GATEWAY_HASH', default='')
SMS_REQUEST_TIMEOUT = config('SMS_REQUEST_TIMEOUT', default=15, cast=int)
SMS_MASKING_CHAR_LIMIT = config('SMS_MASKING_CHAR_LIMIT', default=160, cast=int)
SMS_NON_MASKING_CHAR_LIMIT = config('SMS_NON_MASKING_CHAR_LIMIT', default=160, cast=int)

# HTTPS Settings
#SESSION_COOKIE_SECURE = True
#CSRF_COOKIE_SECURE = True
#SECURE_SSL_REDIRECT = True

# HSTS Settings
#SECURE_HSTS_SECONDS = 31536000 # 1 YEAR
#SECURE_HSTS_INCLUDE_SUBDOMAINS = True
#SECURE_HSTS_PRELOAD = True



# Django Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'django.log'),
            'formatter': 'verbose',
        },
        'payment_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'payment.log'),
            'formatter': 'verbose',
        },
        'speaker_certificate_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'speaker_certificate_django.log'),
            'formatter': 'verbose',
        },
        'speaker_certificate_celery_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'speaker_certificate_celery.log'),
            'formatter': 'verbose',
        },
        'sms_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'sms.log'),
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.template': {
            'handlers': ['file', 'console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.server': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['file', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'debug_event': {
            'handlers': ['file', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'registration': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'payment': {
            'handlers': ['payment_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'speaker_certificate': {
            'handlers': ['speaker_certificate_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'speaker_certificate_celery': {
            'handlers': ['speaker_certificate_celery_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'sms': {
            'handlers': ['sms_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
}

# Override print to also log
import builtins
original_print = builtins.print

def logged_print(*args, **kwargs):
    import logging
    logger = logging.getLogger('registration')
    message = ' '.join(str(arg) for arg in args)
    logger.info(f"PRINT: {message}")
    original_print(*args, **kwargs)

builtins.print = logged_print


# -----------------------------------------------------------------------------
# GLOBAL BUG FIX: Python 3.12 + mod_wsgi '[]' Brackets
# -----------------------------------------------------------------------------
# This monkey-patch fixes a known bug where empty ErrorLists render as [] 
# in certain environments (CPython 3.12 + Apache).
from django.forms.utils import ErrorList

class SilentErrorList(ErrorList):
    def __str__(self):
        return self.as_ul() if self else ""

# Apply the patch to Django's core form components
import django.forms.forms
import django.forms.models
django.forms.forms.ErrorList = SilentErrorList
django.forms.models.ErrorList = SilentErrorList


# Form Rendering
FORM_RENDERER = 'django.forms.renderers.TemplatesSetting'
