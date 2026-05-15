"""
Management command to test the member approval email signal.

Usage: python manage.py test_member_approval <member_id>
"""

from django.core.management.base import BaseCommand
from website.models import Member


class Command(BaseCommand):
    help = 'Test member approval email by approving a pending member'

    def add_arguments(self, parser):
        parser.add_argument('member_id', type=int, help='ID of the member to approve')

    def handle(self, *args, **options):
        member_id = options['member_id']
        
        try:
            member = Member.objects.get(id=member_id)
            self.stdout.write(self.style.WARNING(f"Found member: {member}"))
            self.stdout.write(self.style.WARNING(f"Current status: {member.approval_status}"))
            
            # Update the approval status
            member.approval_status = 'approved'
            member.save(update_fields=['approval_status'])
            
            self.stdout.write(self.style.SUCCESS(f"✓ Member approved and email sent!"))
            self.stdout.write(self.style.SUCCESS(f"Status: {member.approval_status}"))
            
        except Member.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Member with id {member_id} not found'))
