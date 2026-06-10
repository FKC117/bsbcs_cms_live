import os
import sys
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'conference.settings')
import django

django.setup()
from website.models import Member
from django.utils import timezone

member = Member.objects.filter(approval_status='pending').select_related('user_profile').first()
print('member found', bool(member), member and member.user_profile.email)
if member:
    member.approval_status = 'approved'
    member.approved_at = timezone.now()
    member.rejected_at = None
    member.rejection_reason = ''
    member.save(update_fields=['approval_status', 'approved_at', 'rejected_at', 'rejection_reason', 'updated_at'])
    print('saved', member.id, member.approval_status, member.user_profile.email)
