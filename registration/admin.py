from django.db.models import Q
from django.contrib import admin
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.contrib import messages
from .models import FeatureSpeaker, Participant, ParticipantEmailLog, AbstractSubmission, Department, HallRoom, TimeSlot, ProgramDay, ProgramSchedule, ProgramPerson, ProgramPersonEmailLog, ProgramSession, ProgramSessionFaculty, ProgramSessionItem, ProgramTalkSlot, ProgramItemFaculty, PresentationUpload, Invitation, AboutTheConference, Sponsor, Event, Chairperson, Panelist, Moderator, PaymentStatus, UserProfile, CorporateAccountRequest, CorporateAccount, CorporateEventRegistration, CorporateEventComplementaryQuota, CorporateEventAttendee, CorporatePayment, ProgramSchedulePdf, UploadAbstractBook, UploadNoteBook
from .forms import AbstractSubmissionForm, RegistrationForm, ProgramScheduleForm
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from django.core.mail import EmailMessage, send_mail
from .resources import ParticipantResource, AbstractSubmissionResource, TimeSlotResource, PaymentStatusResource, RegistrationKitResource
from .tasks import send_email_task
# SchedulingResource
from .pdf_utils import generate_abstract_pdf, generate_corporate_invoice
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.crypto import get_random_string
from django.utils.html import format_html
from django.utils import timezone
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.contrib.auth import get_user_model
from .views import send_approval_email
from .program_emails import send_program_assignment_email
import time

User = get_user_model()  # Getting the user model.


def write_admin_audit_log(request, obj, action_flag=CHANGE, message='Updated from admin workflow.'):
    if not obj or not getattr(request, 'user', None) or not request.user.is_authenticated:
        return
    content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    LogEntry.objects.create(
        user_id=request.user.pk,
        content_type_id=content_type.pk,
        object_id=str(obj.pk),
        object_repr=str(obj)[:200],
        action_flag=action_flag,
        change_message=message,
    )

class UserProfileAdmin(ImportExportModelAdmin):
    list_display = ('user', 'name', 'phone', 'country')
    list_per_page = 15
    search_fields = ('user__username', 'name', 'phone')
    readonly_fields = ('image_preview',)
    fields = ('user', 'name', 'email', 'phone', 'country', 'image', 'image_preview')

    def image_preview(self, obj):
        if obj and obj.image:
            return format_html('<img src="{}" style="height: 80px; width: 80px; object-fit: cover; border-radius: 8px;" />', obj.image.url)
        return "No image uploaded"

    image_preview.short_description = "Current image"
admin.site.register(UserProfile, UserProfileAdmin)


@admin.register(CorporateAccountRequest)
class CorporateAccountRequestAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'contact_name', 'email', 'phone', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('company_name', 'contact_name', 'email', 'phone')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Company', {
            'fields': ('company_name', 'note')
        }),
        ('Contact person', {
            'fields': ('contact_name', 'contact_designation', 'email', 'phone')
        }),
        ('Admin review', {
            'fields': ('status', 'admin_note')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            old_status = CorporateAccountRequest.objects.filter(pk=obj.pk).values_list('status', flat=True).first()

        super().save_model(request, obj, form, change)

        if obj.status == old_status:
            return

        if obj.status == 'approved':
            corporate_account, created_user = self._create_or_update_corporate_account(request, obj)
            try:
                self._send_corporate_approval_email(request, obj, corporate_account, created_user)
            except Exception as exc:
                self.message_user(request, f"Corporate access approved, but approval email could not be sent: {exc}", messages.ERROR)
                return
            self.message_user(request, f"Corporate access approved for {obj.company_name}.", messages.SUCCESS)
        elif obj.status == 'rejected':
            try:
                self._send_corporate_rejection_email(request, obj)
            except Exception as exc:
                self.message_user(request, f"Corporate request rejected, but rejection email could not be sent: {exc}", messages.ERROR)
                return
            self.message_user(request, f"Corporate access rejection email sent to {obj.email}.", messages.WARNING)

    def _create_or_update_corporate_account(self, request, obj):
        user = User.objects.filter(email__iexact=obj.email).first() or User.objects.filter(username__iexact=obj.email).first()
        created_user = False

        if not user:
            user = User.objects.create_user(username=obj.email, email=obj.email)
            user.set_unusable_password()
            user.first_name = obj.contact_name[:150]
            user.save()
            write_admin_audit_log(request, user, ADDITION, "Created corporate login user from corporate access approval.")
            created_user = True

        corporate_account, account_created = CorporateAccount.objects.update_or_create(
            user=user,
            defaults={
                'source_request': obj,
                'company_name': obj.company_name,
                'contact_name': obj.contact_name,
                'contact_designation': obj.contact_designation,
                'email': obj.email,
                'phone': obj.phone,
                'status': 'approved',
                'approved_at': timezone.now(),
            }
        )
        write_admin_audit_log(
            request,
            corporate_account,
            ADDITION if account_created else CHANGE,
            "Created or updated corporate account from corporate access approval.",
        )
        return corporate_account, created_user

    def _build_absolute_url(self, request, path):
        site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
        if site_url:
            return f"{site_url}{path}"
        return request.build_absolute_uri(path)

    def _send_corporate_approval_email(self, request, obj, corporate_account, created_user):
        user = corporate_account.user
        dashboard_path = reverse('corporate_dashboard')
        login_url = self._build_absolute_url(request, f"{reverse('corporate_login')}?next={dashboard_path}")
        setup_url = None

        if created_user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            setup_url = self._build_absolute_url(
                request,
                reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
            )

        context = {
            'contact_name': obj.contact_name,
            'company_name': obj.company_name,
            'site_name': getattr(settings, 'SITE_NAME', 'BSBCS'),
            'login_url': login_url,
            'setup_url': setup_url,
            'created_user': created_user,
        }
        html_message = render_to_string('emails/corporate_account_approved.html', context)
        send_email_task.delay(
            subject=f"{context['site_name']} Corporate Access Approved",
            body=strip_tags(html_message),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[obj.email],
            html_message=html_message,
        )

    def _send_corporate_rejection_email(self, request, obj):
        context = {
            'contact_name': obj.contact_name,
            'company_name': obj.company_name,
            'site_name': getattr(settings, 'SITE_NAME', 'BSBCS'),
            'admin_note': obj.admin_note,
            'support_email': getattr(settings, 'CONTACT_EMAIL', settings.DEFAULT_FROM_EMAIL),
        }
        html_message = render_to_string('emails/corporate_account_rejected.html', context)
        send_email_task.delay(
            subject=f"{context['site_name']} Corporate Access Request Update",
            body=strip_tags(html_message),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[obj.email],
            html_message=html_message,
        )


@admin.register(CorporateAccount)
class CorporateAccountAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'user', 'email', 'phone', 'status', 'approved_at')
    list_filter = ('status', 'approved_at')
    search_fields = ('company_name', 'user__email', 'user__username', 'contact_name', 'email', 'phone')
    readonly_fields = ('created_at', 'updated_at')
    fields = (
        'user',
        'source_request',
        'company_name',
        'contact_name',
        'contact_designation',
        'email',
        'phone',
        'status',
        'approved_at',
        'created_at',
        'updated_at',
    )


class CorporateEventAttendeeInline(admin.TabularInline):
    model = CorporateEventAttendee
    extra = 0
    fields = ('name', 'email', 'phone', 'degree', 'organization', 'matched_user', 'participant', 'member_match', 'applied_fee', 'review_status')
    readonly_fields = ('matched_user', 'participant', 'member_match', 'applied_fee')

    def member_match(self, obj):
        return obj.member_match_label if obj and obj.pk else '-'
    member_match.short_description = 'Member match'  # type: ignore

    def applied_fee(self, obj):
        return obj.applied_fee_label if obj and obj.pk else '-'
    applied_fee.short_description = 'Fee category'  # type: ignore


@admin.register(CorporateEventComplementaryQuota)
class CorporateEventComplementaryQuotaAdmin(admin.ModelAdmin):
    list_display = ('corporate_account', 'event', 'allocated_count', 'get_used_count', 'get_remaining_count')
    list_filter = ('event',)
    search_fields = ('corporate_account__company_name',)

@admin.register(CorporateEventRegistration)
class CorporateEventRegistrationAdmin(admin.ModelAdmin):
    list_display = ('corporate_account', 'event', 'registration_type', 'submission_mode', 'status', 'total_attendees', 'created_at')
    list_filter = ('registration_type', 'status', 'submission_mode', 'event')
    search_fields = ('corporate_account__company_name', 'event__name', 'attendees__name', 'attendees__email', 'attendees__phone')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [CorporateEventAttendeeInline]
    actions = ['approve_all_pending_attendees', 'create_corporate_payment_invoice']
    fieldsets = (
        ('Step 1 - Corporate submission', {
            'fields': ('corporate_account', 'event', 'registration_type', 'submission_mode', 'status', 'total_attendees')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def approve_all_pending_attendees(self, request, queryset):
        attendees = CorporateEventAttendee.objects.filter(registration__in=queryset, review_status='pending')
        approved_count = approve_corporate_attendees(request, attendees)
        for corporate_registration in queryset:
            self.log_change(request, corporate_registration, "Approved all pending attendees from corporate registration admin action.")
        self.message_user(request, f'{approved_count} corporate attendee(s) approved and notified.')
    approve_all_pending_attendees.short_description = 'Step 2 - Approve all pending attendees and email participants'  # type: ignore

    def create_corporate_payment_invoice(self, request, queryset):
        created_count = 0
        emailed_count = 0
        skipped_count = 0
        for corporate_registration in queryset:
            payment, created, reason = create_corporate_payment_for_registration(corporate_registration, request=request)
            if created:
                created_count += 1
                self.log_addition(request, payment, "Created corporate payment invoice from admin action.")
                if send_corporate_invoice_email(payment, request):
                    emailed_count += 1
                    self.log_change(request, payment, "Sent corporate invoice email from admin action.")
            else:
                skipped_count += 1
                if reason:
                    self.message_user(request, f"{corporate_registration}: {reason}", messages.WARNING)
        self.message_user(request, f'{created_count} corporate invoice(s) created. {emailed_count} email(s) sent. {skipped_count} skipped.')
    create_corporate_payment_invoice.short_description = 'Step 3 - Create corporate invoice/payment for approved attendees'  # type: ignore

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        approved_attendee_ids = []

        for instance in instances:
            old_status = None
            if instance.pk:
                old_status = CorporateEventAttendee.objects.filter(pk=instance.pk).values_list('review_status', flat=True).first()
            instance.save()
            if isinstance(instance, CorporateEventAttendee):
                self.log_change(request, instance, "Changed corporate attendee row from inline admin form.")
            if (
                isinstance(instance, CorporateEventAttendee)
                and instance.review_status == 'approved'
                and old_status != 'approved'
                and not instance.participant_id
            ):
                approved_attendee_ids.append(instance.pk)

        for deleted_object in formset.deleted_objects:
            if isinstance(deleted_object, CorporateEventAttendee):
                self.log_change(request, deleted_object, "Deleted corporate attendee row from inline admin form.")
            deleted_object.delete()
        formset.save_m2m()

        if approved_attendee_ids:
            approved_count = approve_corporate_attendees(
                request,
                CorporateEventAttendee.objects.filter(pk__in=approved_attendee_ids)
            )
            self.message_user(request, f'{approved_count} attendee(s) converted to participants and notified.')


@admin.register(CorporateEventAttendee)
class CorporateEventAttendeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'registration', 'matched_user', 'participant', 'member_match', 'applied_fee', 'review_status')
    list_filter = ('review_status', 'registration__event')
    search_fields = ('name', 'email', 'phone', 'organization', 'registration__corporate_account__company_name')
    readonly_fields = ('matched_user', 'participant', 'created_at', 'updated_at')
    actions = ['approve_selected_attendees', 'deny_selected_attendees']

    def member_match(self, obj):
        return obj.member_match_label
    member_match.short_description = 'Member match'  # type: ignore

    def applied_fee(self, obj):
        return obj.applied_fee_label
    applied_fee.short_description = 'Fee category'  # type: ignore

    def approve_selected_attendees(self, request, queryset):
        approved_count = approve_corporate_attendees(request, queryset)
        for attendee in queryset:
            self.log_change(request, attendee, "Approved corporate attendee from admin action.")
        self.message_user(request, f'{approved_count} corporate attendee(s) approved and notified.')
    approve_selected_attendees.short_description = 'Step 2 - Approve selected attendees and email participants'  # type: ignore

    def deny_selected_attendees(self, request, queryset):
        attendees = list(queryset)
        updated = queryset.update(review_status='denied')
        for attendee in attendees:
            self.log_change(request, attendee, "Denied corporate attendee from admin action.")
        self.message_user(request, f'{updated} corporate attendee(s) denied.')
    deny_selected_attendees.short_description = 'Deny selected attendees'  # type: ignore

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            old_status = CorporateEventAttendee.objects.filter(pk=obj.pk).values_list('review_status', flat=True).first()

        super().save_model(request, obj, form, change)

        if obj.review_status == 'approved' and old_status != 'approved' and not obj.participant_id:
            approved_count = approve_corporate_attendees(
                request,
                CorporateEventAttendee.objects.filter(pk=obj.pk)
            )
            self.log_change(request, obj, "Approved corporate attendee from admin change form.")
            self.message_user(request, f'{approved_count} attendee converted to participant and notified.')


@admin.register(CorporatePayment)
class CorporatePaymentAdmin(admin.ModelAdmin):
    list_display = ('corporate_account', 'event', 'amount', 'status', 'merchant_invoice_number', 'invoice_link', 'transaction_id', 'trxID', 'created_at')
    list_filter = ('status', 'event', 'created_at')
    search_fields = ('corporate_account__company_name', 'event__name', 'merchant_invoice_number', 'transaction_id', 'trxID')
    readonly_fields = ('invoice_link', 'created_at', 'updated_at')
    filter_horizontal = ('attendees',)
    actions = ['regenerate_invoice_pdf', 'send_invoice_email_to_corporate']
    fieldsets = (
        ('Step 4 - Corporate invoice/payment', {
            'fields': ('corporate_registration', 'corporate_account', 'event', 'attendees', 'amount', 'status')
        }),
        ('bKash/payment tracking', {
            'fields': ('merchant_invoice_number', 'transaction_id', 'trxID', 'invoice', 'invoice_link', 'email_sent')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def invoice_link(self, obj):
        if obj and obj.invoice:
            return format_html('<a href="{}" target="_blank">View invoice PDF</a>', obj.invoice.url)
        return 'Invoice PDF not generated yet'
    invoice_link.short_description = 'Invoice PDF'  # type: ignore

    def regenerate_invoice_pdf(self, request, queryset):
        generated = 0
        for corporate_payment in queryset.prefetch_related('attendees'):
            generate_corporate_invoice(corporate_payment)
            self.log_change(request, corporate_payment, "Regenerated corporate invoice PDF from admin action.")
            generated += 1
        self.message_user(request, f'{generated} corporate invoice PDF(s) generated.')
    regenerate_invoice_pdf.short_description = 'Regenerate corporate invoice PDF'  # type: ignore

    def send_invoice_email_to_corporate(self, request, queryset):
        sent = 0
        for corporate_payment in queryset.select_related('corporate_registration', 'corporate_account', 'event').prefetch_related('attendees'):
            if send_corporate_invoice_email(corporate_payment, request):
                self.log_change(request, corporate_payment, "Sent corporate invoice email from admin action.")
                sent += 1
        self.message_user(request, f'{sent} corporate invoice email(s) sent.')
    send_invoice_email_to_corporate.short_description = 'Send corporate invoice email'  # type: ignore
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
    list_display = ('name', 'id','year', 'location', 'start_date', 'event_status', 'registration', 'registration_audience', 'show_publication_tab', 'payment_required', 'member_registration_enabled', 'member_registration_fee', 'company_person_registration_enabled', 'company_person_registration_fee')
    list_filter = ('year', 'event_status', 'registration_audience', 'payment_required', 'member_registration_enabled', 'company_person_registration_enabled')
    search_fields = ('name',)
    list_editable = ('registration_audience', 'show_publication_tab', 'payment_required', 'member_registration_enabled', 'member_registration_fee', 'company_person_registration_enabled', 'company_person_registration_fee')
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

        send_email_task.delay(
            subject=subject,
            body=text_content,
            from_email=from_email,
            recipient_list=recipient_list,
            html_message=html_content,
        )
    except Exception as e:
        print(f"Error queueing consolidated email: {e}")

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
    
    send_email_task.delay(
        subject=subject,
        body=text_content,
        from_email=os.getenv("EMAIL_HOST_USER"),
        recipient_list=[participant.email],
        html_message=html_content,
    )


def send_corporate_attendee_approval_email(participant, event, corporate_account, payable_amount, password=None, include_password=False):
    """Notify a corporate attendee without sending an individual payment link."""
    subject = f'Your Registration for {event.name} {event.year} is Approved'
    context = {
        'participant': participant,
        'event': event,
        'corporate_account': corporate_account,
        'payable_amount': payable_amount,
    }

    if include_password and password:
        context['password'] = password

    html_content = render_to_string('corporate_attendee_approval_email.html', context)
    text_content = strip_tags(html_content)

    send_email_task.delay(
        subject=subject,
        body=text_content,
        from_email=os.getenv("EMAIL_HOST_USER"),
        recipient_list=[participant.email],
        html_message=html_content,
    )


def update_corporate_registration_status(corporate_registration):
    attendees = corporate_registration.attendees.all()
    total = attendees.count()
    approved_count = attendees.filter(review_status='approved').count()
    denied_count = attendees.filter(review_status='denied').count()

    if total and approved_count == total:
        corporate_registration.status = 'approved'
    elif total and denied_count == total:
        corporate_registration.status = 'rejected'
    elif approved_count or denied_count:
        corporate_registration.status = 'partially_approved'
    else:
        corporate_registration.status = 'submitted'
    corporate_registration.total_attendees = total
    corporate_registration.save(update_fields=['status', 'total_attendees', 'updated_at'])


def create_corporate_payment_for_registration(corporate_registration, request=None, selected_attendee_ids=None):
    approved_attendees = CorporateEventAttendee.objects.filter(
        registration=corporate_registration,
        review_status='approved',
        participant__isnull=False,
    ).exclude(
        corporate_payments__status__in=['unpaid', 'initiated', 'pending', 'completed', 'paid']
    ).select_related('participant', 'registration__event').distinct()

    if selected_attendee_ids is not None:
        approved_attendees = approved_attendees.filter(id__in=selected_attendee_ids)

    invoice_attendees = []
    total_amount = 0
    is_complementary = (corporate_registration.registration_type == 'complementary')

    for attendee in approved_attendees:
        payable_amount = 0 if is_complementary else attendee.participant.get_payable_amount()

        payment_status = PaymentStatus.objects.filter(
            participant=attendee.participant,
            event=corporate_registration.event,
        ).first()
        if not payment_status:
            payment_status = PaymentStatus.objects.create(
                participant=attendee.participant,
                event=corporate_registration.event,
                merchant_invoice_number=f"CORPFREE-{corporate_registration.event_id}-{attendee.participant_id}-{int(time.time())}",
                amount=payable_amount,
                status='completed' if not payable_amount else 'unpaid',
            )
        elif is_complementary and payment_status.status == 'unpaid':
            payment_status.amount = 0
            payment_status.status = 'completed'
            payment_status.save(update_fields=['amount', 'status'])

        if payment_status.status in ['completed', 'paid'] and payment_status.amount and payment_status.amount > 0:
            continue

        amount = payment_status.amount if payment_status.amount is not None else payable_amount
        invoice_attendees.append(attendee)
        if amount and amount > 0:
            total_amount += amount

    if not invoice_attendees:
        return None, False, 'No newly approved attendees found for invoicing.'

    existing_payment = CorporatePayment.objects.filter(
        corporate_registration=corporate_registration,
        status__in=['unpaid', 'initiated', 'pending'],
    ).first()
    if existing_payment:
        return existing_payment, False, 'An unpaid corporate payment invoice already exists.'

    corporate_payment = CorporatePayment.objects.create(
        corporate_registration=corporate_registration,
        corporate_account=corporate_registration.corporate_account,
        event=corporate_registration.event,
        amount=total_amount,
        status='completed' if total_amount == 0 else 'unpaid',
        merchant_invoice_number=f"CORPINV-{corporate_registration.event_id}-{corporate_registration.id}-{int(time.time())}",
    )
    corporate_payment.attendees.set(invoice_attendees)

    if total_amount == 0:
        zero_fee_payments = list(PaymentStatus.objects.filter(
            participant__corporate_attendee__in=invoice_attendees,
            event=corporate_registration.event,
        ))
        for payment_status in zero_fee_payments:
            payment_status.status = 'completed'
            payment_status.save(update_fields=['status', 'updated_at'])
            write_admin_audit_log(request, payment_status, CHANGE, "Completed zero-fee corporate payment row during invoice creation.")

    generate_corporate_invoice(corporate_payment)
    return corporate_payment, True, ''


def send_corporate_invoice_email(corporate_payment, request=None):
    corporate_registration = corporate_payment.corporate_registration
    account = corporate_payment.corporate_account
    event = corporate_payment.event
    attendees = CorporateEventAttendee.objects.filter(registration=corporate_registration)
    total_count = attendees.count()
    approved_count = attendees.filter(review_status='approved').count()
    denied_count = attendees.filter(review_status='denied').count()
    pending_count = attendees.filter(review_status='pending').count()
    invoiced_count = corporate_payment.attendees.count()

    invoice_path = None
    if not corporate_payment.invoice:
        invoice_path = generate_corporate_invoice(corporate_payment)
    else:
        try:
            invoice_path = corporate_payment.invoice.path
        except Exception:
            invoice_path = generate_corporate_invoice(corporate_payment)

    payment_url = ''
    invoice_url = ''
    if request:
        payment_url = request.build_absolute_uri(reverse('corporate_payment', kwargs={'payment_id': corporate_payment.id}))
        invoice_url = request.build_absolute_uri(reverse('corporate_payment_invoice', kwargs={'payment_id': corporate_payment.id}))

    subject = f"Corporate invoice for {event.name} {event.year}"
    due_text = (
        f"Total payable: BDT {corporate_payment.amount}\n"
        f"Payment status: {corporate_payment.get_status_display()}\n"
    )
    if corporate_payment.amount and corporate_payment.amount > 0:
        due_text += f"Payment link: {payment_url or 'Please log in to the corporate dashboard to complete payment.'}\n"
    else:
        due_text += "No payment is due for this invoice.\n"

    message = (
        f"Dear {account.contact_name},\n\n"
        f"BSBCS has reviewed the attendee list submitted by {account.company_name} for {event.name} {event.year}.\n\n"
        "Review summary:\n"
        f"Total submitted: {total_count}\n"
        f"Approved: {approved_count}\n"
        f"Denied: {denied_count}\n"
        f"Pending review: {pending_count}\n"
        f"Included in this invoice: {invoiced_count}\n\n"
        f"Invoice number: {corporate_payment.merchant_invoice_number}\n"
        f"{due_text}"
        f"{'Invoice link: ' + invoice_url + chr(10) if invoice_url else ''}\n"
        "The invoice PDF is attached for your records.\n\n"
        "Regards,\n"
        "BSBCS Team"
    )

    send_email_task.delay(
        subject=subject,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[account.email],
        attachment_paths=[invoice_path] if invoice_path and os.path.exists(invoice_path) else None,
    )
    corporate_payment.email_sent = True
    corporate_payment.save(update_fields=['email_sent', 'updated_at'])
    return True


def approve_corporate_attendees(request, queryset):
    approved_count = 0
    touched_registrations = set()

    for attendee in queryset.select_related('registration__event', 'matched_user', 'participant'):
        event = attendee.registration.event
        department_name = (attendee.department or 'Not specified').strip()[:50] or 'Not specified'
        department, _ = Department.objects.get_or_create(event=event, name=department_name)
        
        corp_reg_type = attendee.registration.registration_type
        if corp_reg_type in ['company_person', 'complementary']:
            registration_type = corp_reg_type
        else:
            registration_type = 'member' if attendee.matched_member else 'regular'

        password = None
        include_password = False

        user = attendee.matched_user
        if not user:
            user = User.objects.filter(Q(email__iexact=attendee.email) | Q(username__iexact=attendee.email)).first()

        if not user:
            password = get_random_string(length=12)
            user = User.objects.create_user(username=attendee.email, email=attendee.email, password=password)
            write_admin_audit_log(request, user, ADDITION, "Created user while approving corporate attendee.")
            include_password = True
        elif not attendee.matched_user_id:
            attendee.matched_user = user

        participant = attendee.participant
        if not participant:
            participant = Participant.objects.filter(event=event).filter(
                Q(email__iexact=attendee.email) | Q(phone=attendee.phone)
            ).first()

        participant_defaults = {
            'user': user,
            'registration_type': registration_type,
            'name': attendee.name[:100],
            'degree': (attendee.degree or 'N/A')[:50],
            'year_of_graduation': timezone.now().year,
            'department': department,
            'organization': (attendee.organization or attendee.registration.corporate_account.company_name)[:100],
            'email': attendee.email,
            'phone': attendee.phone,
            'country': attendee.country or 'Bangladesh',
            'BMDC_registration_number': (attendee.bmdc_registration_number or '')[:20],
            'approved': True,
            'denied': False,
        }

        if participant:
            for field, value in participant_defaults.items():
                setattr(participant, field, value)
            participant.save()
            write_admin_audit_log(request, participant, CHANGE, "Updated participant while approving corporate attendee.")
        else:
            participant = Participant.objects.create(event=event, **participant_defaults)
            write_admin_audit_log(request, participant, ADDITION, "Created participant while approving corporate attendee.")

        payable_amount = participant.get_payable_amount()
        payment_status, _ = PaymentStatus.objects.get_or_create(
            participant=participant,
            event=event,
            defaults={
                'merchant_invoice_number': f"CORP-{event.id}-{participant.id}-{int(time.time())}",
                'amount': payable_amount,
                'status': 'unpaid' if payable_amount else 'completed',
            }
        )
        payment_status.amount = payable_amount
        if payable_amount:
            if payment_status.status not in ['completed', 'paid']:
                payment_status.status = 'unpaid'
            payment_status.save()
            write_admin_audit_log(request, payment_status, CHANGE, "Created or updated event payment row for corporate attendee.")
            send_corporate_attendee_approval_email(
                participant,
                event,
                attendee.registration.corporate_account,
                payable_amount,
                password,
                include_password
            )
        else:
            payment_status.status = 'completed'
            payment_status.save()
            write_admin_audit_log(request, payment_status, CHANGE, "Completed zero-fee event payment row for corporate attendee.")
            send_corporate_attendee_approval_email(
                participant,
                event,
                attendee.registration.corporate_account,
                payable_amount,
                password,
                include_password
            )

        attendee.participant = participant
        attendee.review_status = 'approved'
        attendee.save(update_fields=['matched_user', 'participant', 'review_status', 'updated_at'])
        write_admin_audit_log(request, attendee, CHANGE, "Approved corporate attendee and linked participant.")
        touched_registrations.add(attendee.registration_id)
        approved_count += 1

    for registration_id in touched_registrations:
        update_corporate_registration_status(CorporateEventRegistration.objects.get(pk=registration_id))

    return approved_count

# Event Specific Participants admin view START------------------------------------------------------------------------------#
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

def queue_participant_approval_email(request, participant, email_type, password=None, include_password=False, payment_url=None):
    email_log = None
    if participant_email_log_table_ready():
        email_log = ParticipantEmailLog.objects.create(
            participant=participant,
            event=participant.event,
            email=participant.email,
            email_type=email_type,
            status=ParticipantEmailLog.STATUS_QUEUED,
            sent_by=request.user if request.user.is_authenticated else None,
            message='Queued from participant admin action.',
        )

    try:
        task = send_participant_approval_email.delay(
            participant.id,
            email_type,
            log_id=email_log.id if email_log else None,
            sent_by_user_id=request.user.id if request.user.is_authenticated else None,
            password=password,
            include_password=include_password,
            payment_url=payment_url,
        )
    except Exception as exc:
        if email_log:
            email_log.status = ParticipantEmailLog.STATUS_FAILED
            email_log.message = f'Could not queue email task: {exc}'
            email_log.save(update_fields=['status', 'message', 'updated_at'])
        return False
    if email_log:
        email_log.task_id = getattr(task, 'id', '') or ''
        email_log.save(update_fields=['task_id', 'updated_at'])
    return True


def approve_participants(modeladmin, request, queryset):
    approved_count = 0
    queued_count = 0
    for participant in queryset:
        event = participant.event
        payable_amount = participant.get_payable_amount()
        
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

        payment_status, _ = PaymentStatus.objects.get_or_create(
            participant=participant,
            event=event,
            defaults={
                'merchant_invoice_number': f"REG-{event.id}-{participant.id}-{int(time.time())}",
                'amount': payable_amount,
                'status': 'unpaid' if payable_amount else 'completed',
            }
        )
        payment_status.amount = payable_amount

        if payable_amount:
            payment_status.status = payment_status.status if payment_status.status in ['completed', 'paid'] else 'unpaid'
            payment_status.save()
            payment_url = request.build_absolute_uri(reverse('registration:payment', kwargs={
                'event_id': event.id,
                'participant_id': participant.id,
            }))
            email_queued = queue_participant_approval_email(
                request,
                participant,
                ParticipantEmailLog.TYPE_APPROVAL_PAYMENT,
                password=password,
                include_password=include_password,
                payment_url=payment_url,
            )
        else:
            payment_status.merchant_invoice_number = f"FREE-{event.id}-{participant.id}-{int(time.time())}"
            payment_status.status = 'completed'
            payment_status.save()
            email_queued = queue_participant_approval_email(
                request,
                participant,
                ParticipantEmailLog.TYPE_FREE_CONFIRMATION,
                password=password,
                include_password=include_password,
            )
        approved_count += 1
        queued_count += int(bool(email_queued))
        modeladmin.log_change(request, participant, "Approved participant from admin action.")
        modeladmin.log_change(request, payment_status, "Created or updated payment row during participant approval admin action.")
    modeladmin.message_user(request, f'{approved_count} participant(s) approved. {queued_count} approval email(s) queued.', messages.SUCCESS)

def deny_participants(modeladmin, request, queryset):
    participants = list(queryset)
    queryset.update(denied=True, approved=False)
    for participant in participants:
        modeladmin.log_change(request, participant, "Denied participant from admin action.")

approve_participants.short_description = "Approve selected participants"
deny_participants.short_description = "Deny selected participants"

class ParticipantAdmin(ImportExportModelAdmin):
    resource_class = ParticipantResource
    list_display = ('name', 'registration_type', 'email', 'phone', 'department', 'organization', 'BMDC_registration_number', 'country', 'created_at', 'approved', 'denied', 'event')
    list_per_page = 15
    search_fields = ('name', 'phone', 'organization', 'BMDC_registration_number')
    list_filter = ('registration_type', 'approved', 'denied', 'country', 'event')  # Add filters
    actions = [approve_participants, deny_participants]

admin.site.register(Participant, ParticipantAdmin)


@admin.register(ParticipantEmailLog)
class ParticipantEmailLogAdmin(admin.ModelAdmin):
    list_display = ('participant', 'event', 'email', 'email_type', 'status', 'sent_by', 'sent_at', 'created_at')
    list_filter = ('status', 'email_type', 'event', 'created_at')
    search_fields = ('participant__name', 'participant__email', 'email', 'event__name', 'message', 'task_id')
    readonly_fields = (
        'participant',
        'event',
        'email',
        'email_type',
        'status',
        'task_id',
        'message',
        'sent_by',
        'sent_at',
        'created_at',
        'updated_at',
    )
    list_per_page = 25

    def has_add_permission(self, request):
        return False


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
    search_fields = ('name', 'location', 'event__name')
admin.site.register(HallRoom, HallRoomAdmin)
class TimeSlotAdmin(ImportExportModelAdmin):
    resource_class = TimeSlotResource
    list_display = ('slot_type', 'label', 'start_time', 'end_time', 'program_day', 'hall_room', 'event')
    search_fields = ('hall_room', 'program_day')
    list_filter = ('slot_type', 'program_day', 'hall_room', 'event')
admin.site.register(TimeSlot, TimeSlotAdmin)

# Program Day admin view START------------------------------------------------------------------------------#
class ProgramDayAdmin(admin.ModelAdmin):
    list_display = ('event', 'date', 'name')
    list_filter = ('event', 'date', 'name')
    search_fields = ('name', 'event__name')
admin.site.register(ProgramDay, ProgramDayAdmin)

# Abstracts admin view START------------------------------------------------------------------------------#
def approve_for_presentation(modeladmin, request, queryset):
    abstracts = list(queryset)
    queryset.update(approved_for_presentation=True, approved_for_poster=False)

    # send an approval email
    for abstract in abstracts:
        send_approval_email(abstract, "Presentation")
        modeladmin.log_change(request, abstract, "Approved abstract for presentation from admin action.")

def approve_for_poster(modeladmin, request, queryset):
    abstracts = list(queryset)
    queryset.update(approved_for_poster=True, approved_for_presentation=False)

    # send an approval email
    for abstract in abstracts:
        send_approval_email(abstract, "Poster")
        modeladmin.log_change(request, abstract, "Approved abstract for poster from admin action.")
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

    send_email_task.delay(
        subject=subject,
        body=text_content,
        from_email=from_email,
        recipient_list=recipient_list,
        html_message=html_content,
    )
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

            send_email_task.delay(
                subject=subject,
                body=text_content,
                from_email=os.getenv("EMAIL_HOST_USER"),
                recipient_list=participants,
                html_message=html_content,
            )
            try:
                schedule.email_sent = True
                schedule.save()
                self.log_change(request, schedule, "Queued program schedule email from admin action.")
                self.message_user(request, f"Schedule email queued for {schedule.title}")
            except Exception as e:
                messages.error(request, f"Failed to queue email for schedule: {schedule.title}. Error: {e}")
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


@admin.register(ProgramPerson)
class ProgramPersonAdmin(admin.ModelAdmin):
    list_display = ('name', 'profile', 'degree', 'designation', 'institution', 'email', 'country')
    list_filter = ('country', 'events')
    search_fields = ('name', 'degree', 'designation', 'institution', 'email', 'phone', 'profile__name', 'profile__email')
    autocomplete_fields = ('profile',)
    filter_horizontal = ('events',)
    readonly_fields = ('image_preview',)
    actions = ['send_program_assignment_emails']
    fieldsets = (
        ('Identity', {
            'fields': ('profile', 'name', 'degree', 'designation', 'institution', 'events')
        }),
        ('Contact', {
            'fields': ('email', 'phone', 'country')
        }),
        ('Profile', {
            'fields': ('biography', 'image', 'image_preview')
        }),
    )

    def image_preview(self, obj):
        if obj and obj.image:
            return format_html('<img src="{}" style="height: 90px; width: 90px; object-fit: cover; border-radius: 10px;" />', obj.image.url)
        return "No image uploaded"
    image_preview.short_description = 'Current image'  # type: ignore

    @admin.action(description='Send selected program people their program details email')
    def send_program_assignment_emails(self, request, queryset):
        sent_count = 0
        missing_email_count = 0
        without_assignment_count = 0
        failed_count = 0

        for person in queryset:
            try:
                sent, reason = send_program_assignment_email(person)
                if sent:
                    sent_count += 1
                    self.log_change(request, person, "Sent program details email from admin action.")
                elif reason == 'missing_email':
                    missing_email_count += 1
                else:
                    without_assignment_count += 1
            except Exception as exc:
                failed_count += 1
                self.message_user(
                    request,
                    f"Program details email failed for {person.name}: {exc}",
                    messages.ERROR,
                )

        if sent_count:
            self.message_user(
                request,
                f"Program details email sent to {sent_count} program person(s).",
                messages.SUCCESS,
            )
        if missing_email_count:
            self.message_user(
                request,
                f"{missing_email_count} selected program person(s) were skipped because email is missing.",
                messages.WARNING,
            )
        if without_assignment_count:
            self.message_user(
                request,
                f"{without_assignment_count} selected program person(s) were skipped because no program participation detail exists yet.",
                messages.WARNING,
            )
        if failed_count:
            self.message_user(
                request,
                f"{failed_count} program details email(s) failed.",
                messages.ERROR,
            )


@admin.register(ProgramPersonEmailLog)
class ProgramPersonEmailLogAdmin(admin.ModelAdmin):
    list_display = (
        'person',
        'event',
        'last_sent_at',
        'last_sent_by',
        'send_count',
        'last_session_count',
        'last_talk_count',
    )
    list_filter = ('event', 'last_sent_at')
    search_fields = ('person__name', 'person__email', 'event__name', 'last_sent_by__username')
    autocomplete_fields = ('person', 'event', 'last_sent_by')
    readonly_fields = ('last_sent_at', 'send_count', 'last_session_count', 'last_talk_count')


class ProgramSessionFacultyInline(admin.TabularInline):
    model = ProgramSessionFaculty
    extra = 1
    autocomplete_fields = ('person',)
    fields = ('person', 'role', 'order')
    ordering = ('role', 'order')


class ProgramSessionItemInline(admin.TabularInline):
    model = ProgramSessionItem
    extra = 1
    autocomplete_fields = ('abstract_submission',)
    fields = ('order', 'talk_slot', 'start_time', 'end_time', 'title', 'abstract_submission')
    ordering = ('order', 'start_time')


@admin.register(ProgramSession)
class ProgramSessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'event', 'time_slot', 'program_day', 'hall_room', 'start_time', 'end_time', 'order', 'get_chairpersons', 'get_moderators', 'get_panelists')
    list_filter = ('event', 'program_day', 'hall_room', 'time_slot')
    search_fields = ('title', 'event__name', 'faculty_roles__person__name', 'items__title', 'items__abstract_submission__title')
    autocomplete_fields = ('event', 'time_slot', 'program_day', 'hall_room')
    inlines = [ProgramSessionFacultyInline, ProgramSessionItemInline]
    fieldsets = (
        ('Session', {
            'fields': ('event', 'title', 'description', 'order')
        }),
        ('Timing and room', {
            'fields': ('time_slot', 'program_day', 'hall_room', 'start_time', 'end_time')
        }),
    )

    def _people_for_role(self, obj, role):
        return ', '.join(
            obj.faculty_roles.filter(role=role).select_related('person').values_list('person__name', flat=True)
        )

    def get_chairpersons(self, obj):
        return self._people_for_role(obj, ProgramSessionFaculty.ROLE_CHAIRPERSON)
    get_chairpersons.short_description = 'Chairpersons'  # type: ignore

    def get_moderators(self, obj):
        return self._people_for_role(obj, ProgramSessionFaculty.ROLE_MODERATOR)
    get_moderators.short_description = 'Moderators'  # type: ignore

    def get_panelists(self, obj):
        return self._people_for_role(obj, ProgramSessionFaculty.ROLE_PANELIST)
    get_panelists.short_description = 'Panelists'  # type: ignore


class ProgramItemFacultyInline(admin.TabularInline):
    model = ProgramItemFaculty
    extra = 1
    autocomplete_fields = ('person',)
    fields = ('person', 'role', 'order')
    ordering = ('role', 'order')


@admin.register(ProgramTalkSlot)
class ProgramTalkSlotAdmin(admin.ModelAdmin):
    list_display = ('time_label', 'time_slot', 'get_event', 'order', 'label')
    list_filter = ('time_slot__event', 'time_slot__program_day', 'time_slot__hall_room')
    search_fields = ('time_slot__event__name', 'time_slot__program_day__name', 'time_slot__hall_room__name', 'label')
    autocomplete_fields = ('time_slot',)
    ordering = ('time_slot__program_day__date', 'time_slot__start_time', 'order', 'start_time')

    def get_event(self, obj):
        return obj.time_slot.event
    get_event.short_description = 'Event'  # type: ignore


@admin.register(ProgramSessionItem)
class ProgramSessionItemAdmin(admin.ModelAdmin):
    list_display = ('display_title', 'session', 'get_event', 'start_time', 'end_time', 'order', 'get_speakers')
    list_filter = ('session__event', 'session__program_day', 'session__hall_room')
    search_fields = ('title', 'abstract_submission__title', 'session__title', 'faculty_roles__person__name')
    autocomplete_fields = ('session', 'abstract_submission', 'talk_slot')
    inlines = [ProgramItemFacultyInline]
    fieldsets = (
        ('Talk or activity', {
            'fields': ('session', 'title', 'abstract_submission', 'description', 'order')
        }),
        ('Timing', {
            'fields': ('talk_slot', 'start_time', 'end_time')
        }),
    )

    def get_event(self, obj):
        return obj.session.event
    get_event.short_description = 'Event'  # type: ignore

    def get_speakers(self, obj):
        return ', '.join(
            obj.faculty_roles.select_related('person').values_list('person__name', flat=True)
        )
    get_speakers.short_description = 'People'  # type: ignore


@admin.register(PresentationUpload)
class PresentationUploadAdmin(admin.ModelAdmin):
    list_display = ('title', 'presenter_name', 'event', 'source_type', 'uploaded_at')
    list_filter = ('event', 'source_type', 'uploaded_at')
    search_fields = (
        'title',
        'presenter_name',
        'user__email',
        'program_person__name',
        'program_person__email',
        'abstract_submission__title',
        'session__title',
        'session_item__title',
    )
    autocomplete_fields = ('event', 'user', 'program_person', 'abstract_submission', 'session', 'session_item')
    readonly_fields = ('uploaded_at', 'updated_at')


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

    populate_registration_kits.short_description = "Populate Registration Kits for completed payments"

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
                thank_you_email = ThankYouEmail.objects.create(
                    registration_kit=kit,
                    subject=event.email_subject,
                    body=event.email_body,
                )
                self.log_addition(request, thank_you_email, "Created thank-you email row from admin action.")
                created_count += 1

        self.message_user(request, f"Created {created_count} Thank You Emails.", messages.SUCCESS)

    populate_thank_you_emails.short_description = "Populate Thank You Emails"

    def send_thank_you_emails(self, request, queryset):
        """Send emails to participants whose Thank You Emails are pending."""
        count = 0
        for email_obj in queryset:
            if not email_obj.email_sent:
                email_obj.send_email()
                self.log_change(request, email_obj, "Sent thank-you email from admin action.")
                count += 1
        self.message_user(request, f"Successfully sent {count} thank-you emails.", messages.SUCCESS)

    send_thank_you_emails.short_description = "Send Thank You Emails"

#Thank You Email Admin Starts--------------------------------------------------#

# Certificate admin starts ----------------------------------------------------#

from .models import Certificate, CertificateSignatory


class CertificateSignatoryInline(admin.TabularInline):
    model = CertificateSignatory
    extra = 2
    fields = ('order', 'name', 'designation', 'organization', 'signature')


class CertificateAdmin(admin.ModelAdmin):
    list_display = ('id', 'event', 'design_mode')
    list_filter = ('design_mode', 'event')
    search_fields = ('event__name',)
    list_display_links = ('id', 'event')
    fieldsets = (
        (None, {
            'fields': ('event', 'design_mode', 'upload_image')
        }),
        ('HTML design logo overrides', {
            'fields': ('organizer_logo', 'co_organizer_logo', 'event_logo'),
            'description': 'Event logo is optional here. If left blank, the certificate uses the logo from the selected event.'
        }),
    )
    inlines = [CertificateSignatoryInline]
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
from .models import BulkEmail, BulkEmailRecipient, BulkEmailSendLog, BulkEmailsReporting, EmailGroup
from import_export import resources
from import_export.admin import ExportMixin
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.contrib.auth import get_user_model
from django.shortcuts import render
from .tasks import participant_email_log_table_ready, send_participant_approval_email, send_pending_bulk_email_campaign

User = get_user_model()  # Fetch the user model


class BulkEmailRecipientInline(admin.TabularInline):
    model = BulkEmailRecipient
    extra = 0
    fields = ('email', 'name', 'source_type', 'status', 'sent_at', 'error_message')
    readonly_fields = ('sent_at',)
    show_change_link = True


class BulkEmailSendLogInline(admin.TabularInline):
    model = BulkEmailSendLog
    extra = 0
    fields = ('email', 'status', 'message', 'sent_by', 'created_at')
    readonly_fields = ('email', 'status', 'message', 'sent_by', 'created_at')
    can_delete = False
    max_num = 0

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BulkEmail)
class BulkEmailAdmin(admin.ModelAdmin):
    list_display = (
        'subject', 'audience_type', 'event', 'email_group', 'status',
        'recipient_total', 'sent_total', 'failed_total', 'created_at',
    )
    list_filter = ('status', 'audience_type', 'event', 'created_at')
    search_fields = ('subject', 'body', 'event__name', 'email_group__name')
    readonly_fields = (
        'created_at', 'updated_at', 'recipient_total', 'sent_total',
        'failed_total', 'pending_total',
    )
    actions = [
        'prepare_recipients_from_audience',
        'send_pending_recipients',
        'mail_to_active_users',
        'mail_to_email_group',
    ]
    fieldsets = (
        ('Email content', {
            'fields': ('subject', 'body', 'attachment')
        }),
        ('Audience setup', {
            'fields': ('audience_type', 'event', 'email_group', 'status')
        }),
        ('Delivery summary', {
            'fields': ('recipient_total', 'pending_total', 'sent_total', 'failed_total')
        }),
        ('Timestamps', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )
    inlines = []

    def get_inlines(self, request, obj):
        if obj:
            return [BulkEmailRecipientInline, BulkEmailSendLogInline]
        return []

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def recipient_total(self, obj):
        return obj.recipient_count if obj.pk else 0
    recipient_total.short_description = "Recipients"

    def sent_total(self, obj):
        return obj.sent_count if obj.pk else 0
    sent_total.short_description = "Sent"

    def failed_total(self, obj):
        return obj.failed_count if obj.pk else 0
    failed_total.short_description = "Failed"

    def pending_total(self, obj):
        return obj.pending_count if obj.pk else 0
    pending_total.short_description = "Pending"

    def _valid_email_or_none(self, email):
        if not email:
            return None
        normalized = email.strip()
        try:
            validate_email(normalized)
        except ValidationError:
            return None
        return normalized

    def _upsert_recipient(self, bulk_email, email, name='', source_type=BulkEmailRecipient.SOURCE_MANUAL, **links):
        normalized = self._valid_email_or_none(email)
        if not normalized:
            return False
        defaults = {
            'name': name or '',
            'source_type': source_type,
            **{key: value for key, value in links.items() if value is not None},
        }
        _, created = BulkEmailRecipient.objects.get_or_create(
            bulk_email=bulk_email,
            email=normalized,
            defaults=defaults,
        )
        return created

    def _prepare_recipients(self, bulk_email):
        added = 0
        if bulk_email.audience_type == BulkEmail.AUDIENCE_ACTIVE_USERS:
            users = User.objects.filter(is_active=True).exclude(email='')
            for user in users:
                if self._upsert_recipient(
                    bulk_email,
                    user.email,
                    name=user.get_full_name() or user.username,
                    source_type=BulkEmailRecipient.SOURCE_USER,
                    user=user,
                ):
                    added += 1
        elif bulk_email.audience_type == BulkEmail.AUDIENCE_EMAIL_GROUP:
            if not bulk_email.email_group:
                return 0
            for email in bulk_email.email_group.parsed_emails():
                if self._upsert_recipient(
                    bulk_email,
                    email,
                    source_type=BulkEmailRecipient.SOURCE_EMAIL_GROUP,
                ):
                    added += 1
        elif bulk_email.audience_type == BulkEmail.AUDIENCE_EVENT_PARTICIPANTS and bulk_email.event:
            participants = Participant.objects.filter(event=bulk_email.event).exclude(email='')
            for participant in participants:
                if self._upsert_recipient(
                    bulk_email,
                    participant.email,
                    name=participant.name,
                    source_type=BulkEmailRecipient.SOURCE_PARTICIPANT,
                    participant=participant,
                ):
                    added += 1
        elif bulk_email.audience_type == BulkEmail.AUDIENCE_EVENT_UNPAID and bulk_email.event:
            payments = PaymentStatus.objects.filter(
                event=bulk_email.event,
                status__in=['unpaid', 'pending', 'failed', 'initiated'],
                participant__isnull=False,
            ).select_related('participant')
            for payment in payments:
                participant = payment.participant
                if participant and self._upsert_recipient(
                    bulk_email,
                    participant.email,
                    name=participant.name,
                    source_type=BulkEmailRecipient.SOURCE_PARTICIPANT,
                    participant=participant,
                ):
                    added += 1
        elif bulk_email.audience_type == BulkEmail.AUDIENCE_ABSTRACT_SUBMITTERS and bulk_email.event:
            abstracts = AbstractSubmission.objects.filter(event=bulk_email.event).select_related('user')
            for abstract in abstracts:
                email = abstract.user.email if abstract.user_id else ''
                name = abstract.user.get_full_name() or abstract.user.username if abstract.user_id else ''
                if self._upsert_recipient(
                    bulk_email,
                    email,
                    name=name,
                    source_type=BulkEmailRecipient.SOURCE_ABSTRACT,
                    abstract_submission=abstract,
                    user=abstract.user if abstract.user_id else None,
                ):
                    added += 1
        elif bulk_email.audience_type == BulkEmail.AUDIENCE_CORPORATE_CONTACTS:
            accounts = CorporateAccount.objects.filter(is_active=True).exclude(email='')
            for account in accounts:
                if self._upsert_recipient(
                    bulk_email,
                    account.email,
                    name=account.contact_name,
                    source_type=BulkEmailRecipient.SOURCE_CORPORATE,
                    corporate_account=account,
                ):
                    added += 1
            requests = CorporateAccountRequest.objects.filter(status='approved').exclude(email='')
            for account_request in requests:
                if self._upsert_recipient(
                    bulk_email,
                    account_request.email,
                    name=account_request.contact_name,
                    source_type=BulkEmailRecipient.SOURCE_CORPORATE,
                    corporate_request=account_request,
                ):
                    added += 1
        if bulk_email.recipient_count:
            bulk_email.status = BulkEmail.STATUS_RECIPIENTS_READY
            bulk_email.save(update_fields=['status', 'updated_at'])
        return added

    def prepare_recipients_from_audience(self, request, queryset):
        prepared = 0
        for bulk_email in queryset:
            prepared += self._prepare_recipients(bulk_email)
            self.log_change(request, bulk_email, "Prepared bulk email recipients from admin action.")
        self.message_user(request, f"Prepared recipient lists. New valid recipients found: {prepared}.")
    prepare_recipients_from_audience.short_description = "Step 1 - Prepare recipients from selected audience"

    def _send_one_recipient(self, request, bulk_email, recipient):
        send_email_task.delay(
            subject=bulk_email.subject,
            body=bulk_email.body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None) or os.getenv("EMAIL_HOST_USER"),
            recipient_list=[recipient.email],
            attachment_paths=[bulk_email.attachment.path] if bulk_email.attachment else None,
        )
        return True

    def send_pending_recipients(self, request, queryset):
        queued = 0
        for bulk_email in queryset:
            pending_recipients = bulk_email.recipients.filter(status=BulkEmailRecipient.STATUS_PENDING)
            if not pending_recipients.exists():
                self._prepare_recipients(bulk_email)
                pending_recipients = bulk_email.recipients.filter(status=BulkEmailRecipient.STATUS_PENDING)
            if pending_recipients.exists():
                bulk_email.status = BulkEmail.STATUS_SENDING
                bulk_email.save(update_fields=['status', 'updated_at'])
                send_pending_bulk_email_campaign.delay(bulk_email.id, request.user.id)
                self.log_change(request, bulk_email, "Queued bulk email campaign send from admin action.")
                queued += 1
        self.message_user(request, f"Queued {queued} bulk email campaign(s). The Celery worker will send pending recipients.")
    send_pending_recipients.short_description = "Step 2 - Send pending recipients individually"

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

        # Queue the email using BCC
        send_email_task.delay(
            subject=bulk_email.subject,
            body=bulk_email.body,
            from_email='info.bsbcs@gmail.com',
            recipient_list=[],
            bcc=recipients,
        )
        if bulk_email.attachment:
            # Attachments are not currently supported for BCC queue through this helper
            self.message_user(request, "Warning: attachments are not attached for bulk BCC queued email.", level=messages.WARNING)

        BulkEmailsReporting.objects.create(
            subject=bulk_email.subject,
            body=bulk_email.body,
            recipients=', '.join(recipients),  # Convert recipient list to comma-separated string
            attachment=bulk_email.attachment if bulk_email.attachment else None,
        )
        self.log_change(request, bulk_email, "Queued bulk email to active users from admin action.")

        # Notify admin of success
        self.message_user(request, f"Bulk email to {len(recipients)} active users queued successfully.")

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

            send_email_task.delay(
                subject=bulk_email.subject,
                body=bulk_email.body,
                from_email=os.getenv("EMAIL_HOST_USER"),
                recipient_list=[],
                bcc=emails,
            )
            if bulk_email.attachment:
                self.message_user(request, "Warning: attachments are not attached for queued email groups.", level=messages.WARNING)

            BulkEmailsReporting.objects.create(
                subject=bulk_email.subject,
                body=bulk_email.body,
                recipients=', '.join(emails),
                attachment=bulk_email.attachment,
            )

            self.log_change(request, bulk_email, f"Queued bulk email to email group: {group.name}.")
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


@admin.register(BulkEmailRecipient)
class BulkEmailRecipientAdmin(admin.ModelAdmin):
    list_display = ('bulk_email', 'email', 'name', 'source_type', 'status', 'sent_at', 'created_at')
    list_filter = ('status', 'source_type', 'bulk_email__audience_type', 'created_at')
    search_fields = ('bulk_email__subject', 'email', 'name', 'error_message')
    readonly_fields = ('created_at', 'sent_at')


@admin.register(BulkEmailSendLog)
class BulkEmailSendLogAdmin(admin.ModelAdmin):
    list_display = ('bulk_email', 'email', 'status', 'sent_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('bulk_email__subject', 'email', 'message')
    readonly_fields = ('bulk_email', 'recipient', 'email', 'status', 'message', 'sent_by', 'created_at')

    def has_add_permission(self, request):
        return False


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
                        reminder = PendingPaymentReminder.objects.create(
                            participant=participant,
                            event=event,
                            payment_link=reverse('registration:payment', kwargs={
                                'event_id': event.id,
                                'participant_id': participant.id
                            })
                        )
                        self.log_addition(request, reminder, "Created pending payment reminder from admin action.")
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

                # Queue the payment reminder email
                send_email_task.delay(
                    subject=subject,
                    body=text_content,
                    from_email=from_email,
                    recipient_list=recipient_list,
                    html_message=html_content,
                )

                # Update reminder details
                reminder.reminder_count += 1
                reminder.last_reminder_sent = now()
                reminder.save()
                self.log_change(request, reminder, "Queued payment reminder from admin action.")
                success_count += 1

            except Exception as e:
                self.message_user(request, f"Failed to send email to {reminder.participant.email}: {e}", level='error')

        # Provide feedback to the admin
        self.message_user(request, f"Successfully sent {success_count} payment reminder(s).")

    send_payment_reminders.short_description = "Send Payment Reminders"

# Pending Payment Reminder Admin ends here ----------------------------------------------------------#

from django.contrib import admin
from django.contrib.admin.models import LogEntry


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = (
        "action_time",
        "user",
        "action_type",
        "content_type",
        "object_repr",
    )

    list_filter = (
        "user",
        "content_type",
        "action_flag",
        "action_time",
    )

    search_fields = (
        "object_repr",
        "change_message",
        "user__username",
    )

    ordering = ("-action_time",)

    readonly_fields = [field.name for field in LogEntry._meta.fields]

    def action_type(self, obj):
        return obj.get_action_flag_display()

    action_type.short_description = "Action"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
