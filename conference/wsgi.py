"""
WSGI config for conference project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

from dotenv import load_dotenv

# Define the path to your .env file relative to the project root
project_folder = os.path.expanduser('/var/www/html/conference/')
load_dotenv(os.path.join(project_folder, '.env'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'conference.settings')

application = get_wsgi_application()
