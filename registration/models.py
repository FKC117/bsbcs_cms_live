from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.utils.text import slugify
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import FileExtensionValidator


# Create your models here.

# New Models Added here
class UploadAbstractBook(models.Model):
    event = models.ForeignKey('Event', on_delete=models.CASCADE)
    abstract_book = models.FileField(upload_to='media/abstract_books/', blank=True, null=True)

    def __str__(self):
        return f"{self.event.name} {self.event.year} - Abstract Book"

class UploadNoteBook(models.Model):
    event = models.ForeignKey('Event', on_delete=models.CASCADE)
    note_book = models.ImageField(upload_to='media/event_images/', blank=True, null=True)

    def __str__(self):
        return f"{self.event.name} {self.event.year} - Note Book"


# New Models Addition Ends Here

# Create User Profile Model START------------------------------------------------------------------------------------#
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(unique=True, max_length=20)
    country = models.CharField(max_length=100)
    image = models.ImageField(upload_to='images/profiles/', blank=True, null=True)

    def __str__(self):
        return self.user.email


class CorporateAccountRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    company_name = models.CharField(max_length=180)
    contact_name = models.CharField(max_length=120)
    contact_designation = models.CharField(max_length=120, blank=True, null=True)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    note = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.company_name} - {self.contact_name}"

    class Meta:
        ordering = ['-created_at']


class CorporateAccount(models.Model):
    APPROVAL_STATUS_CHOICES = [
        ('approved', 'Approved'),
        ('suspended', 'Suspended'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='corporate_account')
    source_request = models.OneToOneField(
        CorporateAccountRequest,
        on_delete=models.SET_NULL,
        related_name='corporate_account',
        blank=True,
        null=True
    )
    company_name = models.CharField(max_length=180)
    contact_name = models.CharField(max_length=120)
    contact_designation = models.CharField(max_length=120, blank=True, null=True)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    company_logo = models.ImageField(upload_to='images/corporate_logos/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=APPROVAL_STATUS_CHOICES, default='approved')
    approved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.company_name} ({self.user.email})"

    class Meta:
        ordering = ['company_name']


class CorporateEventComplementaryQuota(models.Model):
    corporate_account = models.ForeignKey(CorporateAccount, on_delete=models.CASCADE, related_name='complementary_quotas')
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='complementary_quotas')
    allocated_count = models.PositiveIntegerField(default=0, help_text="Number of free registrations granted.")
    
    def get_used_count(self):
        return CorporateEventAttendee.objects.filter(
            registration__corporate_account=self.corporate_account,
            registration__event=self.event,
            registration__registration_type='complementary',
        ).exclude(review_status='denied').count()

    def get_remaining_count(self):
        return max(0, self.allocated_count - self.get_used_count())

    class Meta:
        unique_together = ('corporate_account', 'event')
        verbose_name_plural = "Corporate Complementary Quotas"

    def __str__(self):
        return f"{self.corporate_account.company_name} - {self.event.name} Quota: {self.allocated_count}"


class CorporateEventRegistration(models.Model):
    SUBMISSION_MODE_CHOICES = [
        ('manual', 'Manual entry'),
        ('csv', 'CSV upload'),
    ]
    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('under_review', 'Under review'),
        ('approved', 'Approved'),
        ('partially_approved', 'Partially approved'),
        ('rejected', 'Rejected'),
    ]
    REGISTRATION_TYPE_CHOICES = [
        ('regular', 'Regular Attendee'),
        ('company_person', 'Company Person'),
        ('complementary', 'Complementary'),
    ]

    corporate_account = models.ForeignKey(CorporateAccount, on_delete=models.CASCADE, related_name='event_registrations')
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='corporate_registrations')
    registration_type = models.CharField(max_length=30, choices=REGISTRATION_TYPE_CHOICES, default='regular')
    submission_mode = models.CharField(max_length=20, choices=SUBMISSION_MODE_CHOICES, default='manual')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='submitted')
    total_attendees = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.corporate_account.company_name} - {self.event.name} ({self.total_attendees})"

    class Meta:
        ordering = ['-created_at']


class CorporateEventAttendee(models.Model):
    REVIEW_STATUS_CHOICES = [
        ('pending', 'Pending review'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
    ]

    registration = models.ForeignKey(CorporateEventRegistration, on_delete=models.CASCADE, related_name='attendees')
    matched_user = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='corporate_event_attendees')
    participant = models.OneToOneField('Participant', on_delete=models.SET_NULL, blank=True, null=True, related_name='corporate_attendee')
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    degree = models.CharField(max_length=120, blank=True, null=True)
    organization = models.CharField(max_length=180, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    department = models.CharField(max_length=120, blank=True, null=True)
    bmdc_registration_number = models.CharField(max_length=80, blank=True, null=True)
    designation = models.CharField(max_length=120, blank=True, null=True)
    notes = models.CharField(max_length=255, blank=True, null=True)
    review_status = models.CharField(max_length=20, choices=REVIEW_STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.registration.event.name}"

    @property
    def matched_member(self):
        if not self.matched_user_id:
            return None
        try:
            profile = self.matched_user.userprofile
            member = getattr(profile, 'member', None)
        except UserProfile.DoesNotExist:
            return None
        if member and member.approval_status == 'approved' and member.is_active_member:
            return member
        return None

    @property
    def member_match_label(self):
        return 'Active member' if self.matched_member else 'Regular attendee'

    @property
    def applied_fee_label(self):
        if self.registration.registration_type == 'complementary':
            return 'Complementary: Free'
        if self.registration.registration_type == 'company_person':
            fee = self.registration.event.company_person_registration_fee or 0
            return 'Company Person: Free' if not fee else f'Company Person: BDT {fee}'
        if self.matched_member:
            member_fee = self.registration.event.member_registration_fee or 0
            return 'Member fee: Free' if not member_fee else f'Member fee: BDT {member_fee}'
        regular_fee = self.registration.event.amount if self.registration.event.payment_required else 0
        return 'Regular fee: Free' if not regular_fee else f'Regular fee: BDT {regular_fee}'

    class Meta:
        ordering = ['name']


class CorporatePayment(models.Model):
    STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('initiated', 'Initiated'),
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    corporate_registration = models.ForeignKey(CorporateEventRegistration, on_delete=models.CASCADE, related_name='corporate_payments')
    corporate_account = models.ForeignKey(CorporateAccount, on_delete=models.CASCADE, related_name='corporate_payments')
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='corporate_payments')
    attendees = models.ManyToManyField(CorporateEventAttendee, blank=True, related_name='corporate_payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unpaid')
    merchant_invoice_number = models.CharField(max_length=255, unique=True)
    transaction_id = models.CharField(max_length=255, blank=True, null=True)
    trxID = models.CharField(max_length=255, blank=True, null=True)
    invoice = models.FileField(upload_to='media/corporate_invoices/', blank=True, null=True)
    email_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.corporate_account.company_name} - {self.event.name} - BDT {self.amount}"

    class Meta:
        ordering = ['-created_at']


# Create Event Models START------------------------------------------------------------------------------------#

from django.urls import reverse

class Event(models.Model):
    EVENT_STATUS_CHOICES = [
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('upcoming', 'Upcoming'),
    ]
    REGISTRATION_STATUS_CHOICES = [
        ('Open', 'Open'),
        ('Closed', 'Closed'),
        ('Starting Soon', 'Starting Soon'),
    ]
    REGISTRATION_AUDIENCE_CHOICES = [
        ('all', 'All users'),
        ('members_only', 'Members only'),
    ]
    name = models.CharField(max_length=200)
    slogan = models.CharField(max_length=200, default="Empowering Survivors, Education & Support")
    year = models.PositiveIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    location = models.CharField(max_length=200, blank=True, null=True)
    event_status = models.CharField(max_length=10, choices=EVENT_STATUS_CHOICES, default='upcoming')
    event_logo = models.ImageField(upload_to='media/event_logos/', blank=True, null=True)
    modal_image = models.ImageField(upload_to='media/modal_images/', blank=True, null=True)
    event_hero_image = models.ImageField(upload_to='media/hero_images/', blank=True, null=True, help_text='Upload an image for the hero section of the event page. Recomended size: 1920x1080')
    registration = models.CharField(max_length=50, choices=REGISTRATION_STATUS_CHOICES, default='Open')
    registration_audience = models.CharField(
        max_length=20,
        choices=REGISTRATION_AUDIENCE_CHOICES,
        default='all',
        help_text='Choose who can register for this event.'
    )
    payment_required = models.BooleanField(default=True, help_text='Check if payment is required')
    amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    member_registration_enabled = models.BooleanField(
        default=False,
        help_text='Allow approved active BSBCS members to register through the member flow'
    )
    member_registration_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text='Optional member-only event fee. Leave blank or set 0 for free member attendance.'
    )
    company_person_registration_enabled = models.BooleanField(
        default=False,
        help_text='Allow company people registration for this event.'
    )
    company_person_registration_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text='Optional company person registration fee.'
    )
    show_publication_tab = models.BooleanField(default=False, help_text="Show or hide the Publication tab on the event page.")
    slug = models.SlugField(max_length=250, unique=True, blank=True)
    description = models.TextField(max_length=1000, blank=True, null=True)
    keywords = models.CharField(max_length=1000, blank=True, null=True, help_text='Enter Keywords seperated by comma')
    author = models.CharField(max_length=100, blank=True, null=True)
    og_image = models.ImageField(upload_to='static/images/og_images/', blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    email_subject = models.CharField(max_length=255, blank=True, null=True, help_text='Thank You email subject text')
    email_body = models.TextField(blank=True, null=True, help_text='Thank You email body text')
    email_button_text = models.CharField(max_length=120, blank=True, null=True, help_text='Optional thank-you email button text')
    email_button_url = models.URLField(max_length=500, blank=True, null=True, help_text='Optional thank-you email button URL')

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(f"{self.name} {self.year}")[:250] or f"event-{self.year}"
            slug_candidate = base_slug
            suffix = 2
            while Event.objects.exclude(pk=self.pk).filter(slug=slug_candidate).exists():
                suffix_text = f"-{suffix}"
                slug_candidate = f"{base_slug[:250 - len(suffix_text)]}{suffix_text}"
                suffix += 1
            self.slug = slug_candidate
        else:
            self.slug = self.slug[:250]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} {self.year}"
    def get_absolute_url(self):
        return reverse('registration:home', args=[self.id])  # type: ignore[attr-defined]



# Thank You Mail Model Starts Here----------------------------------------------------------------------------#
from django.db import models
from django.utils.timezone import now
import os

class ThankYouEmail(models.Model):
    registration_kit = models.OneToOneField(
        'RegistrationKit', 
        on_delete=models.CASCADE, 
        related_name='thank_you_email'
    )
    subject = models.CharField(max_length=255)  # Copied from Event at the time of creation
    body = models.TextField()  # Copied from Event at the time of creation
    button_text = models.CharField(max_length=120, blank=True, null=True)
    button_url = models.URLField(max_length=500, blank=True, null=True)
    email_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(blank=True, null=True)

    def send_email(self):
        """Queue the thank-you email via Celery and mark it when sent."""
        if self.registration_kit.status == 'issued' and not self.email_sent:
            from registration.tasks import send_thank_you_email_task

            send_thank_you_email_task.delay(self.id)
            return True

    def __str__(self):
        return f"Thank You Email for {self.registration_kit.payment_status.participant.name}"


class ThankYouEmailLog(models.Model):
    STATUS_QUEUED = 'queued'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    thank_you_email = models.ForeignKey(ThankYouEmail, on_delete=models.CASCADE, related_name='email_logs')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='thank_you_email_logs')
    participant = models.ForeignKey('Participant', on_delete=models.CASCADE, related_name='thank_you_email_logs')
    email = models.EmailField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    task_id = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='thank_you_email_logs')
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.participant.name} - thank-you email - {self.status}"


# Thank You Mail Model Starts Here----------------------------------------------------------------------------#



#Feature Speaker Models START------------------------------------------------------------------------------------#
class FeatureSpeaker(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    speciality = models.CharField(max_length=200)
    institution = models.CharField(max_length=200)
    biography = models.TextField(default='No biography available')
    image = models.ImageField(upload_to='images/', default='images/default.jpg')

    class Meta:
        verbose_name_plural = 'Feature Speakers'

    def __str__(self):
        return self.name

#Feature Speaker Models END------------------------------------------------------------------------------------#

#Department Models START------------------------------------------------------------------------------------#
class Department(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name

#Department Models END------------------------------------------------------------------------------------#

#Participant Models START------------------------------------------------------------------------------------#
class Participant(models.Model):
    REGISTRATION_TYPE_CHOICES = [
        ('regular', 'Regular'),
        ('member', 'Member'),
        ('company_person', 'Company Person'),
        ('complementary', 'Complementary'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    registration_type = models.CharField(max_length=20, choices=REGISTRATION_TYPE_CHOICES, default='regular')
    name = models.CharField(max_length=100)
    degree = models.CharField(max_length=50)
    year_of_graduation = models.IntegerField()
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    organization = models.CharField(max_length=100)
    email = models.EmailField(blank=False, null=False)
    phone = models.CharField(max_length=20, blank=False, null=False)
    country = models.CharField(max_length=100, default='Bangladesh')
    BMDC_registration_number = models.CharField(max_length=20, blank=True, null=True)
    approved = models.BooleanField(default=False)
    denied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('email', 'event'), ('phone', 'event'))
        

    def __str__(self):
        return self.name

    def get_payable_amount(self):
        if self.registration_type == 'complementary':
            return 0
        if self.registration_type == 'company_person':
            return self.event.company_person_registration_fee or 0
        if self.registration_type == 'member' and (
            self.event.member_registration_enabled
            or self.event.registration_audience == 'members_only'
        ):
            return self.event.member_registration_fee or 0
        return self.event.amount or 0

#Participant Models END------------------------------------------------------------------------------------#

# Creating Payment Status Models START------------------------------------------------------------------------------------#
class PaymentStatus(models.Model):
    STATUS_CHOICES = [
        ('paid', 'Paid'),
        ('pending', 'Pending'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
        ('completed', 'Completed'),
        ('unpaid', 'Unpaid'),
        ('initiated', 'Initiated'),
        ('failed', 'Failed')
    ]
    
    participant = models.OneToOneField(Participant, on_delete=models.CASCADE, related_name='payment_statuses')
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    transaction_id = models.CharField(max_length=255, blank=True, null=True)  # bKash Payment ID
    merchant_invoice_number = models.CharField(max_length=255, unique=True)  # Merchant Invoice Number
    amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='unpaid')
    trxID = models.CharField(max_length=255, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    invoice = models.FileField(upload_to='media/invoices/', blank=True, null=True)
    qr_token = models.UUIDField(unique=True, editable=False, blank=True, null=True)
    qr_code = models.ImageField(upload_to='registration_qr_codes/', blank=True, null=True)
    email_sent = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Auto-set amount from participant/event policy when amount is not already set.
        # This allows member discounted fees to stay different from the regular event fee.
        if self.event and self.participant and self.amount is None:
            self.amount = self.participant.get_payable_amount()

        # Check and remove from PendingPaymentReminder if the status is 'paid' or 'completed'
        if self.status in ['paid', 'completed']:
            PendingPaymentReminder.objects.filter(participant=self.participant, event=self.event).delete()

        # Call the parent save method to retain existing functionality
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.participant.name} - {self.event.name} - {self.amount} - {self.status}"
    
    class Meta:
        verbose_name_plural = 'Payment Status'

# Creating Payment Status Models End --------------------------------------------------------------------#


class ParticipantEmailLog(models.Model):
    TYPE_APPROVAL_PAYMENT = 'approval_payment'
    TYPE_FREE_CONFIRMATION = 'free_confirmation'
    TYPE_CHOICES = [
        (TYPE_APPROVAL_PAYMENT, 'Approval with payment link'),
        (TYPE_FREE_CONFIRMATION, 'Free event confirmation'),
    ]

    STATUS_QUEUED = 'queued'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='email_logs')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='participant_email_logs')
    email = models.EmailField()
    email_type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    task_id = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='participant_email_logs')
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.participant.name} - {self.email_type} - {self.status}"

    class Meta:
        ordering = ['-created_at']


# Hall room Model START---------------------------------------------------------------------------------#
class HallRoom(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    location = models.CharField(max_length=50)

    class Meta:
        verbose_name_plural = 'Hall Room'

    def __str__(self):
        return self.name
    
### Hall room Model END---------------------------------------------------------------------------------#


### Program day-----------------------------------------------------------------------------------------#
class ProgramDay(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=50, default='Day 1')
    date = models.DateField()
    class Meta:
        verbose_name_plural = 'Program Day'
    def __str__(self):
        return self.name

### Timeslot Model START---------------------------------------------------------------------------------#
class TimeSlot(models.Model):
    SLOT_SESSION = 'session'
    SLOT_TEA_BREAK = 'tea_break'
    SLOT_LUNCH = 'lunch'
    SLOT_DINNER = 'dinner'
    SLOT_CEREMONY = 'ceremony'
    SLOT_CUSTOM = 'custom'
    SLOT_TYPE_CHOICES = [
        (SLOT_SESSION, 'Session slot'),
        (SLOT_TEA_BREAK, 'Tea break'),
        (SLOT_LUNCH, 'Lunch'),
        (SLOT_DINNER, 'Dinner'),
        (SLOT_CEREMONY, 'Ceremony'),
        (SLOT_CUSTOM, 'Custom block'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    program_day = models.ForeignKey(ProgramDay, on_delete=models.CASCADE, related_name='ProgramDay')
    start_time = models.TimeField()
    end_time = models.TimeField()
    hall_room = models.ForeignKey(HallRoom, on_delete=models.CASCADE, related_name='timeslots')
    slot_type = models.CharField(max_length=24, choices=SLOT_TYPE_CHOICES, default=SLOT_SESSION)
    label = models.CharField(max_length=120, blank=True, null=True)

    class Meta:
        verbose_name_plural = 'Time Slot'

    def __str__(self):
        start_time_formatted = self.start_time.strftime('%I:%M %p')
        end_time_formatted = self.end_time.strftime('%I:%M %p')
        label = self.label or self.get_slot_type_display()
        return f"{label} - {self.hall_room} - {start_time_formatted} - {end_time_formatted}"

    @property
    def parallel_reserved_person_ids(self):
        overlapping_sessions = ProgramSession.objects.filter(
            event_id=self.event_id,
            program_day_id=self.program_day_id,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        ).exclude(hall_room_id=self.hall_room_id)
        reserved_ids = set(
            ProgramSessionFaculty.objects.filter(
                session__in=overlapping_sessions,
            ).values_list('person_id', flat=True)
        )
        reserved_ids.update(
            ProgramItemFaculty.objects.filter(
                item__session__in=overlapping_sessions,
            ).values_list('person_id', flat=True)
        )
        return sorted(reserved_ids)
    
    def clean(self):
        super().clean()
        if self.event_id and self.program_day and self.program_day.event_id != self.event_id:
            raise ValidationError(_("Program day must belong to the same event as the time slot."))
        if self.event_id and self.hall_room and self.hall_room.event_id != self.event_id:
            raise ValidationError(_("Hall room must belong to the same event as the time slot."))
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError(_("Time slot end time must be after start time."))
        if not all((self.program_day_id, self.hall_room_id, self.start_time, self.end_time)):
            return

        duplicate_time_slots = TimeSlot.objects.filter(
            program_day=self.program_day,
            hall_room=self.hall_room,
            start_time=self.start_time,
            end_time=self.end_time,
        ).exclude(id=self.id)  # type: ignore[attr-defined]

        if duplicate_time_slots.exists():
            raise ValidationError(_("This exact time slot already exists for the same program day and hall room."))

        overlapping_time_slots = TimeSlot.objects.filter(
            program_day=self.program_day,
            hall_room=self.hall_room,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time
        ).exclude(id=self.id)  # type: ignore[attr-defined]

        if overlapping_time_slots.exists():
            raise ValidationError(_("This time slot overlaps with another time slot in the same program day and hall room."))
 
### Timeslot Model END---------------------------------------------------------------------------------#

#Abstract Submission Models START------------------------------------------------------------------------------------#
from django.contrib.auth.models import User
class AbstractSubmission(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    title = models.CharField(max_length=400)
    authors = models.CharField(max_length=500)
    institution = models.CharField(max_length=200)
    introduction = models.TextField()
    methods = models.TextField()
    results = models.TextField()
    conclusion = models.TextField()
    image = models.ImageField(upload_to='media/abstract_images/', null=True, blank=True)
    presentation_file = models.FileField(
        upload_to='media/presentation_files/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'ppt', 'pptx'])],
        null=True,
        blank=True
    )
    approved_for_presentation = models.BooleanField(default=False)
    approved_for_poster = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Abstract Submission'

    def __str__(self):
        return self.title
#Abstract Submission Models END------------------------------------------------------------------------------------#

# Chairperson Model START------------------------------------------------------------------------------------#

class Chairperson(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    degree = models.CharField(max_length=100, blank=True, null=True)
    organization = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(unique=True, blank=False, null=False)
    phone = models.CharField(unique=True, max_length=20, blank=False, null=False)
    country = models.CharField(max_length=100, default='Bangladesh')

    class Meta:
        verbose_name_plural = 'Chairperson'
    def __str__(self):
        return self.name

# Chairperson Model END------------------------------------------------------------------------------------#
# Panelist Model START------------------------------------------------------------------------------------#
class Panelist(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    degree = models.CharField(max_length=100, blank=True, null=True)
    organization = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(unique=True, blank=False, null=False)
    phone = models.CharField(unique=True, max_length=20, blank=False, null=False)
    country = models.CharField(max_length=100, default='Bangladesh')

    def __str__(self):
        return self.name

# Panelist Model END------------------------------------------------------------------------------------#

# Moderator Model START------------------------------------------------------------------------------------#
class Moderator(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    degree = models.CharField(max_length=100, blank=True, null=True)
    organization = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(unique=True, blank=False, null=False)
    phone = models.CharField(unique=True, max_length=20, blank=False, null=False)
    country = models.CharField(max_length=100, default='Bangladesh')

    def __str__(self):
        return self.name

# Moderator Model END------------------------------------------------------------------------------------#

#ProgramSchedule Model START------------------------------------------------------------------------------------#

class ProgramSchedule(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    abstract_submission = models.OneToOneField(AbstractSubmission, on_delete=models.CASCADE)
    presenter = models.TextField(null=True, blank=True)
    time_slots = models.ManyToManyField(TimeSlot, related_name='schedules')
    chairperson = models.ForeignKey(Chairperson, on_delete=models.SET_NULL, null=True, blank=True)
    panelist = models.ManyToManyField(Panelist, blank=True)
    moderator = models.ForeignKey(Moderator, on_delete=models.SET_NULL, null=True, blank=True)
    email_sent = models.BooleanField(default=False)
    # is_parallel = models.BooleanField(default=False)


    class Meta:
        verbose_name_plural = 'Program Schedule'

    @property
    def title(self):
        return self.abstract_submission.title

    @property
    def authors(self):
        return self.abstract_submission.authors

    def clean(self):
        super().clean()
        
        # Check if the abstract is approved for presentation or poster
        if not self.abstract_submission.approved_for_presentation and not self.abstract_submission.approved_for_poster:
            raise ValidationError(_("Abstract must be approved for either presentation or poster to be included in the schedule."))

        # Check for duplicate schedules
        duplicates = ProgramSchedule.objects.filter(abstract_submission__title=self.abstract_submission.title, abstract_submission__authors=self.abstract_submission.authors)
        if self.pk:
            duplicates = duplicates.exclude(pk=self.pk)
        if duplicates.exists():
            raise ValidationError(_("A program schedule with this title and author already exists."))

        # Check for overlapping schedules
        if self.pk:
            overlapping_schedules = ProgramSchedule.objects.filter(time_slots__in=self.time_slots.all()).distinct().exclude(pk=self.pk)  
            if overlapping_schedules.exists():
                overlapping_titles = ', '.join(overlapping_schedules.values_list('abstract_submission__title', flat=True))
                raise ValidationError(_(f"Warning: The schedule overlaps with existing schedules: {overlapping_titles}"))

    def __str__(self):
        return f"{self.title} by {self.authors}"
# ProgramSchedule Model END------------------------------------------------------------------------------------#


class ProgramPerson(models.Model):
    profile = models.OneToOneField(
        UserProfile,
        on_delete=models.SET_NULL,
        related_name='program_person',
        blank=True,
        null=True,
        help_text='Optional website profile used to create or identify this program person.',
    )
    events = models.ManyToManyField(
        Event,
        related_name='program_people',
        blank=True,
        help_text='Events where this person is available for program scheduling.',
    )
    name = models.CharField(max_length=150)
    degree = models.CharField(max_length=120, blank=True, null=True)
    designation = models.CharField(max_length=180, blank=True, null=True)
    institution = models.CharField(max_length=180, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    country = models.CharField(max_length=100, default='Bangladesh')
    biography = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='images/program_people/', blank=True, null=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Program Person'
        verbose_name_plural = 'Program People'

    def __str__(self):
        details = self.institution or self.designation
        return f"{self.name} - {details}" if details else self.name


class ProgramPersonEmailLog(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='program_person_email_logs')
    person = models.ForeignKey(ProgramPerson, on_delete=models.CASCADE, related_name='event_email_logs')
    last_sent_at = models.DateTimeField(blank=True, null=True)
    last_sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='program_person_emails_sent')
    send_count = models.PositiveIntegerField(default=0)
    last_session_count = models.PositiveIntegerField(default=0)
    last_talk_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('event', 'person')
        ordering = ['event__start_date', 'person__name']
        verbose_name = 'Program Person Email Log'
        verbose_name_plural = 'Program Person Email Logs'

    def __str__(self):
        return f"{self.person} - {self.event} email summary"


class SpeakerOutreachTemplate(models.Model):
    event = models.OneToOneField('Event', on_delete=models.CASCADE, related_name='speaker_outreach_template')
    subject = models.CharField(max_length=255, blank=True, null=True)
    intro_body = models.TextField(blank=True, null=True)
    closing_body = models.TextField(blank=True, null=True)
    airfare_body = models.TextField(blank=True, null=True, help_text='Optional paragraph shown when return airfare support is offered.')
    hotel_body = models.TextField(blank=True, null=True, help_text='Optional paragraph shown when hotel accommodation is offered.')
    allowance_body = models.TextField(blank=True, null=True, help_text='Optional paragraph shown when honorarium or allowance is offered.')
    local_transport_body = models.TextField(blank=True, null=True, help_text='Optional paragraph shown when local transport support is offered.')
    special_support_body = models.TextField(blank=True, null=True, help_text='Optional paragraph shown when another special arrangement is offered.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Speaker outreach template'
        verbose_name_plural = 'Speaker outreach templates'

    def __str__(self):
        return f"{self.event.name} {self.event.year} speaker outreach template"


class SpeakerOutreachTemplatePreset(models.Model):
    name = models.CharField(max_length=180)
    subject = models.CharField(max_length=255, blank=True, null=True)
    intro_body = models.TextField(blank=True, null=True)
    closing_body = models.TextField(blank=True, null=True)
    airfare_body = models.TextField(blank=True, null=True)
    hotel_body = models.TextField(blank=True, null=True)
    allowance_body = models.TextField(blank=True, null=True)
    local_transport_body = models.TextField(blank=True, null=True)
    special_support_body = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='speaker_outreach_template_presets')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', '-updated_at']
        verbose_name = 'Speaker outreach template preset'
        verbose_name_plural = 'Speaker outreach template presets'

    def __str__(self):
        return self.name


class SpeakerOutreachCoordination(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_SENT = 'sent'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SENT, 'Sent'),
    ]

    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='speaker_outreach_rows')
    person = models.ForeignKey(ProgramPerson, on_delete=models.CASCADE, related_name='speaker_outreach_rows')
    offer_airfare = models.BooleanField(default=False)
    offer_hotel = models.BooleanField(default=False)
    offer_allowance = models.BooleanField(default=False)
    offer_local_transport = models.BooleanField(default=False)
    offer_special_support = models.BooleanField(default=False)
    custom_notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    send_count = models.PositiveIntegerField(default=0)
    last_subject = models.CharField(max_length=255, blank=True, null=True)
    last_body = models.TextField(blank=True, null=True)
    last_sent_at = models.DateTimeField(blank=True, null=True)
    last_sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='speaker_outreach_sent_rows')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['event__start_date', 'person__name']
        unique_together = ('event', 'person')
        verbose_name = 'Speaker outreach coordination row'
        verbose_name_plural = 'Speaker outreach coordination rows'

    def __str__(self):
        return f"{self.person.name} - {self.event.name} outreach"


class SpeakerOutreachEmailLog(models.Model):
    STATUS_QUEUED = 'queued'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    coordination = models.ForeignKey('SpeakerOutreachCoordination', on_delete=models.SET_NULL, blank=True, null=True, related_name='email_logs')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='speaker_outreach_email_logs')
    person = models.ForeignKey(ProgramPerson, on_delete=models.CASCADE, related_name='speaker_outreach_email_logs')
    email = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField()
    offer_airfare = models.BooleanField(default=False)
    offer_hotel = models.BooleanField(default=False)
    offer_allowance = models.BooleanField(default=False)
    offer_local_transport = models.BooleanField(default=False)
    offer_special_support = models.BooleanField(default=False)
    custom_notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    task_id = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='speaker_outreach_email_logs')
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Speaker outreach email log'
        verbose_name_plural = 'Speaker outreach email logs'

    def __str__(self):
        return f"{self.person.name} - speaker outreach - {self.status}"


class ProgramSession(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='program_sessions')
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.SET_NULL, blank=True, null=True, related_name='program_sessions')
    program_day = models.ForeignKey(ProgramDay, on_delete=models.SET_NULL, blank=True, null=True, related_name='program_sessions')
    hall_room = models.ForeignKey(HallRoom, on_delete=models.SET_NULL, blank=True, null=True, related_name='program_sessions')
    title = models.CharField(max_length=255)
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['program_day__date', 'start_time', 'order', 'id']
        verbose_name = 'Smart Program Session'
        verbose_name_plural = 'Smart Program Sessions'

    def __str__(self):
        return f"{self.event} - {self.title}"

    def clean(self):
        super().clean()
        if self.time_slot and self.time_slot.event_id != self.event_id:
            raise ValidationError(_('Selected time slot must belong to the same event as the session.'))
        if self.time_slot and self.time_slot.slot_type != TimeSlot.SLOT_SESSION:
            raise ValidationError(_('Break, meal, and custom time blocks cannot be assigned to sessions.'))
        if self.program_day and self.program_day.event_id != self.event_id:
            raise ValidationError(_('Selected program day must belong to the same event as the session.'))
        if self.hall_room and self.hall_room.event_id != self.event_id:
            raise ValidationError(_('Selected hall room must belong to the same event as the session.'))
        if self.pk:
            assigned_people = set(self.faculty_roles.values_list('person_id', flat=True))
            assigned_people.update(
                ProgramItemFaculty.objects.filter(item__session=self).values_list('person_id', flat=True)
            )
            if self.conflicting_parallel_people(assigned_people):
                raise ValidationError(_('One or more assigned people already belong to an overlapping session in another hall.'))

    def save(self, *args, **kwargs):
        if self.time_slot:
            self.program_day = self.time_slot.program_day
            self.hall_room = self.time_slot.hall_room
            self.start_time = self.time_slot.start_time
            self.end_time = self.time_slot.end_time
        super().save(*args, **kwargs)

    def overlapping_parallel_sessions(self):
        time_slot = self.time_slot
        program_day_id = time_slot.program_day_id if time_slot else self.program_day_id
        hall_room_id = time_slot.hall_room_id if time_slot else self.hall_room_id
        start_time = time_slot.start_time if time_slot else self.start_time
        end_time = time_slot.end_time if time_slot else self.end_time
        if not self.event_id or not program_day_id or not hall_room_id or not start_time or not end_time:
            return ProgramSession.objects.none()

        sessions = ProgramSession.objects.filter(
            event_id=self.event_id,
            program_day_id=program_day_id,
            start_time__lt=end_time,
            end_time__gt=start_time,
        ).exclude(hall_room_id=hall_room_id)
        if self.pk:
            sessions = sessions.exclude(pk=self.pk)
        return sessions

    @property
    def is_parallel_session(self):
        return self.overlapping_parallel_sessions().exists()

    def conflicting_parallel_people(self, person_ids):
        if not person_ids:
            return {}

        conflicts = {}
        overlapping_sessions = self.overlapping_parallel_sessions().filter(
            Q(faculty_roles__person_id__in=person_ids)
            | Q(items__faculty_roles__person_id__in=person_ids)
        ).select_related('hall_room').prefetch_related(
            'faculty_roles__person',
            'items__faculty_roles__person',
        ).distinct()
        for session in overlapping_sessions:
            session_people = {
                role.person_id
                for role in session.faculty_roles.all()
                if role.person_id in person_ids
            }
            for item in session.items.all():
                session_people.update(
                    role.person_id
                    for role in item.faculty_roles.all()
                    if role.person_id in person_ids
                )
            for person_id in session_people:
                conflicts.setdefault(person_id, []).append(session)
        return conflicts

    @property
    def builder_payload(self):
        role_ids = {
            ProgramSessionFaculty.ROLE_CHAIRPERSON: [],
            ProgramSessionFaculty.ROLE_MODERATOR: [],
            ProgramSessionFaculty.ROLE_PANELIST: [],
        }
        role_labels = {
            ProgramSessionFaculty.ROLE_CHAIRPERSON: [],
            ProgramSessionFaculty.ROLE_MODERATOR: [],
            ProgramSessionFaculty.ROLE_PANELIST: [],
        }
        for role in self.faculty_roles.all():
            if role.role in role_ids:
                role_ids[role.role].append(str(role.person_id))
                role_labels[role.role].append(role.person.name)

        items = []
        for item in self.items.all():
            item_role_ids = {
                ProgramItemFaculty.ROLE_SPEAKER: [],
                ProgramItemFaculty.ROLE_PRESENTER: [],
            }
            item_role_labels = {
                ProgramItemFaculty.ROLE_SPEAKER: [],
                ProgramItemFaculty.ROLE_PRESENTER: [],
            }
            for role in item.faculty_roles.all():
                if role.role in item_role_ids:
                    item_role_ids[role.role].append(str(role.person_id))
                    item_role_labels[role.role].append(role.person.name)
            items.append({
                'id': str(item.id),
                'order': str(item.order),
                'start_time': item.start_time.strftime('%H:%M') if item.start_time else '',
                'end_time': item.end_time.strftime('%H:%M') if item.end_time else '',
                'time_label': (
                    f"{item.start_time.strftime('%I:%M %p').lstrip('0')} - {item.end_time.strftime('%I:%M %p').lstrip('0')}"
                    if item.start_time and item.end_time
                    else 'Time not set'
                ),
                'title': item.title,
                'display_title': item.display_title,
                'talk_slot': str(item.talk_slot_id) if item.talk_slot_id else '',
                'abstract_submission': str(item.abstract_submission_id) if item.abstract_submission_id else '',
                'abstract_title': item.abstract_submission.title if item.abstract_submission else '',
                'speakers': item_role_ids[ProgramItemFaculty.ROLE_SPEAKER],
                'presenters': item_role_ids[ProgramItemFaculty.ROLE_PRESENTER],
                'speaker_labels': item_role_labels[ProgramItemFaculty.ROLE_SPEAKER],
                'presenter_labels': item_role_labels[ProgramItemFaculty.ROLE_PRESENTER],
            })

        return {
            'id': str(self.id),
            'event_label': self.event.name,
            'title': self.title,
            'description': self.description or '',
            'time_slot': str(self.time_slot_id) if self.time_slot_id else '',
            'program_day': str(self.program_day_id) if self.program_day_id else '',
            'hall_room': str(self.hall_room_id) if self.hall_room_id else '',
            'start_time': self.start_time.strftime('%H:%M') if self.start_time else '',
            'end_time': self.end_time.strftime('%H:%M') if self.end_time else '',
            'day_label': self.program_day.name if self.program_day else 'Day',
            'room_label': self.hall_room.name if self.hall_room else 'Room',
            'time_label': (
                f"{self.start_time.strftime('%I:%M %p').lstrip('0')} - {self.end_time.strftime('%I:%M %p').lstrip('0')}"
                if self.start_time and self.end_time
                else 'Time slot'
            ),
            'order': str(self.order),
            'chairpersons': role_ids[ProgramSessionFaculty.ROLE_CHAIRPERSON],
            'moderators': role_ids[ProgramSessionFaculty.ROLE_MODERATOR],
            'panelists': role_ids[ProgramSessionFaculty.ROLE_PANELIST],
            'chairperson_labels': role_labels[ProgramSessionFaculty.ROLE_CHAIRPERSON],
            'moderator_labels': role_labels[ProgramSessionFaculty.ROLE_MODERATOR],
            'panelist_labels': role_labels[ProgramSessionFaculty.ROLE_PANELIST],
            'occupancy': self.timeline_occupancy,
            'talk_slots': [
                {
                    'id': str(talk_slot.id),
                    'time_slot': str(talk_slot.time_slot_id),
                    'start_time': talk_slot.start_time.strftime('%H:%M'),
                    'end_time': talk_slot.end_time.strftime('%H:%M'),
                    'time_label': talk_slot.time_label,
                    'label': talk_slot.label or '',
                }
                for talk_slot in self.time_slot.talk_slots.all()
            ] if self.time_slot else [],
            'parallel_reserved_people': self.time_slot.parallel_reserved_person_ids if self.time_slot else [],
            'items': items,
        }

    @property
    def builder_payload_script_id(self):
        return f'program-session-payload-{self.id}'

    @property
    def timeline_occupancy(self):
        if not self.start_time or not self.end_time:
            return {
                'available': False,
                'summary': 'Add a session time window to measure talk occupancy.',
                'segments': [],
            }

        session_start = (self.start_time.hour * 60) + self.start_time.minute
        session_end = (self.end_time.hour * 60) + self.end_time.minute
        duration = session_end - session_start
        if duration <= 0:
            return {
                'available': False,
                'summary': 'Session end time must be after its start time.',
                'segments': [],
            }

        measured_items = []
        untimed_count = 0
        overflow_count = 0
        overlap_count = 0

        for item in self.items.all():
            if not item.start_time or not item.end_time:
                untimed_count += 1
                continue

            item_start = (item.start_time.hour * 60) + item.start_time.minute
            item_end = (item.end_time.hour * 60) + item.end_time.minute
            if item_end <= item_start:
                untimed_count += 1
                continue

            if item_start < session_start or item_end > session_end:
                overflow_count += 1

            clipped_start = max(item_start, session_start)
            clipped_end = min(item_end, session_end)
            if clipped_end > clipped_start:
                measured_items.append((clipped_start, clipped_end))

        measured_items.sort()
        latest_item_end = None
        for item_start, item_end in measured_items:
            if latest_item_end is not None and item_start < latest_item_end:
                overlap_count += 1
            latest_item_end = max(latest_item_end or item_end, item_end)

        merged_intervals = []
        for item_start, item_end in measured_items:
            if not merged_intervals or item_start > merged_intervals[-1][1]:
                merged_intervals.append([item_start, item_end])
            else:
                merged_intervals[-1][1] = max(merged_intervals[-1][1], item_end)

        segments = []
        cursor = session_start
        occupied_minutes = 0
        for item_start, item_end in merged_intervals:
            if item_start > cursor:
                segments.append({
                    'kind': 'free',
                    'width': ((item_start - cursor) / duration) * 100,
                    'minutes': item_start - cursor,
                })
            segments.append({
                'kind': 'occupied',
                'width': ((item_end - item_start) / duration) * 100,
                'minutes': item_end - item_start,
            })
            occupied_minutes += item_end - item_start
            cursor = max(cursor, item_end)

        if cursor < session_end:
            segments.append({
                'kind': 'free',
                'width': ((session_end - cursor) / duration) * 100,
                'minutes': session_end - cursor,
            })
        if not segments:
            segments.append({
                'kind': 'free',
                'width': 100,
                'minutes': duration,
            })

        available_minutes = max(duration - occupied_minutes, 0)
        if overflow_count:
            status = 'overflow'
            summary = f'{overflow_count} talk item{"s" if overflow_count != 1 else ""} exceed this session window.'
        elif overlap_count:
            status = 'overlap'
            summary = f'{overlap_count} talk timing overlap{"s" if overlap_count != 1 else ""} need review.'
        elif occupied_minutes == 0:
            status = 'empty'
            summary = f'{duration} min available for talks.'
        elif available_minutes:
            status = 'available'
            summary = f'{available_minutes} min still available for talks.'
        else:
            status = 'full'
            summary = 'Talk timing fills this session window.'

        return {
            'available': True,
            'duration_minutes': duration,
            'occupied_minutes': occupied_minutes,
            'available_minutes': available_minutes,
            'measured_count': len(measured_items),
            'untimed_count': untimed_count,
            'overflow_count': overflow_count,
            'overlap_count': overlap_count,
            'status': status,
            'summary': summary,
            'segments': segments,
        }


class ProgramSessionFaculty(models.Model):
    ROLE_CHAIRPERSON = 'chairperson'
    ROLE_MODERATOR = 'moderator'
    ROLE_PANELIST = 'panelist'
    ROLE_CHOICES = [
        (ROLE_CHAIRPERSON, 'Chairperson'),
        (ROLE_MODERATOR, 'Moderator'),
        (ROLE_PANELIST, 'Panelist'),
    ]

    session = models.ForeignKey(ProgramSession, on_delete=models.CASCADE, related_name='faculty_roles')
    person = models.ForeignKey(ProgramPerson, on_delete=models.CASCADE, related_name='session_roles')
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['role', 'order', 'person__name']
        unique_together = ('session', 'person', 'role')
        verbose_name = 'Session Faculty Role'
        verbose_name_plural = 'Session Faculty Roles'

    def __str__(self):
        return f"{self.person} as {self.get_role_display()} in {self.session.title}"

    def clean(self):
        super().clean()
        duplicate_session_role = ProgramSessionFaculty.objects.filter(
            session=self.session,
            person=self.person,
        )
        if self.pk:
            duplicate_session_role = duplicate_session_role.exclude(pk=self.pk)
        if duplicate_session_role.exists():
            raise ValidationError(_('This person already has a chairperson, moderator, or panelist role in this session.'))
        if self.session_id and self.person_id and self.session.conflicting_parallel_people({self.person_id}):
            raise ValidationError(_('This person is already assigned to another session in a parallel hall at the same time.'))


class ProgramSessionItem(models.Model):
    session = models.ForeignKey(ProgramSession, on_delete=models.CASCADE, related_name='items')
    talk_slot = models.OneToOneField(
        'ProgramTalkSlot',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='assigned_item',
    )
    abstract_submission = models.ForeignKey(AbstractSubmission, on_delete=models.SET_NULL, blank=True, null=True, related_name='program_session_items')
    title = models.CharField(max_length=400, blank=True, null=True, help_text='Use this for non-abstract talks or manual titles.')
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'start_time', 'id']
        verbose_name = 'Smart Program Item'
        verbose_name_plural = 'Smart Program Items'

    @property
    def display_title(self):
        return self.title or (self.abstract_submission.title if self.abstract_submission else 'Untitled program item')

    def clean(self):
        super().clean()
        if not self.abstract_submission and not self.title:
            raise ValidationError(_('Add either an abstract submission or a text-based title.'))
        if self.abstract_submission and self.session and self.abstract_submission.event_id != self.session.event_id:
            raise ValidationError(_('Selected abstract must belong to the same event as the session.'))
        if self.talk_slot and self.session and self.talk_slot.time_slot_id != self.session.time_slot_id:
            raise ValidationError(_('Selected talk slot must belong to this session time slot.'))

    def save(self, *args, **kwargs):
        if self.talk_slot:
            self.start_time = self.talk_slot.start_time
            self.end_time = self.talk_slot.end_time
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_title


class ProgramTalkSlot(models.Model):
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, related_name='talk_slots')
    start_time = models.TimeField()
    end_time = models.TimeField()
    order = models.PositiveIntegerField(default=0)
    label = models.CharField(max_length=120, blank=True, null=True)

    class Meta:
        ordering = ['time_slot__start_time', 'order', 'start_time', 'id']
        unique_together = ('time_slot', 'start_time', 'end_time')
        verbose_name = 'Program Talk Slot'
        verbose_name_plural = 'Program Talk Slots'

    def __str__(self):
        return f"{self.time_label} - {self.time_slot}"

    @property
    def time_label(self):
        return f"{self.start_time.strftime('%I:%M %p').lstrip('0')} - {self.end_time.strftime('%I:%M %p').lstrip('0')}"

    def clean(self):
        super().clean()
        if self.time_slot and self.time_slot.slot_type != TimeSlot.SLOT_SESSION:
            raise ValidationError(_('Talk slots can only be generated inside session time slots.'))
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError(_('Talk slot end time must be after start time.'))
        if self.time_slot_id and self.start_time and self.end_time:
            if self.start_time < self.time_slot.start_time or self.end_time > self.time_slot.end_time:
                raise ValidationError(_('Talk slot must stay inside its parent session time slot.'))


class ProgramItemFaculty(models.Model):
    ROLE_SPEAKER = 'speaker'
    ROLE_PRESENTER = 'presenter'
    ROLE_DISCUSSANT = 'discussant'
    ROLE_CHOICES = [
        (ROLE_SPEAKER, 'Speaker'),
        (ROLE_PRESENTER, 'Presenter'),
        (ROLE_DISCUSSANT, 'Discussant'),
    ]

    item = models.ForeignKey(ProgramSessionItem, on_delete=models.CASCADE, related_name='faculty_roles')
    person = models.ForeignKey(ProgramPerson, on_delete=models.CASCADE, related_name='item_roles')
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=ROLE_SPEAKER)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['role', 'order', 'person__name']
        unique_together = ('item', 'person', 'role')
        verbose_name = 'Item Faculty Role'
        verbose_name_plural = 'Item Faculty Roles'

    def __str__(self):
        return f"{self.person} as {self.get_role_display()} for {self.item.display_title}"

    def clean(self):
        super().clean()
        if self.item_id and self.person_id and self.item.session.conflicting_parallel_people({self.person_id}):
            raise ValidationError(_('This person is already assigned to another session in a parallel hall at the same time.'))


class PresentationUpload(models.Model):
    SOURCE_ABSTRACT = 'abstract'
    SOURCE_SESSION_ITEM = 'session_item'
    SOURCE_SESSION_ROLE = 'session_role'
    SOURCE_CHOICES = [
        (SOURCE_ABSTRACT, 'Abstract submission'),
        (SOURCE_SESSION_ITEM, 'Program talk / activity'),
        (SOURCE_SESSION_ROLE, 'Session faculty role'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='presentation_uploads')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='presentation_uploads')
    program_person = models.ForeignKey(
        ProgramPerson,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='presentation_uploads',
    )
    abstract_submission = models.ForeignKey(
        AbstractSubmission,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='presentation_uploads',
    )
    session = models.ForeignKey(
        ProgramSession,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='presentation_uploads',
    )
    session_item = models.ForeignKey(
        ProgramSessionItem,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='presentation_uploads',
    )
    source_type = models.CharField(max_length=30, choices=SOURCE_CHOICES)
    title = models.CharField(max_length=400)
    role_label = models.CharField(max_length=120, blank=True, null=True)
    presenter_name = models.CharField(max_length=150, blank=True, null=True)
    file = models.FileField(
        upload_to='media/presentation_uploads/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'ppt', 'pptx'])],
    )
    notes = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['event__start_date', 'session__start_time', 'session_item__order', 'title']
        verbose_name = 'Presentation Upload'
        verbose_name_plural = 'Presentation Uploads'

    def __str__(self):
        return f"{self.presenter_name or self.user.email} - {self.title}"

    def clean(self):
        super().clean()
        if self.abstract_submission and self.abstract_submission.event_id != self.event_id:
            raise ValidationError(_('Abstract submission must belong to the same event.'))
        if self.session and self.session.event_id != self.event_id:
            raise ValidationError(_('Program session must belong to the same event.'))
        if self.session_item and self.session_item.session.event_id != self.event_id:
            raise ValidationError(_('Program item must belong to the same event.'))


# Invitation Model START------------------------------------------------------------------------------------#
class Invitation(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    designation = models.CharField(max_length=50)
    message = models.TextField()
    image = models.ImageField(upload_to='media/invitation_images/', null=True, blank=True)
    
    def __str__(self):
        return self.name
   
# Invitation Model END------------------------------------------------------------------------------------#
# About the Conference Model START------------------------------------------------------------------------------------#
class AboutTheConference(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField()
    short_description = models.TextField(null=True, blank=True)
    image = models.ImageField(upload_to='media/about_images/', null=True, blank=True)

    class Meta:
        verbose_name_plural = 'About the Conference'
    def __str__(self):
        return self.title
# About the Conference Model END------------------------------------------------------------------------------------#

# Sponsorship Models START------------------------------------------------------------------------------------#
from django.db import models

class Sponsor(models.Model):
    TITLE = 'Title'
    PLATINUM = 'Platinum'
    GOLDEN = 'Golden'
    SILVER = 'Silver'
    LOGISTICS = 'Logistics'
    MEDIA = 'Media'
    IT = 'IT'
    EVENT = 'Event'

    CATEGORY_CHOICES = [
        (TITLE, 'Title'),
        (PLATINUM, 'Platinum'),
        (GOLDEN, 'Golden'),
        (SILVER, 'Silver'),
        (LOGISTICS, 'Logistics'),
        (MEDIA, 'Media'),
        (IT, 'IT'),
        (EVENT, 'Event')
    ]
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    image = models.ImageField(upload_to='media/sponsor_images/', null=True, blank=True)
    category = models.CharField(max_length=200, choices=CATEGORY_CHOICES, null=True, blank=True)

    class Meta:
        verbose_name_plural = 'Sponsors'

    def __str__(self):
        return self.name
# Sponsorship Models END------------------------------------------------------------------------------------#


# EventImage and EventVideo Models START------------------------------------------------------------------------------------#

from django.db import models

class EventImage(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='media/event_images/')
    caption = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return self.caption or "Event Image"

class EventVideo(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    youtube_url = models.URLField()
    caption = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return self.caption or "Event Video"
# EventImage and EventVideo Models END------------------------------------------------------------------------------------#

# Registration kit model START------------------------------------------------------------------------------------#
from django.db import models
from .models import PaymentStatus, Event

class RegistrationKit(models.Model):
    STATUS_CHOICES = [
        ('issued', 'Issued'),
        ('not_issued', 'Not Issued'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="registration_kits")
    payment_status = models.OneToOneField(PaymentStatus, on_delete=models.CASCADE, related_name="registration_kit")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_issued')
    issued_at = models.DateTimeField(blank=True, null=True)  # To track when the kit was issued

    def __str__(self):
        return f"Kit for {self.payment_status.participant.name} - {self.event.name} ({self.status})"

    class Meta:
        verbose_name_plural = "Registration Kits"
        unique_together = ('event', 'payment_status')  # Ensure one kit per event and payment


# Registration kit model END------------------------------------------------------------------------------------#

# Bkash Payment Model START------------------------------------------------------------------------------------#
from django.db import models

class BkashData(models.Model):
    payment_id = models.CharField(max_length=255, unique=True)
    trx_id = models.CharField(max_length=255)
    mode = models.CharField(max_length=50)
    payment_create_time = models.CharField(max_length=150)
    payment_execute_time = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10)
    intent = models.CharField(max_length=20)
    merchant_invoice = models.CharField(max_length=255)
    transaction_status = models.CharField(max_length=50)
    service_fee = models.DecimalField(max_digits=10, decimal_places=2)
    verification_status = models.CharField(max_length=50)
    payer_reference = models.CharField(max_length=255)
    payer_type = models.CharField(max_length=50)
    status_code = models.CharField(max_length=10)
    status_message = models.CharField(max_length=255)

    def __str__(self):
        return f"Payment {self.payment_id} - Status: {self.transaction_status}"



class ProgramSchedulePdf(models.Model):
    event = models.ForeignKey('Event', on_delete=models.CASCADE)
    schedule_image = models.ImageField(upload_to='media/event_images/', blank=True, null=True)
    schedule_pdf = models.FileField(upload_to='media/event_pdfs/', blank=True, null=True)  # Allowing PDFs

    def __str__(self):
        return f"{self.event.name} - Schedule"



# Certificate Model Starts Here----------------------------------------------------------------------------#
class Certificate(models.Model):
    DESIGN_MODE_IMAGE = 'image'
    DESIGN_MODE_HTML = 'html'
    DESIGN_MODE_CHOICES = [
        (DESIGN_MODE_IMAGE, 'Uploaded Image'),
        (DESIGN_MODE_HTML, 'HTML Design'),
    ]

    event = models.ForeignKey('Event', on_delete=models.CASCADE, blank=True, null=True)
    design_mode = models.CharField(max_length=20, choices=DESIGN_MODE_CHOICES, default=DESIGN_MODE_IMAGE)
    upload_image = models.ImageField(upload_to='media/event_images/', blank=True, null=True)
    speaker_upload_image = models.ImageField(upload_to='media/event_images/', blank=True, null=True)
    organizer_logo = models.ImageField(upload_to='certificates/logos/', blank=True, null=True)
    co_organizer_logo = models.ImageField(upload_to='certificates/logos/', blank=True, null=True)
    event_logo = models.ImageField(upload_to='certificates/event_logos/', blank=True, null=True)
    speaker_title = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='Optional title for speaker certificates. Defaults to Certificate of Appreciation.',
    )
    speaker_body = models.TextField(
        blank=True,
        null=True,
        help_text='Optional body text for speaker certificates. Supports {{ event_name }}, {{ event_date }}, and {{ event_location }}.',
    )
    speaker_require_feedback = models.BooleanField(
        default=False,
        help_text='Require linked speaker feedback submission before speaker certificate generation.',
    )
    speaker_require_kit_issue = models.BooleanField(
        default=False,
        help_text='Require linked speaker registration kit issue before speaker certificate generation.',
    )

    def __str__(self):
        if self.event:
            return f"{self.event.name} {self.event.year} Certificate"
        return "Certificate"


class CertificateSignatory(models.Model):
    certificate = models.ForeignKey(Certificate, on_delete=models.CASCADE, related_name='signatories')
    name = models.CharField(max_length=255)
    designation = models.CharField(max_length=255, blank=True, null=True)
    organization = models.TextField(blank=True, null=True)
    signature = models.ImageField(upload_to='certificates/signatures/', blank=True, null=True)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Certificate signatory'
        verbose_name_plural = 'Certificate signatories'

    def __str__(self):
        return self.name


class SpeakerCertificate(models.Model):
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='speaker_certificates')
    program_person = models.ForeignKey('ProgramPerson', on_delete=models.CASCADE, related_name='speaker_certificates')
    profile = models.ForeignKey(
        UserProfile,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='speaker_certificates',
    )
    generated_file = models.ImageField(upload_to='certificates/speakers/generated/', blank=True, null=True)
    issued_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='issued_speaker_certificates',
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    emailed_at = models.DateTimeField(blank=True, null=True)
    downloaded_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-issued_at']
        unique_together = ('event', 'program_person')

    def __str__(self):
        return f"{self.program_person.name} - {self.event.name} Speaker Certificate"


class SpeakerCertificateEmailLog(models.Model):
    STATUS_QUEUED = 'queued'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    certificate = models.ForeignKey(SpeakerCertificate, on_delete=models.CASCADE, related_name='email_logs')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='speaker_certificate_email_logs')
    person = models.ForeignKey(ProgramPerson, on_delete=models.CASCADE, related_name='speaker_certificate_email_logs')
    email = models.EmailField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    task_id = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='speaker_certificate_email_logs')
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.person.name} - speaker certificate - {self.status}"


class EmailAuditLog(models.Model):
    CATEGORY_APPROVAL = 'approval'
    CATEGORY_REGISTRATION = 'registration'
    CATEGORY_MEMBERSHIP = 'membership'
    CATEGORY_BULK_EMAIL = 'bulk_email'
    CATEGORY_THANK_YOU = 'thank_you'
    CATEGORY_INVOICE = 'invoice'
    CATEGORY_PROGRAM = 'program'
    CATEGORY_SPEAKER_CERTIFICATE = 'speaker_certificate'
    CATEGORY_SPEAKER_OUTREACH = 'speaker_outreach'
    CATEGORY_CORPORATE = 'corporate'
    CATEGORY_SYSTEM = 'system'

    CATEGORY_CHOICES = [
        (CATEGORY_APPROVAL, 'Approval emails'),
        (CATEGORY_REGISTRATION, 'Registration emails'),
        (CATEGORY_MEMBERSHIP, 'Membership emails'),
        (CATEGORY_BULK_EMAIL, 'Bulk emails'),
        (CATEGORY_THANK_YOU, 'Thank-you emails'),
        (CATEGORY_INVOICE, 'Invoice emails'),
        (CATEGORY_PROGRAM, 'Program emails'),
        (CATEGORY_SPEAKER_CERTIFICATE, 'Speaker certificate emails'),
        (CATEGORY_SPEAKER_OUTREACH, 'Speaker outreach emails'),
        (CATEGORY_CORPORATE, 'Corporate emails'),
        (CATEGORY_SYSTEM, 'System emails'),
    ]

    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES)
    subject = models.CharField(max_length=255)
    recipients = models.JSONField(default=list)
    recipient_count = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SENT)
    metadata = models.JSONField(default=dict, blank=True)
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='email_audit_logs')
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at', '-id']
        verbose_name = 'Email audit log'
        verbose_name_plural = 'Email audit logs'

    def __str__(self):
        return f"{self.get_category_display()} - {self.subject} ({self.recipient_count})"


class EmailQuotaLock(models.Model):
    key = models.CharField(max_length=40, unique=True, default='global')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Email quota lock'
        verbose_name_plural = 'Email quota locks'

    def __str__(self):
        return self.key


class EmailQuotaReservation(models.Model):
    STATUS_RESERVED = 'reserved'
    STATUS_CONSUMED = 'consumed'
    STATUS_RELEASED = 'released'
    STATUS_CHOICES = [
        (STATUS_RESERVED, 'Reserved'),
        (STATUS_CONSUMED, 'Consumed'),
        (STATUS_RELEASED, 'Released'),
    ]

    reservation_key = models.CharField(max_length=120, db_index=True)
    category = models.CharField(max_length=40, choices=EmailAuditLog.CATEGORY_CHOICES)
    recipient_email = models.EmailField(max_length=320)
    recipient_key = models.CharField(max_length=320, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RESERVED, db_index=True)
    reserved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(blank=True, null=True)
    released_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-reserved_at', '-id']
        verbose_name = 'Email quota reservation'
        verbose_name_plural = 'Email quota reservations'
        constraints = [
            models.UniqueConstraint(fields=['reservation_key', 'recipient_key'], name='unique_email_quota_reservation_key_recipient'),
        ]

    def __str__(self):
        return f"{self.recipient_email} ({self.status})"

    @property
    def is_active(self):
        return self.status == self.STATUS_RESERVED and self.expires_at >= timezone.now()

# Certificate Model Ends Here----------------------------------------------------------------------------#
# Feedback Form Model Starts here----------------------------------------------------------------------------#

class FeedbackQuestion(models.Model):
    TEXT = 'text'         # Simple open-ended question
    RADIO = 'radio'       # Single-choice question (e.g., Very Dissatisfied to Very Satisfied)
    MATRIX = 'matrix'     # Matrix-based question

    QUESTION_TYPES = [
        (TEXT, 'Text (Simple Open-ended)'),
        (RADIO, 'Radio (Single-choice)'),
        (MATRIX, 'Matrix (Row and Column)'),
    ]

    event = models.ManyToManyField(Event, related_name="feedback_questions")  # Link to a specific event
    question_text = models.TextField(blank=True, null=True)  # The question itself
    question_type = models.CharField(
        max_length=10,
        choices=QUESTION_TYPES,
        default=TEXT,
    )
    is_required = models.BooleanField(default=True)  # Whether the question is mandatory

    # Matrix-based additional fields
    rows = models.TextField(
        blank=True,
        null=True,
        help_text="For matrix-type questions: Enter rows separated by commas, e.g., 'Welcome Kit, Venue, Food'."
    )
    columns = models.TextField(
        blank=True,
        null=True,
        help_text="For matrix-type questions: Enter columns separated by commas, e.g., '1, 2, 3, 4, 5, N/A'."
    )

    order = models.PositiveIntegerField(default=0)  # For ordering questions in the frontend

    class Meta:
        ordering = ['order']  # Ensure questions appear in the specified order

    def __str__(self):
        return f"{self.question_text or 'Untitled Question'} (Event: {self.event.name})"

    def get_rows(self):
        """Return rows as a list for matrix questions."""
        if self.rows:
            return [row.strip() for row in self.rows.split(',')]
        return []

    def get_columns(self):
        """Return columns as a list for matrix questions."""
        if self.columns:
            return [column.strip() for column in self.columns.split(',')]
        return []


class FeedbackResponse(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    question = models.ForeignKey(FeedbackQuestion, on_delete=models.CASCADE)
    response = models.TextField()  # Store user response (text or choice)

    def __str__(self):
        return f"{self.participant.name}'s response to {self.question.question_text}"

# Feedback Form Model Ends here----------------------------------------------------------------------------



# Bulk Email Model Starts here----------------------------------------------------------------------------

from django.db import models

class BulkEmail(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_RECIPIENTS_READY = 'recipients_ready'
    STATUS_SENDING = 'sending'
    STATUS_SENT = 'sent'
    STATUS_PARTIAL = 'partial'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_RECIPIENTS_READY, 'Recipients ready'),
        (STATUS_SENDING, 'Sending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_PARTIAL, 'Partially sent'),
    ]

    AUDIENCE_MANUAL = 'manual'
    AUDIENCE_ACTIVE_USERS = 'active_users'
    AUDIENCE_EMAIL_GROUP = 'email_group'
    AUDIENCE_EVENT_PARTICIPANTS = 'event_participants'
    AUDIENCE_EVENT_UNPAID = 'event_unpaid'
    AUDIENCE_MEMBERSHIP_UNPAID = 'membership_unpaid'
    AUDIENCE_ABSTRACT_SUBMITTERS = 'abstract_submitters'
    AUDIENCE_CORPORATE_CONTACTS = 'corporate_contacts'

    AUDIENCE_CHOICES = [
        (AUDIENCE_MANUAL, 'Manual recipients'),
        (AUDIENCE_ACTIVE_USERS, 'Active website users'),
        (AUDIENCE_EMAIL_GROUP, 'Email group'),
        (AUDIENCE_EVENT_PARTICIPANTS, 'Event participants'),
        (AUDIENCE_EVENT_UNPAID, 'Approved event participants with pending payment'),
        (AUDIENCE_MEMBERSHIP_UNPAID, 'Approved members with pending membership payment'),
        (AUDIENCE_ABSTRACT_SUBMITTERS, 'Abstract submitters'),
        (AUDIENCE_CORPORATE_CONTACTS, 'Corporate contacts'),
    ]

    subject = models.CharField(max_length=255)
    body = models.TextField()
    button_text = models.CharField(max_length=120, blank=True, null=True)
    button_url = models.URLField(max_length=500, blank=True, null=True)
    attachment = models.FileField(upload_to='attachments/', blank=True, null=True)
    audience_type = models.CharField(max_length=40, choices=AUDIENCE_CHOICES, default=AUDIENCE_MANUAL)
    event = models.ForeignKey('Event', on_delete=models.SET_NULL, blank=True, null=True, related_name='bulk_emails')
    email_group = models.ForeignKey('EmailGroup', on_delete=models.SET_NULL, blank=True, null=True, related_name='bulk_emails')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='created_bulk_emails')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.subject

    @property
    def recipient_count(self):
        return self.recipients.count()

    @property
    def sent_count(self):
        return self.recipients.filter(status=BulkEmailRecipient.STATUS_SENT).count()

    @property
    def failed_count(self):
        return self.recipients.filter(status=BulkEmailRecipient.STATUS_FAILED).count()

    @property
    def pending_count(self):
        return self.recipients.filter(status=BulkEmailRecipient.STATUS_PENDING).count()


class BulkEmailRecipient(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    SOURCE_MANUAL = 'manual'
    SOURCE_USER = 'user'
    SOURCE_EMAIL_GROUP = 'email_group'
    SOURCE_PARTICIPANT = 'participant'
    SOURCE_MEMBERSHIP = 'membership'
    SOURCE_ABSTRACT = 'abstract'
    SOURCE_CORPORATE = 'corporate'

    SOURCE_CHOICES = [
        (SOURCE_MANUAL, 'Manual'),
        (SOURCE_USER, 'Website user'),
        (SOURCE_EMAIL_GROUP, 'Email group'),
        (SOURCE_PARTICIPANT, 'Participant'),
        (SOURCE_MEMBERSHIP, 'Membership'),
        (SOURCE_ABSTRACT, 'Abstract submitter'),
        (SOURCE_CORPORATE, 'Corporate'),
    ]

    bulk_email = models.ForeignKey(BulkEmail, on_delete=models.CASCADE, related_name='recipients')
    email = models.EmailField()
    name = models.CharField(max_length=180, blank=True, null=True)
    source_type = models.CharField(max_length=30, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='bulk_email_recipients')
    user_profile = models.ForeignKey('UserProfile', on_delete=models.SET_NULL, blank=True, null=True, related_name='bulk_email_recipients')
    participant = models.ForeignKey('Participant', on_delete=models.SET_NULL, blank=True, null=True, related_name='bulk_email_recipients')
    abstract_submission = models.ForeignKey('AbstractSubmission', on_delete=models.SET_NULL, blank=True, null=True, related_name='bulk_email_recipients')
    corporate_account = models.ForeignKey('CorporateAccount', on_delete=models.SET_NULL, blank=True, null=True, related_name='bulk_email_recipients')
    corporate_request = models.ForeignKey('CorporateAccountRequest', on_delete=models.SET_NULL, blank=True, null=True, related_name='bulk_email_recipients')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.email} - {self.bulk_email.subject}"

    class Meta:
        ordering = ['email']
        unique_together = ('bulk_email', 'email')


class BulkEmailSendLog(models.Model):
    bulk_email = models.ForeignKey(BulkEmail, on_delete=models.CASCADE, related_name='send_logs')
    recipient = models.ForeignKey(BulkEmailRecipient, on_delete=models.SET_NULL, blank=True, null=True, related_name='send_logs')
    email = models.EmailField()
    status = models.CharField(max_length=20, choices=BulkEmailRecipient.STATUS_CHOICES)
    message = models.TextField(blank=True, null=True)
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='bulk_email_send_logs')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.bulk_email.subject} - {self.email} - {self.status}"

    class Meta:
        ordering = ['-created_at']


class BulkEmailsReporting(models.Model):  # Tracking sent emails
    subject = models.CharField(max_length=255)
    body = models.TextField()
    button_text = models.CharField(max_length=120, blank=True, null=True)
    button_url = models.URLField(max_length=500, blank=True, null=True)
    recipients = models.TextField()  # Store as comma-separated list
    sent_date = models.DateTimeField(auto_now_add=True)
    attachment = models.FileField(upload_to='attachments/', blank=True, null=True)

    def __str__(self):
        return self.subject

# Bulk Email Model Ends here----------------------------------------------------------------------------#

# Group Email Model Starts here----------------------------------------------------------------------------#
from django.db import models

class EmailGroup(models.Model):
    name = models.CharField(max_length=255, unique=True)  # Name of the group
    email_addresses = models.TextField(help_text="Comma-separated list of email addresses")  # Comma-separated emails

    def __str__(self):
        return self.name

    def parsed_emails(self):
        seen = set()
        emails = []
        for raw_email in self.email_addresses.replace('\n', ',').split(','):
            email = raw_email.strip()
            email_key = email.lower()
            if email and email_key not in seen:
                emails.append(email)
                seen.add(email_key)
        return emails
# Group Email Model Ends Here-----------------------------------------------------------------------------#

# Pending Payment Reminder models starts here-------------------------------------------------------------#

class PendingPaymentReminder(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="pending_reminders")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="pending_reminders")
    reminder_count = models.PositiveIntegerField(default=0)  # Tracks how many emails were sent
    last_reminder_sent = models.DateTimeField(blank=True, null=True)  # Timestamp of the last reminder
    payment_link = models.CharField(max_length=500, blank=True, null=True)  # Payment link for the participant

    def __str__(self):
        return f"{self.participant.name} - {self.event.name}"

    class Meta:
        unique_together = ('participant', 'event')  # Prevent duplicate entries for the same participant/event
# Pending Payment Reminder models ends here-------------------------------------------------------------#
