from django.db.models import Q
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.contrib import messages
from .models import FeatureSpeaker, Participant, AbstractSubmission, Department, HallRoom, TimeSlot, ProgramDay, ProgramSchedule, Invitation, AboutTheConference, Sponsor, Event, Chairperson, Panelist, Moderator, PaymentStatus, UserProfile, ProgramSchedulePdf, UploadAbstractBook, UploadNoteBook
from .forms import AbstractSubmissionForm, RegistrationForm, ProgramScheduleForm
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from django.core.mail import send_mail
from .resources import ParticipantResource, AbstractSubmissionResource, TimeSlotResource, PaymentStatusResource, RegistrationKitResource
# SchedulingResource
from .pdf_utils import generate_abstract_pdf
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.crypto import get_random_string
from django.contrib.auth import get_user_model
from .views import send_approval_email
import time

User = get_user_model()  # Getting the user model.

class UserProfileAdmin(ImportExportModelAdmin):
    list_display = ('user', 'name', 'phone', 'country')
    list_per_page = 15
    search_fields = ('user__username', 'name', 'phone')
admin.site.register(UserProfile, UserProfileAdmin)
# Register your models here.
class InvitationAdmin(admin.ModelAdmin):
    list_display = ('name', 'event')
    list_filter = ('event',)

admin.site.register(Invitation, InvitationAdmin)

class AboutTheConferenceAdmin(admin.ModelAdmin):
    list_display = ('title', 'event')
    list_filter = ('event',)

admin.site.register(AboutTheConference, AboutTheConferenceAdmin)

class ChairpersonAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'country', 'event')
    list_filter = ('event',)
    search_fields = ('name', 'email')
admin.site.register(Chairperson, ChairpersonAdmin)

class PanelistAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'country', 'event')
    list_filter = ('event',)
    search_fields = ('name', 'email')
    list_per_page = 15
admin.site.register(Panelist, PanelistAdmin)

class ModeratorAdmin(admin.ModelAdmin):
    list_display = ('name', 'country', 'event')
    list_filter = ('event',)
    list_per_page = 15
    search_fields = ('name', 'email')
admin.site.register(Moderator, ModeratorAdmin)

class EventAdmin(admin.ModelAdmin):
    list_display = ('name', 'id','year', 'location', 'start_date', 'event_status', 'registration', 'show_publication_tab', 'payment_required')
    list_filter = ('year', 'event_status', 'payment_required')
    search_fields = ('name',)
    list_editable = ('show_publication_tab', 'payment_required')
admin.site.register(Event, EventAdmin)

import os
from dotenv import load_dotenv
load_dotenv()
class FeatureSpeakerAdmin(admin.ModelAdmin):
    list_display = ('name', 'speciality', 'institution', 'event')
    list_filter = ('event',)
    list_per_page = 15
admin.site.register(FeatureSpeaker, FeatureSpeakerAdmin)

#from django.urls import reverse
#def send_consolidated_email(participant, password, include_password):
#    event = participant.event
#    subject = f'Your Registration for {event.name} {event.year} is Approved!'
#       # Path-based payment URL
#    payment_url = reverse('payment', kwargs={
#        'event_id': event.id,
#        'participant_id': participant.id
#    })
#    full_payment_url = f'https://event.bsbcs.org{payment_url}'
#    
#    try:
#        context = {
#            'participant': participant,
#            'event': event,
#            'payment_url': full_payment_url,
#        }
#        if include_password:
#            context['password'] = password
#
#       html_content = render_to_string('consolidated_email.html', context)
#        text_content = strip_tags(html_content)
#        from_email = os.getenv("EMAIL_HOST_USER")
#        recipient_list = [participant.email]
#
#        email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
#        email.attach_alternative(html_content, "text/html")
#        email.send()
#    except Exception as e:
#        print(f"Error sending consolidated email: {e}")



from django.urls import reverse
def send_consolidated_email(request, participant, password, include_password):
    event = participant.event
    subject = f'Your Registration for {event.name} {event.year} is Approved!'
       # Path-based payment URL
    payment_url = reverse('registration:payment', kwargs={
        'event_id': event.id,
        'participant_id': participant.id
    })
    full_payment_url = request.build_absolute_uri(payment_url)

    try:
        context = {
            'participant': participant,
            'event': event,
            'payment_url': full_payment_url,
        }
        if include_password:
            context['password'] = password

        html_content = render_to_string('consolidated_email.html', context)
        text_content = strip_tags(html_content)
        from_email = os.getenv("EMAIL_HOST_USER")
        recipient_list = [participant.email]

        email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
        email.attach_alternative(html_content, "text/html")
        email.send()
    except Exception as e:
        print(f"Error sending consolidated email: {e}")

def send_free_event_confirmation_email(participant, event, password=None, include_password=False):
    """Send confirmation email for free events"""
    subject = f'Registration Confirmed for {event.name} {event.year}'
    
    context = {
        'participant': participant,
        'event': event,
    }
    
    if include_password and password:
        context['password'] = password
    
    html_content = render_to_string('free_event_confirmation_email.html', context)
    text_content = strip_tags(html_content)
    
    email = EmailMultiAlternatives(
        subject, 
        text_content, 
        os.getenv("EMAIL_HOST_USER"),
        [participant.email]
    )
    email.attach_alternative(html_content, "text/html")
    email.send()

# Event Specific Participants admin view START------------------------------------------------------------------------------#
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

def approve_participants(modeladmin, request, queryset):
    for participant in queryset:
        event = participant.event
        
        if not User.objects.filter(email=participant.email).exists():
            password = get_random_string(length=12)
            user = User.objects.create_user(username=participant.email, email=participant.email, password=password)
            include_password = True
        else:
            user = User.objects.get(email=participant.email)
            password = None
            include_password = False

        if not participant.approved:
            participant.approved = True
        if participant.denied:
            participant.denied = False
        participant.save()

        # For free events, update the merchant invoice number to be unique
        if not event.payment_required:
            try:
                payment_status = PaymentStatus.objects.get(participant=participant, event=event)
                # Generate unique merchant invoice number for free events
                merchant_invoice_number = f"FREE-{event.id}-{participant.id}-{int(time.time())}"
                payment_status.merchant_invoice_number = merchant_invoice_number
                payment_status.status = 'completed'
                payment_status.save()
            except PaymentStatus.DoesNotExist:
                pass
        # Handle email based on payment requirement
        if event.payment_required and event.amount:
            # For paid events, send payment email
            send_consolidated_email(request, participant, password, include_password)
        else:
            # For free events, send confirmation email
            send_free_event_confirmation_email(participant, event, password, include_password)

def deny_participants(modeladmin, request, queryset):
    queryset.update(denied=True, approved=False)

approve_participants.short_description = "Approve selected participants"
deny_participants.short_description = "Deny selected participants"

class ParticipantAdmin(ImportExportModelAdmin):
    resource_class = ParticipantResource
    list_display = ('name', 'email', 'phone', 'department', 'organization', 'BMDC_registration_number', 'country', 'created_at', 'approved', 'denied', 'event')
    list_per_page = 15
    search_fields = ('name', 'phone', 'organization', 'BMDC_registration_number')
    list_filter = ('approved', 'denied', 'country', 'event')  # Add filters
    actions = [approve_participants, deny_participants]

admin.site.register(Participant, ParticipantAdmin)


from import_export.admin import ImportExportModelAdmin
from .models import PaymentStatus
from .resources import PaymentStatusResource  # Import the custom resource

class PaymentStatusAdmin(ImportExportModelAdmin):
    resource_class = PaymentStatusResource  # Use the custom resource
    list_display = ('participant', 'event', 'status', 'amount', 'merchant_invoice_number', 'transaction_id', 'trxID', 'invoice', 'email_sent', 'updated_at')
    search_fields = ('participant__name', 'participant__email', 'event__name', 'merchant_invoice_number', 'transaction_id', 'trxID', 'email_sent')
    list_filter = ('status', 'event')
    list_per_page = 15

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(participant__approved=True)

admin.site.register(PaymentStatus, PaymentStatusAdmin)

# Departments admin view START------------------------------------------------------------------------------#
@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'event')
    search_fields = ('name',)
    list_filter = ('event',)
# Departments admin view END-----------------------------------------------------------------------------#



class HallRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'event')
    list_filter = ('event',)
admin.site.register(HallRoom, HallRoomAdmin)
class TimeSlotAdmin(ImportExportModelAdmin):
    resource_class = TimeSlotResource
    list_display = ('start_time', 'end_time', 'program_day', 'hall_room', 'event')
    search_fields = ('hall_room', 'program_day')
    list_filter = ('program_day', 'hall_room', 'event')
admin.site.register(TimeSlot, TimeSlotAdmin)

# Program Day admin view START------------------------------------------------------------------------------#
class ProgramDayAdmin(admin.ModelAdmin):
    list_display = ('event', 'date', 'name')
    list_filter = ('event', 'date', 'name')
admin.site.register(ProgramDay, ProgramDayAdmin)

# Abstracts admin view START------------------------------------------------------------------------------#
def approve_for_presentation(modeladmin, request, queryset):
    queryset.update(approved_for_presentation=True, approved_for_poster=False)

    # send an approval email
    for abstract in queryset:
        send_approval_email(abstract, "Presentation")

def approve_for_poster(modeladmin, request, queryset):
    queryset.update(approved_for_poster=True, approved_for_presentation=False)

    # send an approval email
    for abstract in queryset:
        send_approval_email(abstract, "Poster")
def export_as_pdf(modeladmin, request, queryset):
    if queryset.exists():
        event = queryset.first().event
        buffer = generate_abstract_pdf(event, queryset)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="abstracts.pdf"'
        return response
    else:
        messages.error(request, "No abstracts selected for export.")
        return HttpResponseRedirect(request.get_full_path())

export_as_pdf.short_description = "Export selected abstracts as PDF"

class AbstractSubmissionAdmin(ImportExportModelAdmin):
    list_display = ('title', 'authors', 'institution', 'user', 'approved_for_presentation', 'approved_for_poster', 'event')
    search_fields = ('title', 'authors')
    list_filter = ('approved_for_presentation', 'approved_for_poster', 'event')
    actions = [approve_for_presentation, approve_for_poster, export_as_pdf]
    fields = ['user', 'title', 'authors', 'institution', 'introduction', 'methods', 'results', 'conclusion', 'image', 'presentation_file', 'approved_for_presentation', 'approved_for_poster', 'event']

admin.site.register(AbstractSubmission, AbstractSubmissionAdmin)
# Abstracts admin view END-----------------------------------------------------------------------------#
# Abstracts approval email START------------------------------------------------------------------------------#
def send_approval_email(abstract, approval_type):
    # Determine the subject and email content based on approval type
    subject = f"Abstract Approved for {approval_type.capitalize()}"
    context = {
        'user': abstract.user,
        'abstract': abstract,
        'approval_type': approval_type
    }
    html_content = render_to_string('abstract_approval_email.html', context)
    text_content = strip_tags(html_content)
    from_email = os.getenv("EMAIL_HOST_USER")
    recipient_list = [abstract.user.email]

    # Create and send the email
    email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
    email.attach_alternative(html_content, "text/html")
    email.send()
# Abstracts approval email END-----------------------------------------------------------------------------#
# Program Schedule admin view START------------------------------------------------------------------------------#
from .pdf_utils import generate_schedule_pdf
class ProgramScheduleAdmin(admin.ModelAdmin):
    form = ProgramScheduleForm
    list_display = ('title', 'presenter', 'get_hall_rooms', 'get_program_days', 'get_start_times', 'get_end_times', 'chairperson', 'moderator', 'event', 'email_sent')
    filter_horizontal = ('time_slots', 'panelist')
    list_filter = ('time_slots__program_day', 'time_slots__hall_room', 'time_slots__start_time', 'event', 'email_sent')
    actions = ['send_schedule_email', 'export_schedule_pdf']
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj:
            form.base_fields['abstract_submission'].queryset = AbstractSubmission.objects.filter(pk=obj.abstract_submission.pk)
        else:
            form.base_fields['abstract_submission'].queryset = AbstractSubmission.objects.filter(
                Q(approved_for_presentation=True) | Q(approved_for_poster=True)
            ).exclude(programschedule__isnull=False)
        return form
    def send_schedule_email(self, request, queryset):
        for schedule in queryset:
            participants = [schedule.abstract_submission.user.email]
            subject = f"Program Schedule: {schedule.event.name} {schedule.event.year}"
            context = {
                'schedule': schedule,
                'event': schedule.event,
                'hall_rooms': ", ".join([slot.hall_room.name for slot in schedule.time_slots.all()]),
                'program_days': ", ".join([slot.program_day.name for slot in schedule.time_slots.all()]),
                'start_times': ", ".join([slot.start_time.strftime('%I:%M %p') for slot in schedule.time_slots.all()]),
                'end_times': ", ".join([slot.end_time.strftime('%I:%M %p') for slot in schedule.time_slots.all()]),
            }
            html_content = render_to_string('schedule_mail.html', context)
            text_content = strip_tags(html_content)

            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email= os.getenv("EMAIL_HOST_USER"),
                to=participants
            )
            email.attach_alternative(html_content, "text/html")
            try:
                email.send()
                schedule.email_sent = True
                schedule.save()
                self.message_user(request, f"Email sent to participant for schedule: {schedule.title}")
            except Exception as e:
                messages.error(request, f"Failed to send email for schedule: {schedule.title}. Error: {e}")
    send_schedule_email.short_description = "Send Schedule Email to Participants"
    def export_schedule_pdf(self, request, queryset):
        if queryset.count() == 0:
            self.message_user(request, "No schedules selected for PDF export.", level=messages.WARNING)
            return

        event = queryset.first().event  # Assuming schedules belong to the same event
        pdf_buffer = generate_schedule_pdf(event, queryset)
        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Program_Schedule_{event.name}_{event.year}.pdf"'
        return response

    export_schedule_pdf.short_description = "Export Program Schedule as PDF"
    def get_hall_rooms(self, obj):
        return ", ".join([slot.hall_room.name for slot in obj.time_slots.all()])
    get_hall_rooms.short_description = 'Hall Room'

    def get_program_days(self, obj):
        return ", ".join([slot.program_day.name for slot in obj.time_slots.all()])
    get_program_days.short_description = 'Program Day'

    def get_start_times(self, obj):
        return ", ".join([slot.start_time.strftime('%I:%M %p') for slot in obj.time_slots.all()])
    get_start_times.short_description = 'Start Time'

    def get_end_times(self, obj):
        return ", ".join([slot.end_time.strftime('%I:%M %p') for slot in obj.time_slots.all()])
    get_end_times.short_description = 'End Time'

admin.site.register(ProgramSchedule, ProgramScheduleAdmin)
# Program Schedule admin view END-----------------------------------------------------------------------------#

class SponsorAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'event')
    list_filter = ('category', 'event')
admin.site.register(Sponsor, SponsorAdmin)

# Event Gallery admin view START-------------------------------------------------------------------#

from .models import EventImage, EventVideo

class EventImageAdmin(admin.ModelAdmin):
    list_display = ('image', 'caption', 'event')
    list_filter = ('event',)

class EventVideoAdmin(admin.ModelAdmin):
    list_display = ('youtube_url', 'caption', 'event')
    list_filter = ('event',)

admin.site.register(EventImage, EventImageAdmin)
admin.site.register(EventVideo, EventVideoAdmin)

# Event Gallery admin view END-------------------------------------------------------------------#
# Registration Kit admin view START-------------------------------------------------------------------#
from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from .models import RegistrationKit, PaymentStatus, Event
from .resources import RegistrationKitResource
from django.utils.timezone import now

class RegistrationKitAdmin(ImportExportModelAdmin):
    resource_class = RegistrationKitResource
    list_display = ('participant_name', 'amount', 'payment_status_display', 'payment_status__merchant_invoice_number', 'event', 'kit_status', 'issued_at')
    list_filter = ('status', 'event')
    search_fields = ('payment_status__participant__name', 'payment_status__participant__email', 'payment_status__participant__phone', 'payment_status__merchant_invoice_number')
    actions = ['populate_registration_kits', 'issue_registration_kits']

    def participant_name(self, obj):
        return obj.payment_status.participant.name
    participant_name.short_description = 'Participant Name'

    def amount(self, obj):
        return obj.payment_status.amount
    amount.short_description = 'Amount'

    def payment_status_display(self, obj):
        return obj.payment_status.status
    payment_status_display.short_description = 'Payment Status'

    def event_year(self, obj):
        return obj.event.year
    event_year.short_description = 'Event Year'

    def kit_status(self, obj):
        return obj.status
    kit_status.short_description = 'Registration Kit Status'

    def populate_registration_kits(self, request, queryset):
        paid_payment_statuses = PaymentStatus.objects.filter(status='completed')
        for payment_status in paid_payment_statuses:
            RegistrationKit.objects.get_or_create(
                event=payment_status.event,
                payment_status=payment_status,
                defaults={'status': 'not_issued'}
            )
        self.message_user(request, "Registration Kits populated for participants with completed payments.")

    populate_registration_kits.short_description = "Populate Registration Kits for paid participants"

    def issue_registration_kits(self, request, queryset):
        updated_count = queryset.update(status='issued', issued_at=now())
        self.message_user(request, f"{updated_count} Registration Kits have been issued.")

    issue_registration_kits.short_description = "Issue selected Registration Kits"

admin.site.register(RegistrationKit, RegistrationKitAdmin)


from .models import BkashData
class BkashDataAdmin(ImportExportModelAdmin):
    list_display = ('payment_id', 'trx_id', 'mode', 'payment_create_time', 'payment_execute_time', 'amount', 'currency', 'intent', 'merchant_invoice', 'transaction_status', 'service_fee', 'verification_status', 'payer_reference', 'payer_type', 'status_code', 'status_message')
    list_filter = ('verification_status', 'status_message')
admin.site.register(BkashData, BkashDataAdmin)



class ProgramSchedulePdfAdmin(admin.ModelAdmin):
    list_display = ('event',)  # 'title' is not defined in your model, so I removed it
    list_filter = ('event',)

admin.site.register(ProgramSchedulePdf, ProgramSchedulePdfAdmin)  # Correct registration

# New Model Registration Here
class UploadAbstractBookAdmin(admin.ModelAdmin):
    list_display = ('event',)  # 'title' is not defined in your model, so I removed it
    list_filter = ('event',)

admin.site.register(UploadAbstractBook, UploadAbstractBookAdmin)

class UploadNoteBookAdmin(admin.ModelAdmin):
    list_display = ('event',)  # 'title' is not defined in your model, so I removed it
    list_filter = ('event',)

admin.site.register(UploadNoteBook, UploadNoteBookAdmin)


#Thank You Email Admin Starts--------------------------------------------------#

from django.contrib import admin
from django.utils.safestring import mark_safe
from django.contrib import messages
from .models import ThankYouEmail, RegistrationKit

@admin.register(ThankYouEmail)
class ThankYouEmailAdmin(admin.ModelAdmin):
    list_display = ('participant_name', 'event_name', 'email_sent', 'sent_at', 'email_status_summary')
    list_filter = ('registration_kit__event', 'email_sent')  # Filter by Event & Email Sent status
    search_fields = ('registration_kit__payment_status__participant__name', 'registration_kit__event__name')
    actions = ['populate_thank_you_emails', 'send_thank_you_emails']

    def participant_name(self, obj):
        """Get the participant's name from PaymentStatus."""
        return obj.registration_kit.payment_status.participant.name
    participant_name.short_description = "Participant Name"

    def event_name(self, obj):
        """Get the Event name."""
        return obj.registration_kit.event.name
    event_name.short_description = "Event"

    def email_status_summary(self, obj):
        """Display total emails sent vs. total issued kits."""
        total_issued_kits = RegistrationKit.objects.filter(status='issued').count()
        total_emails_sent = ThankYouEmail.objects.filter(email_sent=True).count()
        return mark_safe(f"<b>{total_emails_sent} / {total_issued_kits}</b>")

    email_status_summary.short_description = "Emails Sent"

    def populate_thank_you_emails(self, request, queryset=None):
        """Create ThankYouEmail instances for issued RegistrationKits using the Event's email template."""
        issued_kits = RegistrationKit.objects.filter(status='issued')
        created_count = 0

        for kit in issued_kits:
            event = kit.event
            if not event.email_subject or not event.email_body:
                continue  

            if not ThankYouEmail.objects.filter(registration_kit=kit).exists():
                ThankYouEmail.objects.create(
                    registration_kit=kit,
                    subject=event.email_subject,
                    body=event.email_body,
                )
                created_count += 1

        self.message_user(request, f"Created {created_count} Thank You Emails.", messages.SUCCESS)

    populate_thank_you_emails.short_description = "Populate Thank You Emails"

    def send_thank_you_emails(self, request, queryset):
        """Send emails to participants whose Thank You Emails are pending."""
        count = 0
        for email_obj in queryset:
            if not email_obj.email_sent:
                email_obj.send_email()
                count += 1
        self.message_user(request, f"Successfully sent {count} thank-you emails.", messages.SUCCESS)

    send_thank_you_emails.short_description = "Send Thank You Emails"

#Thank You Email Admin Starts--------------------------------------------------#

# Certificate admin starts ----------------------------------------------------#

from .models import Certificate


class CertificateAdmin(admin.ModelAdmin):
    list_display = ('id', 'event')
admin.site.register(Certificate, CertificateAdmin)

# Feedback Form Model Starts here----------------------------------------------------------------------------#
from django.contrib import admin
from .models import FeedbackQuestion, FeedbackResponse

@admin.register(FeedbackQuestion)
class FeedbackQuestionAdmin(admin.ModelAdmin):
    list_display = ['question_text', 'question_type', 'is_required', 'order']
    list_filter = ['event', 'question_type']
    list_editable = ['order', 'is_required']
    search_fields = ['question_text']





from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from import_export.admin import ImportExportModelAdmin

class FeedbackResponseResource(resources.ModelResource):
    participant = fields.Field(
        column_name='Participant',
        attribute='participant',
        widget=ForeignKeyWidget(Participant, 'name'))
    
    event = fields.Field(
        column_name='Event',
        attribute='event',
        widget=ForeignKeyWidget(Event, 'name'))
    
    question_text = fields.Field(
        column_name='Question',
        attribute='question__question_text')
    
    response = fields.Field(
        column_name='Response',
        attribute='response')

    class Meta:
        model = FeedbackResponse
        fields = ('id', 'participant', 'event', 'question_text', 'response')
        export_order = fields
        skip_unchanged = True



@admin.register(FeedbackResponse)
class FeedbackResponseAdmin(ImportExportModelAdmin):
    resource_class = FeedbackResponseResource
    list_display = (
        'participant_name', 
        'participant_email',
        'event_link',
        'question_display', 
        'response_display'
    )
    list_select_related = ('participant', 'event', 'question')
    search_fields = (
        'participant__name', 
        'participant__email',
        'event__name', 
        'question__question_text',
        'response'
    )
    list_filter = ('event', 'participant')
    autocomplete_fields = ['participant', 'event', 'question']
    
    fieldsets = (
        (None, {
            'fields': ('participant', 'event', 'question')
        }),
        ('Response Details', {
            'fields': ('response',),
            'classes': ('wide',),
        }),
    )

    # Participant columns
    def participant_name(self, obj):
        url = reverse('admin:registration_participant_change', args=[obj.participant.id])
        return format_html('<a href="{}">{}</a>', url, obj.participant.name)
    participant_name.short_description = 'Participant Name'
    participant_name.admin_order_field = 'participant__name'

    def participant_email(self, obj):
        return obj.participant.email
    participant_email.short_description = 'Email'
    participant_email.admin_order_field = 'participant__email'

    # Event column
    def event_link(self, obj):
        url = reverse('admin:registration_event_change', args=[obj.event.id])
        return format_html('<a href="{}">{}</a>', url, obj.event.name)
    event_link.short_description = 'Event'
    event_link.admin_order_field = 'event__name'

    # Question/Response columns
    def question_display(self, obj):
        return obj.question.question_text
    question_display.short_description = 'Question'

    def response_display(self, obj):
        return obj.response
    response_display.short_description = 'Response'

    # Link configuration
    list_display_links = ('question_display', 'response_display')  # Click these to see full details
    list_per_page = 50

# Feedback Admin Ends Here -----------------------------------------------------#

# Bulk email and group emails admin start here -------------------------------------------------------------#
from django.contrib import admin
from .models import BulkEmail, BulkEmailsReporting, EmailGroup
from import_export import resources
from import_export.admin import ExportMixin
from django.core.mail import EmailMessage
from django.contrib.auth import get_user_model
from django.shortcuts import render

User = get_user_model()  # Fetch the user model


@admin.register(BulkEmail)
class BulkEmailAdmin(admin.ModelAdmin):
    list_display = ('subject', 'created_at')
    actions = ['mail_to_active_users', 'mail_to_email_group']

    def mail_to_active_users(self, request, queryset):
        # Ensure only one email instance is selected
        if queryset.count() != 1:
            self.message_user(request, "Please select exactly one email to send.", level='error')
            return

        # Get the selected BulkEmail instance
        bulk_email = queryset.first()

        # Fetch active users' email addresses
        active_users = User.objects.filter(is_active=True)
        recipients = [user.email for user in active_users if user.email]  # Ensure email is not blank

        # Send the email using BCC
        email = EmailMessage(
            subject=bulk_email.subject,
            body=bulk_email.body,
            from_email='info.bsbcs@gmail.com',
            bcc=recipients,  # Use BCC for privacy
        )
        if bulk_email.attachment:
            email.attach_file(bulk_email.attachment.path)
        email.send()

        # Automatically log the sent email
        BulkEmailsReporting.objects.create(
            subject=bulk_email.subject,
            body=bulk_email.body,
            recipients=', '.join(recipients),  # Convert recipient list to comma-separated string
            attachment=bulk_email.attachment if bulk_email.attachment else None,
        )

        # Notify admin of success
        self.message_user(request, f"Email sent to {len(recipients)} active users and logged successfully.")

    mail_to_active_users.short_description = "Mail to Active Users"

    def mail_to_email_group(self, request, queryset):
        # Ensure one email is selected
        if queryset.count() != 1:
            self.message_user(request, "Please select exactly one email.", level='error')
            return

        bulk_email = queryset.first()

        # Check if group is selected (POST with group_id)
        if 'group_id' in request.POST:
            group_id = request.POST.get('group_id')
            try:
                group = EmailGroup.objects.get(id=group_id)
                emails = [e.strip() for e in group.email_addresses.split(',') if e.strip()]
            except EmailGroup.DoesNotExist:
                self.message_user(request, "Group not found.", level='error')
                return

            # Send email and log...
            email = EmailMessage(
                subject=bulk_email.subject,
                body=bulk_email.body,
                from_email= os.getenv("EMAIL_HOST_USER"),
                bcc=emails,
            )
            if bulk_email.attachment:
                email.attach_file(bulk_email.attachment.path)
            email.send()

            BulkEmailsReporting.objects.create(
                subject=bulk_email.subject,
                body=bulk_email.body,
                recipients=', '.join(emails),
                attachment=bulk_email.attachment,
            )

            self.message_user(request, f"Email sent to group '{group.name}'.")
            return HttpResponseRedirect(request.get_full_path())

        else:
            # Show group selection form
            groups = EmailGroup.objects.all()
            context = {
                'bulk_email': bulk_email,
                'email_groups': groups,
                'queryset': queryset,  # Pass queryset for hidden fields
            }
            return render(request, 'admin/select_email_group.html', context)

    mail_to_email_group.short_description = "Mail to Email Group"


class BulkEmailsReportingResource(resources.ModelResource):
    class Meta:
        model = BulkEmailsReporting


from django.utils.safestring import mark_safe

@admin.register(BulkEmailsReporting)
class BulkEmailsReportingAdmin(ExportMixin, admin.ModelAdmin):
    resource_class = BulkEmailsReportingResource
    list_display = ('subject', 'sent_date', 'recipient_count', 'view_recipients_link')
    list_per_page = 50
    search_fields = ('subject', 'recipients')  # Enable search for subject and recipients
    list_filter = ('sent_date',)  # Filter by sent date

    def recipient_count(self, obj):
        # Show the count of recipients
        return len(obj.recipients.split(','))
    recipient_count.short_description = "Recipient Count"

    def view_recipients_link(self, obj):
        # Create a clickable link to view recipients in detail
        link = f'<a href="/admin/registration/bulkemailsreporting/{obj.id}/change/">{obj.subject} Recipients</a>'
        return mark_safe(link)  # Ensure the HTML is rendered
    view_recipients_link.short_description = "View Recipients"


@admin.register(EmailGroup)
class EmailGroupAdmin(ImportExportModelAdmin):
    list_display = ('name', 'email_addresses')
    list_per_page = 50

# Bulk email and group emails admin Ends here -------------------------------------------------------------#



# Pending Payment Reminder Admin Starts here---------------------------------------------------------------#

from django.utils.timezone import now
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from urllib.parse import urlencode
from django.urls import reverse
from .models import PendingPaymentReminder

@admin.register(PendingPaymentReminder)
class PendingPaymentReminderAdmin(admin.ModelAdmin):
    list_display = ('participant', 'event', 'reminder_count', 'last_reminder_sent', 'payment_link')
    search_fields = ('participant__name', 'participant__email', 'event__name')
    list_filter = ('event',)  # Filter by event
    readonly_fields = ('payment_link',)  # Prevent manual edits to the payment link

    actions = ['refresh_pending_reminders', 'send_payment_reminders']  # Add two actions

    def refresh_pending_reminders(self, request, queryset):
        """
        Custom admin action to refresh the PendingPaymentReminder list.
        """
        added_count = 0
        print("Starting refresh process...")  # Debugging log

        # Process all active events in the system
        events = Event.objects.filter(event_status='active')
        print(f"Processing events: {[event.name for event in events]}")  # Debugging log

        for event in events:
            participants = Participant.objects.filter(event=event, approved=True)
            print(f"Found participants for event {event.name}: {[participant.name for participant in participants]}")  # Debugging log

            for participant in participants:
                if not PendingPaymentReminder.objects.filter(participant=participant, event=event).exists():
                    payment_status = PaymentStatus.objects.filter(participant=participant, event=event).first()
                    print(f"Checking participant {participant.name} with payment status: {payment_status.status if payment_status else 'No Status'}")  # Debugging log

                    if not payment_status or payment_status.status not in ['paid', 'completed']:
                        PendingPaymentReminder.objects.create(
                            participant=participant,
                            event=event,
                            payment_link=reverse('registration:payment', kwargs={
                                'event_id': event.id,
                                'participant_id': participant.id
                            })
                        )
                        print(f"Added {participant.name} to PendingPaymentReminder.")  # Debugging log
                        added_count += 1
                    else:
                        print(f"Skipped {participant.name}: Payment status is {payment_status.status}.")  # Debugging log
                else:
                    print(f"Skipped {participant.name}: Already in PendingPaymentReminder.")  # Debugging log

        # Provide feedback to the admin
        self.message_user(request, f"Successfully added {added_count} participant(s) to Pending Payment Reminders.")
        print(f"Refresh completed. Total added: {added_count}")  # Debugging log

    refresh_pending_reminders.short_description = "Refresh Pending Payment Reminder List"

    def send_payment_reminders(self, request, queryset):
        """
        Custom admin action to send payment reminders to selected participants.
        """
        success_count = 0
        for reminder in queryset:
            # Generate the payment link using the event and participant
            payment_url = reverse('registration:payment', kwargs={
                'event_id': reminder.event.id,
                'participant_id': reminder.participant.id
            })

            # Add login redirect logic
            login_url = reverse('login')
            full_next_url = request.build_absolute_uri(payment_url)
            full_payment_url = f"{request.build_absolute_uri(login_url)}?{urlencode({'next': full_next_url})}"

            try:
                # Prepare email context
                context = {
                    'participant': reminder.participant,
                    'event': reminder.event,
                    'payment_url': full_payment_url
                }

                # Render email content
                subject = f"Payment Reminder for {reminder.event.name} {reminder.event.year}"
                html_content = render_to_string('payment_reminder_email.html', context)
                text_content = strip_tags(html_content)
                from_email = os.getenv("EMAIL_HOST_USER")
                recipient_list = [reminder.participant.email]

                # Send email
                email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
                email.attach_alternative(html_content, "text/html")
                email.send()

                # Update reminder details
                reminder.reminder_count += 1
                reminder.last_reminder_sent = now()
                reminder.save()
                success_count += 1

            except Exception as e:
                self.message_user(request, f"Failed to send email to {reminder.participant.email}: {e}", level='error')

        # Provide feedback to the admin
        self.message_user(request, f"Successfully sent {success_count} payment reminder(s).")

    send_payment_reminders.short_description = "Send Payment Reminders"

# Pending Payment Reminder Admin ends here ----------------------------------------------------------#
