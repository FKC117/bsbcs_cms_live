import os
import django
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'conference.settings')
import sys
# ensure project root is on sys.path so `conference` package imports correctly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
# Also ensure current working directory is on path (helps in some shells)
cwd = str(Path.cwd())
if cwd not in sys.path:
    sys.path.insert(0, cwd)
django.setup()

from registration.pdf_utils import generate_schedule_pdf
from registration.models import Event

# Change event id here to the beta event
EVENT_ID = 10

event = Event.objects.get(pk=EVENT_ID)
buffer = generate_schedule_pdf(event, None)

out_path = Path(__file__).resolve().parent.parent / f'beta_schedule_test_{EVENT_ID}.pdf'
with open(out_path, 'wb') as f:
    f.write(buffer.getvalue())

print('Wrote', out_path)
