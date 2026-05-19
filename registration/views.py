from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.urls import reverse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .forms import RegistrationForm, AbstractSubmissionForm, UserProfileForm, CorporateAccountRequestForm
from .models import *
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
import time
import json
import logging
import csv
import io
from django.http import FileResponse, HttpResponse, Http404
from django.utils import timezone
from django.db import transaction


# Payment logger (writes to payment.log via settings)
logger = logging.getLogger('payment')


@staff_member_required
def admin_workflow_guide(request):
    return render(request, 'admin/workflow_guide.html')


# TEMP CERTIFICATE DESIGN PREVIEW: remove this view once the HTML/CSS design is approved.
def temp_certificate_design_preview(request):
    from website.models import SiteSettings

    site_settings = SiteSettings.objects.first()
    event_id = request.GET.get('event_id')
    event_qs = Event.objects.all()
    if event_id:
        event = event_qs.filter(id=event_id).first()
    else:
        event = event_qs.filter(event_logo__isnull=False).exclude(event_logo='').order_by('-year', '-start_date').first()
    certificate = Certificate.objects.filter(event=event).first() if event else None

    if certificate:
        signatories = [
            {
                'signature_url': signatory.signature.url if signatory.signature else '',
                'name': signatory.name,
                'designation': signatory.designation,
                'organization': signatory.organization,
            }
            for signatory in certificate.signatories.all()
        ]
    else:
        signatories = []

    if not signatories:
        # TEMP CERTIFICATE SIGNATORY DATA: remove after real CertificateSignatory rows are added.
        signatories = [
            {
                'signature_url': '/static/images/certificate_design/left_signature.png',
                'name': 'Prof. Dr. Qamruzzaman Chowdhury',
                'designation': 'President',
                'organization': 'Bangladesh Society For Breast\nCancer Study',
            },
            {
                'signature_url': '/static/images/certificate_design/right_signature.png',
                'name': 'Dr. Don S Dizon',
                'designation': 'Chief Guest',
                'organization': 'Bangladesh Breast Cancer\nConference 2025',
            },
        ]

    return render(request, 'certificate_design/certificate.html', {
        'participant_name': request.GET.get('name', 'Dr. Sample Participant'),
        'site_settings': site_settings,
        'event': event,
        'certificate': certificate,
        'signatories': signatories,
        'signature_count': len(signatories),
    })


def _mask_secret(value: str, show: int = 6):
    if not value:
        return None
    s = str(value)
    if len(s) <= show * 2:
        return '***'
    return f"{s[:show]}...{s[-show:]}"


SENSITIVE_KEYS = {
    'authorization', 'id_token', 'idtoken', 'token', 'app_secret', 'app_key',
    'password', 'pwd', 'msisdn', 'payerreference', 'payer_reference', 'card',
    'cvv', 'pan', 'merchantkey', 'signature', 'access_token'
}


def mask_sensitive(obj):
    """Recursively mask sensitive data inside dicts/lists/strings.

    - keys in SENSITIVE_KEYS are replaced with '***REDACTED***'
    - long strings (likely tokens/JWTs) are shortened via _mask_secret
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k and isinstance(k, str) and k.lower() in SENSITIVE_KEYS:
                out[k] = '***REDACTED***'
            else:
                out[k] = mask_sensitive(v)
        return out
    if isinstance(obj, list):
        return [mask_sensitive(i) for i in obj]
    if isinstance(obj, str):
        # likely a token/JWT if long without spaces
        if len(obj) > 120 or (obj.startswith('eyJ') and '.' in obj):
            return _mask_secret(obj)
        return obj
    # other simple types
    return obj


def get_active_member_for_user(user):
    if not user.is_authenticated:
        return None
    try:
        user_profile = UserProfile.objects.get(user=user)
        member = getattr(user_profile, 'member', None)
    except UserProfile.DoesNotExist:
        return None
    if member and member.approval_status == 'approved' and member.is_active_member:
        return member
    return None


def get_or_create_member_department(event):
    department, _ = Department.objects.get_or_create(event=event, name='BSBCS Member')
    return department


def get_existing_registration_context(participant, event):
    payment_status = PaymentStatus.objects.filter(participant=participant, event=event).first()
    payable_amount = payment_status.amount if payment_status else participant.get_payable_amount()
    payable_amount = payable_amount or 0

    context = {
        'event': event,
        'participant': participant,
        'payment_status': payment_status,
        'payable_amount': payable_amount,
        'status_title': 'Registration Received',
        'status_tone': 'info',
        'message': 'Your registration has already been submitted and is waiting for admin review.',
        'primary_action_url': reverse('registration:home', kwargs={'event_id': event.pk}),
        'primary_action_label': 'Back to Event',
    }

    if participant.denied:
        context.update({
            'status_title': 'Registration Not Approved',
            'status_tone': 'warning',
            'message': 'Your registration request was not approved. Please contact the event team if you need help.',
        })
        return context

    if not participant.approved:
        return context

    if payable_amount and (not payment_status or payment_status.status not in ['completed', 'paid']):
        context.update({
            'status_title': 'Payment Required',
            'status_tone': 'payment',
            'message': 'Your event registration has been approved. Please complete the payment to confirm your seat.',
            'primary_action_url': reverse('registration:payment', kwargs={'event_id': event.pk, 'participant_id': participant.pk}),
            'primary_action_label': 'Complete Payment',
            'secondary_action_url': reverse('registration:home', kwargs={'event_id': event.pk}),
            'secondary_action_label': 'Back to Event',
        })
        return context

    context.update({
        'status_title': 'Registration Confirmed',
        'status_tone': 'success',
        'message': 'You are already registered and confirmed for this event. You can attend the program.',
    })
    return context


# User Profile View STARTS ---------------------------------------------------------------###
def create_profile(request):
    next_url = request.POST.get('next') or request.GET.get('next')
    if request.user.is_authenticated:
        existing_profile = UserProfile.objects.filter(user=request.user).first()
        if existing_profile:
            return redirect(next_url or 'user_profile')

        if request.method == 'POST':
            name = (request.POST.get('name') or '').strip()
            email = (request.POST.get('email') or request.user.email or request.user.username or '').strip()
            phone = (request.POST.get('phone') or '').strip()
            country = (request.POST.get('country') or '').strip()

            if not name or not email or not phone or not country:
                messages.error(request, "Please complete all profile fields.")
            elif UserProfile.objects.filter(email__iexact=email).exists():
                messages.error(request, "A personal profile already exists with this email address.")
            elif UserProfile.objects.filter(phone=phone).exists():
                messages.error(request, "A personal profile already exists with this phone number.")
            elif User.objects.filter(email__iexact=email).exclude(pk=request.user.pk).exists():
                messages.error(request, "This email is already linked to another login account.")
            else:
                request.user.email = email
                if not request.user.username:
                    request.user.username = email
                request.user.save(update_fields=['email', 'username'])
                UserProfile.objects.create(
                    user=request.user,
                    name=name,
                    email=email,
                    phone=phone,
                    country=country,
                )
                messages.success(request, "Your personal BSBCS profile has been created.")
                return redirect(next_url or 'user_profile')

        form = UserProfileForm(initial={
            'name': request.user.get_full_name() or request.user.first_name,
            'email': request.user.email or request.user.username,
        })
        return render(request, 'create_profile.html', {
            'form': form,
            'next_url': next_url,
            'completing_existing_profile': True,
        })

    if request.method == 'POST':
        form = UserProfileForm(request.POST)
        if form.is_valid():
            form.save()
            if next_url:
                from urllib.parse import quote
                return redirect(f'{reverse("login")}?next={quote(next_url)}')
            return redirect('login')
    else:
        form = UserProfileForm()
    return render(request, 'create_profile.html', {'form': form, 'next_url': next_url})


def corporate_account_request(request):
    if request.method == 'POST':
        form = CorporateAccountRequestForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('corporate_account_request_done')
    else:
        form = CorporateAccountRequestForm()

    return render(request, 'corporate_account_request.html', {'form': form})


def corporate_account_request_done(request):
    return render(request, 'corporate_account_request_done.html')

# User profile Views START-----------------------------------------------------###

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from .models import UserProfile, AbstractSubmission, ProgramSchedule, Event, CorporateAccount
from django.db.models import Q
from website.models import SiteSettings, MembershipBenefitModal, MembershipPayment, PendingEventIntent

@login_required
def user_profile(request):
    # Fetch the user's profile
    user_profile = UserProfile.objects.filter(user=request.user).first()
    site_settings = SiteSettings.objects.first()

    corporate_account = CorporateAccount.objects.filter(user=request.user).first()

    if not user_profile:
        return render(request, 'user_profile.html', {
            'user': request.user,
            'needs_profile': True,
            'corporate_account': corporate_account,
            'site_settings': site_settings,
            'next_url': request.GET.get('next') or reverse('user_profile'),
        })

    # Fetch related submissions and schedules
    abstract_submissions = AbstractSubmission.objects.filter(user=request.user)
    program_schedules = ProgramSchedule.objects.filter(abstract_submission__in=abstract_submissions)
    participants = (
        Participant.objects.filter(user=request.user)
        .select_related('event', 'department', 'corporate_attendee__registration__corporate_account')
        .order_by('-created_at')
    )

    # Fetch active, upcoming, and closed events
    active_events = Event.objects.filter(event_status='active').order_by('-start_date')
    upcoming_events = Event.objects.filter(event_status='upcoming').order_by('start_date')
    closed_events = Event.objects.filter(event_status='closed').order_by('-end_date')
    member_events = Event.objects.filter(
        event_status='active',
        registration='Open',
    ).filter(
        Q(member_registration_enabled=True) | Q(registration_audience='members_only')
    ).order_by('start_date')[:6]

    # Fetch payment Status for the user's in registered events
    payment_statuses = (
        PaymentStatus.objects.filter(participant__user=request.user)
        .select_related('event', 'participant', 'participant__corporate_attendee__registration__corporate_account')
    )
    pending_payment_count = payment_statuses.filter(
        status__in=['unpaid', 'pending', 'initiated'],
        participant__corporate_attendee__isnull=True,
    ).count()
    payment_data = []
    for payment in payment_statuses:
        payment_data.append({
            'event': f"{payment.event.name} {payment.event.year}",  # Assuming the event name and year are stored in the Event modelpayment.event.name,
            'trxID': payment.trxID,
            'amount': payment.amount,
            'status': payment.status,
            'updated_at': payment.updated_at,  # Assuming there's an updated_at field in PaymentStatus
        })
    membership_payments = MembershipPayment.objects.filter(user_profile=user_profile).select_related('membership_type').order_by('-created_at')
    pending_event_intents = PendingEventIntent.objects.filter(user_profile=user_profile).select_related('event', 'participant').order_by('-created_at')
    member = getattr(user_profile, 'member', None)
    membership_benefits = MembershipBenefitModal.objects.filter(is_active=True).prefetch_related('benefit_items').first()

    if request.method == 'POST':
        user_profile.name = request.POST.get('name')
        user_profile.email = request.POST.get('email')
        user_profile.phone = request.POST.get('phone')
        user_profile.country = request.POST.get('country')
        if request.FILES.get('image'):
            user_profile.image = request.FILES['image']
        user_profile.save()
        message = "Profile updated successfully"
    else:
        message = ""

    return render(request, 'user_profile.html', {
        'user': request.user,
        'user_profile': user_profile,
        'abstract_submissions': abstract_submissions,
        'program_schedules': program_schedules,
        'participants': participants,
        'message': message,
        'active_events': active_events,
        'upcoming_events': upcoming_events,
        'closed_events': closed_events,
        'member_events': member_events,
        'payment_data': payment_data,
        'payment_statuses': payment_statuses,
        'pending_payment_count': pending_payment_count,
        'membership_payments': membership_payments,
        'pending_event_intents': pending_event_intents,
        'member': member,
        'membership_benefits': membership_benefits,
        'site_settings': site_settings,
    })

# Custom Password Change View STARTS ---------------------------------------------------------------###
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy

class CustomPasswordChangeView(PasswordChangeView):
    template_name = 'change_password.html'

    def get_success_url(self):  # type: ignore[override]
        return reverse_lazy('password_change_done')

# Custom Password Change View ENDS ---------------------------------------------------------------###

# Custom Password Reset View STARTS ---------------------------------------------------------------###
from django.contrib.auth.views import PasswordResetView
class CustomPasswordResetView(PasswordResetView):
    template_name = 'password_reset_form.html'
    email_template_name = 'password_reset_email.html'

    def get_success_url(self):  # type: ignore[override]
        return reverse_lazy('password_reset_done')

# Custom Password Reset View ENDS ---------------------------------------------------------------###

from django.shortcuts import render
from .models import Event, UserProfile

def index(request):
    user_profile = None
    if request.user.is_authenticated:
        try:
            user_profile = UserProfile.objects.get(user=request.user)
        except UserProfile.DoesNotExist:
            pass  # UserProfile does not exist; continue without redirecting

    active_events = Event.objects.filter(event_status='active').order_by('-start_date')
    upcoming_events = Event.objects.filter(event_status='upcoming').order_by('start_date')
    closed_events = Event.objects.filter(event_status='closed').order_by('-end_date')

    context = {
        'user_profile': user_profile,
        'active_events': active_events,
        'upcoming_events': upcoming_events,
        'closed_events': closed_events,
    }
    return render(request, 'index.html', context)


# Login and logout view STARTS -----------------------------------------------------------------------------------###

from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.contrib.auth.forms import AuthenticationForm
from django.urls import reverse  # Import reverse to resolve URL names

def user_login(request):
    form = AuthenticationForm(request, data=request.POST or None)
    form.fields['username'].label = "Email"
    if form.is_valid():
        login(request, form.get_user())
        # Redirect to the 'next' parameter (preserved in GET or POST) or the website homepage
        next_url = request.POST.get('next') or request.GET.get('next')
        # Validate the next URL to avoid open redirects
        from django.utils.http import url_has_allowed_host_and_scheme
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect(reverse('website:homepage'))  # Redirect to website homepage

    return render(request, 'login.html', {'form': form})


def corporate_login(request):
    form = AuthenticationForm(request, data=request.POST or None)
    form.fields['username'].label = "Email"
    dashboard_url = reverse('corporate_dashboard')

    if form.is_valid():
        login(request, form.get_user())
        next_url = request.POST.get('next') or request.GET.get('next') or dashboard_url
        from django.utils.http import url_has_allowed_host_and_scheme
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect(dashboard_url)

    return render(request, 'corporate_login.html', {'form': form, 'dashboard_url': dashboard_url})


@login_required
def corporate_dashboard(request):
    corporate_account = CorporateAccount.objects.filter(user=request.user).first()
    has_personal_profile = UserProfile.objects.filter(user=request.user).exists()
    matching_requests = CorporateAccountRequest.objects.filter(email__iexact=request.user.email).order_by('-created_at')
    open_events = Event.objects.filter(event_status='active', registration='Open').order_by('start_date')
    corporate_payments = CorporatePayment.objects.filter(corporate_account=corporate_account).select_related('event', 'corporate_registration')[:8] if corporate_account else []
    corporate_registrations = (
        CorporateEventRegistration.objects.filter(corporate_account=corporate_account)
        .select_related('event')
        .prefetch_related('attendees', 'corporate_payments')
        [:10]
    ) if corporate_account else []
    dashboard_submissions = []
    for submission in corporate_registrations:
        attendees = list(submission.attendees.all())
        payments = list(submission.corporate_payments.all())
        dashboard_submissions.append({
            'submission': submission,
            'total_count': len(attendees),
            'pending_count': sum(1 for attendee in attendees if attendee.review_status == 'pending'),
            'approved_count': sum(1 for attendee in attendees if attendee.review_status == 'approved'),
            'denied_count': sum(1 for attendee in attendees if attendee.review_status == 'denied'),
            'payments': payments,
        })

    return render(request, 'corporate_dashboard.html', {
        'corporate_account': corporate_account,
        'matching_requests': matching_requests,
        'open_events': open_events,
        'corporate_payments': corporate_payments,
        'corporate_registrations': corporate_registrations,
        'dashboard_submissions': dashboard_submissions,
        'has_personal_profile': has_personal_profile,
    })


def _match_user_for_corporate_attendee(email, phone):
    matched_profile = UserProfile.objects.filter(Q(email__iexact=email) | Q(phone__iexact=phone)).select_related('user').first()
    if matched_profile:
        return matched_profile.user
    return User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first()


def _create_corporate_attendee(registration, attendee_data):
    return CorporateEventAttendee.objects.create(
        registration=registration,
        matched_user=_match_user_for_corporate_attendee(attendee_data['email'], attendee_data['phone']),
        name=attendee_data['name'],
        email=attendee_data['email'],
        phone=attendee_data['phone'],
        degree=attendee_data.get('degree', ''),
        organization=attendee_data.get('organization', ''),
        country=attendee_data.get('country', ''),
        department=attendee_data.get('department', ''),
        bmdc_registration_number=attendee_data.get('bmdc_registration_number', ''),
        designation=attendee_data.get('designation', ''),
        notes=attendee_data.get('notes', ''),
    )


def _clean_corporate_csv_header(header):
    return (header or '').strip().lower().replace(' ', '_').replace('-', '_')


def _parse_corporate_csv(uploaded_file):
    if not uploaded_file.name.lower().endswith('.csv'):
        return [], ['Please upload a CSV file using the BSBCS template.']

    try:
        content = uploaded_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return [], ['The CSV file could not be read. Please save it as UTF-8 CSV and upload again.']

    reader = csv.DictReader(io.StringIO(content))
    required_columns = {'name', 'email', 'phone'}
    headers = {_clean_corporate_csv_header(header) for header in (reader.fieldnames or [])}
    missing_columns = sorted(required_columns - headers)
    if missing_columns:
        return [], [f"Missing required column(s): {', '.join(missing_columns)}."]

    rows = []
    errors = []
    for row_number, row in enumerate(reader, start=2):
        normalized = {
            _clean_corporate_csv_header(key): (value or '').strip()
            for key, value in row.items()
        }
        if not any(normalized.values()):
            continue

        missing_values = [column for column in required_columns if not normalized.get(column)]
        if missing_values:
            errors.append(f"Row {row_number}: missing {', '.join(missing_values)}.")
            continue

        rows.append({
            'name': normalized.get('name', ''),
            'email': normalized.get('email', ''),
            'phone': normalized.get('phone', ''),
            'degree': normalized.get('degree', ''),
            'organization': normalized.get('organization', ''),
            'country': normalized.get('country', ''),
            'department': normalized.get('department', ''),
            'bmdc_registration_number': normalized.get('bmdc_registration_number', ''),
            'designation': normalized.get('designation', ''),
            'notes': normalized.get('notes', ''),
        })

    if not rows and not errors:
        errors.append('The CSV file does not contain any attendee rows.')

    return rows, errors


def _split_corporate_attendee_rows(event, attendee_rows):
    accepted_rows = []
    skipped_rows = []
    seen_keys = set()

    for index, row in enumerate(attendee_rows, start=2):
        email_key = (row.get('email') or '').strip().lower()
        phone_key = (row.get('phone') or '').strip()
        row_keys = {key for key in [f'email:{email_key}', f'phone:{phone_key}'] if key.split(':', 1)[1]}

        if seen_keys.intersection(row_keys):
            skipped_rows.append({
                'row': index,
                'name': row.get('name', ''),
                'reason': 'duplicate inside this CSV file',
            })
            continue

        existing_attendee = CorporateEventAttendee.objects.filter(
            registration__event=event
        ).filter(
            Q(email__iexact=row.get('email', '')) | Q(phone=row.get('phone', ''))
        ).select_related('registration').order_by('-created_at').first()

        if existing_attendee and existing_attendee.review_status == 'approved':
            skipped_rows.append({
                'row': index,
                'name': row.get('name', ''),
                'reason': 'already approved for this event',
            })
            continue

        if existing_attendee and existing_attendee.review_status == 'pending':
            skipped_rows.append({
                'row': index,
                'name': row.get('name', ''),
                'reason': 'already submitted and pending review',
            })
            continue

        if existing_attendee and existing_attendee.review_status == 'denied':
            previous_note = f"Previously denied corporate attendee #{existing_attendee.pk}; resubmitted for review."
            row['notes'] = f"{row.get('notes', '')} {previous_note}".strip()

        existing_participant = Participant.objects.filter(event=event).filter(
            Q(email__iexact=row.get('email', '')) | Q(phone=row.get('phone', ''))
        ).order_by('-created_at').first()

        if existing_participant and existing_participant.approved:
            skipped_rows.append({
                'row': index,
                'name': row.get('name', ''),
                'reason': 'already approved as a participant for this event',
            })
            continue

        if existing_participant and not existing_participant.approved and not existing_participant.denied:
            skipped_rows.append({
                'row': index,
                'name': row.get('name', ''),
                'reason': 'already submitted as a participant and pending review',
            })
            continue

        if existing_participant and existing_participant.denied:
            previous_note = f"Previously denied participant #{existing_participant.pk}; resubmitted by corporate account."
            row['notes'] = f"{row.get('notes', '')} {previous_note}".strip()

        accepted_rows.append(row)
        seen_keys.update(row_keys)

    return accepted_rows, skipped_rows


@login_required
def corporate_event_registration(request, event_id):
    corporate_account = CorporateAccount.objects.filter(user=request.user, status='approved').first()
    if not corporate_account:
        return redirect('corporate_dashboard')

    event = get_object_or_404(Event, id=event_id, event_status='active', registration='Open')
    regular_fee = event.amount if event.payment_required else 0
    member_fee = event.member_registration_fee if event.member_registration_fee is not None else 0
    recent_submissions = CorporateEventRegistration.objects.filter(
        corporate_account=corporate_account,
        event=event,
    ).prefetch_related('attendees')[:5]

    if request.method == 'POST' and request.POST.get('submission_type') == 'csv':
        uploaded_file = request.FILES.get('attendee_file')
        if not uploaded_file:
            messages.error(request, 'Please choose a CSV file to upload.')
        else:
            attendee_rows, upload_errors = _parse_corporate_csv(uploaded_file)
            if upload_errors:
                for error in upload_errors[:8]:
                    messages.error(request, error)
                if len(upload_errors) > 8:
                    messages.error(request, f'{len(upload_errors) - 8} more row error(s) were found. Please correct the CSV and upload again.')
            else:
                accepted_rows, skipped_rows = _split_corporate_attendee_rows(event, attendee_rows)
                if accepted_rows:
                    with transaction.atomic():
                        registration = CorporateEventRegistration.objects.create(
                            corporate_account=corporate_account,
                            event=event,
                            submission_mode='csv',
                            status='submitted',
                            total_attendees=len(accepted_rows),
                        )
                        for attendee_data in accepted_rows:
                            _create_corporate_attendee(registration, attendee_data)
                    messages.success(request, f'{len(accepted_rows)} attendee(s) uploaded for BSBCS admin review.')
                else:
                    messages.warning(request, 'No new attendees were submitted from this CSV.')

                if skipped_rows:
                    reason_counts = {}
                    for skipped in skipped_rows:
                        reason_counts[skipped['reason']] = reason_counts.get(skipped['reason'], 0) + 1
                    summary = '; '.join(f'{count} {reason}' for reason, count in reason_counts.items())
                    messages.warning(request, f'{len(skipped_rows)} row(s) skipped: {summary}.')
                return redirect('corporate_event_registration', event_id=event.id)

    elif request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()

        if not name or not email or not phone:
            messages.error(request, 'Name, email, and phone are required for manual attendee submission.')
        else:
            registration = CorporateEventRegistration.objects.create(
                corporate_account=corporate_account,
                event=event,
                submission_mode='manual',
                status='submitted',
                total_attendees=1,
            )
            _create_corporate_attendee(registration, {
                'name': name,
                'email': email,
                'phone': phone,
                'degree': (request.POST.get('degree') or '').strip(),
                'organization': (request.POST.get('organization') or '').strip(),
                'country': (request.POST.get('country') or '').strip(),
                'department': (request.POST.get('department') or '').strip(),
                'bmdc_registration_number': (request.POST.get('bmdc_registration_number') or '').strip(),
                'designation': (request.POST.get('designation') or '').strip(),
                'notes': (request.POST.get('notes') or '').strip(),
            })
            messages.success(request, f'{name} has been submitted for BSBCS admin review.')
            return redirect('corporate_event_registration', event_id=event.id)

    return render(request, 'corporate_event_registration.html', {
        'corporate_account': corporate_account,
        'event': event,
        'regular_fee': regular_fee,
        'member_fee': member_fee,
        'recent_submissions': recent_submissions,
    })


@login_required
def corporate_event_template_csv(request, event_id):
    corporate_account = CorporateAccount.objects.filter(user=request.user, status='approved').first()
    if not corporate_account:
        return redirect('corporate_dashboard')

    event = get_object_or_404(Event, id=event_id, event_status='active', registration='Open')
    filename = f"bsbcs_corporate_{event.id}_attendee_template.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'name',
        'email',
        'phone',
        'degree',
        'organization',
        'country',
        'department',
        'bmdc_registration_number',
        'designation',
        'notes',
    ])
    return response


def user_logout(request):
    logout(request)
    return redirect(reverse('website:homepage'))  # Redirect to website homepage

# Login and logout view ENDS -----------------------------------------------------------------------------------###

# Home View ---------------------------------------------------------------###
from django.shortcuts import get_object_or_404
from .models import FeatureSpeaker, AboutTheConference, Invitation, Event

def home(request, event_id):
    # print(event_id)
    user_profile = None
    if request.user.is_authenticated:
        try:
            user_profile = UserProfile.objects.get(user=request.user)
        except UserProfile.DoesNotExist:
            user_profile = None  # Handle case where UserProfile doesn't exist
    event = get_object_or_404(Event, id=event_id)
    speakers = FeatureSpeaker.objects.filter(event=event)
    about_conference = AboutTheConference.objects.filter(event=event).first()  # Assuming you have one instance per event
    invitations = Invitation.objects.filter(event=event)
    modal_image_path = 'images/BBCC_2024_Poster_Final.jpg'
    active_member = get_active_member_for_user(request.user)
    existing_participant = None
    if request.user.is_authenticated:
        existing_participant = Participant.objects.filter(user=request.user, event=event).first()
    regular_registration_available = (
        event.event_status == 'active'
        and event.registration == 'Open'
        and event.registration_audience == 'all'
    )
    member_registration_available = (
        event.event_status == 'active'
        and event.registration == 'Open'
        and (event.member_registration_enabled or event.registration_audience == 'members_only')
        and not existing_participant
    )

    context = {
        'user_profile': user_profile,
        'event': event,
        'speakers': speakers,
        'about_conference': about_conference,
        'invitations': invitations,
        'modal_image': modal_image_path,
        'active_member': active_member,
        'existing_participant': existing_participant,
        'regular_registration_available': regular_registration_available,
        'member_registration_available': member_registration_available,
    }

    return render(request, 'home.html', context)
# Home View Ends ---------------------------------------------------------------###

# Home Modal View ---------------------------------------------------------------###
from django.http import JsonResponse
# def modal_image_view(request, event_id):
#     event = get_object_or_404(Event, id=event_id)
#     modal_html = render_to_string('partials/modal_image.html', {'event': event})
#     return JsonResponse({'html': modal_html})
# Home Modal View Ends ---------------------------------------------------------------###

# Participant List View ---------------------------------------------------------------###
from django.shortcuts import get_object_or_404
from .models import Participant, Event

def participant_list(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    approved_paid_participants = Participant.objects.filter(event=event, approved=True, payment_statuses__status='completed')
    
    if request.headers.get('HX-Request'):
        return render(request, 'partials/participant_list.html', {'participants': approved_paid_participants})
    
    return render(request, 'participant_list.html', {'participants': approved_paid_participants, 'event': event})
def participant_list_partial(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    # Filter participants with approved=True and payment status='completed'
    approved_paid_participants = Participant.objects.filter(
        event=event, approved=True, payment_statuses__status='completed'
    )

    return render(request, 'partials/participant_list.html', {'participants': approved_paid_participants})



# About The Conference View ---------------------------------------------------------------###
def about(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    about_conference = AboutTheConference.objects.filter(event=event).first()
    return render(request, 'about.html', {'about_conference': about_conference, 'event': event})
# About The Conference View Ends ---------------------------------------------------------------### 

# Speakers View ---------------------------------------------------------------###
def speakers(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    speakers = FeatureSpeaker.objects.filter(event=event)
    return render(request, 'speakers.html', {'speakers': speakers, 'event': event})
# Speakers View Ends ---------------------------------------------------------------###

# Registration view Starts --------------------------------------------------######
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Event, UserProfile, Participant, PaymentStatus
from .forms import RegistrationForm
from django.db import IntegrityError



# Registration View Ends -----------------------------------------------------------------#
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db import IntegrityError

def registration(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    membership_nudge_available = (
        event.registration == 'Open'
        and (event.member_registration_enabled or event.registration_audience == 'members_only')
    )
    regular_registration_fee = event.amount if event.payment_required and event.amount else 0
    member_registration_fee = event.member_registration_fee or 0

    # Check if the user is authenticated
    if not request.user.is_authenticated:
        return render(request, 'registration_login_prompt.html', {
            'message': 'You need to log in to be able to register for this event.',
            'event': event,
            'membership_nudge_available': membership_nudge_available,
            'regular_registration_fee': regular_registration_fee,
            'member_registration_fee': member_registration_fee,
            'login_url': reverse('login'),
            'signup_url': reverse('create_profile'),
        })

    # Check if registration for the event is open
    if event.registration != 'Open':  # Match case-sensitive values as per your model
        status_message = {
            'Closed': 'Registration for this event is closed.',
            'Starting Soon': 'Registration for this event will start soon. Please check back later.',
        }
        return render(request, 'registration_error.html', {
            'message': status_message.get(event.registration, 'Registration is not open for this event.'),
            'event': event
        })

    active_member = get_active_member_for_user(request.user)
    member_registration_available = (
        event.member_registration_enabled
        or event.registration_audience == 'members_only'
    )

    try:
        user_profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        messages.warning(request, "Please complete your personal BSBCS profile before registering as an individual participant.")
        return redirect(f'{reverse("create_profile")}?next={request.get_full_path()}')

    # Check if the user has already registered for the event
    try:
        participant = Participant.objects.get(user=request.user, event=event)
        return render(request, 'registration_error.html', get_existing_registration_context(participant, event))
    except Participant.DoesNotExist:
        pass  # User has not registered yet, proceed with registration

    if active_member and member_registration_available:
        return redirect('registration:member_registration', event_id=event.pk)

    if event.registration_audience == 'members_only':
        return render(request, 'registration_error.html', {
            'message': 'This event is available for approved active BSBCS members only. Please apply for membership or use member registration after your membership is active.',
            'event': event
        })

    initial_data = {
        'name': user_profile.name,
        'email': request.user.email,
        'phone': user_profile.phone,
    }

    if request.method == 'POST':
        form = RegistrationForm(request.POST, event=event)  # Pass event instance
        if form.is_valid():
            try:
                participant = form.save(commit=False)
                participant.user = request.user  # Assign the logged-in user
                participant.event = event  # Assign the event explicitly
                participant.save()

                # Generate unique merchant invoice number for free events
                merchant_invoice_number = f"REG-{event.pk}-{request.user.id}-{int(time.time())}"

                # Create payment status based on event payment requirement
                if event.payment_required and event.amount:
                    PaymentStatus.objects.create(
                        participant=participant,
                        event=event,
                        status='unpaid',
                        amount=participant.get_payable_amount(),
                        merchant_invoice_number=merchant_invoice_number
                    )
                else:
                    # For free events, create completed payment status
                    PaymentStatus.objects.create(
                        participant=participant,
                        event=event,
                        status='completed',
                        amount=0,
                        merchant_invoice_number=merchant_invoice_number
                    )

                send_registration_form_submission_email(participant)
                messages.success(request, 'Registration form submitted successfully!')
                return redirect('registration:registration_submitted', event_id=event.pk)
            except IntegrityError as e:
                logger.exception("IntegrityError: %s", e)  # Debugging line
                messages.error(request, 'A participant with this email or phone number already exists for this event.')
        else:
            messages.error(request, 'There are errors in your form. Registration failed. Please check the form.')
    else:
        form = RegistrationForm(initial=initial_data, event=event)

    show_membership_nudge = (
        membership_nudge_available
        and event.registration_audience == 'all'
        and not active_member
    )
    show_registration_choice = (
        show_membership_nudge
        and request.method == 'GET'
        and request.GET.get('mode') != 'regular'
    )

    return render(request, 'registration.html', {
        'form': form,
        'event': event,
        'show_membership_nudge': show_membership_nudge,
        'show_registration_choice': show_registration_choice,
        'regular_registration_fee': regular_registration_fee,
        'member_registration_fee': member_registration_fee,
    })


def member_event_registration(request, event_id):
    if not request.user.is_authenticated:
        return redirect(f'{reverse("login")}?next={reverse("registration:member_registration", kwargs={"event_id": event_id})}')

    event = get_object_or_404(Event, id=event_id)

    if event.event_status != 'active' or event.registration != 'Open':
        return render(request, 'registration_error.html', {
            'message': 'Member registration is not open for this event.',
            'event': event
        })

    if not event.member_registration_enabled and event.registration_audience != 'members_only':
        return render(request, 'registration_error.html', {
            'message': 'This event does not currently allow member registration.',
            'event': event
        })

    try:
        user_profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        messages.warning(request, "Please create your profile before registering for this event.")
        return redirect(f'{reverse("create_profile")}?next={reverse("registration:member_registration", kwargs={"event_id": event_id})}')

    member = get_active_member_for_user(request.user)
    if not member:
        return render(request, 'registration_error.html', {
            'message': 'Only approved active BSBCS members can use member event registration.',
            'event': event
        })

    existing_participant = Participant.objects.filter(user=request.user, event=event).first()
    if existing_participant:
        return render(request, 'registration_error.html', get_existing_registration_context(existing_participant, event))

    department = get_or_create_member_department(event)
    payable_amount = event.member_registration_fee or 0
    merchant_invoice_number = f"MEMEVT-{event.pk}-{request.user.id}-{int(time.time())}"

    try:
        participant = Participant.objects.create(
            user=request.user,
            event=event,
            registration_type='member',
            name=user_profile.name,
            degree=(member.position or 'Member')[:50],
            year_of_graduation=0,
            department=department,
            organization=(member.institution or 'BSBCS Member')[:100],
            email=user_profile.email,
            phone=user_profile.phone,
            country=user_profile.country,
            BMDC_registration_number='',
        )
        PaymentStatus.objects.create(
            participant=participant,
            event=event,
            status='unpaid' if payable_amount else 'completed',
            amount=payable_amount,
            merchant_invoice_number=merchant_invoice_number
        )
        send_registration_form_submission_email(participant)
        messages.success(request, 'Your member event registration has been submitted for approval.')
        return redirect('registration:registration_submitted', event_id=event.pk)
    except IntegrityError as e:
        logger.exception("Member registration IntegrityError: %s", e)
        messages.error(request, 'You are already registered for this event with this email or phone number.')
        return redirect('registration:home', event_id=event.pk)

from django.shortcuts import render, get_object_or_404

def registration_submitted(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    logger.debug("Event ID: %s", getattr(event, 'id', None))  # type: ignore[attr-defined]
    return render(request, 'registration_submitted.html', {'event': event})

def registration_message(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    return render(request, 'registration_message.html', {'event': event})
# Email sending function
def send_registration_form_submission_email(participant):
    subject = 'Registration Confirmation'
    # Render the email template with context
    html_content = render_to_string('registration_submitted.html', {'participant': participant})
    text_content = strip_tags(html_content)
    from_email = os.getenv("EMAIL_HOST_USER")
    recipient_list = [participant.email]

    # Create the email
    email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
    email.attach_alternative(html_content, "text/html")
    email.send()


from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import Participant, Event
from .forms import RegistrationForm

def send_approval_email(participant, event):
    subject = f'Registration Approval for {event.name} {event.year}'
    try:
        html_content = render_to_string('registration_badge_download.html', {'participant': participant, 'event': event})
        text_content = strip_tags(html_content)
        from_email = os.getenv("EMAIL_HOST_USER")
        recipient_list = [participant.email]

        email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
        email.attach_alternative(html_content, "text/html")
        email.send()
    except Exception as e:
        logger.exception("Error sending approval email: %s", e)


from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

def send_payment_link_email(participant, event):
        # Only send payment email if payment is required
    if not event.payment_required:
        return  # Don't send payment email for free events
    subject = f'Complete Your Payment for {event.name} {event.year} Conference'
    payment_url = reverse('registration:payment', kwargs={
        'event_id': event.id,
        'participant_id': participant.id
    })
    full_payment_url = f'https://bsbcs.info{payment_url}'

    try:
        html_content = render_to_string('payment_link.html', {'participant': participant, 'event': event, 'payment_url': full_payment_url})
        text_content = strip_tags(html_content)
        from_email = os.getenv("EMAIL_HOST_USER")
        recipient_list = [participant.email]

        email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
        email.attach_alternative(html_content, "text/html")
        email.send()
    except Exception as e:
        logger.exception("Error sending payment link email: %s", e)

# #### Registration process, registration mail Ends ----------------------------------###

# Abstract Submission View
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Event, Participant, PaymentStatus, AbstractSubmission
from .forms import AbstractSubmissionForm

# Custom decorator for approved user
def approved_user_required(view_func):
    def _wrapped_view_func(request, *args, **kwargs):
        event_id = kwargs.get('event_id')
        event = get_object_or_404(Event, id=event_id)
        try:
            participant = Participant.objects.get(email=request.user.email, event=event)
        except Participant.DoesNotExist:
            return render(request, 'error.html', {
                'message': 'You need to register for the event to submit an abstract. Please register first.',
                'event': event,
                'participant': None  # Pass None for participant
            })
        return view_func(request, *args, **kwargs)
    return _wrapped_view_func

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Event, Participant, PaymentStatus, AbstractSubmission
from .forms import AbstractSubmissionForm
from django.db import IntegrityError


# New Abstract_Submission View
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect


def abstract_submission(request, event_id):
    # Check if the user is authenticated
    if not request.user.is_authenticated:
        return render(request, 'login_required_message.html', {
            'message': 'You need to log in to submit an abstract. Please log in or create a profile.',
            'login_url': f'{reverse("login")}?next={request.get_full_path()}',
            'signup_url': f'{reverse("create_profile")}?next={request.get_full_path()}',
        })

    event = get_object_or_404(Event, id=event_id)

    # Fetch the participant associated with the logged-in user and the current event
    try:
        participant = Participant.objects.get(user=request.user, event=event)
    except Participant.DoesNotExist:
        return render(request, 'error.html', {
            'message': 'You are not registered as a participant for this event.',
            'event': event,
            'participant': None  # Pass None to indicate no participant
        })

    # Check if the participant is approved for the specific event
    if not participant.approved:
        return render(request, 'error.html', {
            'message': 'Your registration for this event has not been approved yet. Once approved and payment is done, you will be able to submit an abstract.',
            'event': event,
            'participant': None  # Pass None to indicate no participant
        })

    # Check if the participant has completed the payment for the specific event
    try:
        payment_status = PaymentStatus.objects.get(participant=participant, event=event)
        if payment_status.status != 'completed':
            return render(request, 'error.html', {
                'message': 'You must complete your payment to submit an abstract.',
                'event': event,
                'participant': participant  # Pass participant for payment button
            })
    except PaymentStatus.DoesNotExist:
        return render(request, 'error.html', {
            'message': 'You must complete your payment to submit an abstract.',
            'event': event,
            'participant': participant  # Pass participant for payment button
        })

    if request.method == 'POST':
        form = AbstractSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            abstract = form.save(commit=False)
            # Assign the required fields
            abstract.user = request.user  # Ensure user is assigned
            abstract.event = event  # Assign the current event
            try:
                abstract.save()
                # Send an email to the participant
                try:
                    send_abstract_submission_email(participant)
                    messages.success(request, 'Abstract submitted successfully!')
                except Exception as e:
                    messages.warning(request, f'ABstract SUbmitted but an error occured while sending the mail: {e}')
                return redirect('registration:submission_success', event_id=event.id)  # type: ignore[attr-defined]
            except IntegrityError as e:
                messages.error(request, f'An error occurred while saving your abstract: {e}')
        else:
            messages.error(request, 'There were errors in your form submission. Please check the form.')
    else:
        form = AbstractSubmissionForm()

    return render(request, 'abstract_submission.html', {
        'form': form,
        'event': event,
        'participant': participant
    })

# New Abstract_Submission View Ends

def submission_success(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    return render(request, 'submission_success.html', {'event': event})


def send_abstract_submission_email(participant):
    subject = 'Abstract Submission Confirmation'
    # Render the email template with context
    html_content = render_to_string('submission_success.html', {'participant': participant})
    text_content = strip_tags(html_content)
    from_email = os.getenv("EMAIL_HOST_USER")  # Replace with your sender email
    recipient_list = [participant.email]

    # Create the email
    email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
    email.attach_alternative(html_content, "text/html")
    email.send()

# ### Abstract Submission process, abstract submission mail Ends ----------------------------------###

# Invitation View
def invitation(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    invitations = Invitation.objects.filter(event=event)
    return render(request, 'invitation.html', {'invitations': invitations, 'event': event})


from django.shortcuts import render, get_object_or_404
from .models import ProgramSchedulePdf, Event
def schedule(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    program_schedules = ProgramSchedule.objects.filter(event=event)\
        .select_related('abstract_submission')\
        .prefetch_related('time_slots')\
        .order_by('time_slots__program_day', 'time_slots__start_time')
    
    # Fetch the uploaded PDF from the ProgramSchedulePdf model
    program_schedule_pdf = ProgramSchedulePdf.objects.filter(event=event).first()
    
    return render(request, 'schedule.html', {
        'program_schedules': program_schedules,
        'event': event,
        'program_schedule_pdf': program_schedule_pdf,  # Pass the PDF object to the template
    })


def session_detail(request, event_id, pk):
    event = get_object_or_404(Event, id=event_id)
    session = get_object_or_404(AbstractSubmission, event=event, pk=pk)
    return render(request, 'partials/session_detail.html', {'session': session, 'event': event})

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from .models import Event, ProgramSchedule
from .pdf_utils import generate_schedule_pdf

def download_schedule_pdf(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    program_schedules = ProgramSchedule.objects.filter(event=event)\
        .select_related('abstract_submission')\
        .prefetch_related('time_slots')\
        .order_by('time_slots__program_day', 'time_slots__start_time')
    
    # Pass both event and schedules to the PDF generator
    buffer = generate_schedule_pdf(event, program_schedules)

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="program_schedule_{event.name}_{event.year}.pdf"'
    return response


# Sponsors View START------------------------------------------------------------------------------#
def sponsor_list(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    categories = ['Title', 'Platinum', 'Golden', 'Silver', 'Logistics', 'Media', 'IT', 'Event']
    sponsors_by_category = {category: Sponsor.objects.filter(event=event, category=category) for category in categories}
    return render(request, 'sponsor_list.html', {'sponsors_by_category': sponsors_by_category, 'event': event})

# Sponsors View END--------------------------------------------------------------------------------#

# Publication View START------------------------------------------------------------------------------#
def publication_list(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    publications = AbstractSubmission.objects.filter(event=event, approved_for_presentation=True) | AbstractSubmission.objects.filter(event=event, approved_for_poster=True)
    notebook = UploadNoteBook.objects.filter(event=event).first()
    return render(request, 'publication_list.html', {'event': event, 'publications': publications, 'notebook': notebook})

def publication_detail(request, event_id, pub_id):
    event = get_object_or_404(Event, id=event_id)
    publication = get_object_or_404(AbstractSubmission, event=event, id=pub_id)
    return render(request, 'publication_detail.html', {'event': event, 'publication': publication})
# Publication View END--------------------------------------------------------------------------------#

# Event Gallery View START------------------------------------------------------------------------------#

from django.shortcuts import render, get_object_or_404
from .models import Event, EventImage, EventVideo

def event_gallery(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    images = EventImage.objects.filter(event=event)
    videos = EventVideo.objects.filter(event=event)
    return render(request, 'event_gallery.html', {'event': event, 'images': images, 'videos': videos})

# Event Gallery View END--------------------------------------------------------------------------------#

# Bkash Payment gatweay Integration
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy
from .models import Participant, Event, PaymentStatus
import os
from dotenv import load_dotenv
# lets load environment variables
load_dotenv()

# Access the credentials and production URL from the environment variables
BKASH_USERNAME = os.getenv("BKASH_USERNAME")
BKASH_APP_KEY = os.getenv("BKASH_APP_KEY")
BKASH_APP_SECRET = os.getenv("BKASH_APP_SECRET")
BKASH_PASSWORD = os.getenv("BKASH_PASSWORD")
BKASH_PRODUCTION_URL = os.getenv("BKASH_PRODUCTION_URL")


def render_error_page(request, error_message):
    """Utility function to render the error page with a specific message."""
    context = {
        'title': "Payment Failure",
        'error_message': error_message,
    }
    return render(request, 'payment_message.html', context)

# Step 1: Grant Token

from django.core.cache import cache

def get_bkash_token():
    cached_token = cache.get('bkash_token')  # Check if token exists in cache
    if cached_token:
        logger.info("Using cached token")
        return cached_token

    url = f"{BKASH_PRODUCTION_URL}/tokenized/checkout/token/grant"
    headers = {
        "username": BKASH_USERNAME,
        "password": BKASH_PASSWORD,
        "Content-Type": "application/json"
    }
    payload = {
        "app_key": BKASH_APP_KEY,
        "app_secret": BKASH_APP_SECRET
    }

    try:
        logger.info("Requesting new token")
        response = requests.post(url, json=payload, headers=headers, timeout=30) # 30 sec timeout
        response.raise_for_status()
        token = response.json().get("id_token")

        # Cache the token for 59 minutes (less than its actual expiry time of 60 minutes)
        cache.set('bkash_token', token, timeout=59 * 60)
        logger.info("Token retrieved and cached successfully: %s", _mask_secret(token))
        return token
    except requests.exceptions.Timeout:
        logger.error("Token request timed out")
        return None
    except requests.exceptions.RequestException as e:
        logger.exception("Failed to get token: %s", e)
        return None

# Step 2: Create Payment
def create_bkash_payment(token, amount, payer_reference, callback_url, merchant_invoice_number):
    url = f"{BKASH_PRODUCTION_URL}/tokenized/checkout/create"
    payload = {
        "mode": "0011",
        "amount": str(amount),
        "currency": "BDT",
        "intent": "sale",
        "merchantInvoiceNumber": merchant_invoice_number,
        "callbackURL": callback_url,
        "payerReference": payer_reference
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-APP-Key": BKASH_APP_KEY
    }

    try:
        logger.info("Creating payment - merchantInvoice=%s amount=%s", merchant_invoice_number, payload.get('amount'))
        response = requests.post(url, json=payload, headers=headers, timeout=30) # 30 sec timeout
        response.raise_for_status()  # Raises an exception for HTTP errors (4xx, 5xx)
        return response.json()

    except requests.exceptions.Timeout:
        logger.error("Payment creation timed out for merchantInvoice=%s", merchant_invoice_number)
        return {"statusCode": "408", "statusMessage": "Payment creation request timed out."}

    except requests.exceptions.RequestException as e:
        logger.exception("Error in creating payment for merchantInvoice=%s: %s", merchant_invoice_number, e)
        return None

# Step 3: Execute Payment
def execute_payment(token, payment_id):
    url = f"{BKASH_PRODUCTION_URL}/tokenized/checkout/execute"
    payload = {"paymentID": payment_id}
    headers = {
        "Content-Type": "application/json",
        "accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-APP-Key": BKASH_APP_KEY # Add the required APP Key here
    }
    try:
        logger.info("Executing payment - paymentID=%s", payment_id)
        logger.debug("Execute request headers: %s", json.dumps({k: ('<REDACTED>' if k.lower()=='authorization' else v) for k,v in headers.items()}))
        logger.debug("Execute request body: %s", json.dumps(payload))
        response = requests.post(url, json=payload, headers=headers, timeout=30) # 30 sec timeout
        response.raise_for_status()
        return response.json()
        
    except requests.exceptions.Timeout:
        logger.error("Payment execution timed out for paymentID=%s", payment_id)
        return {"statusCode": "408", "statusMessage": "Payment execution request timed out."}
    
    except requests.exceptions.RequestException as e:
        logger.exception("Error in payment execution for paymentID=%s: %s", payment_id, e)
        resp = getattr(e, 'response', None)
        if resp is not None:
            try:
                resp_body = resp.json()
            except Exception:
                resp_body = getattr(resp, 'text', None)
            logger.error("Payment execution error response: %s", resp_body)
        return None

# Step 4: Query Payment  
import requests

def payment_query(token, payment_id):

    url = f"{BKASH_PRODUCTION_URL}/tokenized/checkout/payment/status"
    payload = {"paymentID": payment_id}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-APP-Key": BKASH_APP_KEY  # Ensure APP Key is properly set
    }

    try:
        logger.info("Querying payment status for paymentID=%s", payment_id)
        response = requests.post(url, json=payload, headers=headers, timeout=30) # 30 sec timeout
        response.raise_for_status()  # Raise an error for HTTP codes >= 400
        
        # Debugging response
        logger.info("Payment query successful: %s", response.status_code)
        try:
            resp_body = response.json()
            logger.debug("Payment query response body: %s", json.dumps(resp_body))
        except Exception:
            logger.debug("Payment query raw response: %s", getattr(response, 'text', None))
        return response.json()
        
    except requests.exceptions.Timeout:
        logger.error("Payment query timed out for paymentID=%s", payment_id)
    
    except requests.exceptions.HTTPError as http_err:
        logger.exception("HTTP error during payment query for paymentID=%s: %s", payment_id, http_err)
        resp = getattr(http_err, 'response', None)
        if resp is not None:
            try:
                resp_body = resp.json()
            except Exception:
                resp_body = getattr(resp, 'text', '')
            logger.error("HTTP response error: %s", resp_body)
        return None
    except requests.exceptions.RequestException as req_err:
        logger.exception("Request error during payment query for paymentID=%s: %s", payment_id, req_err)
        return None

# Step 5: Payment View
from django.urls import reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.contrib import messages
from .models import Participant, Event, PaymentStatus


@login_required
def payment(request, event_id, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)
    event = get_object_or_404(Event, id=event_id)
    payment_status = get_object_or_404(PaymentStatus, participant=participant, event=event)

    if request.method == 'POST':
        try:
            # Step 1: Get token
            token = get_bkash_token()
            if not token:
                messages.error(request, "Failed to get token.")
                return redirect('index')

            # Step 2: Create payment
            amount = payment_status.amount or participant.get_payable_amount()
            if amount <= 0:
                messages.error(request, "No payment is required for this registration.")
                return redirect('registration:home', event_id=event.pk)
            payer_reference = str(getattr(request.user.userprofile, 'phone', None))
            if not payer_reference:
                messages.error(request, "Phone number not found.")
                return redirect('index')

            merchant_invoice_number = f"INV-{event.pk}-{request.user.id}-{int(time.time())}"
            callback_url = request.build_absolute_uri(
                reverse_lazy('registration:payment_success', kwargs={'event_id': event_id, 'participant_id': participant_id})
            ) + f"?merchant_invoice_number={merchant_invoice_number}"
            payment_response = create_bkash_payment(token, amount, payer_reference, callback_url, merchant_invoice_number)
            
            logger.info("Merchant Invoice Number sent to bkash: %s", merchant_invoice_number)
            
            if payment_response and payment_response.get("statusCode") == "0000":  # type: ignore[union-attr]
                # Redirect to bKash payment page
                return redirect(payment_response["bkashURL"])
            else:
                messages.error(request, f"Payment failed: {payment_response.get('statusMessage')}")  # type: ignore[union-attr]
                return redirect('index')

        except Exception as e:
            logger.exception("Error in payment view: %s", e)
            messages.error(request, "An error occurred.")
            return redirect('index')

    return render(request, 'payment.html', {'participant': participant, 'event': event, 'payment_status': payment_status})

# Step 6: Payment Success view
from django.urls import reverse
import time

@login_required
def payment_success(request, event_id, participant_id):
    payment_id = request.GET.get('paymentID')
    merchant_invoice_number = request.GET.get('merchant_invoice_number')
    if not payment_id:
        messages.error(request, "Payment ID not found.")
        return redirect('index')

    # Save payment ID to database for future reference
    participant = get_object_or_404(Participant, id=participant_id)
    event = get_object_or_404(Event, id=event_id)
    
    PaymentStatus.objects.update_or_create(
        participant=participant,
        event=event,
        defaults={
            'transaction_id': payment_id,
            'status': 'pending',
            'amount': participant.get_payable_amount(),
            'merchant_invoice_number': merchant_invoice_number  # Check if this is being set correctly
        }
    )
    logger.info("Generated Merchant Invoice Number: %s", merchant_invoice_number)

    # Redirect to finalize the payment
    messages.success(request, "Payment completed. Finalizing...")
    return redirect(reverse('registration:finalize_payment', kwargs={'event_id': event_id, 'participant_id': participant_id}))


# Step 7: Payment Finalizing View
import time
import logging
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from registration.pdf_utils import generate_corporate_invoice, generate_invoice
@login_required
def finalize_payment(request, event_id, participant_id):
    try:
        # Retrieve PaymentStatus record
        payment_status = get_object_or_404(PaymentStatus, participant_id=participant_id, event_id=event_id)

        # Execute payment logic
        token = get_bkash_token()
        if not token:
            messages.error(request, "Failed to retrieve token.")
            return render(request, 'payment_message.html', {
                'title': "Payment Failure",
                'error_message': "Failed to retrieve token."
            })

        # Call bKash execute API
        execute_response = execute_payment(token, payment_status.transaction_id)

        # Debug point: Log the execute response
        try:
            logger.info("Execute Payment API Response: %s", json.dumps(execute_response))
        except Exception:
            logger.info("Execute Payment API Response (raw): %s", str(execute_response))

        # Handle specific Execute API error cases
        if execute_response:
            status_code = execute_response.get('statusCode')
            status_message = execute_response.get('statusMessage', 'Invalid payment state.')
            
            # Map known error cases
            error_messages = {
                "2001": "Duplicate transaction detected. Please try again.",
                "3001": "Payment was cancelled by the user.",
                "4001": "Wrong OTP provided. Please restart the payment.",
                "5001": "Wrong PIN provided. Please restart the payment.",
            }
            
            # Handle specific errors
            if status_code in error_messages:
                payment_status.status = 'failed'
                payment_status.save()
                return render(request, 'payment_message.html', {
                    'title': 'Payment Failure',
                    'error_message': error_messages[status_code]
                })
            
            # Handle unknown status codes
            elif status_code != "0000":
                payment_status.status = 'failed'
                payment_status.save()
                return render(request, 'payment_message.html', {
                    'title': 'Payment Failure',
                    'error_message': status_message
                })

        # Handle Execute API Success
        if execute_response and execute_response.get('statusCode') == '0000':
            payment_status.status = 'completed'
            payment_status.amount = execute_response.get('amount', payment_status.amount)
            payment_status.merchant_invoice_number = execute_response.get('merchantInvoiceNumber', payment_status.merchant_invoice_number)
            payment_status.transaction_id = execute_response.get('paymentID')
            payment_status.trxID = execute_response.get('trxID')  # Use trxID from execute response
            payment_status.save()

            # Generate Invoice and Send Email
            try:
                invoice_path = generate_invoice(payment_status.participant, payment_status.event, payment_status)
                send_invoice_email(payment_status.participant, payment_status.event, payment_status, invoice_path)
            except Exception as e:
                logger.exception("Invoice/Email Error: %s", e)
                messages.error(request, "Payment completed, but there was an issue generating the invoice or sending the email.")
                return render(request, 'payment_message.html', {
                    'title': 'Payment Completed with Issues',
                    'error_message': 'Please contact support for your invoice.',
                })

            # Render success message
            return render(request, 'finalize_payment.html', {
                'message': "Payment successfully finalized.",
                'payment_details': execute_response,
            })

        # Fallback: Handle incomplete Execute API response
        payment_status.status = 'failed'
        payment_status.save()
        return render(request, 'payment_message.html', {
            'title': 'Payment Failure',
            'error_message': 'Payment finalization failed. Please contact support.',
        })

    except Exception as e:
        logger.exception("Error in finalizing payment: %s", e)
        return render(request, 'payment_message.html', {
            'title': 'Payment Failure',
            'error_message': 'An unexpected error occurred during payment finalization.',
        })

# Step 8: Payment Failure
@login_required
def payment_failure(request, event_id, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)
    event = get_object_or_404(Event, id=event_id)

    # Update payment status to 'failed'
    PaymentStatus.objects.filter(participant=participant, event=event).update(status='failed')

    # Optional: Show a failure reason
    failure_reason = request.GET.get('reason', "Payment failed. Please try again.")
    messages.error(request, failure_reason)
    return render(request, 'payment_message.html', {'event_id': event_id, 'participant_id': participant_id})


def complete_corporate_payment(corporate_payment, execute_response):
    corporate_payment.status = 'completed'
    corporate_payment.amount = execute_response.get('amount', corporate_payment.amount)
    corporate_payment.merchant_invoice_number = execute_response.get('merchantInvoiceNumber', corporate_payment.merchant_invoice_number)
    corporate_payment.transaction_id = execute_response.get('paymentID')
    corporate_payment.trxID = execute_response.get('trxID')
    corporate_payment.save()
    generate_corporate_invoice(corporate_payment)

    for attendee in corporate_payment.attendees.select_related('participant').all():
        if not attendee.participant:
            continue
        PaymentStatus.objects.filter(
            participant=attendee.participant,
            event=corporate_payment.event,
        ).update(
            status='completed',
            transaction_id=corporate_payment.transaction_id,
            trxID=corporate_payment.trxID,
        )


@login_required
def corporate_payment(request, payment_id):
    corporate_payment = get_object_or_404(
        CorporatePayment.objects.select_related('corporate_account', 'event'),
        id=payment_id,
        corporate_account__user=request.user,
    )

    if request.method == 'POST':
        try:
            token = get_bkash_token()
            if not token:
                messages.error(request, "Failed to get token.")
                return redirect('corporate_dashboard')

            if not corporate_payment.amount or corporate_payment.amount <= 0:
                messages.error(request, "No payment is required for this corporate invoice.")
                return redirect('corporate_dashboard')

            merchant_invoice_number = f"CORP-{corporate_payment.event_id}-{corporate_payment.id}-{int(time.time())}"
            callback_url = request.build_absolute_uri(
                reverse('corporate_payment_success', kwargs={'payment_id': corporate_payment.id})
            ) + f"?merchant_invoice_number={merchant_invoice_number}"
            payment_response = create_bkash_payment(
                token,
                corporate_payment.amount,
                corporate_payment.corporate_account.phone,
                callback_url,
                merchant_invoice_number
            )

            if payment_response and payment_response.get("statusCode") == "0000":
                corporate_payment.status = 'initiated'
                corporate_payment.merchant_invoice_number = merchant_invoice_number
                corporate_payment.save(update_fields=['status', 'merchant_invoice_number', 'updated_at'])
                generate_corporate_invoice(corporate_payment)
                return redirect(payment_response["bkashURL"])

            messages.error(request, f"Payment failed: {payment_response.get('statusMessage') if payment_response else 'Unable to create payment.'}")
            return redirect('corporate_payment', payment_id=corporate_payment.id)
        except Exception as exc:
            logger.exception("Error in corporate payment view: %s", exc)
            messages.error(request, "An error occurred.")
            return redirect('corporate_dashboard')

    return render(request, 'corporate_payment.html', {
        'corporate_payment': corporate_payment,
        'event': corporate_payment.event,
    })


@login_required
def corporate_payment_invoice(request, payment_id):
    corporate_payment = get_object_or_404(
        CorporatePayment.objects.select_related('corporate_account', 'event').prefetch_related('attendees'),
        id=payment_id,
        corporate_account__user=request.user,
    )
    if not corporate_payment.invoice:
        generate_corporate_invoice(corporate_payment)
    try:
        invoice_file = corporate_payment.invoice.open('rb')
    except FileNotFoundError as exc:
        generate_corporate_invoice(corporate_payment)
        try:
            invoice_file = corporate_payment.invoice.open('rb')
        except FileNotFoundError as retry_exc:
            raise Http404("Invoice PDF could not be generated.") from retry_exc

    response = FileResponse(invoice_file, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="corporate_invoice_{corporate_payment.id}.pdf"'
    return response


@login_required
def corporate_payment_success(request, payment_id):
    corporate_payment = get_object_or_404(CorporatePayment, id=payment_id, corporate_account__user=request.user)
    payment_id_value = request.GET.get('paymentID')
    merchant_invoice_number = request.GET.get('merchant_invoice_number')
    if not payment_id_value:
        messages.error(request, "Payment ID not found.")
        return redirect('corporate_payment', payment_id=corporate_payment.id)

    corporate_payment.transaction_id = payment_id_value
    corporate_payment.merchant_invoice_number = merchant_invoice_number or corporate_payment.merchant_invoice_number
    corporate_payment.status = 'pending'
    corporate_payment.save(update_fields=['transaction_id', 'merchant_invoice_number', 'status', 'updated_at'])
    return redirect(reverse('corporate_finalize_payment', kwargs={'payment_id': corporate_payment.id}))


@login_required
def corporate_finalize_payment(request, payment_id):
    corporate_payment = get_object_or_404(CorporatePayment, id=payment_id, corporate_account__user=request.user)
    token = get_bkash_token()
    if not token:
        messages.error(request, "Failed to retrieve token.")
        return render(request, 'payment_message.html', {
            'title': "Payment Failure",
            'error_message': "Failed to retrieve token."
        })

    execute_response = execute_payment(token, corporate_payment.transaction_id)
    try:
        logger.info("Corporate execute payment response: %s", json.dumps(execute_response))
    except Exception:
        logger.info("Corporate execute payment response raw: %s", str(execute_response))

    if execute_response and execute_response.get('statusCode') == '0000':
        complete_corporate_payment(corporate_payment, execute_response)
        return render(request, 'finalize_payment.html', {
            'message': "Corporate payment successfully finalized.",
            'payment_details': execute_response,
        })

    corporate_payment.status = 'failed'
    corporate_payment.save(update_fields=['status', 'updated_at'])
    return render(request, 'payment_message.html', {
        'title': 'Payment Failure',
        'error_message': execute_response.get('statusMessage', 'Payment finalization failed.') if execute_response else 'Payment finalization failed.',
    })


@login_required
def corporate_payment_failure(request, payment_id):
    corporate_payment = get_object_or_404(CorporatePayment, id=payment_id, corporate_account__user=request.user)
    corporate_payment.status = 'failed'
    corporate_payment.save(update_fields=['status', 'updated_at'])
    messages.error(request, request.GET.get('reason', "Payment failed. Please try again."))
    return render(request, 'payment_message.html', {'title': 'Payment Failure'})

# Invoice Generation Start ----------------------------------------------------------------#
from django.core.mail import EmailMessage
def send_invoice_email(participant, event, payment_status, invoice_path):
    subject = f"Payment done and Invoice for {event.name}"
    message = (
        f"Dear {participant.name},\n\n"
        f"Thank you for registering for {event.name}.\n"
        f"Please find your invoice attached.\n\n"
        "Best regards,\nConference Team"
    )
    recipient = participant.email

    # Create Email
    email = EmailMessage(subject, message, to=[recipient])
    email.attach_file(invoice_path)
    
    try:
        email.send()
        payment_status.email_sent = True
        payment_status.invoice = invoice_path
        payment_status.save()
        logger.info("Email sent to %s", recipient)
    except Exception as e:
        logger.exception("Error sending email: %s", e)




#-----------------------------Abstract Book Upload Link-----------------------------------#
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from .models import UploadAbstractBook

def download_abstract_book(request, event_id):
    abstract_book = get_object_or_404(UploadAbstractBook, event_id=event_id)

    if not abstract_book.abstract_book:
        raise Http404("Abstract book not found.")

    response = FileResponse(abstract_book.abstract_book.open('rb'), as_attachment=True)
    response['Content-Disposition'] = f'attachment; filename="{abstract_book.abstract_book.name.split("/")[-1]}"'

    return response




# Certificate Genration View #


from django.core.mail import EmailMessage
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from PIL import Image, ImageDraw, ImageFont
from .models import Certificate, Participant, Event, RegistrationKit  # Import RegistrationKit
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

def _certificate_output_filename(participant_name):
    safe_name = "".join(ch if ch.isalnum() or ch in (' ', '-', '_') else '' for ch in participant_name).strip()
    safe_name = safe_name.replace(' ', '_') or 'Participant'
    return f"BBCC_Certificate_{safe_name}.jpg"


def _get_chrome_executable():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def _get_certificate_signatories(certificate):
    return [
        {
            'signature_url': signatory.signature.url if signatory.signature else '',
            'name': signatory.name,
            'designation': signatory.designation,
            'organization': signatory.organization,
        }
        for signatory in certificate.signatories.all()
    ]


def _render_html_certificate_to_jpeg(request, participant, event, certificate, output_path):
    from website.models import SiteSettings

    signatories = _get_certificate_signatories(certificate)
    if not signatories:
        raise ValueError("No signatories configured for this HTML certificate.")

    base_url = request.build_absolute_uri('/')
    html = render_to_string('certificate_design/certificate.html', {
        'participant_name': participant.name,
        'site_settings': SiteSettings.objects.first(),
        'event': event,
        'certificate': certificate,
        'signatories': signatories,
        'signature_count': len(signatories),
        'capture_mode': True,
        'base_url': base_url,
    }, request=request)

    output = Path(output_path)
    render_dir = output.parent / 'html_render'
    render_dir.mkdir(parents=True, exist_ok=True)
    html_path = render_dir / f"{output.stem}.html"
    png_path = render_dir / f"{output.stem}.png"
    chrome_profile = Path(tempfile.mkdtemp(prefix=f"{output.stem}_chrome_"))
    html_path.write_text(html, encoding='utf-8')

    chrome = _get_chrome_executable()
    if not chrome:
        raise RuntimeError("Chrome/Edge was not found on the server, so the HTML certificate cannot be rendered to JPEG.")

    file_url = html_path.resolve().as_uri()
    command = [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-crash-reporter",
        "--disable-crashpad",
        "--disable-features=Crashpad",
        "--hide-scrollbars",
        "--allow-file-access-from-files",
        f"--user-data-dir={chrome_profile.resolve()}",
        "--window-size=1632,1155",
        f"--screenshot={png_path.resolve()}",
        file_url,
    ]
    subprocess.run(command, check=True, timeout=30, cwd=str(settings.BASE_DIR))

    image = Image.open(png_path).convert('RGB')
    image.save(output_path, 'JPEG', quality=95)


def generate_certificate(request, event_id):
    # Fetch the participant details for the current user and event
    participant = get_object_or_404(Participant, user=request.user, event_id=event_id)

    # Fetch the registration kit for the participant
    registration_kit = get_object_or_404(RegistrationKit, payment_status__participant=participant, event_id=event_id)

    # Check if the registration kit is issued
    if registration_kit.status != 'issued':
        return JsonResponse({
            'success': False,
            'error': 'Your registration kit has not been issued yet.',
        }, status=400)

    participant_name = participant.name

    # Fetch the certificate template for the event
    event = get_object_or_404(Event, id=event_id)
    certificate = get_object_or_404(Certificate, event=event)  # Fetch certificate for the event
    output_filename = _certificate_output_filename(participant_name)
    output_path = os.path.join(settings.MEDIA_ROOT, 'certificates', output_filename)

    # Ensure the output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        if certificate.design_mode == Certificate.DESIGN_MODE_HTML:
            _render_html_certificate_to_jpeg(request, participant, event, certificate, output_path)
        else:
            if not certificate.upload_image:
                raise ValueError("No uploaded certificate image configured for this event.")

            template_path = certificate.upload_image.path
            image = Image.open(template_path)
            draw = ImageDraw.Draw(image)

            font_size = 40
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except OSError:
                font = ImageFont.load_default()

            text_position = (520, 470)
            draw.text(text_position, participant_name, font=font, fill="black")
            image.save(output_path)

        response = FileResponse(open(output_path, 'rb'), as_attachment=True, filename=output_filename)
        response['Content-Type'] = 'image/jpeg'
        return response

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f"Error generating or sending certificate: {str(e)}",
        }, status=500)

#Feedback Form Model Starts here----------------------------------------------------------------------------#


from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from .models import Event, Participant, FeedbackQuestion, FeedbackResponse, RegistrationKit

@login_required
def event_feedback_view(request, event_id):
    # Get the event
    event = get_object_or_404(Event, id=event_id)

    # check if the event is over
    if event.event_status != 'closed':
        return HttpResponseForbidden("Feedback for this event is not available now.")

    # Check if the logged-in user has a Registration Kit issued for this event
    try:
        registration_kit = RegistrationKit.objects.get(
            payment_status__participant__user=request.user,  # Check if the logged-in user is linked to the participant
            event=event,
            status='issued'  # Ensure the registration kit is marked as issued
        )
    except RegistrationKit.DoesNotExist:
        # Redirect non-eligible users (no issued registration kit) to an error or informational page
        return render(request, 'feedback_access_denied.html', {'event': event})

    # Get all feedback questions for the event
    questions = event.feedback_questions.all()  # type: ignore[attr-defined]

    if request.method == 'POST':
        # Save feedback responses for the confirmed participant
        for question in questions:
            response_key = f"response_{question.id}"
            if question.question_type == 'matrix':
                # Handle matrix-based responses
                for index, row in enumerate(question.get_rows(), start=1):
                    row_response = request.POST.get(f"{response_key}_{index}", None)
                    if row_response:
                        FeedbackResponse.objects.create(
                            participant=registration_kit.payment_status.participant,  # Associate the feedback with the participant
                            event=event,
                            question=question,
                            response=f"{row}: {row_response}"
                        )
            else:
                # Handle text and radio responses
                user_response = request.POST.get(response_key, None)
                if user_response:
                    FeedbackResponse.objects.create(
                        participant=registration_kit.payment_status.participant,  # Associate the feedback with the participant
                        event=event,
                        question=question,
                        response=user_response
                    )
        return render(request, 'feedback_success.html', {'event': event})

    return render(request, 'event_feedback.html', {'event': event, 'questions': questions})






# Admin Dashboard Starts Here ------------------------------------------------------------------------------------#

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.db.models import Sum, Q
from django.urls import reverse
from registration.models import (
    Participant,
    PaymentStatus,
    Event,
    AbstractSubmission,
    ProgramSchedule,
    CorporateAccountRequest,
    CorporateEventRegistration,
    CorporateEventAttendee,
    CorporatePayment,
)
from django.core.paginator import Paginator
from urllib.parse import urlencode
from collections import Counter, defaultdict


UNPAID_PAYMENT_STATUSES = ['unpaid', 'pending', 'failed', 'initiated']
PAID_PAYMENT_STATUSES = ['paid', 'completed']


def admin_changelist_url(model, query_params=None):
    opts = model._meta
    url = reverse(f'admin:{opts.app_label}_{opts.model_name}_changelist')
    if query_params:
        return f'{url}?{urlencode(query_params, doseq=True)}'
    return url


def admin_change_url(obj):
    opts = obj._meta
    return reverse(f'admin:{opts.app_label}_{opts.model_name}_change', args=[obj.pk])


def build_event_metrics_chart_data(event_metrics):
    return {
        'labels': [metric['name'] for metric in event_metrics],
        'approved': [metric['approved_participants'] for metric in event_metrics],
        'pending_payments': [metric['pending_payments'] for metric in event_metrics],
        'revenue': [float(metric['revenue_collected']) for metric in event_metrics],
    }


def build_event_metrics(events, event_filter=None):
    event_metrics = []
    for event in events:
        if event_filter and str(event.id) != event_filter:  # type: ignore[attr-defined]
            continue
        metrics = {
            'name': event.name,
            'approved_participants': Participant.objects.filter(event=event).count(),
            'pending_payments': PaymentStatus.objects.filter(
                event=event, status__in=UNPAID_PAYMENT_STATUSES
            ).count(),
            'revenue_collected': PaymentStatus.objects.filter(
                event=event, status__in=PAID_PAYMENT_STATUSES
            ).aggregate(total=Sum('amount'))['total'] or 0,
        }
        event_metrics.append(metrics)
    return event_metrics


def get_dashboard_scoped_events(events, event_filter=None):
    scoped_events = events
    if event_filter:
        scoped_events = scoped_events.filter(id=event_filter)
    return scoped_events


QUEUE_TYPE_CHOICES = [
    ('all', 'All'),
    ('participants', 'Participants'),
    ('payments', 'Payments'),
    ('corporate', 'Corporate'),
    ('members', 'Members'),
    ('abstracts', 'Abstracts'),
]


def build_attention_queue(events, event_filter=None, page_number=None, queue_type='all', per_page=8):
    from website.models import Member

    if queue_type not in {choice[0] for choice in QUEUE_TYPE_CHOICES}:
        queue_type = 'all'

    scoped_events = get_dashboard_scoped_events(events, event_filter)
    event_ids = list(scoped_events.values_list('id', flat=True))
    event_scope = {'event_id__in': event_ids}
    event_filter_query = {}
    if event_filter:
        event_filter_query['event__id__exact'] = event_filter
    entries = []

    if queue_type in ('all', 'participants'):
        participant_workflow_url = admin_changelist_url(Participant, {
            **event_filter_query,
            'approved__exact': '0',
            'denied__exact': '0',
        })
        pending_participants = Participant.objects.filter(
            **event_scope,
            approved=False,
            denied=False,
        ).select_related('event').order_by('-created_at')
        entries.extend([
            {
                'label': 'Participant',
                'title': f'{item.name} - {item.event.name}',
                'meta': item.email,
                'status': 'Pending approval',
                'url': participant_workflow_url,
                'detail_url': admin_change_url(item),
                'sort_date': item.created_at,
            }
            for item in pending_participants
        ])

    if queue_type in ('all', 'payments'):
        approved_unpaid_payments = PaymentStatus.objects.filter(
            **event_scope,
            participant__approved=True,
            status__in=UNPAID_PAYMENT_STATUSES,
        ).select_related('event', 'participant').order_by('-updated_at')
        entries.extend([
            {
                'label': 'Payment',
                'title': f'{item.participant.name} - {item.event.name}',
                'meta': f'BDT {item.amount or 0}',
                'status': item.get_status_display(),
                'url': admin_changelist_url(PaymentStatus, {
                    **event_filter_query,
                    'status__exact': item.status,
                }),
                'detail_url': admin_change_url(item),
                'sort_date': item.updated_at,
            }
            for item in approved_unpaid_payments
        ])

    if queue_type in ('all', 'corporate'):
        pending_corporate_attendees = CorporateEventAttendee.objects.filter(
            registration__event_id__in=event_ids,
            review_status='pending',
        ).select_related('registration__event', 'registration__corporate_account').order_by('-created_at')
        corporate_attendee_workflow_url = admin_changelist_url(CorporateEventAttendee, {
            'registration__event__id__exact': event_filter,
            'review_status__exact': 'pending',
        } if event_filter else {'review_status__exact': 'pending'})
        entries.extend([
            {
                'label': 'Corporate',
                'title': f'{item.name} - {item.registration.event.name}',
                'meta': item.registration.corporate_account.company_name,
                'status': item.get_review_status_display(),
                'url': corporate_attendee_workflow_url,
                'detail_url': admin_change_url(item),
                'sort_date': item.created_at,
            }
            for item in pending_corporate_attendees
        ])

    if queue_type in ('all', 'abstracts'):
        abstract_workflow_url = admin_changelist_url(AbstractSubmission, event_filter_query)
        pending_abstracts = AbstractSubmission.objects.filter(
            event_id__in=event_ids,
            approved_for_presentation=False,
            approved_for_poster=False,
        ).select_related('event', 'user').order_by('-updated_at')
        entries.extend([
            {
                'label': 'Abstract',
                'title': f'{item.title} - {item.event.name}',
                'meta': item.user.email,
                'status': 'Needs review',
                'url': abstract_workflow_url,
                'detail_url': admin_change_url(item),
                'sort_date': item.updated_at,
            }
            for item in pending_abstracts
        ])

    if queue_type in ('all', 'members'):
        if event_filter:
            pending_members = Member.objects.filter(
                user_profile__pending_event_intents__event_id__in=event_ids,
                user_profile__pending_event_intents__status='pending',
                approval_status='pending',
            ).select_related('user_profile').distinct().order_by('-created_at')
        else:
            pending_members = Member.objects.filter(
                approval_status='pending'
            ).select_related('user_profile').order_by('-created_at')
        member_workflow_url = admin_changelist_url(Member, {'approval_status__exact': 'pending'})
        entries.extend([
            {
                'label': 'Member',
                'title': item.user_profile.name,
                'meta': item.user_profile.email,
                'status': item.get_approval_status_display(),
                'url': member_workflow_url,
                'detail_url': admin_change_url(item),
                'sort_date': item.created_at,
            }
            for item in pending_members
        ])

    if queue_type in ('all', 'corporate') and not event_filter:
        corporate_access_workflow_url = admin_changelist_url(CorporateAccountRequest, {'status__exact': 'pending'})
        pending_corporate_requests = CorporateAccountRequest.objects.filter(status='pending').order_by('-created_at')
        entries.extend([
            {
                'label': 'Corporate access',
                'title': item.company_name,
                'meta': f'{item.contact_name} - {item.email}',
                'status': item.get_status_display(),
                'url': corporate_access_workflow_url,
                'detail_url': admin_change_url(item),
                'sort_date': item.created_at,
            }
            for item in pending_corporate_requests
        ])

    entries.sort(key=lambda item: item['sort_date'], reverse=True)
    return Paginator(entries, per_page).get_page(page_number), queue_type


def build_dashboard_operations(events, event_filter=None, event_status_filter=None, queue_page_number=None, queue_type='all'):
    from website.models import Member, MembershipPayment, SiteSettings, MembershipBenefitModal

    scoped_events = get_dashboard_scoped_events(events, event_filter)

    event_ids = list(scoped_events.values_list('id', flat=True))
    event_scope = {'event_id__in': event_ids}
    event_filter_query = {}
    if event_filter:
        event_filter_query['event__id__exact'] = event_filter

    pending_participants = Participant.objects.filter(
        **event_scope,
        approved=False,
        denied=False,
    ).select_related('event').order_by('-created_at')

    approved_unpaid_payments = PaymentStatus.objects.filter(
        **event_scope,
        participant__approved=True,
        status__in=UNPAID_PAYMENT_STATUSES,
    ).select_related('event', 'participant').order_by('-updated_at')

    pending_corporate_requests = CorporateAccountRequest.objects.filter(status='pending').order_by('-created_at')
    corporate_access_request_count = 0 if event_filter else pending_corporate_requests.count()
    pending_corporate_attendees = CorporateEventAttendee.objects.filter(
        registration__event_id__in=event_ids,
        review_status='pending',
    ).select_related('registration__event', 'registration__corporate_account').order_by('-created_at')
    pending_corporate_registrations = CorporateEventRegistration.objects.filter(
        event_id__in=event_ids,
        status__in=['submitted', 'under_review'],
    ).select_related('event', 'corporate_account').order_by('-created_at')
    unpaid_corporate_payments = CorporatePayment.objects.filter(
        event_id__in=event_ids,
        status__in=UNPAID_PAYMENT_STATUSES,
    ).select_related('event', 'corporate_account').order_by('-created_at')

    pending_abstracts = AbstractSubmission.objects.filter(
        event_id__in=event_ids,
        approved_for_presentation=False,
        approved_for_poster=False,
    ).select_related('event', 'user').order_by('-updated_at')

    pending_members = Member.objects.filter(approval_status='pending').select_related('user_profile').order_by('-created_at')
    pending_event_members = Member.objects.filter(
        user_profile__pending_event_intents__event_id__in=event_ids,
        user_profile__pending_event_intents__status='pending',
        approval_status='pending',
    ).select_related('user_profile').distinct().order_by('-created_at')
    pending_membership_payments = MembershipPayment.objects.filter(
        status__in=['initiated', 'pending', 'failed']
    ).select_related('user_profile', 'membership_type').order_by('-updated_at')
    if event_filter:
        pending_membership_payment_count = MembershipPayment.objects.filter(
            user_profile__pending_event_intents__event_id__in=event_ids,
            user_profile__pending_event_intents__status='pending',
            status__in=['initiated', 'pending', 'failed'],
        ).distinct().count()
    else:
        pending_membership_payment_count = pending_membership_payments.count()

    open_events = scoped_events.filter(
        Q(event_status='active') | Q(registration='Open')
    ).order_by('start_date')

    event_health = []
    for event in open_events[:8]:
        approved_count = Participant.objects.filter(event=event, approved=True).count()
        pending_count = Participant.objects.filter(event=event, approved=False, denied=False).count()
        unpaid_count = PaymentStatus.objects.filter(
            event=event,
            participant__approved=True,
            status__in=UNPAID_PAYMENT_STATUSES,
        ).count()
        warnings = []
        if event.registration == 'Open' and event.event_status == 'closed':
            warnings.append('Registration open while event is closed')
        if event.payment_required and not event.amount:
            warnings.append('Payment required but regular fee is empty')
        if event.member_registration_enabled and event.member_registration_fee is None:
            warnings.append('Member fee not set, treated as free')
        if event.registration_audience == 'members_only' and not event.member_registration_enabled:
            warnings.append('Members-only event without member flow enabled')

        event_health.append({
            'event': event,
            'approved_count': approved_count,
            'pending_count': pending_count,
            'unpaid_count': unpaid_count,
            'warnings': warnings,
            'admin_url': admin_change_url(event),
        })

    action_cards = [
        {
            'label': 'Participant approvals',
            'count': pending_participants.count(),
            'tone': 'warning',
            'description': 'Individual event registrations waiting for admin approval.',
            'url': admin_changelist_url(Participant, {
                **event_filter_query,
                'approved__exact': '0',
                'denied__exact': '0',
            }),
        },
        {
            'label': 'Approved but unpaid',
            'count': approved_unpaid_payments.count(),
            'tone': 'danger',
            'description': 'Approved participants who still need payment completion.',
            'url': admin_changelist_url(PaymentStatus, {
                **event_filter_query,
                'status__in': UNPAID_PAYMENT_STATUSES,
            }),
        },
        {
            'label': 'Corporate review',
            'count': pending_corporate_attendees.count() + corporate_access_request_count,
            'tone': 'primary',
            'description': 'Corporate access requests and attendee rows waiting for review.' if not event_filter else 'Corporate attendee rows waiting for review for this event.',
            'url': admin_changelist_url(CorporateEventAttendee, {
                'registration__event__id__exact': event_filter,
                'review_status__exact': 'pending',
            } if event_filter else {'review_status__exact': 'pending'}),
        },
        {
            'label': 'Membership approvals',
            'count': pending_event_members.count() if event_filter else pending_members.count(),
            'tone': 'success',
            'description': 'Membership applications waiting for approval or rejection.' if not event_filter else 'Membership applications tied to this event through member-event intent.',
            'url': admin_changelist_url(Member, {'approval_status__exact': 'pending'}),
        },
        {
            'label': 'Abstract review',
            'count': pending_abstracts.count(),
            'tone': 'info',
            'description': 'Abstracts not yet marked for oral or poster presentation.',
            'url': admin_changelist_url(AbstractSubmission, event_filter_query),
        },
        {
            'label': 'Corporate invoices',
            'count': unpaid_corporate_payments.count(),
            'tone': 'secondary',
            'description': 'Corporate invoices not marked paid or completed.',
            'url': admin_changelist_url(CorporatePayment, {
                'event__id__exact': event_filter,
                'status__in': UNPAID_PAYMENT_STATUSES,
            } if event_filter else {'status__in': UNPAID_PAYMENT_STATUSES}),
        },
    ]

    return {
        'action_cards': action_cards,
        'event_health': event_health,
        'queue_page_obj': build_attention_queue(events, event_filter, queue_page_number, queue_type)[0],
        'queue_type': queue_type,
        'queue_type_choices': QUEUE_TYPE_CHOICES,
        'pending_corporate_registrations_count': pending_corporate_registrations.count(),
        'pending_membership_payments_count': pending_membership_payment_count,
        'is_event_filtered': bool(event_filter),
        'admin_links': {
            'create_event': reverse('admin:registration_event_add'),
            'create_bulk_email': reverse('admin:registration_bulkemail_add'),
            'program_schedules': admin_changelist_url(ProgramSchedule),
            'site_settings': admin_changelist_url(SiteSettings),
            'membership_benefits': admin_changelist_url(MembershipBenefitModal),
            'participants': admin_changelist_url(Participant),
            'payments': admin_changelist_url(PaymentStatus),
            'corporate_registrations': admin_changelist_url(CorporateEventRegistration),
            'corporate_attendees': admin_changelist_url(CorporateEventAttendee),
            'corporate_payments': admin_changelist_url(CorporatePayment),
            'membership': admin_changelist_url(Member),
            'membership_payments': admin_changelist_url(MembershipPayment),
            'abstracts': admin_changelist_url(AbstractSubmission),
            'events': admin_changelist_url(Event),
        },
    }


@staff_member_required
def global_dashboard(request):
    from website.models import SiteSettings

    event_filter = request.GET.get('event')
    event_status_filter = request.GET.get('event_status')
    page_number = request.GET.get('page')
    event_page_number = request.GET.get('event_page')
    org_page_number = request.GET.get('org_page')
    queue_page_number = request.GET.get('queue_page')
    queue_type = request.GET.get('queue_type', 'all')

    events = Event.objects.all()
    if event_status_filter:
        events = events.filter(event_status=event_status_filter)
    operations = build_dashboard_operations(events, event_filter, event_status_filter, queue_page_number, queue_type)

    event_metrics = build_event_metrics(events, event_filter)

    event_paginator = Paginator(event_metrics, 8)
    event_page_obj = event_paginator.get_page(event_page_number)

    totals = {
        'participants': sum(m['approved_participants'] for m in event_metrics),
        'pending_payments': sum(m['pending_payments'] for m in event_metrics),
        'revenue': sum(m['revenue_collected'] for m in event_metrics)
    }
    scoped_events = get_dashboard_scoped_events(events, event_filter)
    scoped_event_ids = scoped_events.values_list('id', flat=True)
    scoped_participants = Participant.objects.filter(event_id__in=scoped_event_ids)
    totals.update({
        'unique_participants': scoped_participants.values('email').distinct().count(),
        'member_participants': scoped_participants.filter(registration_type='member').count(),
        'regular_participants': scoped_participants.exclude(registration_type='member').count(),
    })

    participant_summary, participant_totals, participant_chart_data, organization_page_obj, organization_chart_data = get_participant_summary(request, org_page_number)

    paginator = Paginator(participant_summary, 10)
    page_obj = paginator.get_page(page_number)

    query_params = {}
    if event_filter: query_params['event'] = event_filter
    if event_status_filter: query_params['event_status'] = event_status_filter
    query_string = urlencode(query_params)

    context = {
        'site_settings': SiteSettings.objects.first(),
        'all_events': Event.objects.all(),
        'event_page_obj': event_page_obj,
        'totals': totals,
        'page_obj': page_obj,
        'participant_totals': participant_totals,
        'organization_page_obj': organization_page_obj,
        'dashboard_chart_data': {
            'event_metrics': build_event_metrics_chart_data(event_metrics),
            'participant_status': participant_chart_data,
            'organizations': organization_chart_data,
        },
        'operations': operations,
        'current_filters': {
            'event': event_filter,
            'event_status': event_status_filter
        },
        'query_string': query_string,
        'event_query_string': query_string,
        'participant_query_string': query_string,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'partials/dashboard_content.html', context)
    return render(request, 'dashboard.html', context)


@staff_member_required
def dashboard_event_ledger(request):
    event_filter = request.GET.get('event')
    event_status_filter = request.GET.get('event_status')
    event_page_number = request.GET.get('event_page')

    events = Event.objects.all()
    if event_status_filter:
        events = events.filter(event_status=event_status_filter)

    query_params = {}
    if event_filter:
        query_params['event'] = event_filter
    if event_status_filter:
        query_params['event_status'] = event_status_filter

    event_page_obj = Paginator(build_event_metrics(events, event_filter), 8).get_page(event_page_number)
    return render(request, 'partials/dashboard_event_ledger.html', {
        'event_page_obj': event_page_obj,
        'event_query_string': urlencode(query_params),
    })


@staff_member_required
def dashboard_participant_preview(request):
    event_filter = request.GET.get('event')
    event_status_filter = request.GET.get('event_status')
    page_number = request.GET.get('page')

    query_params = {}
    if event_filter:
        query_params['event'] = event_filter
    if event_status_filter:
        query_params['event_status'] = event_status_filter

    participant_summary, _, _, _, _ = get_participant_summary(request)
    page_obj = Paginator(participant_summary, 10).get_page(page_number)
    return render(request, 'partials/dashboard_participant_preview.html', {
        'page_obj': page_obj,
        'participant_query_string': urlencode(query_params),
    })


@staff_member_required
def dashboard_attention_queue(request):
    event_filter = request.GET.get('event')
    event_status_filter = request.GET.get('event_status')
    queue_page_number = request.GET.get('queue_page')
    queue_type = request.GET.get('queue_type', 'all')

    events = Event.objects.all()
    if event_status_filter:
        events = events.filter(event_status=event_status_filter)

    query_params = {}
    if event_filter:
        query_params['event'] = event_filter
    if event_status_filter:
        query_params['event_status'] = event_status_filter
    queue_filter_query_string = urlencode(query_params)
    if queue_type:
        query_params['queue_type'] = queue_type

    queue_page_obj, normalized_queue_type = build_attention_queue(events, event_filter, queue_page_number, queue_type)

    context = {
        'queue_page_obj': queue_page_obj,
        'queue_type': normalized_queue_type,
        'queue_type_choices': QUEUE_TYPE_CHOICES,
        'queue_query_string': urlencode(query_params),
        'queue_filter_query_string': queue_filter_query_string,
    }
    return render(request, 'partials/dashboard_attention_queue.html', context)


def get_participant_summary(request, org_page_number=None):
    event_filter = request.GET.get('event')
    event_status_filter = request.GET.get('event_status')

    events = Event.objects.all()
    if event_status_filter:
        events = events.filter(event_status=event_status_filter)
    if event_filter:
        events = events.filter(id=event_filter)

    if not events.exists():
        return [], {}, {'labels': [], 'approved': [], 'denied': [], 'pending': []}, [], {'labels': [], 'counts': []}

    event_ids = events.values_list('id', flat=True)

    participant_rows = list(Participant.objects.filter(event_id__in=event_ids).values(
        'name', 'email', 'approved', 'denied', 'event__name', 'country', 'organization'
    ))
    if not participant_rows:
        return [], {}, {'labels': [], 'approved': [], 'denied': [], 'pending': []}, [], {'labels': [], 'counts': []}

    participant_summary = []
    organization_counts = Counter()
    status_by_event = defaultdict(lambda: {'approved': 0, 'denied': 0, 'pending': 0})
    totals = {
        'total_participants': 0,
        'approved_participants': 0,
        'denied_participants': 0,
        'pending_participants': 0,
        'local_participants': 0,
        'foreign_participants': 0,
    }

    for participant in participant_rows:
        event_name = participant.get('event__name') or 'Untitled event'
        organization = (participant.get('organization') or 'Not specified').strip() or 'Not specified'
        country = participant.get('country') or ''
        approved = bool(participant.get('approved'))
        denied = bool(participant.get('denied'))

        participant_summary.append({
            'name': participant.get('name') or '',
            'email': participant.get('email') or '',
            'approved': approved,
            'denied': denied,
            'event_name': event_name,
            'country': country,
            'organization': organization,
        })

        totals['total_participants'] += 1
        organization_counts[organization] += 1

        if approved:
            totals['approved_participants'] += 1
            status_by_event[event_name]['approved'] += 1
        elif denied:
            totals['denied_participants'] += 1
            status_by_event[event_name]['denied'] += 1
        else:
            totals['pending_participants'] += 1
            status_by_event[event_name]['pending'] += 1

        if 'bangladesh' in country.lower():
            totals['local_participants'] += 1
        else:
            totals['foreign_participants'] += 1

    organization_summary = [
        {'organization': organization, 'participant_count': count}
        for organization, count in organization_counts.most_common()
    ]
    organization_paginator = Paginator(organization_summary, 10)
    organization_page_obj = organization_paginator.get_page(org_page_number)

    participant_chart_data = {
        'labels': list(status_by_event.keys()),
        'approved': [counts['approved'] for counts in status_by_event.values()],
        'denied': [counts['denied'] for counts in status_by_event.values()],
        'pending': [counts['pending'] for counts in status_by_event.values()],
    }
    organization_chart_data = {
        'labels': [item['organization'] for item in organization_summary[:15]],
        'counts': [item['participant_count'] for item in organization_summary[:15]],
    }

    return participant_summary, totals, participant_chart_data, organization_page_obj, organization_chart_data
