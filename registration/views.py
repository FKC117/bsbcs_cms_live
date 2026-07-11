# pyrefly: ignore [missing-import]
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from .dashboard_permissions import (
    dashboard_permission_required,
    user_can_access_dashboard_area,
)
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.urls import NoReverseMatch, reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.text import slugify
from .forms import (
    RegistrationForm,
    AbstractSubmissionForm,
    UserProfileForm,
    CorporateAccountRequestForm,
    ProgramSessionBuilderForm,
    ProgramSessionItemBuilderFormSet,
    ProgramDayQuickCreateForm,
    HallRoomQuickCreateForm,
    TimeSlotQuickCreateForm,
    TimeSlotGeneratorForm,
    GeneratedTimeSlotPreviewFormSet,
    ProgramPersonQuickCreateForm,
    DashboardEventForm,
    DashboardAbstractSubmissionForm,
    DashboardParticipantCreateForm,
    COUNTRY_NAME_CHOICES,
    COUNTRY_NAME_REQUIRED_CHOICES,
    DEFAULT_COUNTRY,
    normalize_country_name,
    normalize_phone_number,
)
from .models import *
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
import time
import json
import logging
import csv
import io
import os
import re
import zipfile
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from datetime import datetime, timedelta
from django.http import FileResponse, HttpResponse, Http404
from django.utils import timezone
from django.db import transaction
from .program_emails import (
    build_program_assignment_summary,
    count_program_assignment_talks,
    send_program_assignment_email,
)
from .bulk_email_services import (
    prepare_bulk_email_recipients,
    sync_bulk_email_status,
    upsert_bulk_email_recipient,
)
from .bulk_sms_services import (
    prepare_bulk_sms_recipients,
    sync_bulk_sms_status,
    upsert_bulk_sms_recipient,
)
from .email_audit import get_email_quota_snapshot, plan_bulk_email_send
from .tasks import (
    participant_email_log_table_ready,
    speaker_certificate_email_log_table_ready,
    thank_you_email_log_table_ready,
    send_email_task,
    send_sms_task,
    send_manual_participant_account_email,
    send_participant_approval_email,
    send_thank_you_email_task,
    send_speaker_certificate_email,
    send_speaker_outreach_email_task,
    send_pending_bulk_email_campaign,
    send_pending_bulk_sms_campaign,
)
from .pdf_utils import generate_abstract_pdf, generate_event_report_pdf, generate_invoice
from .sms import (
    estimate_sms_units,
    get_system_sms_content,
    get_sms_segment_char_limit,
    query_sms_balance,
    query_sms_multi_status,
    query_sms_status,
    queue_registration_payment_received_sms,
    resolve_sms_caller_id,
    resolve_sms_url,
)


# Payment logger (writes to payment.log via settings)
logger = logging.getLogger('payment')
speaker_certificate_logger = logging.getLogger('speaker_certificate')


def _humanize_provider_key(key):
    return str(key).replace('_', ' ').replace('-', ' ').strip().title()


def _provider_row_dicts(response):
    if isinstance(response, list):
        return [row for row in response if isinstance(row, dict)]
    if isinstance(response, dict):
        for key in ('Data', 'data', 'Rows', 'rows', 'Result', 'result'):
            value = response.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _status_note_from_text(text):
    normalized = (text or '').strip().upper()
    if normalized == 'ACCEPTD':
        return 'Gateway accepted the SMS for processing. This is not final delivery confirmation yet.'
    if normalized:
        return f'Provider returned status text: {text}.'
    return ''


def _build_provider_result_summary(result, *, kind):
    if not result:
        return None

    response = result.get('response') if isinstance(result, dict) else None
    provider_status = result.get('provider_status') if isinstance(result, dict) else None
    http_status = result.get('http_status') if isinstance(result, dict) else None
    summary = {
        'kind': kind,
        'ok': result.get('status') in {'ok', 'sent'} if isinstance(result, dict) else False,
        'headline': 'No provider response available.',
        'subheadline': '',
        'details': [],
        'note': '',
        'rows': [],
        'raw_pretty': json.dumps(result, indent=2, ensure_ascii=True, default=str),
    }

    if kind == 'balance' and isinstance(response, dict):
        balance = response.get('Balance')
        credit_limit = response.get('CreditLimit')
        summary['headline'] = f"Balance: {balance if balance is not None else '-'}"
        summary['subheadline'] = f"Credit limit: {credit_limit if credit_limit is not None else '-'}"
        summary['details'] = [
            f"HTTP status: {http_status}",
            f"Balance API status: {'success' if summary['ok'] else 'failed'}",
        ]
        return summary

    if kind == 'status' and isinstance(response, dict):
        status_text = response.get('Text') or ''
        summary['headline'] = status_text or f"Provider status: {provider_status or '-'}"
        summary['subheadline'] = f"Message ID: {response.get('Message_ID') or response.get('messageid') or '-'}"
        summary['details'] = [
            f"HTTP status: {http_status}",
            f"Provider status: {provider_status if provider_status is not None else '-'}",
        ]
        summary['note'] = _status_note_from_text(status_text)
        return summary

    if kind == 'multi_status':
        raw_rows = _provider_row_dicts(response)
        rows = []
        for row in raw_rows:
            rows.append({
                'message_id': row.get('Message_ID') or row.get('messageid') or row.get('MessageId') or '-',
                'status_text': row.get('Text') or row.get('text') or row.get('Status') or row.get('status') or '-',
                'detail_text': row.get('Description') or row.get('description') or row.get('OperatorStatus') or row.get('operatorStatus') or row.get('Delivery Time') or row.get('deliveryTime') or '-',
            })
        summary['rows'] = rows
        summary['headline'] = 'Campaign status lookup completed.' if summary['ok'] else 'Campaign status lookup failed.'
        if rows:
            summary['subheadline'] = f"Provider returned {len(rows)} status row(s)."
        elif isinstance(response, dict):
            summary['subheadline'] = response.get('Text') or response.get('Status') or ''
        elif isinstance(response, list):
            summary['subheadline'] = f"Provider returned {len(response)} raw row(s)."
        summary['details'] = [
            f"HTTP status: {http_status}",
            f"Provider status: {provider_status if provider_status is not None else '-'}",
        ]
        for row in raw_rows:
            text_value = row.get('Text') or row.get('text') or row.get('StatusText') or row.get('statusText') or row.get('Status') or row.get('status') or ''
            if text_value:
                summary['note'] = _status_note_from_text(text_value)
                if summary['note']:
                    break
        return summary

    summary['details'] = [
        f"HTTP status: {http_status}",
        f"Provider status: {provider_status if provider_status is not None else '-'}",
    ]
    return summary


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
    certificate_kind = (request.GET.get('kind') or 'participant').strip().lower()

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

    template_name = 'certificate_design/speaker_certificate.html' if certificate_kind == 'speaker' else 'certificate_design/certificate.html'
    context = {
        'participant_name': request.GET.get('name', 'Dr. Sample Participant'),
        'site_settings': site_settings,
        'event': event,
        'certificate': certificate,
        'signatories': signatories,
        'signature_count': len(signatories),
    }
    if certificate_kind == 'speaker':
        context.update({
            'speaker_title': _speaker_certificate_title(certificate),
            'speaker_body': _render_speaker_certificate_body(certificate, event),
        })
    return render(request, template_name, context)


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


SYNTHETIC_PARTICIPANT_DEPARTMENTS = {'BSBCS Member', 'Corporate Registration', 'Corporate registration'}
SYNTHETIC_PARTICIPANT_ORGANIZATIONS = {'BSBCS Member', 'Corporate Registration', 'Corporate registration'}


def clean_public_participant_value(value, synthetic_values=None):
    value = (value or '').strip()
    if not value:
        return ''
    if value in {'N/A', 'Not provided', 'Not specified'}:
        return ''
    if synthetic_values and value in synthetic_values:
        return ''
    return value


def get_or_create_participant_department(event, department_name=None):
    department_name = (department_name or '').strip()[:50] or 'Not specified'
    department, _ = Department.objects.get_or_create(event=event, name=department_name)
    return department


def get_previous_participant_department_name(email, current_event=None):
    if not email:
        return ''
    previous_participants = Participant.objects.filter(
        email__iexact=email,
        department__isnull=False,
    ).select_related('department').order_by('-created_at')
    if current_event:
        previous_participants = previous_participants.exclude(event=current_event)
    for participant in previous_participants:
        department_name = participant.department.name if participant.department_id else ''
        if department_name and department_name not in SYNTHETIC_PARTICIPANT_DEPARTMENTS:
            return department_name
    return ''


def get_previous_participant_organization(email, current_event=None):
    if not email:
        return ''
    previous_participants = Participant.objects.filter(
        email__iexact=email,
    ).order_by('-created_at')
    if current_event:
        previous_participants = previous_participants.exclude(event=current_event)
    for participant in previous_participants:
        organization = clean_public_participant_value(
            participant.organization,
            SYNTHETIC_PARTICIPANT_ORGANIZATIONS,
        )
        if organization:
            return organization
    return ''


def get_participant_member(participant):
    try:
        user_profile = participant.user.userprofile
        return getattr(user_profile, 'member', None)
    except (AttributeError, UserProfile.DoesNotExist):
        pass

    if not participant.email:
        return None
    user_profile = UserProfile.objects.filter(email__iexact=participant.email).first()
    return getattr(user_profile, 'member', None) if user_profile else None


def resolve_public_participant_department(participant):
    department_name = participant.department.name if participant.department_id else ''
    public_department = clean_public_participant_value(department_name, SYNTHETIC_PARTICIPANT_DEPARTMENTS)
    if public_department:
        return public_department

    corporate_attendee = getattr(participant, 'corporate_attendee', None)
    corporate_department = clean_public_participant_value(getattr(corporate_attendee, 'department', ''))
    if corporate_department:
        return corporate_department

    previous_department = get_previous_participant_department_name(participant.email, participant.event)
    if previous_department:
        return previous_department

    member = get_participant_member(participant)
    if member:
        first_specialty = member.specialties.first()
        if first_specialty:
            return first_specialty.name

    return 'Not specified'


def resolve_public_participant_organization(participant):
    organization = clean_public_participant_value(
        participant.organization,
        SYNTHETIC_PARTICIPANT_ORGANIZATIONS,
    )
    if organization:
        return organization

    corporate_attendee = getattr(participant, 'corporate_attendee', None)
    corporate_organization = clean_public_participant_value(getattr(corporate_attendee, 'organization', ''))
    if corporate_organization:
        return corporate_organization

    member = get_participant_member(participant)
    member_institution = clean_public_participant_value(getattr(member, 'institution', ''))
    if member_institution:
        return member_institution

    previous_organization = get_previous_participant_organization(participant.email, participant.event)
    if previous_organization:
        return previous_organization

    return 'Not specified'


def resolve_public_participant_designation(participant):
    corporate_attendee = getattr(participant, 'corporate_attendee', None)
    corporate_designation = clean_public_participant_value(getattr(corporate_attendee, 'designation', ''))
    if corporate_designation:
        return corporate_designation

    member = get_participant_member(participant)
    member_position = clean_public_participant_value(getattr(member, 'position', ''))
    if member_position:
        return member_position

    return 'N/A'


def apply_public_participant_display(participant):
    participant.display_department = resolve_public_participant_department(participant)
    participant.display_organization = resolve_public_participant_organization(participant)
    participant.display_designation = resolve_public_participant_designation(participant)
    return participant


def build_public_participant_list_context(request, event):
    search_query = (request.GET.get('q') or '').strip()
    participants = (
        Participant.objects
        .filter(event=event, approved=True, payment_statuses__status='completed')
        .select_related('department', 'corporate_attendee', 'user__userprofile', 'user__userprofile__member')
    )
    if search_query:
        participants = participants.filter(
            Q(name__icontains=search_query)
            | Q(degree__icontains=search_query)
            | Q(organization__icontains=search_query)
            | Q(country__icontains=search_query)
            | Q(department__name__icontains=search_query)
            | Q(corporate_attendee__designation__icontains=search_query)
            | Q(corporate_attendee__department__icontains=search_query)
            | Q(corporate_attendee__organization__icontains=search_query)
        ).distinct()

    page_obj = Paginator(participants, 12).get_page(request.GET.get('page'))
    for participant in page_obj.object_list:
        apply_public_participant_display(participant)

    query_params = request.GET.copy()
    query_params.pop('page', None)

    return {
        'event': event,
        'page_obj': page_obj,
        'search_query': search_query,
        'query_string': query_params.urlencode(),
    }


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

        corporate_account = CorporateAccount.objects.filter(user=request.user).first()
        is_corporate = corporate_account is not None

        if request.method == 'POST':
            name = (request.POST.get('name') or '').strip()
            email = (request.POST.get('email') or request.user.email or request.user.username or '').strip()
            phone = (request.POST.get('phone') or '').strip()
            country = normalize_country_name(request.POST.get('country'))

            if not name or not email or not phone or not country:
                messages.error(request, "Please complete all profile fields.")
            else:
                try:
                    phone = normalize_phone_number(phone, country)
                except ValidationError as exc:
                    messages.error(request, exc.messages[0])
                    phone = ''

            if not name or not email or not phone or not country:
                pass
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
                if is_corporate:
                    company_logo = request.FILES.get('company_logo')
                    if company_logo:
                        corporate_account.company_logo = company_logo
                        corporate_account.save(update_fields=['company_logo', 'updated_at'])

                messages.success(request, "Your personal BSBCS profile has been created.")
                return redirect(next_url or 'user_profile')

        form = UserProfileForm(initial={
            'name': request.user.get_full_name() or request.user.first_name,
            'email': request.user.email or request.user.username,
            'country': DEFAULT_COUNTRY,
        })
        return render(request, 'create_profile.html', {
            'form': form,
            'next_url': next_url,
            'completing_existing_profile': True,
            'is_corporate': is_corporate,
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
from .models import UserProfile, AbstractSubmission, ProgramSchedule, Event, CorporateAccount, PresentationUpload
from django.db.models import Q
from website.models import SiteSettings, MembershipBenefitModal, MembershipPayment, PendingEventIntent


def _safe_presentation_filename(*parts):
    raw_name = '_'.join(str(part or '').strip() for part in parts if str(part or '').strip())
    safe_name = ''.join(ch if ch.isalnum() or ch in (' ', '-', '_', '.') else '_' for ch in raw_name).strip()
    return safe_name.replace(' ', '_') or 'presentation'


def _user_program_people(user, user_profile):
    identifiers = Q()
    if user_profile:
        identifiers |= Q(profile=user_profile)
        if user_profile.email:
            identifiers |= Q(email__iexact=user_profile.email)
    if user.email:
        identifiers |= Q(email__iexact=user.email)
    if not identifiers:
        return ProgramPerson.objects.none()
    return ProgramPerson.objects.filter(identifiers).distinct()


def _latest_presentation_upload_map(user):
    uploads = (
        PresentationUpload.objects.filter(user=user)
        .select_related('event', 'abstract_submission', 'session', 'session_item', 'program_person')
        .order_by('-uploaded_at')
    )
    latest = {}
    for upload in uploads:
        if upload.abstract_submission_id:
            latest.setdefault(('abstract', upload.abstract_submission_id), upload)
        if upload.session_item_id:
            latest.setdefault(('session_item', upload.session_item_id), upload)
        elif upload.session_id:
            latest.setdefault(('session', upload.session_id), upload)
    return latest


def _build_user_presentation_assignments(user, user_profile, abstract_submissions):
    latest_uploads = _latest_presentation_upload_map(user)
    assignments = []

    for abstract in abstract_submissions.select_related('event').order_by('-updated_at'):
        latest = latest_uploads.get(('abstract', abstract.id))
        assignments.append({
            'assignment_type': 'abstract',
            'assignment_id': abstract.id,
            'event': abstract.event,
            'title': abstract.title,
            'role': 'Abstract presenter',
            'time_label': 'Scheduled after abstract review',
            'status_label': 'Presentation' if abstract.approved_for_presentation else ('Poster' if abstract.approved_for_poster else 'Submitted'),
            'file': latest.file if latest else abstract.presentation_file,
            'uploaded_at': latest.uploaded_at if latest else None,
        })

    program_people = list(_user_program_people(user, user_profile))
    if program_people:
        person_ids = [person.id for person in program_people]
        item_roles = (
            ProgramItemFaculty.objects.filter(person_id__in=person_ids)
            .select_related(
                'person',
                'item',
                'item__session',
                'item__session__event',
                'item__session__program_day',
                'item__session__hall_room',
            )
            .order_by('item__session__event__start_date', 'item__session__start_time', 'item__order')
        )
        seen_items = set()
        for role in item_roles:
            item = role.item
            if item.id in seen_items:
                continue
            seen_items.add(item.id)
            session = item.session
            latest = latest_uploads.get(('session_item', item.id))
            assignments.append({
                'assignment_type': 'session_item',
                'assignment_id': item.id,
                'event': session.event,
                'title': item.display_title,
                'role': 'Program talk / activity',
                'time_label': (
                    f"{session.program_day.name if session.program_day else 'Day'} · "
                    f"{session.hall_room.name if session.hall_room else 'Room'} · "
                    f"{item.start_time.strftime('%I:%M %p').lstrip('0') if item.start_time else 'Start'} - "
                    f"{item.end_time.strftime('%I:%M %p').lstrip('0') if item.end_time else 'End'}"
                ),
                'status_label': role.get_role_display(),
                'file': latest.file if latest else None,
                'uploaded_at': latest.uploaded_at if latest else None,
            })

        session_roles = (
            ProgramSessionFaculty.objects.filter(person_id__in=person_ids)
            .select_related('person', 'session', 'session__event', 'session__program_day', 'session__hall_room')
            .order_by('session__event__start_date', 'session__start_time')
        )
        seen_sessions = set()
        for role in session_roles:
            session = role.session
            if session.id in seen_sessions:
                continue
            seen_sessions.add(session.id)
            latest = latest_uploads.get(('session', session.id))
            assignments.append({
                'assignment_type': 'session',
                'assignment_id': session.id,
                'event': session.event,
                'title': session.title,
                'role': 'Session faculty',
                'time_label': (
                    f"{session.program_day.name if session.program_day else 'Day'} · "
                    f"{session.hall_room.name if session.hall_room else 'Room'} · "
                    f"{session.start_time.strftime('%I:%M %p').lstrip('0') if session.start_time else 'Start'} - "
                    f"{session.end_time.strftime('%I:%M %p').lstrip('0') if session.end_time else 'End'}"
                ),
                'status_label': role.get_role_display(),
                'file': latest.file if latest else None,
                'uploaded_at': latest.uploaded_at if latest else None,
            })

    assignments.sort(key=lambda item: (
        item['event'].start_date or datetime.max.date(),
        item['title'].lower(),
    ))
    return assignments


def _save_user_presentation_upload(request, user_profile):
    presentation_file = request.FILES.get('presentation_file')
    if not presentation_file:
        messages.error(request, 'Please choose a PDF, PPT, or PPTX file before uploading.')
        return redirect(f"{reverse('user_profile')}?tab=presentations")

    assignment_type = request.POST.get('assignment_type')
    assignment_id = request.POST.get('assignment_id')
    program_people = _user_program_people(request.user, user_profile)
    program_person = program_people.first()

    upload_kwargs = {
        'user': request.user,
        'program_person': program_person,
        'presenter_name': user_profile.name,
        'file': presentation_file,
        'notes': request.POST.get('presentation_notes', '').strip(),
    }

    if assignment_type == 'abstract':
        abstract = get_object_or_404(AbstractSubmission, id=assignment_id, user=request.user)
        upload_kwargs.update({
            'event': abstract.event,
            'abstract_submission': abstract,
            'source_type': PresentationUpload.SOURCE_ABSTRACT,
            'title': abstract.title,
            'role_label': 'Abstract presenter',
        })
        upload = PresentationUpload.objects.create(**upload_kwargs)
        abstract.presentation_file = upload.file.name
        abstract.save(update_fields=['presentation_file', 'updated_at'])
    elif assignment_type == 'session_item':
        item = get_object_or_404(
            ProgramSessionItem.objects.select_related('session', 'session__event'),
            id=assignment_id,
            faculty_roles__person__in=program_people,
        )
        upload_kwargs.update({
            'event': item.session.event,
            'session': item.session,
            'session_item': item,
            'source_type': PresentationUpload.SOURCE_SESSION_ITEM,
            'title': item.display_title,
            'role_label': 'Program talk / activity',
        })
        PresentationUpload.objects.create(**upload_kwargs)
    elif assignment_type == 'session':
        session = get_object_or_404(
            ProgramSession.objects.select_related('event'),
            id=assignment_id,
            faculty_roles__person__in=program_people,
        )
        upload_kwargs.update({
            'event': session.event,
            'session': session,
            'source_type': PresentationUpload.SOURCE_SESSION_ROLE,
            'title': session.title,
            'role_label': 'Session faculty',
        })
        PresentationUpload.objects.create(**upload_kwargs)
    else:
        messages.error(request, 'Presentation assignment could not be identified.')
        return redirect(f"{reverse('user_profile')}?tab=presentations")

    messages.success(request, 'Presentation uploaded successfully.')
    return redirect(f"{reverse('user_profile')}?tab=presentations")


@login_required
def download_speaker_certificate(request, certificate_id):
    speaker_certificate_logger.info(
        "Speaker certificate download requested: certificate_id=%s user_id=%s is_staff=%s",
        certificate_id,
        request.user.id if request.user.is_authenticated else None,
        request.user.is_staff if request.user.is_authenticated else False,
    )
    certificate = get_object_or_404(
        SpeakerCertificate.objects.select_related('profile', 'event', 'program_person'),
        pk=certificate_id,
    )
    if not certificate.generated_file:
        speaker_certificate_logger.warning(
            "Speaker certificate download failed: missing file certificate_id=%s person_id=%s event_id=%s",
            certificate.id,
            certificate.program_person_id,
            certificate.event_id,
        )
        raise Http404("Speaker certificate file is not available.")
    if not request.user.is_staff:
        if not certificate.profile_id or certificate.profile.user_id != request.user.id:
            speaker_certificate_logger.warning(
                "Speaker certificate download denied: certificate_id=%s user_id=%s profile_user_id=%s",
                certificate.id,
                request.user.id,
                certificate.profile.user_id if certificate.profile_id else None,
            )
            raise Http404("Speaker certificate not found.")
        certificate.downloaded_at = timezone.now()
        certificate.save(update_fields=['downloaded_at'])
    speaker_certificate_logger.info(
        "Speaker certificate download started: certificate_id=%s person_id=%s event_id=%s file=%s",
        certificate.id,
        certificate.program_person_id,
        certificate.event_id,
        certificate.generated_file.name,
    )
    return FileResponse(
        certificate.generated_file.open('rb'),
        as_attachment=True,
        filename=os.path.basename(certificate.generated_file.name),
    )


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
    presentation_assignments = _build_user_presentation_assignments(request.user, user_profile, abstract_submissions)
    speaker_certificates = (
        SpeakerCertificate.objects.filter(profile=user_profile)
        .select_related('event', 'program_person')
        .order_by('-issued_at')
    )

    if request.method == 'POST':
        if request.POST.get('profile_action') == 'upload_presentation':
            return _save_user_presentation_upload(request, user_profile)

        selected_country = normalize_country_name(request.POST.get('country'))
        if not selected_country:
            messages.error(request, 'Please choose a valid country from the list.')
            message = ''
        else:
            submitted_phone = (request.POST.get('phone') or '').strip()
            try:
                normalized_phone = normalize_phone_number(submitted_phone, selected_country)
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
                message = ''
            else:
                if UserProfile.objects.filter(phone=normalized_phone).exclude(pk=user_profile.pk).exists():
                    messages.error(request, 'A user with this phone number already exists.')
                    message = ''
                else:
                    user_profile.name = request.POST.get('name')
                    user_profile.email = request.POST.get('email')
                    user_profile.phone = normalized_phone
                    user_profile.country = selected_country
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
        'presentation_assignments': presentation_assignments,
        'speaker_certificates': speaker_certificates,
        'site_settings': site_settings,
        'country_choices': COUNTRY_NAME_CHOICES,
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
def corporate_profile_edit(request):
    from .forms import CorporateAccountEditForm
    corporate_account = CorporateAccount.objects.filter(user=request.user).first()
    if not corporate_account:
        return redirect('corporate_dashboard')

    if request.method == 'POST':
        form = CorporateAccountEditForm(request.POST, request.FILES, instance=corporate_account)
        if form.is_valid():
            form.save()
            messages.success(request, 'Corporate profile updated successfully.')
            return redirect('corporate_dashboard')
    else:
        form = CorporateAccountEditForm(instance=corporate_account)

    return render(request, 'corporate_profile_edit.html', {
        'form': form,
        'corporate_account': corporate_account,
    })


@login_required
def corporate_dashboard(request):
    corporate_account = CorporateAccount.objects.filter(user=request.user).first()
    has_personal_profile = UserProfile.objects.filter(user=request.user).exists()
    matching_requests = CorporateAccountRequest.objects.filter(email__iexact=request.user.email).order_by('-created_at')
    
    open_events_base = Event.objects.filter(event_status='active', registration='Open').order_by('start_date')
    open_events = []
    from .models import CorporateEventComplementaryQuota
    for event in open_events_base:
        if corporate_account:
            quota_obj = CorporateEventComplementaryQuota.objects.filter(corporate_account=corporate_account, event=event).first()
            remaining_quota = quota_obj.get_remaining_count() if quota_obj else 0
        else:
            remaining_quota = 0
        open_events.append({
            'event': event,
            'remaining_quota': remaining_quota
        })

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

        country_value = normalize_country_name(normalized.get('country')) or DEFAULT_COUNTRY
        try:
            phone_value = normalize_phone_number(normalized.get('phone', ''), country_value)
        except ValidationError as exc:
            errors.append(f"Row {row_number}: {exc.messages[0]}")
            continue

        rows.append({
            'name': normalized.get('name', ''),
            'email': normalized.get('email', ''),
            'phone': phone_value,
            'degree': normalized.get('degree', ''),
            'organization': normalized.get('organization', ''),
            'country': country_value,
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
    
    # Determine registration type from query params or POST
    reg_type = request.POST.get('registration_type') or request.GET.get('reg_type') or 'regular'
    
    # Validate complementary quota
    remaining_quota = 0
    from .models import CorporateEventComplementaryQuota
    quota_obj = CorporateEventComplementaryQuota.objects.filter(corporate_account=corporate_account, event=event).first()
    if quota_obj:
        remaining_quota = quota_obj.get_remaining_count()
        
    if reg_type == 'complementary' and remaining_quota <= 0:
        messages.error(request, 'You do not have any remaining complementary spots for this event.')
        return redirect('corporate_dashboard')

    if reg_type == 'company_person':
        regular_fee = event.company_person_registration_fee or 0
    elif reg_type == 'complementary':
        regular_fee = 0
    else:
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
                
                # Check quota specifically for complementary
                if reg_type == 'complementary' and len(accepted_rows) > remaining_quota:
                    messages.error(request, f'You can only submit up to {remaining_quota} complementary attendees. You attempted to submit {len(accepted_rows)}.')
                    accepted_rows = []
                    
                if accepted_rows:
                    with transaction.atomic():
                        registration = CorporateEventRegistration.objects.create(
                            corporate_account=corporate_account,
                            event=event,
                            registration_type=reg_type,
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
                return redirect(f"{reverse('corporate_event_registration', args=[event.id])}?reg_type={reg_type}")

    elif request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        country = normalize_country_name(request.POST.get('country'))

        if not name or not email or not phone:
            messages.error(request, 'Name, email, and phone are required for manual attendee submission.')
        elif not country:
            messages.error(request, 'Please choose a valid country from the list.')
        else:
            try:
                phone = normalize_phone_number(phone, country)
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
                phone = ''

        if name and email and phone and country and reg_type == 'complementary' and remaining_quota < 1:
            messages.error(request, 'You have no remaining complementary spots.')
        elif name and email and phone and country:
            registration = CorporateEventRegistration.objects.create(
                corporate_account=corporate_account,
                event=event,
                registration_type=reg_type,
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
                'country': country,
                'department': (request.POST.get('department') or '').strip(),
                'bmdc_registration_number': (request.POST.get('bmdc_registration_number') or '').strip(),
                'designation': (request.POST.get('designation') or '').strip(),
                'notes': (request.POST.get('notes') or '').strip(),
            })
            messages.success(request, f'{name} has been submitted for BSBCS admin review.')
            return redirect(f"{reverse('corporate_event_registration', args=[event.id])}?reg_type={reg_type}")

    return render(request, 'corporate_event_registration.html', {
        'corporate_account': corporate_account,
        'event': event,
        'reg_type': reg_type,
        'remaining_quota': remaining_quota,
        'regular_fee': regular_fee,
        'member_fee': member_fee,
        'recent_submissions': recent_submissions,
        'country_choices': COUNTRY_NAME_CHOICES,
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
    context = build_public_participant_list_context(request, event)

    if request.headers.get('HX-Request'):
        return render(request, 'partials/participant_list.html', context)

    return render(request, 'participant_list.html', context)


def participant_list_partial(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    context = build_public_participant_list_context(request, event)
    return render(request, 'partials/participant_list.html', context)



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

def _starts_with_suggestions(values, limit=200):
    seen = set()
    suggestions = []
    for value in values:
        text = (value or '').strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        suggestions.append(text)
        if len(suggestions) >= limit:
            break
    return suggestions

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
        'country': user_profile.country or DEFAULT_COUNTRY,
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
    organization_suggestions = _starts_with_suggestions(
        Participant.objects.exclude(organization__isnull=True)
        .exclude(organization__exact='')
        .order_by('organization')
        .values_list('organization', flat=True)
    )
    department_suggestions = _starts_with_suggestions(
        Department.objects.order_by('name').values_list('name', flat=True)
    )

    return render(request, 'registration.html', {
        'form': form,
        'event': event,
        'show_membership_nudge': show_membership_nudge,
        'show_registration_choice': show_registration_choice,
        'regular_registration_fee': regular_registration_fee,
        'member_registration_fee': member_registration_fee,
        'organization_suggestions': organization_suggestions,
        'department_suggestions': department_suggestions,
        'country_choices': COUNTRY_NAME_REQUIRED_CHOICES,
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

    department_name = get_previous_participant_department_name(user_profile.email, event)
    if not department_name:
        first_specialty = member.specialties.first()
        department_name = first_specialty.name if first_specialty else ''
    department = get_or_create_participant_department(event, department_name)
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
            organization=(member.institution or 'Not provided')[:100],
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
    html_content = render_to_string('registration_submitted.html', {'participant': participant})
    text_content = strip_tags(html_content)
    from_email = os.getenv("EMAIL_HOST_USER")
    recipient_list = [participant.email]

    send_email_task.delay(
        subject=subject,
        body=text_content,
        from_email=from_email,
        recipient_list=recipient_list,
        html_message=html_content,
        audit_category=EmailAuditLog.CATEGORY_REGISTRATION,
        audit_metadata={
            'participant_id': participant.id,
            'event_id': participant.event_id,
            'source': 'registration_submission',
        },
    )
    sms_payload = get_system_sms_content(
        'registration_submission',
        context={
            'participant_name': participant.name,
            'event_name': participant.event.name,
            'event_year': participant.event.year,
        },
    )
    send_sms_task.delay(
        participant.phone,
        sms_payload['body'],
        country=participant.country,
        context={
            'source': 'registration_submission',
            'participant_id': participant.id,
            'event_id': participant.event_id,
        },
        sms_type=sms_payload['sms_type'],
        fallback_sms_type=sms_payload.get('fallback_sms_type'),
    )


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

        send_email_task.delay(
            subject=subject,
            body=text_content,
            from_email=from_email,
            recipient_list=recipient_list,
            html_message=html_content,
            audit_category=EmailAuditLog.CATEGORY_APPROVAL,
            audit_metadata={
                'participant_id': participant.id,
                'event_id': event.id,
                'source': 'registration_approval',
            },
        )
    except Exception as e:
        logger.exception("Error queueing approval email: %s", e)


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

        send_email_task.delay(
            subject=subject,
            body=text_content,
            from_email=from_email,
            recipient_list=recipient_list,
            html_message=html_content,
            audit_category=EmailAuditLog.CATEGORY_REGISTRATION,
            audit_metadata={
                'participant_id': participant.id,
                'event_id': event.id,
                'source': 'payment_link',
            },
        )
    except Exception as e:
        logger.exception("Error queueing payment link email: %s", e)

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
    html_content = render_to_string('submission_success.html', {'participant': participant})
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
    latest_abstract = participant.abstractsubmission_set.order_by('-id').first()
    sms_payload = get_system_sms_content(
        'abstract_submission',
        context={
            'participant_name': participant.name,
            'event_name': participant.event.name,
            'event_year': participant.event.year,
            'abstract_title': latest_abstract.title if latest_abstract else '',
        },
    )
    send_sms_task.delay(
        participant.phone,
        sms_payload['body'],
        country=participant.country,
        context={
            'source': 'abstract_submission',
            'participant_id': participant.id,
            'event_id': participant.event_id,
        },
        sms_type=sms_payload['sms_type'],
        fallback_sms_type=sms_payload.get('fallback_sms_type'),
    )

# ### Abstract Submission process, abstract submission mail Ends ----------------------------------###

# Invitation View
def invitation(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    invitations = Invitation.objects.filter(event=event)
    return render(request, 'invitation.html', {'invitations': invitations, 'event': event})


def schedule(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    program_sessions = ProgramSession.objects.filter(event=event).select_related(
        'program_day',
        'hall_room',
        'time_slot',
    ).prefetch_related(
        'faculty_roles__person',
        'items__abstract_submission',
        'items__talk_slot',
        'items__faculty_roles__person',
    ).order_by('program_day__date', 'start_time', 'order')

    program_days = ProgramDay.objects.filter(event=event).order_by('date', 'name')
    program_schedule_pdf = ProgramSchedulePdf.objects.filter(event=event).first()
    program_schedules = ProgramSchedule.objects.filter(event=event)\
        .select_related('abstract_submission')\
        .prefetch_related('time_slots')\
        .order_by('time_slots__program_day', 'time_slots__start_time')

    time_slots = TimeSlot.objects.filter(event=event).select_related(
        'program_day',
        'hall_room',
    ).prefetch_related(
        'program_sessions__faculty_roles__person',
        'program_sessions__items__faculty_roles__person',
        'program_sessions__items__abstract_submission',
        'program_sessions__items__talk_slot',
    ).order_by('program_day__date', 'start_time', 'hall_room__name')

    def get_grouped_faculty_roles(session):
        """Group session faculty roles by role type with person names."""
        grouped = {}
        for role in session.faculty_roles.all():
            role_label = role.get_role_display()
            if role_label not in grouped:
                grouped[role_label] = []
            grouped[role_label].append(role.person.name)
        return grouped

    def get_item_speaker_presenter_label(item):
        """Get speaker or presenter names for an item, prioritizing speakers."""
        speakers = []
        presenters = []
        for role in item.faculty_roles.all():
            if role.role == ProgramItemFaculty.ROLE_SPEAKER and role.person.name not in speakers:
                speakers.append(role.person.name)
            elif role.role == ProgramItemFaculty.ROLE_PRESENTER and role.person.name not in presenters:
                presenters.append(role.person.name)
        if speakers:
            return ', '.join(speakers)
        if presenters:
            return ', '.join(presenters)
        return ''

    session_days = []
    if time_slots.exists() or program_sessions.exists():
        slots_by_day = defaultdict(list)
        for slot in time_slots:
            slots_by_day[slot.program_day_id].append(slot)

        sessions_by_slot = defaultdict(list)
        sessions_by_time_window = defaultdict(list)
        unassigned_sessions_by_day = defaultdict(list)
        for session in program_sessions:
            session.grouped_faculty_roles = get_grouped_faculty_roles(session)
            for item in session.items.all():
                item.speaker_presenter_label = get_item_speaker_presenter_label(item)
            if session.time_slot_id:
                sessions_by_slot[session.time_slot_id].append(session)
            elif session.program_day_id:
                unassigned_sessions_by_day[session.program_day_id].append(session)

            time_window_key = (session.program_day_id, session.start_time, session.end_time)
            sessions_by_time_window[time_window_key].append(session)

        for day in program_days:
            rows = []
            for slot in slots_by_day.get(day.id, []):
                if slot.slot_type == TimeSlot.SLOT_SESSION:
                    slot_sessions = sessions_by_slot.get(slot.id, [])
                    for session in slot_sessions:
                        time_window_key = (session.program_day_id, session.start_time, session.end_time)
                        window_sessions = sessions_by_time_window.get(time_window_key, [])
                        session.parallel_sessions = len(window_sessions)
                        session.is_parallel = len(window_sessions) > 1
                        rows.append({'type': 'session', 'session': session})
                else:
                    rows.append({'type': 'slot', 'slot': slot})

            for session in unassigned_sessions_by_day.get(day.id, []):
                time_window_key = (session.program_day_id, session.start_time, session.end_time)
                window_sessions = sessions_by_time_window.get(time_window_key, [])
                session.parallel_sessions = len(window_sessions)
                session.is_parallel = len(window_sessions) > 1
                rows.append({'type': 'session', 'session': session})

            session_days.append({
                'day': day,
                'rows': rows,
            })

    return render(request, 'schedule.html', {
        'event': event,
        'program_sessions': program_sessions,
        'session_days': session_days,
        'program_schedule_pdf': program_schedule_pdf,
        'program_schedules': program_schedules,
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


SUCCESS_PAYMENT_STATUSES = ['completed', 'paid']
BKASH_ALREADY_COMPLETED_CODE = '2062'


def _payment_user_log_context(request):
    user = getattr(request, 'user', None)
    user_profile = getattr(user, 'userprofile', None) if user and user.is_authenticated else None
    return {
        'user_id': getattr(user, 'id', None),
        'user_email': getattr(user, 'email', '') or getattr(user, 'username', ''),
        'username': getattr(user, 'username', ''),
        'user_profile_id': getattr(user_profile, 'id', None),
        'user_profile_email': getattr(user_profile, 'email', None),
    }


def _event_payment_log_context(request, payment_status, extra=None):
    participant = payment_status.participant
    context = {
        **_payment_user_log_context(request),
        'flow': 'event',
        'event_id': payment_status.event_id,
        'participant_id': participant.id,
        'participant_email': participant.email,
        'payment_status_id': payment_status.id,
        'merchant_invoice_number': payment_status.merchant_invoice_number,
        'paymentID': payment_status.transaction_id,
        'trxID': payment_status.trxID,
        'amount': str(payment_status.amount),
        'status': payment_status.status,
    }
    if extra:
        context.update(extra)
    return context


def _log_event_payment(level, message, request, payment_status, extra=None):
    payload = _event_payment_log_context(request, payment_status, extra)
    getattr(logger, level)(message + " %s", json.dumps(payload, default=str))


def _render_event_payment_success(request, payment_status, payment_details=None, message="Payment successfully finalized."):
    return render(
        request,
        'finalize_payment.html',
        {
            'message': message,
            'payment_details': payment_details or {
                'paymentID': payment_status.transaction_id,
                'trxID': payment_status.trxID,
                'amount': payment_status.amount,
                'merchantInvoiceNumber': payment_status.merchant_invoice_number,
                'transactionStatus': payment_status.status,
            },
        }
    )

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
    _log_event_payment('info', 'payment_access', request, payment_status, {'method': request.method})

    if participant.user_id != request.user.id:
        _log_event_payment('warning', 'payment_access_denied', request, payment_status, {
            'reason': 'participant_owner_mismatch',
            'owner_user_id': participant.user_id,
        })
        messages.error(request, "You are not allowed to access this payment link.")
        return redirect('registration:home', event_id=event.pk)

    if payment_status.status in SUCCESS_PAYMENT_STATUSES:
        _log_event_payment('info', 'payment_access_already_completed', request, payment_status, {
            'method': request.method,
            'status_before': payment_status.status,
            'reason': 'payment_already_completed_before_create',
        })
        messages.info(request, "This event payment is already completed.")
        return _render_event_payment_success(
            request,
            payment_status,
            message="Payment already finalized.",
        )

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

            logger.info(
                "payment_create_response %s",
                json.dumps(_event_payment_log_context(request, payment_status, {
                    'merchant_invoice_number': merchant_invoice_number,
                    'bkash_statusCode': payment_response.get('statusCode') if payment_response else None,
                    'bkash_statusMessage': payment_response.get('statusMessage') if payment_response else None,
                    'paymentID': payment_response.get('paymentID') if payment_response else None,
                }), default=str)
            )

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
    payment_status = get_object_or_404(PaymentStatus, participant=participant, event=event)
    _log_event_payment('info', 'payment_callback_received', request, payment_status, {
        'paymentID': payment_id,
        'merchant_invoice_number': merchant_invoice_number,
        'callback_status': request.GET.get('status'),
    })

    if participant.user_id != request.user.id:
        _log_event_payment('warning', 'payment_callback_denied', request, payment_status, {
            'reason': 'participant_owner_mismatch',
            'owner_user_id': participant.user_id,
        })
        messages.error(request, "You are not allowed to access this payment link.")
        return redirect('registration:home', event_id=event.pk)

    if payment_status.status in SUCCESS_PAYMENT_STATUSES:
        _log_event_payment('info', 'payment_callback_already_completed', request, payment_status, {
            'paymentID': payment_id,
            'status_before': payment_status.status,
        })
        return redirect(reverse('registration:finalize_payment', kwargs={'event_id': event_id, 'participant_id': participant_id}))

    status_before = payment_status.status
    payment_status.transaction_id = payment_id
    payment_status.status = 'pending'
    payment_status.amount = participant.get_payable_amount()
    payment_status.merchant_invoice_number = merchant_invoice_number or payment_status.merchant_invoice_number
    payment_status.save()
    _log_event_payment('info', 'payment_callback_marked_pending', request, payment_status, {
        'paymentID': payment_id,
        'status_before': status_before,
        'status_after': payment_status.status,
    })

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
        _log_event_payment('info', 'payment_finalize_access', request, payment_status, {
            'method': request.method,
            'status_before': payment_status.status,
        })

        if payment_status.participant.user_id != request.user.id:
            _log_event_payment('warning', 'payment_finalize_denied', request, payment_status, {
                'reason': 'participant_owner_mismatch',
                'owner_user_id': payment_status.participant.user_id,
            })
            messages.error(request, "You are not allowed to access this payment link.")
            return redirect('registration:home', event_id=event_id)

        if payment_status.status in SUCCESS_PAYMENT_STATUSES:
            _log_event_payment('info', 'payment_finalize_skip_already_completed', request, payment_status, {
                'status_before': payment_status.status,
            })
            return _render_event_payment_success(
                request,
                payment_status,
                message="Payment already finalized.",
            )

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
        logger.info(
            "payment_execute_response %s",
            json.dumps(_event_payment_log_context(request, payment_status, {
                'bkash_statusCode': execute_response.get('statusCode') if execute_response else None,
                'bkash_statusMessage': execute_response.get('statusMessage') if execute_response else None,
                'paymentID': execute_response.get('paymentID') if execute_response else payment_status.transaction_id,
                'trxID': execute_response.get('trxID') if execute_response else payment_status.trxID,
                'status_before': payment_status.status,
                'raw_response': execute_response,
            }), default=str)
        )

        # Handle specific Execute API error cases
        if execute_response:
            status_code = execute_response.get('statusCode')
            status_message = execute_response.get('statusMessage', 'Invalid payment state.')

            if status_code == BKASH_ALREADY_COMPLETED_CODE:
                query_response = payment_query(token, payment_status.transaction_id)
                logger.info(
                    "payment_query_after_already_completed %s",
                    json.dumps(_event_payment_log_context(request, payment_status, {
                        'bkash_statusCode': query_response.get('statusCode') if query_response else None,
                        'bkash_statusMessage': query_response.get('statusMessage') if query_response else None,
                        'paymentID': payment_status.transaction_id,
                        'raw_response': query_response,
                    }), default=str)
                )
                if query_response and (
                    query_response.get('transactionStatus') == 'Completed'
                    or query_response.get('statusCode') == '0000'
                ):
                    status_before = payment_status.status
                    payment_status.status = 'completed'
                    payment_status.amount = query_response.get('amount', payment_status.amount)
                    payment_status.merchant_invoice_number = query_response.get('merchantInvoiceNumber', payment_status.merchant_invoice_number)
                    payment_status.transaction_id = query_response.get('paymentID', payment_status.transaction_id)
                    payment_status.trxID = query_response.get('trxID', payment_status.trxID)
                    payment_status.save()
                    queue_registration_payment_received_sms(payment_status, source='registration_payment_completed_already_completed')
                    _log_event_payment('warning', 'payment_execute_already_completed_marked_completed', request, payment_status, {
                        'status_before': status_before,
                        'status_after': payment_status.status,
                        'bkash_statusCode': status_code,
                    })
                    return _render_event_payment_success(
                        request,
                        payment_status,
                        query_response,
                        message="Payment already completed with bKash and finalized locally.",
                    )
                _log_event_payment('warning', 'payment_execute_already_completed_kept_pending', request, payment_status, {
                    'bkash_statusCode': status_code,
                    'bkash_statusMessage': status_message,
                })
                return render(request, 'payment_message.html', {
                    'title': 'Payment Needs Review',
                    'error_message': 'bKash says this payment was already completed, but local verification was inconclusive. Please contact support.',
                })

            # Map known error cases
            error_messages = {
                "2001": "Duplicate transaction detected. Please try again.",
                "3001": "Payment was cancelled by the user.",
                "4001": "Wrong OTP provided. Please restart the payment.",
                "5001": "Wrong PIN provided. Please restart the payment.",
            }

            # Handle specific errors
            if status_code in error_messages:
                if payment_status.status not in SUCCESS_PAYMENT_STATUSES:
                    status_before = payment_status.status
                    payment_status.status = 'failed'
                    payment_status.save()
                    _log_event_payment('warning', 'payment_finalize_marked_failed', request, payment_status, {
                        'status_before': status_before,
                        'status_after': payment_status.status,
                        'bkash_statusCode': status_code,
                        'bkash_statusMessage': status_message,
                    })
                return render(request, 'payment_message.html', {
                    'title': 'Payment Failure',
                    'error_message': error_messages[status_code]
                })

            # Handle unknown status codes
            elif status_code != "0000":
                if payment_status.status not in SUCCESS_PAYMENT_STATUSES:
                    status_before = payment_status.status
                    payment_status.status = 'failed'
                    payment_status.save()
                    _log_event_payment('warning', 'payment_finalize_marked_failed', request, payment_status, {
                        'status_before': status_before,
                        'status_after': payment_status.status,
                        'bkash_statusCode': status_code,
                        'bkash_statusMessage': status_message,
                    })
                return render(request, 'payment_message.html', {
                    'title': 'Payment Failure',
                    'error_message': status_message
                })

        # Handle Execute API Success
        if execute_response and execute_response.get('statusCode') == '0000':
            status_before = payment_status.status
            payment_status.status = 'completed'
            payment_status.amount = execute_response.get('amount', payment_status.amount)
            payment_status.merchant_invoice_number = execute_response.get('merchantInvoiceNumber', payment_status.merchant_invoice_number)
            payment_status.transaction_id = execute_response.get('paymentID')
            payment_status.trxID = execute_response.get('trxID')  # Use trxID from execute response
            payment_status.save()
            queue_registration_payment_received_sms(payment_status, source='registration_payment_completed')
            _log_event_payment('info', 'payment_finalize_marked_completed', request, payment_status, {
                'status_before': status_before,
                'status_after': payment_status.status,
                'bkash_statusCode': execute_response.get('statusCode'),
                'bkash_statusMessage': execute_response.get('statusMessage'),
            })

            # Generate Invoice and Send Email
            try:
                invoice_path = generate_invoice(payment_status.participant, payment_status.event, payment_status)
                _log_event_payment('info', 'payment_invoice_generated', request, payment_status, {
                    'invoice_path': invoice_path,
                })
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
        if payment_status.status not in SUCCESS_PAYMENT_STATUSES:
            status_before = payment_status.status
            payment_status.status = 'failed'
            payment_status.save()
            _log_event_payment('warning', 'payment_finalize_marked_failed', request, payment_status, {
                'status_before': status_before,
                'status_after': payment_status.status,
                'reason': 'incomplete_execute_response',
            })
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
    payment_status = get_object_or_404(PaymentStatus, participant=participant, event=event)
    _log_event_payment('warning', 'payment_failure_callback', request, payment_status, {
        'reason': request.GET.get('reason', "Payment failed. Please try again."),
        'status_before': payment_status.status,
    })

    if participant.user_id != request.user.id:
        _log_event_payment('warning', 'payment_failure_denied', request, payment_status, {
            'reason': 'participant_owner_mismatch',
            'owner_user_id': participant.user_id,
        })
        messages.error(request, "You are not allowed to access this payment link.")
        return redirect('registration:home', event_id=event.pk)

    # Update payment status to 'failed'
    if payment_status.status not in SUCCESS_PAYMENT_STATUSES:
        payment_status.status = 'failed'
        payment_status.save()
    else:
        _log_event_payment('warning', 'payment_failure_completed_overwrite_skipped', request, payment_status, {
            'status_after': payment_status.status,
        })

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
        participant_payment = PaymentStatus.objects.filter(
            participant=attendee.participant,
            event=corporate_payment.event,
        ).first()
        if not participant_payment:
            continue
        participant_payment.status = 'completed'
        participant_payment.transaction_id = corporate_payment.transaction_id
        participant_payment.trxID = corporate_payment.trxID
        participant_payment.save(update_fields=['status', 'transaction_id', 'trxID', 'updated_at'])
        invoice_path = generate_invoice(attendee.participant, corporate_payment.event, participant_payment)
        participant_payment.invoice = os.path.relpath(invoice_path, settings.MEDIA_ROOT)
        participant_payment.save(update_fields=['invoice', 'updated_at'])
        if not participant_payment.email_sent:
            send_corporate_participant_invoice_email(
                attendee.participant,
                corporate_payment.event,
                participant_payment,
                invoice_path,
                corporate_payment.corporate_account,
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

    try:
        send_email_task.delay(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            attachment_paths=[invoice_path] if invoice_path else None,
            audit_category=EmailAuditLog.CATEGORY_INVOICE,
            audit_metadata={
                'participant_id': participant.id,
                'event_id': event.id,
                'payment_status_id': payment_status.id,
            },
        )
        payment_status.email_sent = True
        payment_status.invoice = os.path.relpath(invoice_path, settings.MEDIA_ROOT)
        payment_status.save()
        logger.info("Invoice email queued to %s", recipient)
    except Exception as e:
        logger.exception("Error queueing invoice email: %s", e)


def send_corporate_participant_invoice_email(participant, event, payment_status, invoice_path, corporate_account):
    subject = f"Corporate-sponsored registration confirmed for {event.name}"
    message = (
        f"Dear {participant.name},\n\n"
        f"{corporate_account.company_name} has completed the corporate registration payment for "
        f"your attendance at {event.name} {event.year}.\n\n"
        "Your individual registration invoice is attached. It includes your secure QR code for "
        "verification at the registration desk.\n\n"
        "Best regards,\n"
        "BSBCS Team"
    )

    try:
        send_email_task.delay(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[participant.email],
            attachment_paths=[invoice_path] if invoice_path else None,
            audit_category=EmailAuditLog.CATEGORY_CORPORATE,
            audit_metadata={
                'participant_id': participant.id,
                'event_id': event.id,
                'payment_status_id': payment_status.id,
                'corporate_account_id': corporate_account.id,
            },
        )
        payment_status.email_sent = True
        payment_status.invoice = os.path.relpath(invoice_path, settings.MEDIA_ROOT)
        payment_status.save(update_fields=['email_sent', 'invoice', 'updated_at'])
        logger.info("Corporate participant invoice queued for %s", participant.email)
        return True
    except Exception as exc:
        logger.exception("Could not queue corporate participant invoice to %s: %s", participant.email, exc)
        return False




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


def _speaker_certificate_output_filename(person_name):
    safe_name = "".join(ch if ch.isalnum() or ch in (' ', '-', '_') else '' for ch in person_name).strip()
    safe_name = safe_name.replace(' ', '_') or 'Speaker'
    return f"BBCC_Speaker_Certificate_{safe_name}.jpg"


def _chest_card_output_filename(participant_name):
    safe_name = "".join(ch if ch.isalnum() or ch in (' ', '-', '_') else '' for ch in participant_name).strip()
    safe_name = safe_name.replace(' ', '_') or 'Participant'
    return f"BSBCS_Chest_Card_{safe_name}.png"


def _chest_card_pdf_output_filename(participant_name):
    safe_name = "".join(ch if ch.isalnum() or ch in (' ', '-', '_') else '' for ch in participant_name).strip()
    safe_name = safe_name.replace(' ', '_') or 'Participant'
    return f"BSBCS_Chest_Card_{safe_name}.pdf"


def _chest_card_bulk_pdf_output_filename(event):
    event_slug = slugify(f'{event.name}-{event.year}') or f'event-{event.id}'
    return f"BSBCS_Chest_Cards_{event_slug}.pdf"


def _chest_card_vendor_zip_output_filename(event):
    event_slug = slugify(f'{event.name}-{event.year}') or f'event-{event.id}'
    return f"BSBCS_Chest_Cards_{event_slug}_vendor_bundle.zip"


def _mm_to_px(value_mm, dpi):
    return max(int(round(float(value_mm) * float(dpi) / 25.4)), 1)


def _load_badge_font(size):
    candidates = ['arial.ttf', r'C:\Windows\Fonts\arial.ttf', r'C:\Windows\Fonts\ARIAL.TTF', 'DejaVuSans.ttf']
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text_to_width(draw, text, font, max_width):
    words = [word for word in (text or '').split() if word]
    if not words:
        return ['']
    lines = []
    current = []
    for word in words:
        candidate = ' '.join(current + [word])
        bbox = draw.textbbox((0, 0), candidate, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width or not current:
            current.append(word)
        else:
            lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))
    return lines


def _fit_text_to_box(draw, text, box_width, box_height, start_size):
    min_size = 12
    for size in range(max(int(start_size), min_size), min_size - 1, -1):
        font = _load_badge_font(size)
        lines = _wrap_text_to_width(draw, text, font, box_width)
        line_boxes = [draw.textbbox((0, 0), line or ' ', font=font) for line in lines]
        line_height = max((bbox[3] - bbox[1]) for bbox in line_boxes) if line_boxes else size
        total_height = (line_height * len(lines)) + max(len(lines) - 1, 0) * 4
        max_line_width = max((bbox[2] - bbox[0]) for bbox in line_boxes) if line_boxes else 0
        if total_height <= box_height and max_line_width <= box_width:
            return font, lines, line_height
    fallback_font = _load_badge_font(min_size)
    fallback_lines = _wrap_text_to_width(draw, text, fallback_font, box_width)
    fallback_bbox = draw.textbbox((0, 0), fallback_lines[0] or ' ', font=fallback_font)
    return fallback_font, fallback_lines, fallback_bbox[3] - fallback_bbox[1]


def _hex_to_rgb(hex_value, default=(15, 23, 42)):
    value = (hex_value or '').strip().lstrip('#')
    if len(value) == 3:
        value = ''.join(ch * 2 for ch in value)
    if len(value) != 6:
        return default
    try:
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return default


def _event_certificate_date_label(event):
    if not event or not event.start_date:
        return ''
    if event.end_date and event.end_date != event.start_date:
        return f"{event.start_date:%d %B %Y} to {event.end_date:%d %B %Y}"
    return f"{event.start_date:%d %B %Y}"


def _speaker_certificate_title(certificate):
    if certificate and certificate.speaker_title:
        return certificate.speaker_title
    return 'Certificate of Appreciation'


def _render_speaker_certificate_body(certificate, event):
    body = (
        certificate.speaker_body
        if certificate and certificate.speaker_body
        else 'In recognition of your invaluable contribution as a Guest Speaker in the {{ event_name }}, held on {{ event_date }} at {{ event_location }}.'
    )
    replacements = {
        'event_name': event.name if event else '',
        'event name': event.name if event else '',
        'event_date': _event_certificate_date_label(event),
        'event date': _event_certificate_date_label(event),
        'event_location': event.location if event and event.location else 'the announced venue',
        'event location': event.location if event and event.location else 'the announced venue',
    }
    for key, value in replacements.items():
        body = re.sub(r"{{\s*" + re.escape(key) + r"\s*}}", value or '', body, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', body).strip()


def _speaker_profile_for_person(person):
    if not person:
        return None
    if person.profile_id:
        return person.profile
    if person.email:
        return UserProfile.objects.filter(email__iexact=person.email).first()
    return None


def _speaker_related_participant(person, event, profile=None):
    participant_qs = Participant.objects.filter(event=event).select_related('user')
    profile = profile or _speaker_profile_for_person(person)
    if profile and profile.user_id:
        participant = participant_qs.filter(user=profile.user).order_by('-created_at').first()
        if participant:
            return participant
    if person and person.email:
        return participant_qs.filter(email__iexact=person.email).order_by('-created_at').first()
    return None


def _speaker_role_labels(person, event):
    role_values = (
        ProgramItemFaculty.objects.filter(
            person=person,
            item__session__event=event,
            role__in=[ProgramItemFaculty.ROLE_SPEAKER, ProgramItemFaculty.ROLE_PRESENTER],
        )
        .values_list('role', flat=True)
        .distinct()
    )
    labels = []
    for role in role_values:
        if role == ProgramItemFaculty.ROLE_SPEAKER:
            labels.append('Speaker')
        elif role == ProgramItemFaculty.ROLE_PRESENTER:
            labels.append('Presenter')
    return ', '.join(labels) or 'Speaker'


def _default_speaker_outreach_subject(event):
    return f"Invitation to join {event.name} {event.year} as a speaker"


def _default_speaker_outreach_intro(event, role_label='Speaker'):
    return (
        f"We are pleased to invite you to join {event.name} {event.year} as {role_label}. "
        f"The event will be held on {event.start_date}"
        + (f" to {event.end_date}" if event.end_date and event.end_date != event.start_date else "")
        + (f" at {event.location}." if event.location else ".")
    )


def _speaker_outreach_template(event):
    template, _ = SpeakerOutreachTemplate.objects.get_or_create(
        event=event,
        defaults={
            'subject': _default_speaker_outreach_subject(event),
            'intro_body': _default_speaker_outreach_intro(event),
            'closing_body': 'We would be grateful for your positive confirmation at your convenience.\n\nWarm regards,\nBSBCS Secretariat',
            'airfare_body': 'We would be pleased to arrange return air ticket support for your participation.',
            'hotel_body': 'We would be pleased to arrange your hotel accommodation for the event dates.',
            'allowance_body': 'We would also be pleased to provide the agreed speaker allowance or honorarium.',
            'local_transport_body': 'Local transport support will be arranged for your official event movements.',
            'special_support_body': 'Additional special arrangements are available and will be coordinated with you directly.',
        },
    )
    return template


def _speaker_outreach_row(event, person):
    row, _ = SpeakerOutreachCoordination.objects.get_or_create(event=event, person=person)
    return row


def _clean_message_block(value):
    cleaned = (value or '').strip()
    return '' if cleaned.lower() == 'none' else cleaned


def _speaker_outreach_compose_message(event, person, template, coordination):
    role_label = _speaker_role_labels(person, event)
    blocks = [f"Dear {person.name},"]

    intro_body = _clean_message_block(template.intro_body) or _default_speaker_outreach_intro(event, role_label=role_label)
    blocks.append(intro_body)

    amenity_blocks = []
    airfare_body = _clean_message_block(template.airfare_body)
    hotel_body = _clean_message_block(template.hotel_body)
    allowance_body = _clean_message_block(template.allowance_body)
    local_transport_body = _clean_message_block(template.local_transport_body)
    special_support_body = _clean_message_block(template.special_support_body)
    if coordination.offer_airfare and airfare_body:
        amenity_blocks.append(airfare_body)
    if coordination.offer_hotel and hotel_body:
        amenity_blocks.append(hotel_body)
    if coordination.offer_allowance and allowance_body:
        amenity_blocks.append(allowance_body)
    if coordination.offer_local_transport and local_transport_body:
        amenity_blocks.append(local_transport_body)
    if coordination.offer_special_support and special_support_body:
        amenity_blocks.append(special_support_body)

    if amenity_blocks:
        blocks.append('To support your participation, we would also be pleased to confirm the following arrangements:')
        blocks.append('\n'.join(f'- {item}' for item in amenity_blocks))

    closing_body = _clean_message_block(template.closing_body)
    if closing_body:
        blocks.append(closing_body)

    return '\n\n'.join(block for block in blocks if block)


def _speaker_outreach_people_queryset(event, search_query=''):
    qs = ProgramPerson.objects.filter(
        events=event,
    ).select_related('profile').distinct().order_by('name')
    query_text = (search_query or '').strip()
    if query_text:
        qs = qs.filter(
            Q(name__icontains=query_text)
            | Q(email__icontains=query_text)
            | Q(institution__icontains=query_text)
            | Q(designation__icontains=query_text)
        )
    return qs


def _speaker_outreach_existing_global_person(cleaned_data):
    email = (cleaned_data.get('email') or '').strip().lower()
    phone = (cleaned_data.get('phone') or '').strip()
    name = (cleaned_data.get('name') or '').strip()
    institution = (cleaned_data.get('institution') or '').strip()

    base_qs = ProgramPerson.objects.all()
    if email:
        match = base_qs.filter(email__iexact=email).first()
        if match:
            return match
    if phone:
        match = base_qs.filter(phone=phone).first()
        if match:
            return match
    if name:
        lookup = Q(name__iexact=name)
        if institution:
            lookup &= Q(institution__iexact=institution)
        match = base_qs.filter(lookup).first()
        if match:
            return match
    return None


def _speaker_outreach_library_queryset(search_query=''):
    qs = ProgramPerson.objects.select_related('profile').all().order_by('name')
    query_text = (search_query or '').strip()
    if query_text:
        qs = qs.filter(
            Q(name__icontains=query_text)
            | Q(email__icontains=query_text)
            | Q(institution__icontains=query_text)
            | Q(designation__icontains=query_text)
            | Q(country__icontains=query_text)
        )
    return qs


def _speaker_outreach_profile_queryset(search_query=''):
    qs = UserProfile.objects.select_related('member').order_by('name', 'email')
    query_text = (search_query or '').strip()
    if query_text:
        qs = qs.filter(
            Q(name__icontains=query_text)
            | Q(email__icontains=query_text)
            | Q(phone__icontains=query_text)
            | Q(country__icontains=query_text)
            | Q(member__institution__icontains=query_text)
            | Q(member__position__icontains=query_text)
        )
    return qs.distinct()[:8]


def _speaker_outreach_profile_rows(search_query='', event=None, selected_profile_id=None):
    profiles = list(_speaker_outreach_profile_queryset(search_query))
    if not profiles:
        return []
    profile_ids = [profile.id for profile in profiles]
    linked_people = {person.profile_id: person for person in ProgramPerson.objects.filter(profile_id__in=profile_ids).prefetch_related('events')}
    rows = []
    for profile in profiles:
        linked_person = linked_people.get(profile.id)
        is_in_event = bool(event and linked_person and linked_person.events.filter(pk=event.pk).exists())
        rows.append({
            'profile': profile,
            'linked_person': linked_person,
            'is_in_event': is_in_event,
            'is_selected': bool(selected_profile_id and str(profile.id) == str(selected_profile_id)),
        })
    return rows


def _speaker_outreach_profile_seed_data(profile):
    member = getattr(profile, 'member', None)
    return {
        'name': profile.name or '',
        'degree': '',
        'designation': getattr(member, 'position', '') or '',
        'institution': getattr(member, 'institution', '') or '',
        'email': profile.email or '',
        'phone': profile.phone or '',
        'country': profile.country or 'Bangladesh',
    }


def _apply_speaker_outreach_preset_to_template(preset, template):
    template.subject = preset.subject
    template.intro_body = preset.intro_body
    template.closing_body = preset.closing_body
    template.airfare_body = preset.airfare_body
    template.hotel_body = preset.hotel_body
    template.allowance_body = preset.allowance_body
    template.local_transport_body = preset.local_transport_body
    template.special_support_body = preset.special_support_body
    template.save()


def _speaker_outreach_rows(event, template, search_query=''):
    people = list(_speaker_outreach_people_queryset(event, search_query))
    coordinations = {
        row.person_id: row
        for row in SpeakerOutreachCoordination.objects.filter(event=event, person__in=people).select_related('last_sent_by', 'person')
    }
    latest_logs = {}
    for log in SpeakerOutreachEmailLog.objects.filter(event=event, person__in=people).select_related('sent_by').order_by('person_id', '-created_at'):
        latest_logs.setdefault(log.person_id, log)

    rows = []
    for person in people:
        coordination = coordinations.get(person.id) or SpeakerOutreachCoordination(event=event, person=person)
        latest_log = latest_logs.get(person.id)
        rows.append({
            'person': person,
            'coordination': coordination,
            'role_label': _speaker_outreach_role_label(person, event),
            'email': (person.email or (person.profile.email if person.profile_id and person.profile and person.profile.email else '') or '').strip(),
            'latest_log': latest_log,
            'preview_subject': (template.subject or '').strip() or _default_speaker_outreach_subject(event),
            'preview_body': _speaker_outreach_compose_message(event, person, template, coordination),
        })
    return rows


def _speaker_outreach_role_label(person, event):
    role_label = _speaker_role_labels(person, event)
    return role_label if role_label and role_label != 'Speaker' else ('Speaker' if ProgramItemFaculty.objects.filter(person=person, item__session__event=event, role=ProgramItemFaculty.ROLE_SPEAKER).exists() else ('Presenter' if ProgramItemFaculty.objects.filter(person=person, item__session__event=event, role=ProgramItemFaculty.ROLE_PRESENTER).exists() else 'Prospect'))


def _save_speaker_outreach_row_options(event, people, source):
    saved = 0
    coordination_map = {
        row.person_id: row
        for row in SpeakerOutreachCoordination.objects.filter(event=event, person__in=people)
    }
    for person in people:
        coordination = coordination_map.get(person.id) or SpeakerOutreachCoordination(event=event, person=person)
        coordination.offer_airfare = bool(source.get(f'offer_airfare_{person.id}'))
        coordination.offer_hotel = bool(source.get(f'offer_hotel_{person.id}'))
        coordination.offer_allowance = bool(source.get(f'offer_allowance_{person.id}'))
        coordination.offer_local_transport = bool(source.get(f'offer_local_transport_{person.id}'))
        coordination.offer_special_support = bool(source.get(f'offer_special_support_{person.id}'))
        coordination.custom_notes = None
        coordination.save()
        saved += 1
    return saved


def _queue_speaker_outreach_email(event, template, person, coordination, sent_by=None):
    recipient_email = ((person.email or '').strip() or ((person.profile.email or '').strip() if person.profile_id and person.profile else ''))
    if not recipient_email:
        return 'missing_email', None

    subject = (template.subject or '').strip() or _default_speaker_outreach_subject(event)
    body = _speaker_outreach_compose_message(event, person, template, coordination)
    email_log = SpeakerOutreachEmailLog.objects.create(
        coordination=coordination if coordination.pk else None,
        event=event,
        person=person,
        email=recipient_email,
        subject=subject,
        body=body,
        offer_airfare=coordination.offer_airfare,
        offer_hotel=coordination.offer_hotel,
        offer_allowance=coordination.offer_allowance,
        offer_local_transport=coordination.offer_local_transport,
        offer_special_support=coordination.offer_special_support,
        custom_notes=coordination.custom_notes,
        status=SpeakerOutreachEmailLog.STATUS_QUEUED,
        sent_by=sent_by if getattr(sent_by, 'is_authenticated', False) else None,
        message='Queued from Speaker Outreach Center.',
    )
    try:
        task = send_speaker_outreach_email_task.delay(email_log.id)
    except Exception as exc:
        email_log.status = SpeakerOutreachEmailLog.STATUS_FAILED
        email_log.message = f'Could not queue outreach email task: {exc}'
        email_log.save(update_fields=['status', 'message', 'updated_at'])
        raise
    email_log.task_id = getattr(task, 'id', '') or ''
    email_log.save(update_fields=['task_id', 'updated_at'])
    return 'queued', email_log


def _speaker_certificate_requirements_met(person, event, certificate):
    profile = _speaker_profile_for_person(person)
    participant = _speaker_related_participant(person, event, profile)
    has_feedback = bool(
        participant and FeedbackResponse.objects.filter(event=event, participant=participant).exists()
    )
    has_kit = bool(
        participant and RegistrationKit.objects.filter(
            event=event,
            payment_status__participant=participant,
            status='issued',
        ).exists()
    )
    feedback_required = bool(certificate and certificate.speaker_require_feedback)
    kit_required = bool(certificate and certificate.speaker_require_kit_issue)
    eligible = (has_feedback or not feedback_required) and (has_kit or not kit_required)
    return {
        'profile': profile,
        'participant': participant,
        'has_feedback': has_feedback,
        'has_kit': has_kit,
        'eligible': eligible,
    }


def _participant_certificate_requirements_met(participant, event):
    payment_status = PaymentStatus.objects.filter(participant=participant, event=event).first()
    registration_kit = RegistrationKit.objects.filter(
        payment_status__participant=participant,
        event=event,
    ).select_related('payment_status').first()
    has_feedback = FeedbackResponse.objects.filter(event=event, participant=participant).exists()
    is_approved = bool(participant and participant.approved)
    payment_completed = bool(payment_status and payment_status.status in SUCCESS_PAYMENT_STATUSES)
    kit_issued = bool(registration_kit and registration_kit.status == 'issued')
    eligible = all([is_approved, payment_completed, kit_issued, has_feedback])
    return {
        'payment_status': payment_status,
        'registration_kit': registration_kit,
        'is_approved': is_approved,
        'payment_completed': payment_completed,
        'kit_issued': kit_issued,
        'has_feedback': has_feedback,
        'eligible': eligible,
    }


def _read_email_button_fields(source, text_key='button_text', url_key='button_url'):
    button_text = (source.get(text_key) or '').strip()
    button_url = (source.get(url_key) or '').strip()
    if bool(button_text) != bool(button_url):
        raise ValueError('Provide both button text and button link, or leave both blank.')
    if button_url:
        try:
            URLValidator(schemes=['http', 'https'])(button_url)
        except ValidationError as exc:
            raise ValueError('Enter a valid full button link starting with http:// or https://.') from exc
    return button_text or None, button_url or None


def _queue_thank_you_email_for_kit(kit, event, subject, body, button_text=None, button_url=None, sent_by=None, force_resend=False):
    participant = kit.payment_status.participant if kit.payment_status_id else None
    recipient_email = participant.email if participant and participant.email else ''
    if not recipient_email:
        return 'missing_email', None

    thank_you_email, _ = ThankYouEmail.objects.get_or_create(
        registration_kit=kit,
        defaults={
            'subject': subject,
            'body': body,
            'button_text': button_text,
            'button_url': button_url,
        },
    )

    update_fields = []
    if thank_you_email.subject != subject:
        thank_you_email.subject = subject
        update_fields.append('subject')
    if thank_you_email.body != body:
        thank_you_email.body = body
        update_fields.append('body')
    if thank_you_email.button_text != button_text:
        thank_you_email.button_text = button_text
        update_fields.append('button_text')
    if thank_you_email.button_url != button_url:
        thank_you_email.button_url = button_url
        update_fields.append('button_url')
    if update_fields:
        thank_you_email.save(update_fields=update_fields)

    if thank_you_email.email_sent and not force_resend:
        return 'already_sent', thank_you_email

    email_log = None
    if thank_you_email_log_table_ready():
        email_log = ThankYouEmailLog.objects.create(
            thank_you_email=thank_you_email,
            event=event,
            participant=participant,
            email=recipient_email,
            status=ThankYouEmailLog.STATUS_QUEUED,
            sent_by=sent_by if getattr(sent_by, 'is_authenticated', False) else None,
            message='Queued for resend from Certificate Center participant thank-you section.' if force_resend else 'Queued from Certificate Center participant thank-you section.',
        )
    try:
        task = send_thank_you_email_task.delay(
            thank_you_email.id,
            log_id=email_log.id if email_log else None,
            sent_by_user_id=sent_by.id if getattr(sent_by, 'is_authenticated', False) else None,
            force_resend=force_resend,
        )
    except Exception as exc:
        if email_log:
            email_log.status = ThankYouEmailLog.STATUS_FAILED
            email_log.message = f'Could not queue email task: {exc}'
            email_log.save(update_fields=['status', 'message', 'updated_at'])
        raise
    if email_log:
        email_log.task_id = getattr(task, 'id', '') or ''
        email_log.save(update_fields=['task_id', 'updated_at'])
    return 'queued', thank_you_email


def _queue_thank_you_emails_for_kits(kits, event, subject, body, button_text=None, button_url=None, sent_by=None, force_resend=False):
    counts = {
        'queued': 0,
        'already_sent': 0,
        'missing_email': 0,
        'failed': 0,
    }
    for kit in kits:
        try:
            result, _ = _queue_thank_you_email_for_kit(
                kit,
                event,
                subject,
                body,
                button_text=button_text,
                button_url=button_url,
                sent_by=sent_by,
                force_resend=force_resend,
            )
        except Exception:
            counts['failed'] += 1
            continue
        if result in counts:
            counts[result] += 1
    return counts


def _certificate_center_kit_rows_queryset(event, search_query=''):
    qs = RegistrationKit.objects.select_related(
        'payment_status__participant',
        'payment_status__event',
    ).filter(event=event, status='issued').order_by('-issued_at', 'payment_status__participant__name')
    query_text = (search_query or '').strip()
    if query_text:
        qs = qs.filter(
            Q(payment_status__participant__name__icontains=query_text)
            | Q(payment_status__participant__email__icontains=query_text)
            | Q(payment_status__participant__phone__icontains=query_text)
            | Q(payment_status__participant__organization__icontains=query_text)
            | Q(payment_status__merchant_invoice_number__icontains=query_text)
        )
    return qs


def _feedback_question_display_parts(question):
    if question.question_type == FeedbackQuestion.RADIO:
        return {
            'rows': [],
            'columns': question.get_columns() or ['Very satisfied', 'Satisfied', 'Neutral', 'Needs improvement'],
        }
    if question.question_type == FeedbackQuestion.MATRIX:
        return {
            'rows': question.get_rows() or ['Venue', 'Food', 'Sessions'],
            'columns': question.get_columns() or ['1', '2', '3', '4', '5'],
        }
    return {
        'rows': [],
        'columns': [],
    }


def _build_feedback_report_data(event, search_query=''):
    questions = list(event.feedback_questions.all().order_by('order', 'id'))
    submitted_participant_ids = FeedbackResponse.objects.filter(event=event).values_list('participant_id', flat=True).distinct()
    participants_qs = Participant.objects.filter(event=event, id__in=submitted_participant_ids).select_related(
        'payment_statuses',
        'payment_statuses__registration_kit',
    ).order_by('name', 'id')
    query_text = (search_query or '').strip()
    if query_text:
        participants_qs = participants_qs.filter(
            Q(name__icontains=query_text)
            | Q(email__icontains=query_text)
            | Q(phone__icontains=query_text)
            | Q(organization__icontains=query_text)
            | Q(payment_statuses__merchant_invoice_number__icontains=query_text)
        )

    participants = list(participants_qs)
    response_qs = FeedbackResponse.objects.filter(
        event=event,
        participant__in=participants,
    ).select_related('question', 'participant').order_by('participant_id', 'question__order', 'question_id', 'id')

    answers_by_participant = defaultdict(lambda: defaultdict(list))
    question_response_values = defaultdict(list)
    question_answered_participants = defaultdict(set)
    for response in response_qs:
        clean_value = (response.response or '').strip()
        answers_by_participant[response.participant_id][response.question_id].append(clean_value)
        if clean_value:
            question_response_values[response.question_id].append(clean_value)
            question_answered_participants[response.question_id].add(response.participant_id)

    rows = []
    insights = []
    totals = {
        'participants': len(participants),
        'submitted': len(participants),
        'pending': 0,
        'approved': 0,
        'paid': 0,
        'issued': 0,
    }

    total_submitted_participants = len(participants)

    for question in questions:
        display_parts = _feedback_question_display_parts(question)
        response_values = question_response_values.get(question.id, [])
        answered_participants = len(question_answered_participants.get(question.id, set()))
        insight = {
            'question': question,
            'kind': question.question_type,
            'response_count': len(response_values),
            'answered_participants': answered_participants,
            'submitted_participants': total_submitted_participants,
        }

        if question.question_type == FeedbackQuestion.RADIO:
            option_counts = Counter()
            known_options = list(display_parts['columns'])
            extra_options = []
            for value in response_values:
                option_counts[value] += 1
                if value not in known_options and value not in extra_options:
                    extra_options.append(value)
            bars = []
            for option in known_options + extra_options:
                count = option_counts.get(option, 0)
                percent = round((count / answered_participants) * 100) if answered_participants else 0
                bars.append({
                    'label': option,
                    'count': count,
                    'percent': percent,
                })
            insight['bars'] = bars
            insight['has_data'] = any(bar['count'] for bar in bars)

        elif question.question_type == FeedbackQuestion.MATRIX:
            row_labels = list(display_parts['rows'])
            column_labels = list(display_parts['columns'])
            matrix_counts = defaultdict(Counter)
            extra_rows = []
            extra_columns = []
            for value in response_values:
                if ':' in value:
                    row_label, column_label = [part.strip() for part in value.split(':', 1)]
                else:
                    row_label, column_label = value.strip(), ''
                if row_label:
                    matrix_counts[row_label][column_label] += 1
                    if row_label not in row_labels and row_label not in extra_rows:
                        extra_rows.append(row_label)
                    if column_label and column_label not in column_labels and column_label not in extra_columns:
                        extra_columns.append(column_label)
            all_rows = row_labels + extra_rows
            all_columns = column_labels + extra_columns
            matrix_rows = []
            for row_label in all_rows:
                row_total = sum(matrix_counts[row_label].values())
                cells = []
                for column_label in all_columns:
                    count = matrix_counts[row_label].get(column_label, 0)
                    intensity = 28 + round((count / row_total) * 62) if row_total and count else 0
                    cells.append({
                        'label': column_label,
                        'count': count,
                        'intensity': intensity,
                        'use_light_text': intensity >= 55,
                    })
                matrix_rows.append({
                    'label': row_label,
                    'total': row_total,
                    'cells': cells,
                })
            insight['matrix_columns'] = all_columns
            insight['matrix_rows'] = matrix_rows
            insight['has_data'] = any(row['total'] for row in matrix_rows)

        else:
            text_answers = []
            for value in response_values:
                if value and value not in text_answers:
                    text_answers.append(value)
            insight['text_answers'] = text_answers
            insight['has_data'] = bool(text_answers)

        insights.append(insight)

    for participant in participants:
        payment_status = getattr(participant, 'payment_statuses', None)
        registration_kit = getattr(payment_status, 'registration_kit', None) if payment_status else None
        payment_completed = bool(payment_status and payment_status.status in ['paid', 'completed'])
        kit_issued = bool(registration_kit and registration_kit.status == 'issued')
        participant_answers = answers_by_participant.get(participant.id, {})
        question_answers = []
        answered_questions = 0

        for question in questions:
            answer_values = [value for value in participant_answers.get(question.id, []) if value]
            if answer_values:
                answered_questions += 1
            question_answers.append({
                'question': question,
                'values': answer_values,
                'display_value': ' | '.join(answer_values) if answer_values else '',
                'has_answer': bool(answer_values),
            })

        if participant.approved:
            totals['approved'] += 1
        if payment_completed:
            totals['paid'] += 1
        if kit_issued:
            totals['issued'] += 1

        rows.append({
            'participant': participant,
            'payment_status': payment_status,
            'registration_kit': registration_kit,
            'invoice_number': payment_status.merchant_invoice_number if payment_status else '',
            'payment_completed': payment_completed,
            'kit_issued': kit_issued,
            'feedback_submitted': True,
            'answered_questions': answered_questions,
            'question_answers': question_answers,
        })

    return {
        'questions': questions,
        'rows': rows,
        'insights': insights,
        'totals': totals,
    }


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


def _render_html_template_to_image(template_name, context, output_path, capture_width=1632, capture_height=1155, image_format='JPEG'):
    output = Path(output_path)
    render_dir = output.parent / 'html_render'
    render_dir.mkdir(parents=True, exist_ok=True)
    html_path = render_dir / f"{output.stem}.html"
    png_path = render_dir / f"{output.stem}.png"
    chrome_profile = Path(tempfile.mkdtemp(prefix=f"{output.stem}_chrome_"))
    chrome_home = Path(tempfile.mkdtemp(prefix=f"{output.stem}_home_"))
    chrome_config = chrome_home / 'config'
    chrome_cache = chrome_home / 'cache'
    chrome_runtime = chrome_home / 'runtime'
    for path in (chrome_config, chrome_cache, chrome_runtime):
        path.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_to_string(template_name, context), encoding='utf-8')

    chrome = _get_chrome_executable()
    if not chrome:
        raise RuntimeError('Chrome/Edge was not found on the server, so the HTML design cannot be rendered to an image.')

    file_url = html_path.resolve().as_uri()
    command = [
        chrome,
        '--headless=new',
        '--no-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        '--disable-crash-reporter',
        '--disable-crashpad',
        '--disable-breakpad',
        '--disable-features=Crashpad',
        '--no-first-run',
        '--no-default-browser-check',
        '--hide-scrollbars',
        '--allow-file-access-from-files',
        f'--user-data-dir={chrome_profile.resolve()}',
        f'--window-size={capture_width},{capture_height}',
        f'--screenshot={png_path.resolve()}',
        file_url,
    ]
    env = os.environ.copy()
    env['HOME'] = str(chrome_home.resolve())
    env['XDG_CONFIG_HOME'] = str(chrome_config.resolve())
    env['XDG_CACHE_HOME'] = str(chrome_cache.resolve())
    env['XDG_RUNTIME_DIR'] = str(chrome_runtime.resolve())
    subprocess.run(command, check=True, timeout=30, cwd=str(settings.BASE_DIR), env=env)

    image = Image.open(png_path)
    if (image_format or 'JPEG').upper() == 'PNG':
        image.save(output_path, 'PNG')
    else:
        image.convert('RGB').save(output_path, 'JPEG', quality=95)


def _render_html_template_to_pdf(template_name, context, output_path):
    output = Path(output_path)
    render_dir = output.parent / 'html_render'
    render_dir.mkdir(parents=True, exist_ok=True)
    html_path = render_dir / f"{output.stem}.html"
    pdf_path = render_dir / f"{output.stem}.pdf"
    chrome_profile = Path(tempfile.mkdtemp(prefix=f"{output.stem}_chrome_pdf_"))
    chrome_home = Path(tempfile.mkdtemp(prefix=f"{output.stem}_home_pdf_"))
    chrome_config = chrome_home / 'config'
    chrome_cache = chrome_home / 'cache'
    chrome_runtime = chrome_home / 'runtime'
    for path in (chrome_config, chrome_cache, chrome_runtime):
        path.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_to_string(template_name, context), encoding='utf-8')

    chrome = _get_chrome_executable()
    if not chrome:
        raise RuntimeError('Chrome/Edge was not found on the server, so the HTML design cannot be rendered to PDF.')

    file_url = html_path.resolve().as_uri()
    command = [
        chrome,
        '--headless=new',
        '--no-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        '--disable-crash-reporter',
        '--disable-crashpad',
        '--disable-breakpad',
        '--disable-features=Crashpad',
        '--no-first-run',
        '--no-default-browser-check',
        '--allow-file-access-from-files',
        '--print-to-pdf-no-header',
        '--no-pdf-header-footer',
        f'--user-data-dir={chrome_profile.resolve()}',
        f'--print-to-pdf={pdf_path.resolve()}',
        file_url,
    ]
    env = os.environ.copy()
    env['HOME'] = str(chrome_home.resolve())
    env['XDG_CONFIG_HOME'] = str(chrome_config.resolve())
    env['XDG_CACHE_HOME'] = str(chrome_cache.resolve())
    env['XDG_RUNTIME_DIR'] = str(chrome_runtime.resolve())
    subprocess.run(command, check=True, timeout=30, cwd=str(settings.BASE_DIR), env=env)
    shutil.copyfile(pdf_path, output_path)


def _render_certificate_html_to_jpeg(template_name, context, output_path, capture_width=1632, capture_height=1155):
    _render_html_template_to_image(template_name, context, output_path, capture_width=capture_width, capture_height=capture_height, image_format='JPEG')


def _render_html_certificate_to_jpeg(request, participant, event, certificate, output_path):
    from website.models import SiteSettings

    signatories = _get_certificate_signatories(certificate)
    if not signatories:
        raise ValueError("No signatories configured for this HTML certificate.")

    base_url = request.build_absolute_uri('/')
    context = {
        'participant_name': participant.name,
        'site_settings': SiteSettings.objects.first(),
        'event': event,
        'certificate': certificate,
        'signatories': signatories,
        'signature_count': len(signatories),
        'capture_mode': True,
        'base_url': base_url,
    }
    _render_certificate_html_to_jpeg('certificate_design/certificate.html', context, output_path)


def _render_speaker_certificate_to_jpeg(request, person, event, certificate, output_path):
    from website.models import SiteSettings

    signatories = _get_certificate_signatories(certificate)
    if not signatories:
        raise ValueError("No signatories configured for this HTML certificate.")

    base_url = request.build_absolute_uri('/')
    context = {
        'participant_name': person.name,
        'site_settings': SiteSettings.objects.first(),
        'event': event,
        'certificate': certificate,
        'signatories': signatories,
        'signature_count': len(signatories),
        'capture_mode': True,
        'base_url': base_url,
        'speaker_title': _speaker_certificate_title(certificate),
        'speaker_body': _render_speaker_certificate_body(certificate, event),
    }
    _render_certificate_html_to_jpeg('certificate_design/speaker_certificate.html', context, output_path)


def _chest_card_base_url(request=None):
    if request is not None:
        return request.build_absolute_uri('/')
    site_url = (getattr(settings, 'SITE_URL', '') or 'http://127.0.0.1:8000').strip()
    return f"{site_url.rstrip('/')}/"


def _render_chest_card_html_to_png(request, participant, event, design, payment_status, output_path):
    base_url = _chest_card_base_url(request)
    capture_width = _mm_to_px(design.width_mm, design.dpi)
    capture_height = _mm_to_px(design.height_mm, design.dpi)
    from website.models import SiteSettings

    context = {
        'participant_name': participant.name,
        'participant_organization': participant.organization or '',
        'event': event,
        'design': design,
        'site_settings': SiteSettings.objects.first(),
        'badge_title': (design.badge_title or '').strip() or 'Participant',
        'invoice_number': payment_status.merchant_invoice_number if payment_status else '',
        'qr_code_url': payment_status.qr_code.url if payment_status and payment_status.qr_code else '',
        'capture_mode': True,
        'base_url': base_url,
    }
    _render_html_template_to_image('chest_card_design/chest_card.html', context, output_path, capture_width=capture_width, capture_height=capture_height, image_format='PNG')


def _render_bulk_chest_card_html_to_pdf(request, event, design, payments, output_path):
    from website.models import SiteSettings

    base_url = _chest_card_base_url(request)
    items = []
    for payment_status in payments:
        participant = payment_status.participant
        items.append({
            'participant_name': participant.name,
            'participant_organization': participant.organization or '',
            'invoice_number': payment_status.merchant_invoice_number or '',
            'qr_code_url': payment_status.qr_code.url if payment_status.qr_code else '',
        })

    context = {
        'event': event,
        'design': design,
        'site_settings': SiteSettings.objects.first(),
        'badge_title': (design.badge_title or '').strip() or 'Participant',
        'capture_mode': False,
        'pdf_mode': True,
        'base_url': base_url,
        'items': items,
    }
    _render_html_template_to_pdf('chest_card_design/chest_card_bulk.html', context, output_path)


def _render_chest_card_html_to_pdf(request, participant, event, design, payment_status, output_path):
    from website.models import SiteSettings

    base_url = _chest_card_base_url(request)
    context = {
        'participant_name': participant.name,
        'participant_organization': participant.organization or '',
        'event': event,
        'design': design,
        'site_settings': SiteSettings.objects.first(),
        'badge_title': (design.badge_title or '').strip() or 'Participant',
        'invoice_number': payment_status.merchant_invoice_number if payment_status else '',
        'qr_code_url': payment_status.qr_code.url if payment_status and payment_status.qr_code else '',
        'capture_mode': False,
        'pdf_mode': True,
        'base_url': base_url,
    }
    _render_html_template_to_pdf('chest_card_design/chest_card.html', context, output_path)


def _render_png_badge_to_pdf(png_path, pdf_path, width_mm, height_mm):
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas

    canvas = pdf_canvas.Canvas(pdf_path, pagesize=(float(width_mm) * mm, float(height_mm) * mm))
    canvas.drawImage(str(png_path), 0, 0, width=float(width_mm) * mm, height=float(height_mm) * mm, preserveAspectRatio=False, mask='auto')
    canvas.showPage()
    canvas.save()


def _render_overlay_chest_card_to_png(participant, design, payment_status, output_path):
    if not payment_status or not payment_status.qr_code:
        raise ValueError('QR code is required before generating an overlay chest card.')

    width_px = _mm_to_px(design.width_mm, design.dpi)
    height_px = _mm_to_px(design.height_mm, design.dpi)
    if design.overlay_reference_image:
        canvas = Image.open(design.overlay_reference_image.path).convert('RGBA').resize((width_px, height_px))
    else:
        canvas = Image.new('RGBA', (width_px, height_px), (255, 255, 255, 0))

    qr_size_px = _mm_to_px(design.qr_size_mm, design.dpi)
    qr_x_px = _mm_to_px(design.qr_x_mm, design.dpi)
    qr_y_px = _mm_to_px(design.qr_y_mm, design.dpi)
    qr_image = Image.open(payment_status.qr_code.path).convert('RGBA').resize((qr_size_px, qr_size_px))
    canvas.paste(qr_image, (qr_x_px, qr_y_px), qr_image)

    draw = ImageDraw.Draw(canvas)
    box_x = _mm_to_px(design.name_x_mm, design.dpi)
    box_y = _mm_to_px(design.name_y_mm, design.dpi)
    box_width = _mm_to_px(design.name_width_mm, design.dpi)
    box_height = _mm_to_px(design.name_height_mm, design.dpi)
    font, lines, line_height = _fit_text_to_box(draw, participant.name, box_width, box_height, design.font_size_pt)
    total_height = (line_height * len(lines)) + max(len(lines) - 1, 0) * 4
    current_y = box_y + max((box_height - total_height) // 2, 0)
    fill = _hex_to_rgb(design.font_color)

    for line in lines:
        bbox = draw.textbbox((0, 0), line or ' ', font=font)
        line_width = bbox[2] - bbox[0]
        if design.text_align == ChestCardDesign.TEXT_ALIGN_LEFT:
            current_x = box_x
        elif design.text_align == ChestCardDesign.TEXT_ALIGN_RIGHT:
            current_x = box_x + max(box_width - line_width, 0)
        else:
            current_x = box_x + max((box_width - line_width) // 2, 0)
        draw.text((current_x, current_y), line, font=font, fill=fill)
        current_y += line_height + 4

    canvas.save(output_path, 'PNG')


def _media_relative_path(file_path):
    relative_path = os.path.relpath(file_path, settings.MEDIA_ROOT)
    return relative_path.replace('\\', '/')


def _get_or_create_chest_card(participant, payment_status=None):
    if not participant:
        return None
    chest_card, _ = ChestCard.objects.get_or_create(
        participant=participant,
        defaults={
            'event': participant.event,
            'payment_status': payment_status,
        },
    )
    updates = []
    if chest_card.event_id != participant.event_id:
        chest_card.event = participant.event
        updates.append('event')
    if payment_status and chest_card.payment_status_id != payment_status.id:
        chest_card.payment_status = payment_status
        updates.append('payment_status')
    if updates:
        chest_card.save(update_fields=updates + ['updated_at'])
    return chest_card


def _mark_event_chest_cards_outdated(event):
    if not event:
        return
    ChestCard.objects.filter(event=event).exclude(status=ChestCard.STATUS_PENDING).update(status=ChestCard.STATUS_OUTDATED)


def ensure_participant_chest_card_generated(participant, request=None):
    if not participant:
        return None

    payment_status = PaymentStatus.objects.filter(participant=participant, event=participant.event).first()
    chest_card = _get_or_create_chest_card(participant, payment_status=payment_status)
    if not chest_card:
        return None

    if not participant.approved or participant.denied:
        chest_card.status = ChestCard.STATUS_PENDING
        chest_card.last_error = None
        chest_card.save(update_fields=['status', 'last_error', 'updated_at'])
        return None

    if not payment_status or payment_status.status not in ['paid', 'completed']:
        chest_card.status = ChestCard.STATUS_PENDING
        chest_card.last_error = None
        chest_card.save(update_fields=['status', 'last_error', 'updated_at'])
        return None

    if not payment_status.qr_code:
        chest_card.status = ChestCard.STATUS_PENDING
        chest_card.last_error = 'QR code is not ready yet.'
        chest_card.save(update_fields=['status', 'last_error', 'updated_at'])
        return None

    design = ChestCardDesign.objects.filter(event=participant.event).first()
    if not design:
        chest_card.status = ChestCard.STATUS_PENDING
        chest_card.last_error = 'Chest card design is not configured for this event.'
        chest_card.save(update_fields=['status', 'last_error', 'updated_at'])
        return None

    try:
        output_paths = {
            'pdf': _generate_chest_card_file(request, participant, participant.event, design, output_format='pdf'),
        }
        if design.design_mode == ChestCardDesign.MODE_OVERLAY:
            output_paths['png'] = _generate_chest_card_file(request, participant, participant.event, design, output_format='png')

        chest_card.payment_status = payment_status
        chest_card.generated_pdf = _media_relative_path(output_paths['pdf'])
        if output_paths.get('png'):
            chest_card.generated_png = _media_relative_path(output_paths['png'])
        chest_card.generated_at = timezone.now()
        chest_card.design_updated_at = design.updated_at
        chest_card.status = ChestCard.STATUS_GENERATED
        chest_card.last_error = None
        chest_card.save()
        return output_paths
    except Exception as exc:
        chest_card.status = ChestCard.STATUS_FAILED
        chest_card.last_error = str(exc)
        chest_card.save(update_fields=['status', 'last_error', 'updated_at'])
        raise


def _chest_card_cache_timestamp(*values):
    latest = 0.0
    for value in values:
        if not value:
            continue
        if hasattr(value, 'timestamp'):
            latest = max(latest, value.timestamp())
    return latest


def _is_cached_chest_card_current(output_path, design, payment_status):
    if not os.path.exists(output_path):
        return False
    required_ts = _chest_card_cache_timestamp(
        getattr(design, 'updated_at', None),
        getattr(payment_status, 'updated_at', None),
    )
    if not required_ts:
        return True
    return os.path.getmtime(output_path) >= required_ts


def _sync_chest_card_file_record(participant, event, payment_status, design, output_path, output_format):
    chest_card = _get_or_create_chest_card(participant, payment_status=payment_status)
    if not chest_card:
        return

    file_timestamp = datetime.fromtimestamp(os.path.getmtime(output_path), tz=timezone.get_current_timezone()) if os.path.exists(output_path) else timezone.now()
    chest_card.event = event
    chest_card.payment_status = payment_status
    if (output_format or 'pdf').lower() == 'png':
        chest_card.generated_png = _media_relative_path(output_path)
    else:
        chest_card.generated_pdf = _media_relative_path(output_path)
        if design.design_mode == ChestCardDesign.MODE_HTML:
            chest_card.generated_png = None
    chest_card.generated_at = file_timestamp
    chest_card.design_updated_at = getattr(design, 'updated_at', None)
    chest_card.status = ChestCard.STATUS_GENERATED
    chest_card.last_error = None
    chest_card.save()


def _generate_chest_card_file(request, participant, event, design, output_format='pdf'):
    payment_status = PaymentStatus.objects.filter(participant=participant, event=event).first()
    if not payment_status:
        raise ValueError('No payment row was found for this participant and event.')
    if not payment_status.qr_code:
        raise ValueError('Generate the participant QR code first from Payment Center before creating the chest card.')

    event_slug = slugify(f'{event.name}-{event.year}') or f'event-{event.id}'
    output_dir = os.path.join(settings.MEDIA_ROOT, 'chest_cards', 'generated', event_slug)
    os.makedirs(output_dir, exist_ok=True)

    if (output_format or 'pdf').lower() == 'png':
        output_filename = _chest_card_output_filename(participant.name)
        output_path = os.path.join(output_dir, output_filename)
        if _is_cached_chest_card_current(output_path, design, payment_status):
            _sync_chest_card_file_record(participant, event, payment_status, design, output_path, 'png')
            return output_path
        if design.design_mode == ChestCardDesign.MODE_HTML:
            _render_chest_card_html_to_png(request, participant, event, design, payment_status, output_path)
        else:
            _render_overlay_chest_card_to_png(participant, design, payment_status, output_path)
        _sync_chest_card_file_record(participant, event, payment_status, design, output_path, 'png')
        return output_path

    output_filename = _chest_card_pdf_output_filename(participant.name)
    output_path = os.path.join(output_dir, output_filename)
    if _is_cached_chest_card_current(output_path, design, payment_status):
        _sync_chest_card_file_record(participant, event, payment_status, design, output_path, 'pdf')
        return output_path
    if design.design_mode == ChestCardDesign.MODE_HTML:
        _render_chest_card_html_to_pdf(request, participant, event, design, payment_status, output_path)
    else:
        temp_png_path = os.path.join(output_dir, _chest_card_output_filename(participant.name))
        if not _is_cached_chest_card_current(temp_png_path, design, payment_status):
            _render_overlay_chest_card_to_png(participant, design, payment_status, temp_png_path)
            _sync_chest_card_file_record(participant, event, payment_status, design, temp_png_path, 'png')
        _render_png_badge_to_pdf(temp_png_path, output_path, design.width_mm, design.height_mm)
    _sync_chest_card_file_record(participant, event, payment_status, design, output_path, 'pdf')
    return output_path


def _render_chest_card_png_to_bulk_pdf(output_path, png_paths, width_mm, height_mm):
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas

    canvas = pdf_canvas.Canvas(output_path, pagesize=(float(width_mm) * mm, float(height_mm) * mm))
    for png_path in png_paths:
        canvas.setPageSize((float(width_mm) * mm, float(height_mm) * mm))
        canvas.drawImage(str(png_path), 0, 0, width=float(width_mm) * mm, height=float(height_mm) * mm, preserveAspectRatio=False, mask='auto')
        canvas.showPage()
    canvas.save()
    return output_path


def _build_chest_card_bulk_pdf(request, event, design, payments):
    if not payments:
        raise ValueError('No QR-ready participants are available for bulk PDF generation.')

    event_slug = slugify(f'{event.name}-{event.year}') or f'event-{event.id}'
    output_dir = os.path.join(settings.MEDIA_ROOT, 'chest_cards', 'generated', event_slug, 'bulk')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, _chest_card_bulk_pdf_output_filename(event))

    if design.design_mode == ChestCardDesign.MODE_HTML:
        _render_bulk_chest_card_html_to_pdf(request, event, design, payments, output_path)
        return output_path, len(payments)

    png_paths = []
    for payment in payments:
        png_paths.append(_generate_chest_card_file(request, payment.participant, event, design, output_format='png'))
    return _render_chest_card_png_to_bulk_pdf(output_path, png_paths, design.width_mm, design.height_mm), len(png_paths)


def _build_chest_card_vendor_zip(request, event, design, payments):
    if not payments:
        raise ValueError('No QR-ready participants are available for vendor export.')

    csv_buffer = io.StringIO()
    csv_writer = csv.writer(csv_buffer)
    csv_writer.writerow(['participant_name', 'email', 'phone', 'organization', 'invoice_number', 'pdf_file'])

    zip_buffer = io.BytesIO()
    used_names = set()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for payment in payments:
            pdf_path = _generate_chest_card_file(request, payment.participant, event, design, output_format='pdf')
            file_name = os.path.basename(pdf_path)
            if file_name in used_names:
                stem, extension = os.path.splitext(file_name)
                file_name = f'{stem}_{payment.id}{extension}'
            used_names.add(file_name)

            with open(pdf_path, 'rb') as pdf_file:
                archive.writestr(file_name, pdf_file.read())

            participant = payment.participant
            csv_writer.writerow([
                participant.name,
                participant.email,
                participant.phone,
                participant.organization or '',
                payment.merchant_invoice_number or '',
                file_name,
            ])

        archive.writestr('manifest.csv', csv_buffer.getvalue().encode('utf-8'))

    zip_buffer.seek(0)
    return zip_buffer, len(used_names)


def _generate_speaker_certificate_file(request, event, person, certificate, issued_by=None):
    speaker_certificate_logger.info(
        "Speaker certificate generation requested: event_id=%s person_id=%s issued_by=%s design_mode=%s",
        event.id if event else None,
        person.id if person else None,
        issued_by.id if issued_by else None,
        certificate.design_mode if certificate else None,
    )
    requirements = _speaker_certificate_requirements_met(person, event, certificate)
    if not requirements['eligible']:
        blockers = []
        if certificate.speaker_require_feedback and not requirements['has_feedback']:
            blockers.append('feedback')
        if certificate.speaker_require_kit_issue and not requirements['has_kit']:
            blockers.append('kit issue')
        blocker_text = ' and '.join(blockers) or 'speaker eligibility requirements'
        speaker_certificate_logger.warning(
            "Speaker certificate generation blocked: event_id=%s person_id=%s blockers=%s",
            event.id if event else None,
            person.id if person else None,
            blocker_text,
        )
        raise ValueError(f"{person.name} is not eligible yet. Missing {blocker_text}.")

    output_filename = _speaker_certificate_output_filename(person.name)
    output_path = os.path.join(settings.MEDIA_ROOT, 'certificates', 'speakers', 'generated', output_filename)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if certificate.design_mode == Certificate.DESIGN_MODE_HTML:
        _render_speaker_certificate_to_jpeg(request, person, event, certificate, output_path)
    else:
        if not certificate.speaker_upload_image:
            speaker_certificate_logger.warning(
                "Speaker certificate generation failed: missing uploaded speaker image event_id=%s person_id=%s",
                event.id if event else None,
                person.id if person else None,
            )
            raise ValueError("No uploaded speaker certificate image configured for this event.")
        image = Image.open(certificate.speaker_upload_image.path)
        draw = ImageDraw.Draw(image)
        try:
            title_font = ImageFont.truetype("arial.ttf", 34)
            name_font = ImageFont.truetype("arial.ttf", 42)
        except OSError:
            title_font = ImageFont.load_default()
            name_font = ImageFont.load_default()
        draw.text((470, 365), _speaker_certificate_title(certificate), font=title_font, fill="black")
        draw.text((520, 470), person.name, font=name_font, fill="black")
        image.save(output_path)

    profile = requirements['profile']
    record, _ = SpeakerCertificate.objects.get_or_create(
        event=event,
        program_person=person,
        defaults={
            'profile': profile,
            'issued_by': issued_by,
        },
    )
    update_fields = []
    relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT).replace('\\', '/')
    if record.generated_file.name != relative_path:
        record.generated_file = relative_path
        update_fields.append('generated_file')
    if profile and record.profile_id != profile.id:
        record.profile = profile
        update_fields.append('profile')
    if issued_by and record.issued_by_id != issued_by.id:
        record.issued_by = issued_by
        update_fields.append('issued_by')
    if update_fields:
        record.save(update_fields=update_fields)
    speaker_certificate_logger.info(
        "Speaker certificate generated: certificate_id=%s event_id=%s person_id=%s file=%s profile_id=%s",
        record.id,
        event.id if event else None,
        person.id if person else None,
        record.generated_file.name,
        record.profile_id,
    )
    return record, output_path


def _speaker_certificate_rows(event, certificate, search_query=''):
    people = (
        ProgramPerson.objects.filter(
            events=event,
            item_roles__item__session__event=event,
            item_roles__role__in=[ProgramItemFaculty.ROLE_SPEAKER, ProgramItemFaculty.ROLE_PRESENTER],
        )
        .select_related('profile')
        .distinct()
        .order_by('name')
    )
    if search_query:
        people = people.filter(
            Q(name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(institution__icontains=search_query)
            | Q(profile__email__icontains=search_query)
        )
    issued_map = {
        row.program_person_id: row
        for row in SpeakerCertificate.objects.filter(event=event).select_related('profile', 'program_person')
    }
    latest_email_log_map = {}
    if speaker_certificate_email_log_table_ready():
        for log in SpeakerCertificateEmailLog.objects.filter(event=event).select_related('sent_by').order_by('certificate_id', '-created_at'):
            latest_email_log_map.setdefault(log.certificate_id, log)
    rows = []
    for person in people:
        requirements = _speaker_certificate_requirements_met(person, event, certificate)
        profile = requirements['profile']
        issued_record = issued_map.get(person.id)
        rows.append({
            'person': person,
            'profile': profile,
            'participant': requirements['participant'],
            'email': (profile.email if profile else '') or (person.email or ''),
            'role_label': _speaker_outreach_role_label(person, event),
            'has_feedback': requirements['has_feedback'],
            'has_kit': requirements['has_kit'],
            'eligible': requirements['eligible'],
            'issued_record': issued_record,
            'latest_email_log': latest_email_log_map.get(issued_record.id) if issued_record else None,
        })
    return rows


def generate_certificate(request, event_id):
    participant = get_object_or_404(Participant, user=request.user, event_id=event_id)
    event = get_object_or_404(Event, id=event_id)
    requirements = _participant_certificate_requirements_met(participant, event)

    if not requirements['is_approved']:
        return JsonResponse({
            'success': False,
            'error': 'Your registration for this event has not been approved yet.',
        }, status=403)

    if not requirements['payment_completed']:
        return JsonResponse({
            'success': False,
            'error': 'Your payment is not completed yet.',
        }, status=403)

    registration_kit = requirements['registration_kit']
    if not requirements['kit_issued'] or not registration_kit:
        return JsonResponse({
            'success': False,
            'error': 'Your registration kit has not been issued yet.',
        }, status=403)

    if not requirements['has_feedback']:
        return JsonResponse({
            'success': False,
            'error': 'Please submit your feedback form before downloading the certificate.',
        }, status=403)

    participant_name = participant.name
    certificate = get_object_or_404(Certificate, event=event)
    output_filename = _certificate_output_filename(participant_name)
    output_path = os.path.join(settings.MEDIA_ROOT, 'certificates', output_filename)

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
    event = get_object_or_404(Event, id=event_id)

    if event.event_status != 'closed':
        return HttpResponseForbidden("Feedback for this event is not available now.")

    participant = Participant.objects.filter(user=request.user, event=event).first()
    if not participant:
        return render(request, 'feedback_access_denied.html', {'event': event})

    requirements = _participant_certificate_requirements_met(participant, event)
    registration_kit = requirements['registration_kit']
    if not requirements['is_approved'] or not requirements['payment_completed'] or not requirements['kit_issued'] or not registration_kit:
        return render(request, 'feedback_access_denied.html', {'event': event})

    questions = event.feedback_questions.all()  # type: ignore[attr-defined]
    for question in questions:
        if question.question_type == FeedbackQuestion.RADIO:
            question.display_columns = question.get_columns() or ['Very satisfied', 'Satisfied', 'Neutral', 'Needs improvement']
            question.display_rows = []
        elif question.question_type == FeedbackQuestion.MATRIX:
            question.display_rows = question.get_rows() or ['Venue', 'Food', 'Sessions']
            question.display_columns = question.get_columns() or ['1', '2', '3', '4', '5']
        else:
            question.display_rows = []
            question.display_columns = []

    if request.method == 'POST':
        for question in questions:
            response_key = f"response_{question.id}"
            if question.question_type == 'matrix':
                matrix_rows = getattr(question, 'display_rows', None) or question.get_rows()
                for index, row in enumerate(matrix_rows, start=1):
                    row_response = request.POST.get(f"{response_key}_{index}", None)
                    if row_response:
                        FeedbackResponse.objects.create(
                            participant=registration_kit.payment_status.participant,
                            event=event,
                            question=question,
                            response=f"{row}: {row_response}"
                        )
            else:
                user_response = request.POST.get(response_key, None)
                if user_response:
                    FeedbackResponse.objects.create(
                        participant=registration_kit.payment_status.participant,
                        event=event,
                        question=question,
                        response=user_response
                    )
        return render(request, 'feedback_success.html', {'event': event})

    return render(request, 'event_feedback.html', {'event': event, 'questions': questions})






# Admin Dashboard Starts Here ------------------------------------------------------------------------------------#

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import render
from django.db import transaction
from django.db.models import Count, Sum, Q
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
    RegistrationKit,
    BulkEmail,
    BulkEmailRecipient,
    BulkEmailSendLog,
    EmailGroup,
)
from django.core.paginator import Paginator
from urllib.parse import urlencode
from collections import Counter, defaultdict


UNPAID_PAYMENT_STATUSES = ['unpaid', 'pending', 'failed', 'initiated']
PAID_PAYMENT_STATUSES = ['completed']


def admin_changelist_url(model, query_params=None):
    opts = model._meta
    url = reverse(f'admin:{opts.app_label}_{opts.model_name}_changelist')
    if query_params:
        return f'{url}?{urlencode(query_params, doseq=True)}'
    return url


def dashboard_workflow_url(view_name, query_params=None):
    url = reverse(view_name)
    cleaned_params = {
        key: value
        for key, value in (query_params or {}).items()
        if value not in (None, '')
    }
    if cleaned_params:
        return f'{url}?{urlencode(cleaned_params, doseq=True)}'
    return url


def admin_change_url(obj):
    opts = obj._meta
    try:
        return reverse(f'admin:{opts.app_label}_{opts.model_name}_change', args=[obj.pk])
    except NoReverseMatch:
        return ''


def dashboard_log_action(request, obj, action_flag=CHANGE, message='Updated from dashboard workflow.'):
    if not obj or not getattr(request, 'user', None) or not request.user.is_authenticated:
        return
    try:
        content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        LogEntry.objects.create(
            user_id=request.user.pk,
            content_type_id=content_type.pk,
            object_id=str(obj.pk),
            object_repr=str(obj)[:200],
            action_flag=action_flag,
            change_message=message,
        )
    except Exception as exc:
        logger.exception("Could not write dashboard audit log for %s: %s", obj, exc)



def _build_exact_match_q(field_name, values):
    query = Q()
    for value in values:
        if value not in (None, ''):
            query |= Q(**{f'{field_name}__iexact': value})
    return query


def _journey_candidate_key(profile=None, user=None, email='', phone='', name=''):
    if profile:
        return f'profile:{profile.id}'
    if user:
        return f'user:{user.id}'
    if email:
        return f'email:{email.strip().lower()}'
    if phone:
        return f'phone:{phone.strip()}'
    return f'name:{name.strip().lower()}'


def _append_journey_item(items, when, label, title, detail='', tone='neutral', workflow_url='', admin_url=''):
    if not when:
        return
    items.append({
        'at': when,
        'label': label,
        'title': title,
        'detail': detail,
        'tone': tone,
        'workflow_url': workflow_url,
        'admin_url': admin_url,
    })


def _journey_candidates(search_query):
    query_text = (search_query or '').strip()
    if not query_text:
        return []

    buckets = {}

    def add_candidate(profile=None, user=None, name='', email='', phone='', source=''):
        key = _journey_candidate_key(profile=profile, user=user, email=email, phone=phone, name=name)
        row = buckets.setdefault(key, {
            'profile': None,
            'user': None,
            'name': '',
            'emails': set(),
            'phones': set(),
            'sources': set(),
        })
        if profile and not row['profile']:
            row['profile'] = profile
        if user and not row['user']:
            row['user'] = user
        if name and not row['name']:
            row['name'] = name
        if email:
            row['emails'].add(email.strip().lower())
        if phone:
            row['phones'].add(phone.strip())
        if source:
            row['sources'].add(source)

    for profile in UserProfile.objects.select_related('user', 'member').filter(
        Q(name__icontains=query_text) | Q(email__icontains=query_text) | Q(phone__icontains=query_text)
    )[:12]:
        add_candidate(profile=profile, user=profile.user, name=profile.name, email=profile.email, phone=profile.phone, source='Website profile')

    for participant in Participant.objects.select_related('user', 'user__userprofile').filter(
        Q(name__icontains=query_text) | Q(email__icontains=query_text) | Q(phone__icontains=query_text) | Q(organization__icontains=query_text)
    ).order_by('-created_at')[:18]:
        add_candidate(profile=getattr(participant.user, 'userprofile', None), user=participant.user, name=participant.name, email=participant.email, phone=participant.phone, source='Event participant')

    for attendee in CorporateEventAttendee.objects.select_related(
        'matched_user',
        'matched_user__userprofile',
        'participant__user',
        'participant__user__userprofile',
    ).filter(
        Q(name__icontains=query_text) | Q(email__icontains=query_text) | Q(phone__icontains=query_text) | Q(organization__icontains=query_text)
    ).order_by('-created_at')[:18]:
        matched_user = attendee.matched_user or getattr(attendee.participant, 'user', None)
        add_candidate(
            profile=getattr(matched_user, 'userprofile', None) if matched_user else None,
            user=matched_user,
            name=attendee.name,
            email=attendee.email,
            phone=attendee.phone,
            source='Corporate attendee',
        )

    for account in CorporateAccount.objects.select_related('user', 'user__userprofile').filter(
        Q(company_name__icontains=query_text) | Q(contact_name__icontains=query_text) | Q(email__icontains=query_text) | Q(phone__icontains=query_text)
    )[:12]:
        add_candidate(profile=getattr(account.user, 'userprofile', None), user=account.user, name=account.contact_name or account.company_name, email=account.email, phone=account.phone, source='Corporate account')

    for access_request in CorporateAccountRequest.objects.filter(
        Q(company_name__icontains=query_text) | Q(contact_name__icontains=query_text) | Q(email__icontains=query_text) | Q(phone__icontains=query_text)
    ).order_by('-created_at')[:12]:
        add_candidate(name=access_request.contact_name or access_request.company_name, email=access_request.email, phone=access_request.phone, source='Corporate access request')

    results = []
    for key, row in buckets.items():
        profile = row['profile']
        user = row['user'] or getattr(profile, 'user', None)
        emails = sorted(row['emails'])
        results.append({
            'key': key,
            'profile': profile,
            'user': user,
            'name': row['name'] or getattr(profile, 'name', '') or (emails[0] if emails else 'Unknown person'),
            'emails': emails,
            'phones': sorted(row['phones']),
            'sources': sorted(row['sources']),
        })

    results.sort(key=lambda item: (item['name'].lower(), item['emails'][0] if item['emails'] else ''))
    return results[:10]



def _select_journey_candidates(candidates, selected_key=''):
    if not candidates:
        return []
    if selected_key:
        return [candidate for candidate in candidates if candidate.get('key') == selected_key]
    if len(candidates) == 1:
        return candidates
    return []


def _build_journey_record(candidate):
    from website.models import Member, MembershipPayment, PendingEventIntent

    profile = candidate.get('profile')
    user = candidate.get('user') or getattr(profile, 'user', None)
    emails = candidate.get('emails', [])
    phones = candidate.get('phones', [])
    user_ids = [user.id] if user else []
    profile_ids = [profile.id] if profile else []

    participant_match = Q()
    if user_ids:
        participant_match |= Q(user_id__in=user_ids)
    if emails:
        participant_match |= _build_exact_match_q('email', emails)
    if phones:
        participant_match |= Q(phone__in=phones)

    profile_match = Q()
    if profile_ids:
        profile_match |= Q(user_profile_id__in=profile_ids)
    if emails:
        profile_match |= _build_exact_match_q('user_profile__email', emails)
    if phones:
        profile_match |= Q(user_profile__phone__in=phones)

    corporate_match = Q()
    if user_ids:
        corporate_match |= Q(matched_user_id__in=user_ids)
    if emails:
        corporate_match |= _build_exact_match_q('email', emails)
    if phones:
        corporate_match |= Q(phone__in=phones)

    participants = Participant.objects.none()
    if participant_match:
        participants = Participant.objects.filter(participant_match).select_related(
            'event',
            'user',
            'corporate_attendee__registration__corporate_account',
        ).order_by('-created_at').distinct()

    members = Member.objects.none()
    membership_payments = MembershipPayment.objects.none()
    intents = PendingEventIntent.objects.none()
    if profile_match:
        members = Member.objects.filter(profile_match).select_related('user_profile', 'membership_type').order_by('-updated_at').distinct()
        membership_payments = MembershipPayment.objects.filter(profile_match).select_related('user_profile', 'membership_type').order_by('-updated_at').distinct()
        intents = PendingEventIntent.objects.filter(profile_match).select_related('user_profile', 'event').order_by('-updated_at').distinct()

    participant_payments = PaymentStatus.objects.filter(participant__in=participants).select_related('participant', 'event').order_by('-updated_at') if participants.exists() else PaymentStatus.objects.none()
    kits = RegistrationKit.objects.filter(payment_status__participant__in=participants).select_related('event', 'payment_status__participant').order_by('-issued_at') if participants.exists() else RegistrationKit.objects.none()
    participant_emails = ParticipantEmailLog.objects.filter(participant__in=participants).select_related('event').order_by('-created_at') if participants.exists() else ParticipantEmailLog.objects.none()
    thank_you_logs = ThankYouEmailLog.objects.filter(participant__in=participants).select_related('event').order_by('-created_at') if participants.exists() else ThankYouEmailLog.objects.none()

    corporate_requests = CorporateAccountRequest.objects.none()
    corporate_accounts = CorporateAccount.objects.none()
    if emails or phones:
        corporate_lookup = Q()
        for email in emails:
            corporate_lookup |= Q(email__iexact=email)
        if phones:
            corporate_lookup |= Q(phone__in=phones)
        corporate_requests = CorporateAccountRequest.objects.filter(corporate_lookup).order_by('-updated_at').distinct()
        corporate_accounts = CorporateAccount.objects.filter(corporate_lookup).select_related('user').order_by('-updated_at').distinct()

    corporate_attendees = CorporateEventAttendee.objects.filter(corporate_match).select_related('registration__event', 'registration__corporate_account').order_by('-updated_at').distinct() if corporate_match else CorporateEventAttendee.objects.none()
    corporate_payments = CorporatePayment.objects.filter(attendees__in=corporate_attendees).select_related('corporate_account', 'event').order_by('-updated_at').distinct() if corporate_attendees.exists() else CorporatePayment.objects.none()

    bulk_email_logs = BulkEmailSendLog.objects.none()
    speaker_outreach_logs = SpeakerOutreachEmailLog.objects.none()
    speaker_certificate_logs = SpeakerCertificateEmailLog.objects.none()
    if emails:
        email_match = _build_exact_match_q('email', emails)
        bulk_email_logs = BulkEmailSendLog.objects.filter(email_match).select_related('bulk_email', 'sent_by').order_by('-created_at')
        speaker_outreach_logs = SpeakerOutreachEmailLog.objects.filter(email_match).select_related('event', 'person', 'sent_by').order_by('-created_at')
        speaker_certificate_logs = SpeakerCertificateEmailLog.objects.filter(email_match).select_related('event', 'person', 'sent_by').order_by('-created_at')

    bulk_sms_logs = BulkSMSSendLog.objects.none()
    if phones:
        bulk_sms_logs = BulkSMSSendLog.objects.filter(phone__in=phones).select_related('bulk_sms', 'sent_by').order_by('-created_at')

    timeline = []
    if user:
        _append_journey_item(timeline, user.date_joined, 'Account', 'Website login account available', f'Username: {user.username}', 'info')

    for member in members[:6]:
        _append_journey_item(
            timeline,
            member.created_at,
            'Membership',
            'Membership application created',
            f'{member.user_profile.name} - {member.get_approval_status_display()}',
            'info',
            dashboard_workflow_url('dashboard_membership_center', {'q': member.user_profile.email}),
            admin_change_url(member),
        )
        if member.approved_at:
            _append_journey_item(
                timeline,
                member.approved_at,
                'Membership',
                'Membership approved',
                'Active member' if member.is_active_member else 'Approved but inactive',
                'success',
                dashboard_workflow_url('dashboard_membership_center', {'q': member.user_profile.email}),
                admin_change_url(member),
            )
        if member.rejected_at:
            _append_journey_item(
                timeline,
                member.rejected_at,
                'Membership',
                'Membership rejected',
                member.rejection_reason or 'Reason not recorded.',
                'danger',
                dashboard_workflow_url('dashboard_membership_center', {'q': member.user_profile.email}),
                admin_change_url(member),
            )

    for payment in membership_payments[:8]:
        detail = f'BDT {payment.amount} - {payment.get_status_display()}'
        if payment.membership_type:
            detail = f'{payment.membership_type.name} - {detail}'
        _append_journey_item(
            timeline,
            payment.updated_at or payment.created_at,
            'Membership payment',
            'Membership payment updated',
            detail,
            'success' if payment.status == 'completed' else 'warning',
            dashboard_workflow_url('dashboard_payment_center', {'source': 'membership', 'q': payment.user_profile.email}),
            admin_change_url(payment),
        )

    for intent in intents[:6]:
        detail = f'{intent.event.name} {intent.event.year} - {intent.get_status_display()}'
        if intent.note:
            detail = f'{detail} - {intent.note}'
        _append_journey_item(
            timeline,
            intent.completed_at or intent.updated_at or intent.created_at,
            'Member event request',
            'Membership event request updated',
            detail,
            'success' if intent.status == 'completed' else 'warning',
            dashboard_workflow_url('dashboard_membership_center', {'panel': 'intents', 'q': intent.user_profile.email}),
            admin_change_url(intent),
        )

    for participant in participants[:12]:
        participant_workflow_url = dashboard_workflow_url('dashboard_participant_center', {'event': participant.event_id, 'q': participant.email})
        participant_admin_url = admin_change_url(participant)
        _append_journey_item(
            timeline,
            participant.created_at,
            'Participant',
            'Event registration application submitted',
            f'{participant.event.name} {participant.event.year}',
            'info',
            participant_workflow_url,
            participant_admin_url,
        )

        approval_log = participant.email_logs.filter(
            email_type__in=[ParticipantEmailLog.TYPE_APPROVAL_PAYMENT, ParticipantEmailLog.TYPE_FREE_CONFIRMATION]
        ).order_by('sent_at', 'created_at').first()
        approval_at = None
        if approval_log:
            approval_at = approval_log.sent_at or approval_log.created_at
        elif participant.approved and getattr(participant, 'payment_statuses', None):
            approval_at = participant.payment_statuses.updated_at

        if participant.approved:
            _append_journey_item(
                timeline,
                approval_at or participant.created_at,
                'Participant',
                'Event registration approved',
                f'{participant.event.name} {participant.event.year}',
                'success',
                participant_workflow_url,
                participant_admin_url,
            )
        elif participant.denied:
            _append_journey_item(
                timeline,
                approval_at or participant.created_at,
                'Participant',
                'Event registration denied',
                f'{participant.event.name} {participant.event.year}',
                'danger',
                participant_workflow_url,
                participant_admin_url,
            )

    for payment in participant_payments[:12]:
        detail = f'{payment.event.name} {payment.event.year} - BDT {payment.amount or 0} - {payment.get_status_display()}'
        _append_journey_item(
            timeline,
            payment.updated_at,
            'Event payment',
            'Event payment updated',
            detail,
            'success' if payment.status in PAID_PAYMENT_STATUSES else 'warning',
            dashboard_workflow_url('dashboard_payment_center', {'source': 'event', 'event': payment.event_id, 'q': payment.participant.email}),
            admin_change_url(payment),
        )

    for kit in kits[:6]:
        _append_journey_item(
            timeline,
            kit.issued_at,
            'Kit',
            'Registration kit issued',
            f'{kit.event.name} {kit.event.year}',
            'success',
            dashboard_workflow_url('dashboard_registration_kit_center', {'event': kit.event_id, 'q': kit.payment_status.participant.email}),
            admin_change_url(kit),
        )

    for email_log in participant_emails[:8]:
        detail = f'{email_log.event.name} {email_log.event.year} - {email_log.get_email_type_display()} - {email_log.get_status_display()}'
        _append_journey_item(
            timeline,
            email_log.sent_at or email_log.created_at,
            'Email',
            'Participant email activity',
            detail,
            'success' if email_log.status == ParticipantEmailLog.STATUS_SENT else 'warning',
            dashboard_workflow_url('dashboard_participant_center', {'event': email_log.event_id, 'q': email_log.email}),
            admin_change_url(email_log),
        )

    for thank_you in thank_you_logs[:8]:
        detail = f'{thank_you.event.name} {thank_you.event.year} - {thank_you.get_status_display()}'
        _append_journey_item(
            timeline,
            thank_you.sent_at or thank_you.created_at,
            'Thank-you email',
            'Thank-you email activity',
            detail,
            'success' if thank_you.status == ThankYouEmailLog.STATUS_SENT else 'warning',
            dashboard_workflow_url('dashboard_certificate_center', {'event': thank_you.event_id}),
            admin_change_url(thank_you),
        )

    for email_log in bulk_email_logs[:8]:
        detail = f'{email_log.bulk_email.subject} - {email_log.get_status_display()}'
        if email_log.message:
            detail = f'{detail} - {email_log.message}'
        _append_journey_item(
            timeline,
            email_log.created_at,
            'Bulk email',
            'Bulk email send recorded',
            detail,
            'success' if email_log.status == BulkEmailRecipient.STATUS_SENT else 'warning' if email_log.status == BulkEmailRecipient.STATUS_SKIPPED else 'danger',
            dashboard_workflow_url('dashboard_bulk_email_center'),
            admin_change_url(email_log),
        )

    for outreach_log in speaker_outreach_logs[:6]:
        detail = f'{outreach_log.event.name} {outreach_log.event.year} - {outreach_log.get_status_display()} - {outreach_log.subject}'
        if outreach_log.message:
            detail = f'{detail} - {outreach_log.message}'
        _append_journey_item(
            timeline,
            outreach_log.sent_at or outreach_log.created_at,
            'Speaker email',
            'Speaker outreach email recorded',
            detail,
            'success' if outreach_log.status == SpeakerOutreachEmailLog.STATUS_SENT else 'warning' if outreach_log.status == SpeakerOutreachEmailLog.STATUS_SKIPPED else 'danger',
            dashboard_workflow_url('dashboard_speaker_outreach_center', {'event': outreach_log.event_id}),
            admin_change_url(outreach_log),
        )

    for certificate_log in speaker_certificate_logs[:6]:
        detail = f'{certificate_log.event.name} {certificate_log.event.year} - {certificate_log.get_status_display()}'
        if certificate_log.message:
            detail = f'{detail} - {certificate_log.message}'
        _append_journey_item(
            timeline,
            certificate_log.sent_at or certificate_log.created_at,
            'Certificate email',
            'Speaker certificate email recorded',
            detail,
            'success' if certificate_log.status == SpeakerCertificateEmailLog.STATUS_SENT else 'warning' if certificate_log.status == SpeakerCertificateEmailLog.STATUS_SKIPPED else 'danger',
            dashboard_workflow_url('dashboard_certificate_center', {'event': certificate_log.event_id}),
            admin_change_url(certificate_log),
        )

    for sms_log in bulk_sms_logs[:8]:
        detail = f'{sms_log.bulk_sms.subject} - {sms_log.get_status_display()}'
        if sms_log.provider_status:
            detail = f'{detail} - Provider: {sms_log.provider_status}'
        if sms_log.message:
            detail = f'{detail} - {sms_log.message}'
        _append_journey_item(
            timeline,
            sms_log.created_at,
            'SMS',
            'Bulk SMS send recorded',
            detail,
            'success' if sms_log.status == BulkSMSRecipient.STATUS_SENT else 'warning' if sms_log.status == BulkSMSRecipient.STATUS_SKIPPED else 'danger',
            dashboard_workflow_url('dashboard_bulk_sms_center'),
            admin_change_url(sms_log),
        )

    for access_request in corporate_requests[:6]:
        _append_journey_item(
            timeline,
            access_request.updated_at or access_request.created_at,
            'Corporate access',
            'Corporate access request updated',
            f'{access_request.company_name} - {access_request.get_status_display()}',
            'success' if access_request.status == 'approved' else 'warning' if access_request.status == 'pending' else 'danger',
            dashboard_workflow_url('dashboard_corporate_center', {'request_status': access_request.status, 'q': access_request.email}),
            admin_change_url(access_request),
        )

    for account in corporate_accounts[:6]:
        _append_journey_item(
            timeline,
            account.approved_at or account.updated_at or account.created_at,
            'Corporate account',
            'Corporate account updated',
            f'{account.company_name} - {account.get_status_display()}',
            'success' if account.status == 'approved' else 'warning',
            dashboard_workflow_url('dashboard_corporate_center', {'q': account.email}),
            admin_change_url(account),
        )

    for attendee in corporate_attendees[:8]:
        detail = f'{attendee.registration.event.name} {attendee.registration.event.year} - {attendee.registration.corporate_account.company_name} - {attendee.get_review_status_display()}'
        tone = 'success' if attendee.review_status == 'approved' else 'warning' if attendee.review_status == 'pending' else 'danger'
        _append_journey_item(
            timeline,
            attendee.updated_at or attendee.created_at,
            'Corporate attendee',
            'Corporate attendee updated',
            detail,
            tone,
            dashboard_workflow_url('dashboard_corporate_center', {'event': attendee.registration.event_id, 'q': attendee.email}),
            admin_change_url(attendee),
        )

    for payment in corporate_payments[:8]:
        detail = f'{payment.event.name} {payment.event.year} - {payment.corporate_account.company_name} - BDT {payment.amount} - {payment.get_status_display()}'
        _append_journey_item(
            timeline,
            payment.updated_at or payment.created_at,
            'Corporate payment',
            'Corporate payment updated',
            detail,
            'success' if payment.status in ['completed', 'paid'] else 'warning',
            dashboard_workflow_url('dashboard_payment_center', {'source': 'corporate', 'event': payment.event_id, 'q': payment.corporate_account.email}),
            admin_change_url(payment),
        )

    timeline.sort(key=lambda item: item['at'], reverse=True)
    member = members.first()
    latest_participant = participants.first()
    message_total = (
        participant_emails.count()
        + thank_you_logs.count()
        + bulk_email_logs.count()
        + speaker_outreach_logs.count()
        + speaker_certificate_logs.count()
        + bulk_sms_logs.count()
    )
    return {
        'name': candidate['name'],
        'emails': emails,
        'phones': phones,
        'sources': candidate.get('sources', []),
        'timeline': timeline[:48],
        'summary': {
            'participants': participants.count(),
            'event_payments': participant_payments.count(),
            'membership_payments': membership_payments.count(),
            'corporate_rows': corporate_requests.count() + corporate_accounts.count() + corporate_attendees.count(),
            'messages': message_total,
        },
        'membership_status': member.get_approval_status_display() if member else 'No membership record',
        'latest_event': f'{latest_participant.event.name} {latest_participant.event.year}' if latest_participant else 'No event registration yet',
        'account_joined_at': user.date_joined if user else None,
    }

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
        participant_revenue = PaymentStatus.objects.filter(
            event=event, status__in=['paid', 'completed']
        ).aggregate(total=Sum('amount'))['total'] or 0
        corporate_revenue = CorporatePayment.objects.filter(
            event=event, status__in=['paid', 'completed']
        ).aggregate(total=Sum('amount'))['total'] or 0
        metrics = {
            'name': event.name,
            'approved_participants': Participant.objects.filter(event=event).count(),
            'pending_payments': PaymentStatus.objects.filter(
                event=event, status__in=UNPAID_PAYMENT_STATUSES
            ).count(),
            'revenue_collected': participant_revenue + corporate_revenue,
        }
        event_metrics.append(metrics)
    return event_metrics


def get_dashboard_scoped_events(events, event_filter=None):
    scoped_events = events
    if event_filter:
        scoped_events = scoped_events.filter(id=event_filter)
    return scoped_events


def build_event_report(event):
    participants_qs = Participant.objects.filter(event=event)
    payment_qs = PaymentStatus.objects.filter(event=event).select_related('participant')
    kit_qs = RegistrationKit.objects.filter(event=event)
    abstracts_qs = AbstractSubmission.objects.filter(event=event)
    corporate_reg_qs = CorporateEventRegistration.objects.filter(event=event)
    corporate_attendee_qs = CorporateEventAttendee.objects.filter(registration__event=event)
    corporate_payment_qs = CorporatePayment.objects.filter(event=event)

    registrations_started = participants_qs.count()
    approved_count = participants_qs.filter(approved=True).count()
    denied_count = participants_qs.filter(denied=True).count()
    pending_count = participants_qs.filter(approved=False, denied=False).count()

    member_count = participants_qs.filter(registration_type='member').count()
    regular_count = participants_qs.filter(registration_type='regular').count()
    company_person_count = participants_qs.filter(registration_type='company_person').count()
    complementary_count = participants_qs.filter(registration_type='complementary').count()

    bangladesh_count = 0
    abroad_count = 0

    participant_paid_count = payment_qs.filter(status__in=['paid', 'completed']).count()
    participant_unpaid_count = payment_qs.filter(status__in=UNPAID_PAYMENT_STATUSES).count()
    participant_failed_count = payment_qs.filter(status__in=['failed', 'cancelled', 'refunded']).count()
    participant_missing_payment_count = max(registrations_started - payment_qs.count(), 0)

    participant_revenue = payment_qs.filter(status__in=['paid', 'completed']).aggregate(total=Sum('amount'))['total'] or 0
    corporate_revenue = corporate_payment_qs.filter(status__in=['paid', 'completed']).aggregate(total=Sum('amount'))['total'] or 0
    total_revenue = participant_revenue + corporate_revenue

    completed_participant_ids = set(payment_qs.filter(status__in=['paid', 'completed']).values_list('participant_id', flat=True))
    issued_participant_ids = set(kit_qs.filter(status='issued').values_list('payment_status__participant_id', flat=True))
    feedback_participant_ids = set(FeedbackResponse.objects.filter(event=event).values_list('participant_id', flat=True).distinct())
    unlocked_certificate_ids = set(participants_qs.filter(approved=True).values_list('id', flat=True)) & completed_participant_ids & issued_participant_ids & feedback_participant_ids

    attended_count = kit_qs.filter(status='issued').count()
    attendance_rate = round((attended_count / approved_count) * 100) if approved_count else 0

    abstracts_submitted = abstracts_qs.count()
    abstracts_presentation = abstracts_qs.filter(approved_for_presentation=True).count()
    abstracts_poster = abstracts_qs.filter(approved_for_poster=True).count()
    abstracts_pending = abstracts_qs.filter(approved_for_presentation=False, approved_for_poster=False).count()
    abstracts_with_files = abstracts_qs.exclude(presentation_file='').count()

    institution_counts = Counter()
    country_counts = Counter()

    def normalize_whitespace(value):
        return ' '.join(str(value or '').split()).strip()

    def normalize_country(value):
        normalized = normalize_whitespace(value)
        if not normalized:
            return 'Not specified'
        lowered = normalized.lower()
        if lowered in {'bd', 'b.d.', 'bangladesh'}:
            return 'Bangladesh'
        return normalized

    for participant in participants_qs.values('organization', 'country'):
        organization = normalize_whitespace(participant.get('organization')) or 'Not specified'
        country = normalize_country(participant.get('country'))
        institution_counts[organization] += 1
        country_counts[country] += 1

    bangladesh_count = country_counts.get('Bangladesh', 0)
    abroad_count = max(registrations_started - bangladesh_count, 0)

    institution_rows = [
        {'label': label, 'count': count}
        for label, count in institution_counts.most_common(10)
    ]
    country_rows = [
        {'label': label, 'count': count}
        for label, count in country_counts.most_common(10)
    ]

    corporate_total_attendees = corporate_attendee_qs.count()
    corporate_approved = corporate_attendee_qs.filter(review_status='approved').count()
    corporate_pending = corporate_attendee_qs.filter(review_status='pending').count()
    corporate_denied = corporate_attendee_qs.filter(review_status='denied').count()

    thank_you_records_total = ThankYouEmail.objects.filter(registration_kit__event=event).count()
    thank_you_sent_total = ThankYouEmail.objects.filter(registration_kit__event=event, email_sent=True).count()
    speaker_certificate_issued_total = SpeakerCertificate.objects.filter(event=event).count()
    speaker_certificate_sent_total = SpeakerCertificateEmailLog.objects.filter(event=event, status=SpeakerCertificateEmailLog.STATUS_SENT).values('certificate_id').distinct().count()
    show_post_event_certificate_summary = bool(
        event
        and event.event_status == 'closed'
        and (
            unlocked_certificate_ids
            or feedback_participant_ids
            or thank_you_records_total
            or speaker_certificate_issued_total
        )
    )

    return {
        'event': event,
        'overview': {
            'registrations_started': registrations_started,
            'approved': approved_count,
            'denied': denied_count,
            'pending': pending_count,
            'member_count': member_count,
            'regular_count': regular_count,
            'company_person_count': company_person_count,
            'complementary_count': complementary_count,
            'bangladesh_count': bangladesh_count,
            'abroad_count': abroad_count,
            'participant_paid_count': participant_paid_count,
            'participant_unpaid_count': participant_unpaid_count + participant_missing_payment_count,
            'participant_failed_count': participant_failed_count,
            'attended_count': attended_count,
            'attendance_rate': attendance_rate,
            'participant_revenue': participant_revenue,
            'corporate_revenue': corporate_revenue,
            'total_revenue': total_revenue,
            'corporate_registrations': corporate_reg_qs.count(),
            'corporate_total_attendees': corporate_total_attendees,
            'corporate_approved': corporate_approved,
            'corporate_pending': corporate_pending,
            'corporate_denied': corporate_denied,
            'abstracts_submitted': abstracts_submitted,
            'abstracts_presentation': abstracts_presentation,
            'abstracts_poster': abstracts_poster,
            'abstracts_pending': abstracts_pending,
            'abstracts_with_files': abstracts_with_files,
            'participant_certificate_unlocked': len(unlocked_certificate_ids),
            'feedback_submitted_total': len(feedback_participant_ids),
            'thank_you_records_total': thank_you_records_total,
            'thank_you_sent_total': thank_you_sent_total,
            'thank_you_pending_total': max(attended_count - thank_you_sent_total, 0),
            'speaker_certificate_issued_total': speaker_certificate_issued_total,
            'speaker_certificate_sent_total': speaker_certificate_sent_total,
            'show_post_event_certificate_summary': show_post_event_certificate_summary,
        },
        'institutions': institution_rows,
        'countries': country_rows,
        'chart_data': {
            'registration_status': {
                'labels': ['Approved', 'Pending', 'Denied'],
                'counts': [approved_count, pending_count, denied_count],
            },
            'registration_types': {
                'labels': ['Member', 'Regular', 'Company person', 'Complementary'],
                'counts': [member_count, regular_count, company_person_count, complementary_count],
            },
            'payment_status': {
                'labels': ['Paid/Completed', 'Open/Unpaid', 'Failed/Cancelled'],
                'counts': [participant_paid_count, participant_unpaid_count + participant_missing_payment_count, participant_failed_count],
            },
            'countries': {
                'labels': [row['label'] for row in country_rows],
                'counts': [row['count'] for row in country_rows],
            },
            'institutions': {
                'labels': [row['label'] for row in institution_rows],
                'counts': [row['count'] for row in institution_rows],
            },
            'abstracts': {
                'labels': ['Submitted', 'Presentation', 'Poster', 'Pending'],
                'counts': [abstracts_submitted, abstracts_presentation, abstracts_poster, abstracts_pending],
            },
        },
    }


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
        participant_workflow_url = dashboard_workflow_url('dashboard_participant_center', {
            'event': event_filter,
            'status': 'pending',
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
                'url': dashboard_workflow_url('dashboard_participant_center', {
                    'event': item.event_id,
                    'status': 'pending',
                    'q': item.email,
                }) if not event_filter else participant_workflow_url,
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
                'url': dashboard_workflow_url('dashboard_payment_center', {
                    'source': 'event',
                    'status': item.status,
                    'event': item.event_id,
                    'q': item.participant.email,
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
        corporate_attendee_workflow_url = dashboard_workflow_url('dashboard_corporate_center', {
            'event': event_filter,
            'attendee_status': 'pending',
        })
        entries.extend([
            {
                'label': 'Corporate',
                'title': f'{item.name} - {item.registration.event.name}',
                'meta': item.registration.corporate_account.company_name,
                'status': item.get_review_status_display(),
                'url': dashboard_workflow_url('dashboard_corporate_center', {
                    'event': item.registration.event_id,
                    'attendee_status': 'pending',
                    'q': item.email,
                }) if not event_filter else corporate_attendee_workflow_url,
                'detail_url': admin_change_url(item),
                'sort_date': item.created_at,
            }
            for item in pending_corporate_attendees
        ])

    if queue_type in ('all', 'abstracts'):
        abstract_workflow_url = dashboard_workflow_url('dashboard_abstract_center', {
            'event': event_filter,
            'status': 'pending',
        })
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
                'url': dashboard_workflow_url('dashboard_abstract_center', {
                    'event': item.event_id,
                    'status': 'pending',
                    'q': item.title,
                }) if not event_filter else abstract_workflow_url,
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
        member_workflow_url = dashboard_workflow_url('dashboard_membership_center', {'approval_status': 'pending'})
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
        corporate_access_workflow_url = dashboard_workflow_url('dashboard_corporate_center', {'request_status': 'pending'})
        pending_corporate_requests = CorporateAccountRequest.objects.filter(status='pending').order_by('-created_at')
        entries.extend([
            {
                'label': 'Corporate access',
                'title': item.company_name,
                'meta': f'{item.contact_name} - {item.email}',
                'status': item.get_status_display(),
                'url': dashboard_workflow_url('dashboard_corporate_center', {
                    'request_status': 'pending',
                    'q': item.email,
                }) or corporate_access_workflow_url,
                'detail_url': admin_change_url(item),
                'sort_date': item.created_at,
            }
            for item in pending_corporate_requests
        ])

    entries.sort(key=lambda item: item['sort_date'], reverse=True)
    return Paginator(entries, per_page).get_page(page_number), queue_type


def staff_activity_queryset(filters=None):
    filters = filters or {}
    log_entries = LogEntry.objects.select_related('user', 'content_type').order_by('-action_time')

    search_query = (filters.get('q') or '').strip()
    if search_query:
        log_entries = log_entries.filter(
            Q(user__username__icontains=search_query)
            | Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
            | Q(object_repr__icontains=search_query)
            | Q(change_message__icontains=search_query)
            | Q(content_type__model__icontains=search_query)
            | Q(content_type__app_label__icontains=search_query)
        )

    staff_filter = filters.get('staff') or ''
    if staff_filter:
        log_entries = log_entries.filter(user_id=staff_filter)

    model_filter = filters.get('model') or ''
    if model_filter:
        try:
            app_label, model_name = model_filter.split('.', 1)
        except ValueError:
            app_label, model_name = '', ''
        if app_label and model_name:
            log_entries = log_entries.filter(
                content_type__app_label=app_label,
                content_type__model=model_name,
            )

    action_filter = filters.get('action') or ''
    if action_filter:
        action_map = {
            'added': ADDITION,
            'changed': CHANGE,
            'deleted': DELETION,
        }
        action_flag = action_map.get(action_filter)
        if action_flag:
            log_entries = log_entries.filter(action_flag=action_flag)

    date_from = _parse_dashboard_date(filters.get('date_from'))
    if date_from:
        log_entries = log_entries.filter(action_time__date__gte=date_from)

    date_to = _parse_dashboard_date(filters.get('date_to'))
    if date_to:
        log_entries = log_entries.filter(action_time__date__lte=date_to)

    return log_entries


def staff_activity_row(entry):
    model_class = entry.content_type.model_class() if entry.content_type else None
    detail_url = ''
    if model_class and entry.object_id and not entry.is_deletion():
        try:
            detail_url = reverse(
                f'admin:{entry.content_type.app_label}_{entry.content_type.model}_change',
                args=[entry.object_id],
            )
        except Exception:
            detail_url = ''

    if entry.is_addition():
        action_label = 'Added'
        tone = 'success'
    elif entry.is_change():
        action_label = 'Changed'
        tone = 'info'
    elif entry.is_deletion():
        action_label = 'Deleted'
        tone = 'danger'
    else:
        action_label = entry.get_action_flag_display()
        tone = 'neutral'

    return {
        'staff': entry.user.get_full_name() or entry.user.get_username(),
        'action': action_label,
        'tone': tone,
        'object': entry.object_repr,
        'model': entry.content_type.name.title() if entry.content_type else 'Admin record',
        'model_key': f'{entry.content_type.app_label}.{entry.content_type.model}' if entry.content_type else '',
        'message': entry.get_change_message(),
        'time': entry.action_time,
        'detail_url': detail_url,
    }


def build_staff_activity(page_number=None, per_page=8, filters=None):
    activity_rows = []
    log_entries = staff_activity_queryset(filters)[:500]
    for entry in log_entries:
        activity_rows.append(staff_activity_row(entry))

    return Paginator(activity_rows, per_page).get_page(page_number)


def staff_activity_filter_context(filters):
    model_choices = [
        {
            'value': f'{row["content_type__app_label"]}.{row["content_type__model"]}',
            'label': row['content_type__model'].replace('_', ' ').title(),
        }
        for row in LogEntry.objects.filter(content_type__isnull=False)
        .values('content_type__app_label', 'content_type__model')
        .distinct()
        .order_by('content_type__model')
    ]
    staff_choices = User.objects.filter(
        pk__in=LogEntry.objects.values('user_id')
    ).order_by('username')
    return {
        'filters': filters,
        'model_choices': model_choices,
        'staff_choices': staff_choices,
        'action_choices': [
            ('', 'All actions'),
            ('added', 'Added'),
            ('changed', 'Changed'),
            ('deleted', 'Deleted'),
        ],
    }


def get_staff_activity_filters(request):
    return {
        'q': (request.GET.get('activity_q') or '').strip(),
        'staff': request.GET.get('activity_staff') or '',
        'model': request.GET.get('activity_model') or '',
        'action': request.GET.get('activity_action') or '',
        'date_from': request.GET.get('activity_date_from') or '',
        'date_to': request.GET.get('activity_date_to') or '',
    }


def staff_activity_query_params(request, filters=None):
    filters = filters or get_staff_activity_filters(request)
    query_params = {}
    event_filter = request.POST.get('event') or request.GET.get('event')
    event_status_filter = request.POST.get('event_status') or request.GET.get('event_status')
    if event_filter:
        query_params['event'] = event_filter
    if event_status_filter:
        query_params['event_status'] = event_status_filter

    filter_param_map = {
        'q': 'activity_q',
        'staff': 'activity_staff',
        'model': 'activity_model',
        'action': 'activity_action',
        'date_from': 'activity_date_from',
        'date_to': 'activity_date_to',
    }
    for key, param_name in filter_param_map.items():
        value = filters.get(key)
        if value:
            query_params[param_name] = value
    return query_params


def build_dashboard_operations(events, event_filter=None, event_status_filter=None, queue_page_number=None, queue_type='all', user=None):
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
        if event.member_registration_enabled and event.executive_member_registration_fee is None:
            warnings.append('EC member fee not set, treated as free')
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

    participant_center_url = reverse('dashboard_participant_center')
    participant_center_params = {}
    if event_filter:
        participant_center_params['event'] = event_filter
    participant_pending_url = f"{participant_center_url}?{urlencode({**participant_center_params, 'status': 'pending'})}"
    participant_unpaid_url = f"{participant_center_url}?{urlencode({**participant_center_params, 'status': 'approved_unpaid'})}"

    action_cards = [
        {
            'label': 'Participant approvals',
            'permission_area': 'participants',
            'count': pending_participants.count(),
            'tone': 'warning',
            'description': 'Individual event registrations waiting for admin approval.',
            'url': participant_pending_url,
            'internal': True,
        },
        {
            'label': 'Approved but unpaid',
            'permission_area': 'payments',
            'count': approved_unpaid_payments.count(),
            'tone': 'danger',
            'description': 'Approved participants who still need payment completion.',
            'url': participant_unpaid_url,
            'internal': True,
        },
        {
            'label': 'Corporate review',
            'permission_area': 'corporate',
            'count': pending_corporate_attendees.count() + corporate_access_request_count,
            'tone': 'primary',
            'description': 'Corporate access requests and attendee rows waiting for review.' if not event_filter else 'Corporate attendee rows waiting for review for this event.',
            'url': dashboard_workflow_url('dashboard_corporate_center', {
                'event': event_filter,
                'attendee_status': 'pending',
                'request_status': 'pending',
            }),
            'internal': True,
        },
        {
            'label': 'Membership approvals',
            'permission_area': 'membership',
            'count': pending_event_members.count() if event_filter else pending_members.count(),
            'tone': 'success',
            'description': 'Membership applications waiting for approval or rejection.' if not event_filter else 'Membership applications tied to this event through member-event intent.',
            'url': dashboard_workflow_url('dashboard_membership_center', {'approval_status': 'pending'}),
            'internal': True,
        },
        {
            'label': 'Abstract review',
            'permission_area': 'abstracts',
            'count': pending_abstracts.count(),
            'tone': 'info',
            'description': 'Abstracts not yet marked for oral or poster presentation.',
            'url': admin_changelist_url(AbstractSubmission, event_filter_query),
        },
        {
            'label': 'Corporate invoices',
            'permission_area': 'payments',
            'count': unpaid_corporate_payments.count(),
            'tone': 'secondary',
            'description': 'Corporate invoices not marked paid or completed.',
            'url': dashboard_workflow_url('dashboard_payment_center', {
                'source': 'corporate',
                'status': 'open',
                'event': event_filter,
            }),
            'internal': True,
        },
    ]
    if user is not None and not user.is_superuser:
        action_cards = [
            card for card in action_cards
            if user_can_access_dashboard_area(user, card['permission_area'])
        ]

    payment_center_url = reverse('dashboard_payment_center')

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
            'payments': payment_center_url,
            'corporate_registrations': dashboard_workflow_url('dashboard_corporate_center', {'event': event_filter}),
            'corporate_attendees': dashboard_workflow_url('dashboard_corporate_center', {'event': event_filter, 'attendee_status': 'pending'}),
            'corporate_payments': dashboard_workflow_url('dashboard_payment_center', {'source': 'corporate', 'event': event_filter}),
            'membership': dashboard_workflow_url('dashboard_membership_center', {'approval_status': 'pending'}),
            'membership_payments': dashboard_workflow_url('dashboard_payment_center', {'source': 'membership'}),
            'abstracts': admin_changelist_url(AbstractSubmission),
            'events': admin_changelist_url(Event),
        },
    }


@dashboard_permission_required('dashboard')
def global_dashboard(request):
    from website.models import SiteSettings

    event_filter = request.POST.get('event') or request.GET.get('event')
    event_status_filter = request.POST.get('event_status') or request.GET.get('event_status')
    page_number = request.GET.get('page')
    event_page_number = request.GET.get('event_page')
    org_page_number = request.GET.get('org_page')
    queue_page_number = request.GET.get('queue_page')
    activity_page_number = request.GET.get('activity_page')
    queue_type = request.GET.get('queue_type', 'all')
    activity_filters = get_staff_activity_filters(request)

    events = Event.objects.all()
    if event_status_filter:
        events = events.filter(event_status=event_status_filter)
    operations = build_dashboard_operations(
        events,
        event_filter,
        event_status_filter,
        queue_page_number,
        queue_type,
        request.user,
    )

    event_metrics = build_event_metrics(events, event_filter)
    selected_event = get_dashboard_scoped_events(events, event_filter).first() if event_filter else None
    event_report = build_event_report(selected_event) if selected_event else None
    executive_member_summary = _executive_member_dashboard_summary(selected_event) if selected_event else None

    if request.method == 'POST':
        dashboard_action = (request.POST.get('dashboard_action') or '').strip()
        if dashboard_action == 'register_executive_members':
            if not selected_event:
                messages.error(request, 'Select an event first to register executive members.')
            else:
                results = _register_executive_members_for_event(request, selected_event)
                messages.success(
                    request,
                    f"Executive member sync finished for {selected_event.name}. "
                    f"Created {results['created']}, updated {results['updated']}, "
                    f"invoice emails queued {results['email_queued']}."
                )
                if results['skipped_paid']:
                    messages.warning(request, f"{results['skipped_paid']} existing paid registration(s) were left unchanged for manual review.")
                if results['skipped_missing_profile']:
                    messages.warning(request, f"{results['skipped_missing_profile']} executive member(s) were skipped because profile/email/phone data is incomplete.")
                if results['skipped_already_synced']:
                    messages.info(request, f"{results['skipped_already_synced']} executive member(s) were already synced for this event and were skipped.")
                if results['email_failed']:
                    messages.warning(request, f"{results['email_failed']} confirmation email(s) could not be queued. Check Celery or email settings.")
            redirect_params = {}
            if event_filter:
                redirect_params['event'] = event_filter
            if event_status_filter:
                redirect_params['event_status'] = event_status_filter
            redirect_url = reverse('global_dashboard')
            if redirect_params:
                redirect_url = f"{redirect_url}?{urlencode(redirect_params)}"
            return redirect(redirect_url)
        if dashboard_action == 'export_event_report_pdf':
            if not selected_event or not event_report:
                messages.error(request, 'Select an event first to export the event report PDF.')
                redirect_params = {}
                if event_filter:
                    redirect_params['event'] = event_filter
                if event_status_filter:
                    redirect_params['event_status'] = event_status_filter
                redirect_url = reverse('global_dashboard')
                if redirect_params:
                    redirect_url = f"{redirect_url}?{urlencode(redirect_params)}"
                return redirect(redirect_url)
            from website.models import SiteSettings
            feedback_report_data = _build_feedback_report_data(selected_event, '') if selected_event.event_status == 'closed' else None
            pdf_buffer = generate_event_report_pdf(
                selected_event,
                event_report,
                site_settings=SiteSettings.objects.first(),
                feedback_report_data=feedback_report_data,
            )
            safe_event_name = slugify(f"{selected_event.name}-{selected_event.year}") or f"event-{selected_event.id}"
            response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="event-report-{safe_event_name}.pdf"'
            return response

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
        'staff_activity_page_obj': build_staff_activity(activity_page_number, filters=activity_filters),
        'dashboard_chart_data': {
            'event_metrics': build_event_metrics_chart_data(event_metrics),
            'participant_status': participant_chart_data,
            'organizations': organization_chart_data,
            'event_report': event_report['chart_data'] if event_report else {},
        },
        'selected_event': selected_event,
        'event_report': event_report,
        'executive_member_summary': executive_member_summary,
        'operations': operations,
        'current_filters': {
            'event': event_filter,
            'event_status': event_status_filter
        },
        'query_string': query_string,
        'event_query_string': query_string,
        'participant_query_string': query_string,
        'activity_query_string': urlencode(staff_activity_query_params(request, activity_filters)),
        'activity_filter_context': staff_activity_filter_context(activity_filters),
    }

    if request.headers.get('HX-Request'):
        return render(request, 'partials/dashboard_content.html', context)
    return render(request, 'dashboard.html', context)


@dashboard_permission_required('events')
def dashboard_event_builder(request):
    from website.models import SiteSettings

    recent_events = Event.objects.order_by('-year', '-start_date', 'name')[:6]

    if request.method == 'POST':
        form = DashboardEventForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save()
            dashboard_log_action(request, event, ADDITION, 'Created event from Event builder dashboard.')
            messages.success(request, f'"{event}" was created. You can now add program details, registration content, and event assets.')
            next_action = request.POST.get('next_action')
            if next_action == 'program':
                return redirect(f"{reverse('dashboard_program_session_builder')}?event={event.id}")
            if next_action == 'admin':
                return redirect(reverse('admin:registration_event_change', args=[event.id]))
            return redirect(f"{reverse('dashboard_event_builder')}?created={event.id}")
        messages.error(request, 'Please correct the highlighted event details.')
    else:
        form = DashboardEventForm(initial={
            'year': timezone.now().year,
            'event_status': 'upcoming',
            'registration': 'Starting Soon',
            'registration_audience': 'all',
            'payment_required': True,
        })

    created_event = Event.objects.filter(pk=request.GET.get('created')).first()
    context = {
        'site_settings': SiteSettings.objects.first(),
        'form': form,
        'recent_events': recent_events,
        'created_event': created_event,
        'event_status_choices': Event.EVENT_STATUS_CHOICES,
        'registration_status_choices': Event.REGISTRATION_STATUS_CHOICES,
        'registration_audience_choices': Event.REGISTRATION_AUDIENCE_CHOICES,
    }
    return render(request, 'dashboard_event_builder.html', context)


def _send_abstract_approval_email(abstract, approval_type):
    subject = f"Abstract Approved for {approval_type.capitalize()}"
    context = {
        'user': abstract.user,
        'abstract': abstract,
        'approval_type': approval_type,
    }
    html_content = render_to_string('abstract_approval_email.html', context)
    text_content = strip_tags(html_content)
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or os.getenv("EMAIL_HOST_USER")
    recipient_email = abstract.user.email if abstract.user_id else ''
    if not recipient_email:
        return False

    send_email_task.delay(
        subject=subject,
        body=text_content,
        from_email=from_email,
        recipient_list=[recipient_email],
        html_message=html_content,
    )
    return True


def _abstract_status_label(abstract):
    if abstract.approved_for_presentation:
        return 'Presentation'
    if abstract.approved_for_poster:
        return 'Poster'
    return 'Pending'


def _send_dashboard_participant_payment_email(request, participant, password=None, include_password=False):
    event = participant.event
    payment_url = reverse('registration:payment', kwargs={
        'event_id': event.id,
        'participant_id': participant.id,
    })
    context = {
        'participant': participant,
        'event': event,
        'payment_url': request.build_absolute_uri(payment_url),
    }
    if include_password and password:
        context['password'] = password

    html_content = render_to_string('consolidated_email.html', context)
    text_content = strip_tags(html_content)
    send_email_task.delay(
        subject=f'Your Registration for {event.name} {event.year} is Approved!',
        body=text_content,
        from_email=os.getenv("EMAIL_HOST_USER"),
        recipient_list=[participant.email],
        html_message=html_content,
    )


def _send_dashboard_free_event_confirmation(participant, password=None, include_password=False):
    event = participant.event
    context = {
        'participant': participant,
        'event': event,
    }
    if include_password and password:
        context['password'] = password

    attachment_paths = []
    try:
        payment_status = PaymentStatus.objects.filter(participant=participant, event=event).first()
        if payment_status:
            invoice_path = None
            if payment_status.invoice:
                try:
                    invoice_path = payment_status.invoice.path
                except Exception:
                    invoice_path = None

            if not invoice_path or not os.path.exists(invoice_path):
                invoice_path = generate_invoice(participant, event, payment_status)
                relative_invoice_path = os.path.relpath(invoice_path, settings.MEDIA_ROOT).replace('\\', '/')
                payment_status.invoice = relative_invoice_path
                payment_status.save(update_fields=['invoice'])

            if invoice_path and os.path.exists(invoice_path):
                attachment_paths.append(invoice_path)
    except Exception:
        attachment_paths = []

    html_content = render_to_string('free_event_confirmation_email.html', context)
    text_content = strip_tags(html_content)
    send_email_task.delay(
        subject=f'Registration Confirmed for {event.name} {event.year}',
        body=text_content,
        from_email=os.getenv("EMAIL_HOST_USER"),
        recipient_list=[participant.email],
        html_message=html_content,
        attachment_paths=attachment_paths,
    )


def _queue_dashboard_participant_email(request, participant, email_type, password=None, include_password=False, payment_url=None):
    email_log = None
    if participant_email_log_table_ready():
        email_log = ParticipantEmailLog.objects.create(
            participant=participant,
            event=participant.event,
            email=participant.email,
            email_type=email_type,
            status=ParticipantEmailLog.STATUS_QUEUED,
            sent_by=request.user if request.user.is_authenticated else None,
            message='Queued from participant center.',
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
        logger.exception("Could not queue participant approval email for %s: %s", participant.id, exc)
        return False

    if email_log:
        email_log.task_id = getattr(task, 'id', '') or ''
        email_log.save(update_fields=['task_id', 'updated_at'])
    return True


def _approve_dashboard_participant(request, participant):
    event = participant.event
    payable_amount = participant.get_payable_amount()
    password = None
    include_password = False

    participant_user = participant.user
    if not participant_user.has_usable_password():
        password = get_random_string(length=12)
        participant_user.set_password(password)
        if not participant_user.email:
            participant_user.email = participant.email
        participant_user.save(update_fields=['password', 'email'])
        include_password = True

    participant.approved = True
    participant.denied = False
    participant.save(update_fields=['approved', 'denied'])
    dashboard_log_action(request, participant, CHANGE, 'Approved participant from Participant Center dashboard.')

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
        if payment_status.status not in SUCCESS_PAYMENT_STATUSES:
            payment_status.status = 'unpaid'
        payment_status.save()
        dashboard_log_action(request, payment_status, CHANGE, 'Created or updated participant payment row during dashboard approval.')
        payment_url = request.build_absolute_uri(reverse('registration:payment', kwargs={
            'event_id': event.id,
            'participant_id': participant.id,
        }))
        email_queued = _queue_dashboard_participant_email(
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
        dashboard_log_action(request, payment_status, CHANGE, 'Marked free participant payment as completed during dashboard approval.')
        email_queued = _queue_dashboard_participant_email(
            request,
            participant,
            ParticipantEmailLog.TYPE_FREE_CONFIRMATION,
            password=password,
            include_password=include_password,
        )

    return payment_status, email_queued



def _executive_member_matches_event_participant(event, member):
    profile = getattr(member, 'user_profile', None)
    if not profile:
        return None
    user = getattr(profile, 'user', None)
    email = (getattr(profile, 'email', '') or '').strip()
    phone = (getattr(profile, 'phone', '') or '').strip()

    participant_qs = Participant.objects.filter(event=event)
    lookup = Q()
    if user:
        lookup |= Q(user=user)
    if email:
        lookup |= Q(email__iexact=email)
    if phone:
        lookup |= Q(phone=phone)
    if not lookup:
        return None
    return participant_qs.filter(lookup).select_related('payment_statuses', 'department').first()


def _get_executive_member_registration_fee(event):
    return event.executive_member_registration_fee or 0


def _executive_member_sync_needed(event, participant):
    if not participant:
        return True
    if not participant.approved or participant.denied:
        return True

    payment_status = getattr(participant, 'payment_statuses', None)
    if not payment_status:
        return True

    executive_member_fee = _get_executive_member_registration_fee(event)
    if executive_member_fee:
        if (payment_status.amount or 0) != executive_member_fee:
            return True
        return payment_status.status not in ['unpaid', 'initiated', 'pending', *SUCCESS_PAYMENT_STATUSES]

    if payment_status.status not in SUCCESS_PAYMENT_STATUSES:
        return True
    if (payment_status.amount or 0) != 0:
        return True
    if not payment_status.invoice or not payment_status.qr_token or not payment_status.qr_code:
        return True
    if not RegistrationKit.objects.filter(event=event, payment_status=payment_status).exists():
        return True
    return False


def _executive_member_dashboard_summary(event):
    from website.models import Member

    executive_members = Member.objects.filter(
        approval_status='approved',
        is_active_member=True,
        is_executive_member=True,
    ).select_related('user_profile__user').order_by('user_profile__name')

    eligible_total = executive_members.count()
    registered_total = 0
    synced_total = 0
    pending_total = 0

    for member in executive_members:
        participant = _executive_member_matches_event_participant(event, member)
        sync_needed = _executive_member_sync_needed(event, participant)
        if participant:
            registered_total += 1
        if sync_needed:
            pending_total += 1
        else:
            synced_total += 1

    return {
        'eligible_total': eligible_total,
        'registered_total': registered_total,
        'synced_total': synced_total,
        'pending_total': pending_total,
    }


def _register_executive_members_for_event(request, event):
    from website.models import Member

    executive_members = Member.objects.filter(
        approval_status='approved',
        is_active_member=True,
        is_executive_member=True,
    ).select_related('user_profile__user').prefetch_related('specialties').order_by('user_profile__name')

    results = {
        'created': 0,
        'updated': 0,
        'skipped_paid': 0,
        'skipped_missing_profile': 0,
        'skipped_already_synced': 0,
        'email_queued': 0,
        'email_failed': 0,
    }

    executive_member_fee = _get_executive_member_registration_fee(event)

    for member in executive_members:
        profile = getattr(member, 'user_profile', None)
        user = getattr(profile, 'user', None) if profile else None
        if not profile or not user or not profile.email or not profile.phone:
            results['skipped_missing_profile'] += 1
            continue

        participant = _executive_member_matches_event_participant(event, member)
        existing_payment_status = getattr(participant, 'payment_statuses', None) if participant else None
        if existing_payment_status and existing_payment_status.status in SUCCESS_PAYMENT_STATUSES and (existing_payment_status.amount or 0) > 0:
            results['skipped_paid'] += 1
            continue
        if not _executive_member_sync_needed(event, participant):
            results['skipped_already_synced'] += 1
            continue

        department_name = get_previous_participant_department_name(profile.email, event)
        if not department_name:
            first_specialty = member.specialties.first()
            department_name = first_specialty.name if first_specialty else 'Executive Committee'
        department = get_or_create_participant_department(event, department_name)

        if participant is None:
            participant = Participant.objects.create(
                user=user,
                event=event,
                registration_type='member',
                name=profile.name,
                degree=(member.position or 'Executive Member')[:50],
                year_of_graduation=0,
                department=department,
                organization=(member.institution or 'BSBCS')[:100],
                email=profile.email,
                phone=profile.phone,
                country=profile.country or 'Bangladesh',
                BMDC_registration_number='',
                approved=True,
                denied=False,
            )
            dashboard_log_action(request, participant, ADDITION, 'Created executive member participant from Global Dashboard.')
            results['created'] += 1
        else:
            participant.user = user
            participant.registration_type = 'member'
            participant.name = profile.name
            participant.degree = (member.position or participant.degree or 'Executive Member')[:50]
            participant.department = participant.department if participant.department_id else department
            participant.organization = (member.institution or participant.organization or 'BSBCS')[:100]
            participant.email = profile.email
            participant.phone = profile.phone
            participant.country = profile.country or participant.country or 'Bangladesh'
            participant.approved = True
            participant.denied = False
            participant.save(update_fields=['user', 'registration_type', 'name', 'degree', 'department', 'organization', 'email', 'phone', 'country', 'approved', 'denied'])
            dashboard_log_action(request, participant, CHANGE, 'Updated executive member participant from Global Dashboard.')
            results['updated'] += 1

        if executive_member_fee:
            payment_status, _ = PaymentStatus.objects.get_or_create(
                participant=participant,
                event=event,
                defaults={
                    'merchant_invoice_number': f"EC-{event.id}-{participant.id}-{int(time.time())}",
                    'amount': executive_member_fee,
                    'status': 'unpaid',
                }
            )
            if not payment_status.merchant_invoice_number:
                payment_status.merchant_invoice_number = f"EC-{event.id}-{participant.id}-{int(time.time())}"
            payment_status.amount = executive_member_fee
            if payment_status.status not in SUCCESS_PAYMENT_STATUSES:
                payment_status.status = 'unpaid'
            payment_status.email_sent = False
            payment_status.save()
            dashboard_log_action(request, payment_status, CHANGE, 'Prepared executive member payment row from Global Dashboard approval sync.')

            payment_url = request.build_absolute_uri(reverse('registration:payment', kwargs={
                'event_id': event.id,
                'participant_id': participant.id,
            }))
            queued = _queue_dashboard_participant_email(
                request,
                participant,
                ParticipantEmailLog.TYPE_APPROVAL_PAYMENT,
                payment_url=payment_url,
            )
        else:
            payment_status, _ = PaymentStatus.objects.get_or_create(
                participant=participant,
                event=event,
                defaults={
                    'merchant_invoice_number': f"EC-FREE-{event.id}-{participant.id}-{int(time.time())}",
                    'amount': 0,
                    'status': 'completed',
                }
            )

            if not payment_status.merchant_invoice_number.startswith(f"EC-FREE-{event.id}-{participant.id}-"):
                payment_status.merchant_invoice_number = f"EC-FREE-{event.id}-{participant.id}-{int(time.time())}"
            payment_status.amount = 0
            payment_status.status = 'completed'
            payment_status.email_sent = False
            payment_status.save()
            RegistrationKit.objects.get_or_create(
                event=event,
                payment_status=payment_status,
                defaults={'status': 'not_issued'},
            )
            dashboard_log_action(request, payment_status, CHANGE, 'Marked executive member event registration as complimentary and completed from Global Dashboard.')

            _generate_event_payment_invoice(payment_status)

            queued = _queue_dashboard_participant_email(
                request,
                participant,
                ParticipantEmailLog.TYPE_FREE_CONFIRMATION,
            )

        if queued:
            results['email_queued'] += 1
        else:
            results['email_failed'] += 1

    return results


def _participant_dashboard_status(participant):
    if participant.denied:
        return 'Denied'
    if not participant.approved:
        return 'Pending approval'
    payment_status = getattr(participant, 'payment_statuses', None)
    if not payment_status:
        return 'Approved - no payment row'
    if payment_status.status in SUCCESS_PAYMENT_STATUSES:
        return 'Approved and paid'
    return 'Approved but unpaid'


@dashboard_permission_required('participants')
def dashboard_participant_lookup(request):
    query = (request.GET.get('q') or request.GET.get('email') or '').strip().lower()
    event_id = request.GET.get('event')
    if not query:
        return JsonResponse({'ok': True, 'results': []})

    profiles = list(
        UserProfile.objects.filter(
            Q(email__icontains=query) | Q(name__icontains=query)
        ).select_related('user').order_by('name')[:8]
    )
    profile_user_ids = {profile.user_id for profile in profiles}
    users = list(
        User.objects.filter(
            Q(email__icontains=query)
            | Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        ).exclude(pk__in=profile_user_ids).order_by('email')[:8]
    )

    results = []
    seen_emails = set()
    candidates = [(profile.user, profile) for profile in profiles] + [(user, None) for user in users]
    for user, profile in candidates:
        email = ((profile.email if profile else user.email or user.username) or '').strip().lower()
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        participant_scope = Participant.objects.filter(email__iexact=email).select_related('department').order_by('-created_at')
        previous_participant = participant_scope.first()
        already_registered = bool(event_id and participant_scope.filter(event_id=event_id).exists())
        results.append({
            'email': email,
            'account_found': True,
            'profile_found': bool(profile),
            'already_registered': already_registered,
            'message': (
                'Already registered for this event.'
                if already_registered
                else 'Website profile found.'
                if profile
                else 'Login account found. A profile will be created.'
            ),
            'profile': {
                'name': profile.name if profile else user.get_full_name(),
                'email': email,
                'phone': profile.phone if profile else '',
                'country': profile.country if profile else 'Bangladesh',
                'degree': previous_participant.degree if previous_participant else '',
                'year_of_graduation': previous_participant.year_of_graduation if previous_participant else '',
                'department_name': previous_participant.department.name if previous_participant and previous_participant.department_id else '',
                'organization': previous_participant.organization if previous_participant else '',
                'BMDC_registration_number': previous_participant.BMDC_registration_number if previous_participant else '',
            },
        })
        if len(results) >= 8:
            break

    data = {'ok': True, 'results': results}
    exact_result = next((result for result in results if result['email'] == query), None)
    if request.GET.get('email') and exact_result:
        data.update(exact_result)
    elif request.GET.get('email') and '@' in query:
        data.update({
            'email': query,
            'account_found': False,
            'profile_found': False,
            'already_registered': False,
            'message': 'No account found. Complete the essentials to create the account and profile.',
            'profile': {'email': query, 'country': 'Bangladesh'},
        })
    return JsonResponse(data)


@dashboard_permission_required('abstracts')
def dashboard_abstract_center(request):
    from website.models import SiteSettings

    event_filter = request.POST.get('event') if request.method == 'POST' else request.GET.get('event')
    status_filter = request.POST.get('status') if request.method == 'POST' else request.GET.get('status', 'pending')
    search_query = ((request.POST.get('q') if request.method == 'POST' else request.GET.get('q', '')) or '').strip()

    query_params = {}
    if event_filter:
        query_params['event'] = event_filter
    if status_filter:
        query_params['status'] = status_filter
    if search_query:
        query_params['q'] = search_query
    redirect_url = reverse('dashboard_abstract_center')
    if query_params:
        redirect_url = f"{redirect_url}?{urlencode(query_params)}"

    selected_event = Event.objects.filter(pk=event_filter).first() if event_filter else None
    abstract_form = DashboardAbstractSubmissionForm(
        selected_event=selected_event,
        prefix='abstract',
    )
    selected_ids = request.POST.getlist('abstract_ids')
    show_abstract_form = False
    if request.method == 'POST':
        action = request.POST.get('abstract_action')
        if action == 'create_abstract':
            abstract_form = DashboardAbstractSubmissionForm(
                request.POST,
                request.FILES,
                selected_event=selected_event,
                prefix='abstract',
            )
            show_abstract_form = True
            if abstract_form.is_valid():
                abstract = abstract_form.save()
                dashboard_log_action(request, abstract, ADDITION, 'Added abstract from Abstract approval dashboard.')
                messages.success(request, f'Abstract "{abstract.title}" added and kept pending for review.')
                create_redirect = reverse('dashboard_abstract_center')
                create_params = {
                    'event': abstract.event_id,
                    'status': 'pending',
                    'q': abstract.title,
                }
                return redirect(f"{create_redirect}?{urlencode(create_params)}")
            messages.error(request, 'Please correct the highlighted abstract form fields.')

        selected_abstracts = AbstractSubmission.objects.filter(pk__in=selected_ids).select_related('event', 'user')

        if action in ('approve_presentation', 'approve_poster') and not selected_ids:
            messages.error(request, 'Select at least one abstract before approving.')
            return redirect(redirect_url)

        if action == 'approve_presentation':
            sent_count = 0
            for abstract in selected_abstracts:
                abstract.approved_for_presentation = True
                abstract.approved_for_poster = False
                abstract.save(update_fields=['approved_for_presentation', 'approved_for_poster', 'updated_at'])
                dashboard_log_action(request, abstract, CHANGE, 'Approved abstract for presentation from dashboard.')
                sent_count += int(_send_abstract_approval_email(abstract, 'Presentation'))
            messages.success(request, f'{selected_abstracts.count()} abstract(s) approved for presentation. {sent_count} email(s) sent.')
            return redirect(redirect_url)

        if action == 'approve_poster':
            sent_count = 0
            for abstract in selected_abstracts:
                abstract.approved_for_poster = True
                abstract.approved_for_presentation = False
                abstract.save(update_fields=['approved_for_poster', 'approved_for_presentation', 'updated_at'])
                dashboard_log_action(request, abstract, CHANGE, 'Approved abstract for poster from dashboard.')
                sent_count += int(_send_abstract_approval_email(abstract, 'Poster'))
            messages.success(request, f'{selected_abstracts.count()} abstract(s) approved for poster. {sent_count} email(s) sent.')
            return redirect(redirect_url)

        if action == 'mark_pending':
            if not selected_ids:
                messages.error(request, 'Select at least one abstract before marking pending.')
                return redirect(redirect_url)
            pending_abstracts = list(selected_abstracts)
            updated = selected_abstracts.update(approved_for_presentation=False, approved_for_poster=False)
            for abstract in pending_abstracts:
                dashboard_log_action(request, abstract, CHANGE, 'Moved abstract back to pending review from dashboard.')
            messages.success(request, f'{updated} abstract(s) moved back to pending review.')
            return redirect(redirect_url)

        if action == 'export_pdf':
            if not selected_ids:
                messages.error(request, 'Select abstracts before exporting.')
                return redirect(redirect_url)
            first_abstract = selected_abstracts.first()
            if not first_abstract:
                messages.error(request, 'Selected abstracts were not found.')
                return redirect(redirect_url)
            event = first_abstract.event
            event_abstracts = selected_abstracts.filter(event=event).order_by('title')
            buffer = generate_abstract_pdf(event, event_abstracts)
            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="abstracts-{event.id}.pdf"'
            return response

    abstracts = AbstractSubmission.objects.select_related('event', 'user').order_by('-updated_at')
    if event_filter:
        abstracts = abstracts.filter(event_id=event_filter)
    if status_filter == 'pending':
        abstracts = abstracts.filter(approved_for_presentation=False, approved_for_poster=False)
    elif status_filter == 'presentation':
        abstracts = abstracts.filter(approved_for_presentation=True)
    elif status_filter == 'poster':
        abstracts = abstracts.filter(approved_for_poster=True)
    elif status_filter == 'approved':
        abstracts = abstracts.filter(Q(approved_for_presentation=True) | Q(approved_for_poster=True))
    if search_query:
        abstracts = abstracts.filter(
            Q(title__icontains=search_query)
            | Q(authors__icontains=search_query)
            | Q(institution__icontains=search_query)
            | Q(user__email__icontains=search_query)
            | Q(user__username__icontains=search_query)
        )

    event_scope = {'event_id': event_filter} if event_filter else {}
    totals = {
        'all': AbstractSubmission.objects.filter(**event_scope).count(),
        'pending': AbstractSubmission.objects.filter(
            **event_scope,
            approved_for_presentation=False,
            approved_for_poster=False,
        ).count(),
        'presentation': AbstractSubmission.objects.filter(**event_scope, approved_for_presentation=True).count(),
        'poster': AbstractSubmission.objects.filter(**event_scope, approved_for_poster=True).count(),
        'with_files': AbstractSubmission.objects.filter(**event_scope).exclude(presentation_file='').count(),
    }

    page_obj = Paginator(abstracts, 12).get_page(request.GET.get('page'))
    for abstract in page_obj.object_list:
        abstract.dashboard_status_label = _abstract_status_label(abstract)

    context = {
        'site_settings': SiteSettings.objects.first(),
        'events': Event.objects.order_by('-year', 'name'),
        'page_obj': page_obj,
        'totals': totals,
        'current_filters': {
            'event': str(event_filter or ''),
            'status': status_filter or '',
            'q': search_query,
        },
        'abstract_form': abstract_form,
        'show_abstract_form': show_abstract_form,
        'query_string': urlencode(query_params),
        'status_choices': [
            ('pending', 'Pending review'),
            ('approved', 'Approved'),
            ('presentation', 'Presentation'),
            ('poster', 'Poster'),
            ('all', 'All abstracts'),
        ],
    }
    return render(request, 'dashboard_abstract_center.html', context)


@dashboard_permission_required('participants')
def dashboard_participant_center(request):
    from website.models import SiteSettings

    event_filter = request.POST.get('event') if request.method == 'POST' else request.GET.get('event')
    legacy_status_filter = request.POST.get('status') if request.method == 'POST' else request.GET.get('status')
    approval_status = request.POST.get('approval_status') if request.method == 'POST' else request.GET.get('approval_status')
    payment_status_filter = request.POST.get('payment_status') if request.method == 'POST' else request.GET.get('payment_status')
    search_query = ((request.POST.get('q') if request.method == 'POST' else request.GET.get('q', '')) or '').strip()

    legacy_filter_map = {
        'pending': ('pending', 'all'),
        'approved_unpaid': ('approved', 'unpaid_group'),
        'approved_paid': ('approved', 'paid_group'),
        'approved': ('approved', 'all'),
        'denied': ('denied', 'all'),
        'missing_payment': ('approved', 'missing'),
        'all': ('all', 'all'),
    }
    if not approval_status and legacy_status_filter in legacy_filter_map:
        approval_status, payment_status_filter = legacy_filter_map[legacy_status_filter]
    approval_status = approval_status or 'pending'
    payment_status_filter = payment_status_filter or 'all'

    query_params = {}
    if event_filter:
        query_params['event'] = event_filter
    if approval_status:
        query_params['approval_status'] = approval_status
    if payment_status_filter:
        query_params['payment_status'] = payment_status_filter
    if search_query:
        query_params['q'] = search_query
    redirect_url = reverse('dashboard_participant_center')
    if query_params:
        redirect_url = f"{redirect_url}?{urlencode(query_params)}"

    selected_event = Event.objects.filter(pk=event_filter).first() if event_filter else None
    participant_form = DashboardParticipantCreateForm(
        selected_event=selected_event,
        prefix='participant',
    )
    show_participant_form = False
    participant_lookup_email = ''
    participant_lookup_completed = False
    selected_ids = request.POST.getlist('participant_ids')
    if request.method == 'POST':
        action = request.POST.get('participant_action')
        if action == 'create_participant':
            participant_lookup_email = (request.POST.get('participant_lookup_email') or '').strip().lower()
            participant_lookup_completed = request.POST.get('participant_lookup_completed') == '1'
            participant_form = DashboardParticipantCreateForm(
                request.POST,
                selected_event=selected_event,
                prefix='participant',
            )
            show_participant_form = True
            participant_form_is_valid = participant_form.is_valid()
            submitted_email = (request.POST.get('participant-email') or '').strip().lower()
            if not participant_lookup_completed or participant_lookup_email != submitted_email:
                participant_form.add_error('email', 'Check this email address before adding the participant.')
                participant_form_is_valid = False
            if participant_form_is_valid:
                try:
                    with transaction.atomic():
                        participant = participant_form.save(commit=False)
                        normalized_email = participant.email.strip().lower()
                        participant.email = normalized_email
                        participant_user = User.objects.filter(email__iexact=normalized_email).first()
                        if participant_user is None:
                            participant_user = User.objects.filter(username__iexact=normalized_email).first()
                        if participant_user is None:
                            participant_user = User(username=normalized_email, email=normalized_email)
                            account_password = get_random_string(length=12)
                            participant_user.set_password(account_password)
                            participant_user.save()
                        elif not participant_user.has_usable_password():
                            account_password = get_random_string(length=12)
                            participant_user.set_password(account_password)
                            if not participant_user.email:
                                participant_user.email = normalized_email
                            participant_user.save(update_fields=['password', 'email'])
                        else:
                            account_password = None

                        UserProfile.objects.get_or_create(
                            user=participant_user,
                            defaults={
                                'name': participant.name,
                                'email': normalized_email,
                                'phone': participant.phone,
                                'country': participant.country,
                            },
                        )
                        participant.user = participant_user
                        participant.approved = False
                        participant.denied = False
                        participant.save()
                        dashboard_log_action(request, participant, ADDITION, 'Added participant from Participant Center dashboard.')

                        if account_password:
                            transaction.on_commit(
                                lambda participant_id=participant.id, password=account_password: (
                                    send_manual_participant_account_email.delay(participant_id, password)
                                )
                            )

                        if participant_form.cleaned_data['approval_state'] == 'approved':
                            _, email_queued = _approve_dashboard_participant(request, participant)
                            messages.success(
                                request,
                                f'{participant.name} was added and approved. '
                                f'Approval email {"queued" if email_queued else "could not be queued"}.'
                                f'{" Login credentials were also queued." if account_password else ""}',
                            )
                            create_approval_filter = 'approved'
                        else:
                            messages.success(
                                request,
                                f'{participant.name} was added and is waiting for approval.'
                                f'{" Login credentials were queued." if account_password else ""}',
                            )
                            create_approval_filter = 'pending'

                    create_params = {
                        'event': participant.event_id,
                        'approval_status': create_approval_filter,
                        'payment_status': 'all',
                        'q': participant.email,
                    }
                    return redirect(f"{reverse('dashboard_participant_center')}?{urlencode(create_params)}")
                except IntegrityError:
                    logger.exception("Manual participant creation failed because of a duplicate row.")
                    participant_form.add_error(None, 'A participant with this email or phone already exists for the selected event.')
                except Exception as exc:
                    logger.exception("Manual participant creation failed: %s", exc)
                    participant_form.add_error(None, f'Could not add participant: {exc}')
            messages.error(request, 'Please correct the highlighted participant details.')

        selected_participants = Participant.objects.filter(pk__in=selected_ids).select_related('event', 'department')

        if action in ('approve', 'deny') and not selected_ids:
            messages.error(request, 'Select at least one participant first.')
            return redirect(redirect_url)

        if action == 'approve':
            approved_count = 0
            queued_count = 0
            for participant in selected_participants:
                try:
                    _, email_queued = _approve_dashboard_participant(request, participant)
                    approved_count += 1
                    queued_count += int(bool(email_queued))
                except Exception as exc:
                    logger.exception("Participant center approval failed for %s: %s", participant.id, exc)
                    messages.error(request, f'Could not approve {participant.name}: {exc}')
            if approved_count:
                messages.success(request, f'{approved_count} participant(s) approved. {queued_count} approval email(s) queued.')
            return redirect(redirect_url)

        if action == 'deny':
            denied_participants = list(selected_participants)
            updated = selected_participants.update(approved=False, denied=True)
            for participant in denied_participants:
                dashboard_log_action(request, participant, CHANGE, 'Denied participant from Participant Center dashboard.')
            messages.success(request, f'{updated} participant(s) denied.')
            return redirect(redirect_url)

    participants = Participant.objects.select_related('event', 'department', 'user', 'payment_statuses').order_by('-created_at')
    if event_filter:
        participants = participants.filter(event_id=event_filter)

    if approval_status == 'pending':
        participants = participants.filter(approved=False, denied=False)
    elif approval_status == 'approved':
        participants = participants.filter(approved=True)
    elif approval_status == 'denied':
        participants = participants.filter(denied=True)

    if payment_status_filter == 'unpaid_group':
        participants = participants.filter(payment_statuses__status__in=UNPAID_PAYMENT_STATUSES)
    elif payment_status_filter == 'paid_group':
        participants = participants.filter(payment_statuses__status__in=PAID_PAYMENT_STATUSES)
    elif payment_status_filter in ('unpaid', 'pending', 'initiated', 'failed', 'paid', 'completed', 'cancelled', 'refunded'):
        participants = participants.filter(payment_statuses__status=payment_status_filter)
    elif payment_status_filter == 'missing':
        participants = participants.filter(payment_statuses__isnull=True)
    elif payment_status_filter == 'not_required':
        participants = participants.filter(payment_statuses__status__in=PAID_PAYMENT_STATUSES, payment_statuses__amount=0)

    if search_query:
        participants = participants.filter(
            Q(name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(organization__icontains=search_query)
            | Q(BMDC_registration_number__icontains=search_query)
            | Q(event__name__icontains=search_query)
        )

    event_scope = {'event_id': event_filter} if event_filter else {}
    payment_event_scope = {'event_id': event_filter} if event_filter else {}
    totals = {
        'all': Participant.objects.filter(**event_scope).count(),
        'pending': Participant.objects.filter(**event_scope, approved=False, denied=False).count(),
        'approved': Participant.objects.filter(**event_scope, approved=True).count(),
        'denied': Participant.objects.filter(**event_scope, denied=True).count(),
        'approved_unpaid': PaymentStatus.objects.filter(
            **payment_event_scope,
            participant__approved=True,
            status__in=UNPAID_PAYMENT_STATUSES,
        ).count(),
        'approved_paid': PaymentStatus.objects.filter(
            **payment_event_scope,
            participant__approved=True,
            status__in=PAID_PAYMENT_STATUSES,
        ).count(),
        'missing_payment': Participant.objects.filter(**event_scope, approved=True, payment_statuses__isnull=True).count(),
    }
    if participant_email_log_table_ready():
        email_log_scope = {'event_id': event_filter} if event_filter else {}
        totals.update({
            'email_queued': ParticipantEmailLog.objects.filter(**email_log_scope, status=ParticipantEmailLog.STATUS_QUEUED).count(),
            'email_sent': ParticipantEmailLog.objects.filter(**email_log_scope, status=ParticipantEmailLog.STATUS_SENT).count(),
            'email_failed': ParticipantEmailLog.objects.filter(**email_log_scope, status=ParticipantEmailLog.STATUS_FAILED).count(),
        })
    else:
        totals.update({'email_queued': 0, 'email_sent': 0, 'email_failed': 0})

    page_obj = Paginator(participants, 15).get_page(request.GET.get('page'))
    for participant in page_obj.object_list:
        participant.dashboard_status_label = _participant_dashboard_status(participant)
        participant.latest_email_log = None
    if participant_email_log_table_ready() and page_obj.object_list:
        participant_ids = [participant.id for participant in page_obj.object_list]
        latest_logs = {}
        for email_log in ParticipantEmailLog.objects.filter(participant_id__in=participant_ids).select_related('sent_by').order_by('participant_id', '-created_at'):
            latest_logs.setdefault(email_log.participant_id, email_log)
        for participant in page_obj.object_list:
            participant.latest_email_log = latest_logs.get(participant.id)

    context = {
        'site_settings': SiteSettings.objects.first(),
        'events': Event.objects.order_by('-year', 'name'),
        'page_obj': page_obj,
        'totals': totals,
        'current_filters': {
            'event': str(event_filter or ''),
            'status': legacy_status_filter or '',
            'approval_status': approval_status,
            'payment_status': payment_status_filter,
            'q': search_query,
        },
        'query_string': urlencode(query_params),
        'approval_status_choices': [
            ('pending', 'Pending approval'),
            ('approved', 'Approved'),
            ('denied', 'Denied'),
            ('all', 'All participants'),
        ],
        'payment_status_choices': [
            ('all', 'All payment statuses'),
            ('unpaid_group', 'Needs payment'),
            ('paid_group', 'Paid or completed'),
            ('unpaid', 'Unpaid'),
            ('pending', 'Pending'),
            ('initiated', 'Initiated'),
            ('failed', 'Failed'),
            ('paid', 'Paid'),
            ('completed', 'Completed'),
            ('missing', 'No payment row'),
            ('not_required', 'No fee required'),
        ],
        'participant_form': participant_form,
        'show_participant_form': show_participant_form,
        'participant_lookup_email': participant_lookup_email,
        'participant_lookup_completed': participant_lookup_completed,
    }
    return render(request, 'dashboard_participant_center.html', context)


def _parse_dashboard_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


@dashboard_permission_required('membership')
def dashboard_membership_center(request):
    from website.models import (
        Member,
        MembershipBenefitItem,
        MembershipBenefitModal,
        MembershipPayment,
        MembershipType,
        PendingEventIntent,
        SiteSettings,
    )
    from website.utils_membership import ensure_membership_payment_for_member

    approval_filter = request.POST.get('approval_status') if request.method == 'POST' else request.GET.get('approval_status')
    active_filter = request.POST.get('active_status') if request.method == 'POST' else request.GET.get('active_status')
    type_filter = request.POST.get('membership_type') if request.method == 'POST' else request.GET.get('membership_type')
    search_query = ((request.POST.get('q') if request.method == 'POST' else request.GET.get('q', '')) or '').strip()
    panel = (request.POST.get('panel') if request.method == 'POST' else request.GET.get('panel')) or 'applications'

    approval_filter = approval_filter or 'pending'
    active_filter = active_filter or 'all'
    query_params = {
        'approval_status': approval_filter,
        'active_status': active_filter,
        'panel': panel,
    }
    if type_filter:
        query_params['membership_type'] = type_filter
    if search_query:
        query_params['q'] = search_query
    redirect_url = f"{reverse('dashboard_membership_center')}?{urlencode(query_params)}"

    def filtered_members_queryset(force_approval=None):
        queryset = Member.objects.select_related('user_profile', 'membership_type').prefetch_related(
            'specialties',
            'research_interest_areas',
        ).order_by('-created_at')
        effective_approval = force_approval or approval_filter
        if effective_approval != 'all':
            queryset = queryset.filter(approval_status=effective_approval)
        if type_filter:
            queryset = queryset.filter(membership_type_id=type_filter)
        today = timezone.now().date()
        if active_filter == 'active':
            queryset = queryset.filter(is_active_member=True)
        elif active_filter == 'inactive':
            queryset = queryset.filter(is_active_member=False)
        elif active_filter == 'expired':
            queryset = queryset.filter(subscription_expiry_date__lt=today)
        if search_query:
            queryset = queryset.filter(
                Q(user_profile__name__icontains=search_query)
                | Q(user_profile__email__icontains=search_query)
                | Q(user_profile__phone__icontains=search_query)
                | Q(institution__icontains=search_query)
                | Q(position__icontains=search_query)
            )
        return queryset

    if request.method == 'POST':
        action = request.POST.get('membership_action')
        selected_ids = request.POST.getlist('member_ids')

        if action in ('approve', 'reject') and not selected_ids:
            messages.error(request, 'Select at least one membership application first.')
            return redirect(redirect_url)

        selected_members = Member.objects.filter(pk__in=selected_ids).select_related('user_profile', 'membership_type')

        if action == 'approve':
            approved_count = 0
            for member in selected_members.filter(approval_status='pending'):
                member.approval_status = 'approved'
                member.approved_at = timezone.now()
                member.rejected_at = None
                member.rejection_reason = ''
                member.save(update_fields=['approval_status', 'approved_at', 'rejected_at', 'rejection_reason', 'updated_at'])
                ensure_membership_payment_for_member(member)
                dashboard_log_action(request, member, CHANGE, 'Approved member from Membership Center dashboard.')
                approved_count += 1
            messages.success(request, f'{approved_count} membership application(s) approved. Approval emails follow the existing membership signal.')
            return redirect(redirect_url)

        if action == 'reject':
            rejection_reason = (request.POST.get('rejection_reason') or '').strip()
            if not rejection_reason:
                messages.error(request, 'Write a rejection reason before rejecting selected applications.')
                return redirect(redirect_url)
            rejected_count = 0
            for member in selected_members.filter(approval_status='pending'):
                member.approval_status = 'rejected'
                member.rejected_at = timezone.now()
                member.rejection_reason = rejection_reason
                member.is_active_member = False
                member.save(update_fields=['approval_status', 'rejected_at', 'rejection_reason', 'is_active_member', 'updated_at'])
                dashboard_log_action(request, member, CHANGE, 'Rejected member from Membership Center dashboard.')
                rejected_count += 1
            messages.success(request, f'{rejected_count} membership application(s) rejected. Rejection emails follow the existing membership signal.')
            return redirect(redirect_url)

        if action == 'update_member':
            member = get_object_or_404(Member.objects.select_related('user_profile', 'membership_type'), pk=request.POST.get('member_id'))
            requested_status = request.POST.get('member_approval_status') or member.approval_status
            if requested_status not in dict(Member.APPROVAL_STATUS_CHOICES):
                requested_status = member.approval_status

            if requested_status == 'rejected':
                reason = (request.POST.get('member_rejection_reason') or member.rejection_reason or '').strip()
                if not reason:
                    messages.error(request, 'Add a rejection reason before marking a member as rejected.')
                    return redirect(redirect_url)
                member.rejection_reason = reason
                member.rejected_at = member.rejected_at or timezone.now()
                member.is_active_member = False
            elif requested_status == 'approved':
                member.approved_at = member.approved_at or timezone.now()

            member.approval_status = requested_status
            member.membership_type_id = request.POST.get('member_membership_type') or None
            member.is_active_member = request.POST.get('member_is_active') == 'on'
            member.subscription_start_date = _parse_dashboard_date(request.POST.get('member_start_date'))
            member.subscription_expiry_date = _parse_dashboard_date(request.POST.get('member_expiry_date'))
            try:
                member.order = int(request.POST.get('member_order') or member.order or 0)
            except (TypeError, ValueError):
                member.order = member.order or 0
            member.save(update_fields=[
                'approval_status',
                'approved_at',
                'rejected_at',
                'rejection_reason',
                'membership_type',
                'is_active_member',
                'subscription_start_date',
                'subscription_expiry_date',
                'order',
                'updated_at',
            ])
            dashboard_log_action(request, member, CHANGE, 'Updated member status from Membership Center dashboard.')
            messages.success(request, f'{member.user_profile.name} membership details updated.')
            return redirect(redirect_url)

    members_queryset = filtered_members_queryset(force_approval='pending')
    member_page = Paginator(members_queryset, 15).get_page(request.GET.get('page'))

    approved_unpaid_queryset = Member.objects.filter(
        approval_status='approved',
        is_active_member=False,
    ).select_related('user_profile', 'membership_type').order_by('-approved_at', '-updated_at')
    if type_filter:
        approved_unpaid_queryset = approved_unpaid_queryset.filter(membership_type_id=type_filter)
    if search_query:
        approved_unpaid_queryset = approved_unpaid_queryset.filter(
            Q(user_profile__name__icontains=search_query)
            | Q(user_profile__email__icontains=search_query)
            | Q(user_profile__phone__icontains=search_query)
            | Q(institution__icontains=search_query)
            | Q(position__icontains=search_query)
        )
    approved_unpaid_page = Paginator(approved_unpaid_queryset, 15).get_page(request.GET.get('approved_unpaid_page'))

    active_members_queryset = Member.objects.filter(
        approval_status='approved',
        is_active_member=True,
    ).select_related('user_profile', 'membership_type').order_by('-updated_at')
    if type_filter:
        active_members_queryset = active_members_queryset.filter(membership_type_id=type_filter)
    if active_filter == 'expired':
        active_members_queryset = active_members_queryset.filter(subscription_expiry_date__lt=timezone.now().date())
    if search_query:
        active_members_queryset = active_members_queryset.filter(
            Q(user_profile__name__icontains=search_query)
            | Q(user_profile__email__icontains=search_query)
            | Q(user_profile__phone__icontains=search_query)
            | Q(institution__icontains=search_query)
            | Q(position__icontains=search_query)
        )
    active_page = Paginator(active_members_queryset, 10).get_page(request.GET.get('active_page'))

    shown_profile_ids = {
        member.user_profile_id
        for member in list(member_page.object_list) + list(approved_unpaid_page.object_list) + list(active_page.object_list)
        if member.user_profile_id
    }
    latest_payment_by_profile = {}
    if shown_profile_ids:
        for payment in MembershipPayment.objects.filter(user_profile_id__in=shown_profile_ids).select_related('membership_type').order_by('user_profile_id', '-created_at'):
            latest_payment_by_profile.setdefault(payment.user_profile_id, payment)
    for member in list(member_page.object_list) + list(approved_unpaid_page.object_list) + list(active_page.object_list):
        member.latest_membership_payment = latest_payment_by_profile.get(member.user_profile_id)

    intent_queryset = PendingEventIntent.objects.select_related(
        'user_profile',
        'event',
        'participant',
    ).order_by('-created_at')
    if search_query:
        intent_queryset = intent_queryset.filter(
            Q(user_profile__name__icontains=search_query)
            | Q(user_profile__email__icontains=search_query)
            | Q(event__name__icontains=search_query)
        )
    intent_page = Paginator(intent_queryset, 8).get_page(request.GET.get('intent_page'))

    today = timezone.now().date()
    totals = {
        'all': Member.objects.count(),
        'pending': Member.objects.filter(approval_status='pending').count(),
        'approved': Member.objects.filter(approval_status='approved').count(),
        'approved_unpaid': Member.objects.filter(approval_status='approved', is_active_member=False).count(),
        'rejected': Member.objects.filter(approval_status='rejected').count(),
        'active': Member.objects.filter(approval_status='approved', is_active_member=True).count(),
        'inactive': Member.objects.filter(approval_status='approved', is_active_member=False).count(),
        'expired': Member.objects.filter(approval_status='approved', subscription_expiry_date__lt=today).count(),
        'payment_open': MembershipPayment.objects.exclude(status='completed').count(),
        'payment_completed': MembershipPayment.objects.filter(status='completed').count(),
        'pending_intents': PendingEventIntent.objects.filter(status='pending').count(),
    }

    benefit_modal = MembershipBenefitModal.objects.prefetch_related('benefit_items').filter(is_active=True).first()
    context = {
        'site_settings': SiteSettings.objects.first(),
        'member_page': member_page,
        'approved_unpaid_page': approved_unpaid_page,
        'active_page': active_page,
        'intent_page': intent_page,
        'membership_types': MembershipType.objects.order_by('order', 'name'),
        'benefit_modal': benefit_modal,
        'benefit_items': MembershipBenefitItem.objects.filter(modal=benefit_modal, is_active=True).order_by('order', 'id') if benefit_modal else [],
        'benefit_admin_url': admin_changelist_url(MembershipBenefitModal),
        'membership_type_admin_url': admin_changelist_url(MembershipType),
        'totals': totals,
        'current_filters': {
            'approval_status': approval_filter,
            'active_status': active_filter,
            'membership_type': str(type_filter or ''),
            'q': search_query,
            'panel': panel,
            'event': '',
        },
        'query_string': urlencode(query_params),
        'approval_choices': [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('all', 'All applications')],
        'active_choices': [('all', 'All status'), ('active', 'Active'), ('inactive', 'Inactive'), ('expired', 'Expired')],
    }
    return render(request, 'dashboard_membership_center.html', context)


def _generate_event_payment_invoice(payment_record):
    from .pdf_utils import generate_invoice

    invoice_path = generate_invoice(payment_record.participant, payment_record.event, payment_record)
    payment_record.invoice = os.path.relpath(invoice_path, settings.MEDIA_ROOT)
    payment_record.save(update_fields=['invoice', 'updated_at'])
    return invoice_path


def _send_event_payment_invoice_email(payment_record):
    if not payment_record.invoice:
        _generate_event_payment_invoice(payment_record)

    subject = f"Invoice for {payment_record.event.name} {payment_record.event.year}"
    message = (
        f"Dear {payment_record.participant.name},\n\n"
        f"Please find your invoice for {payment_record.event.name} {payment_record.event.year} attached.\n\n"
        "Best regards,\nBSBCS Team"
    )

    send_email_task.delay(
        subject=subject,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[payment_record.participant.email],
        attachment_paths=[payment_record.invoice.path] if getattr(payment_record, 'invoice', None) else None,
    )
    payment_record.email_sent = True
    payment_record.save(update_fields=['email_sent', 'updated_at'])


def _generate_membership_payment_invoice(payment_record):
    from website.utils_membership import generate_membership_invoice

    invoice_path = generate_membership_invoice(payment_record)
    payment_record.invoice = os.path.relpath(invoice_path, settings.MEDIA_ROOT)
    payment_record.save(update_fields=['invoice', 'updated_at'])
    return invoice_path


def _activate_membership_for_completed_payment(payment_record):
    from dateutil.relativedelta import relativedelta
    from website.models import Member
    from website.utils_membership import process_pending_event_intents

    member, _ = Member.objects.get_or_create(user_profile=payment_record.user_profile)
    if member.approval_status != 'approved':
        return False

    today = timezone.now().date()
    if not member.subscription_start_date or not member.subscription_expiry_date or member.subscription_expiry_date < today:
        member.subscription_start_date = today
        current_expiry = today
    else:
        current_expiry = member.subscription_expiry_date

    member.is_active_member = True
    member.subscription_expiry_date = current_expiry + relativedelta(years=payment_record.duration_years)
    member.membership_type = payment_record.membership_type
    member.save()
    process_pending_event_intents(member)
    return True


def _normalize_payment_amount(raw_amount, fallback):
    if raw_amount in (None, ''):
        return fallback
    try:
        return Decimal(str(raw_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Enter a valid amount.')


def _build_dashboard_absolute_url(request, path):
    site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
    if site_url:
        return f"{site_url}{path}"
    return request.build_absolute_uri(path)


def _send_dashboard_corporate_approval_email(request, access_request, corporate_account, created_user):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    user = corporate_account.user
    dashboard_path = reverse('corporate_dashboard')
    login_url = _build_dashboard_absolute_url(request, f"{reverse('corporate_login')}?next={dashboard_path}")
    setup_url = None
    if created_user:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        setup_url = _build_dashboard_absolute_url(
            request,
            reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token}),
        )

    context = {
        'contact_name': access_request.contact_name,
        'company_name': access_request.company_name,
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
        recipient_list=[access_request.email],
        html_message=html_message,
    )


def _send_dashboard_corporate_rejection_email(access_request):
    context = {
        'contact_name': access_request.contact_name,
        'company_name': access_request.company_name,
        'site_name': getattr(settings, 'SITE_NAME', 'BSBCS'),
        'admin_note': access_request.admin_note,
        'support_email': getattr(settings, 'CONTACT_EMAIL', settings.DEFAULT_FROM_EMAIL),
    }
    html_message = render_to_string('emails/corporate_account_rejected.html', context)
    send_email_task.delay(
        subject=f"{context['site_name']} Corporate Access Request Update",
        body=strip_tags(html_message),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[access_request.email],
        html_message=html_message,
    )


def _approve_dashboard_corporate_request(request, access_request):
    user = User.objects.filter(email__iexact=access_request.email).first() or User.objects.filter(username__iexact=access_request.email).first()
    created_user = False
    if not user:
        user = User.objects.create_user(username=access_request.email, email=access_request.email)
        user.set_unusable_password()
        user.first_name = access_request.contact_name[:150]
        user.save()
        created_user = True
        dashboard_log_action(request, user, ADDITION, 'Created corporate login user from Corporate Center dashboard.')

    corporate_account, account_created = CorporateAccount.objects.update_or_create(
        user=user,
        defaults={
            'source_request': access_request,
            'company_name': access_request.company_name,
            'contact_name': access_request.contact_name,
            'contact_designation': access_request.contact_designation,
            'email': access_request.email,
            'phone': access_request.phone,
            'status': 'approved',
            'approved_at': timezone.now(),
        },
    )
    access_request.status = 'approved'
    access_request.save(update_fields=['status', 'updated_at'])
    dashboard_log_action(
        request,
        corporate_account,
        ADDITION if account_created else CHANGE,
        'Approved corporate access from Corporate Center dashboard.',
    )
    _send_dashboard_corporate_approval_email(request, access_request, corporate_account, created_user)
    return corporate_account


@dashboard_permission_required('corporate')
def dashboard_corporate_center(request):
    from website.models import SiteSettings

    site_settings = SiteSettings.objects.first()
    event_filter = request.POST.get('event') if request.method == 'POST' else request.GET.get('event')
    request_status = request.POST.get('request_status') if request.method == 'POST' else request.GET.get('request_status')
    attendee_status = request.POST.get('attendee_status') if request.method == 'POST' else request.GET.get('attendee_status')
    account_status = request.POST.get('account_status') if request.method == 'POST' else request.GET.get('account_status')
    active_panel = request.POST.get('panel') if request.method == 'POST' else request.GET.get('panel')
    search_query = ((request.POST.get('q') if request.method == 'POST' else request.GET.get('q', '')) or '').strip()
    request_status = request_status or 'pending'
    attendee_status = attendee_status or 'pending'
    account_status = account_status or 'approved'
    active_panel = active_panel or 'access'

    query_params = {
        'request_status': request_status,
        'attendee_status': attendee_status,
        'account_status': account_status,
    }
    if event_filter:
        query_params['event'] = event_filter
    if search_query:
        query_params['q'] = search_query
    if active_panel:
        query_params['panel'] = active_panel
    redirect_url = f"{reverse('dashboard_corporate_center')}?{urlencode(query_params)}"

    if request.method == 'POST':
        action = request.POST.get('corporate_action')
        try:
            if action == 'approve_requests':
                request_ids = request.POST.getlist('request_ids')
                if not request_ids:
                    messages.error(request, 'Select at least one corporate access request first.')
                    return redirect(redirect_url)
                approved = 0
                for access_request in CorporateAccountRequest.objects.filter(pk__in=request_ids):
                    _approve_dashboard_corporate_request(request, access_request)
                    approved += 1
                messages.success(request, f'{approved} corporate access request(s) approved and emailed.')

            elif action == 'reject_requests':
                request_ids = request.POST.getlist('request_ids')
                admin_note = (request.POST.get('admin_note') or '').strip()
                if not request_ids:
                    messages.error(request, 'Select at least one corporate access request first.')
                    return redirect(redirect_url)
                rejected = 0
                for access_request in CorporateAccountRequest.objects.filter(pk__in=request_ids):
                    access_request.status = 'rejected'
                    if admin_note:
                        access_request.admin_note = admin_note
                    access_request.save(update_fields=['status', 'admin_note', 'updated_at'])
                    _send_dashboard_corporate_rejection_email(access_request)
                    dashboard_log_action(request, access_request, CHANGE, 'Rejected corporate access from Corporate Center dashboard.')
                    rejected += 1
                messages.success(request, f'{rejected} corporate access request(s) rejected and emailed.')

            elif action in ('approve_attendees', 'deny_attendees'):
                attendee_ids = request.POST.getlist('attendee_ids')
                if not attendee_ids:
                    messages.error(request, 'Select at least one corporate attendee first.')
                    return redirect(redirect_url)
                attendees = CorporateEventAttendee.objects.filter(pk__in=attendee_ids).select_related('registration')
                if action == 'approve_attendees':
                    from registration.admin import approve_corporate_attendees

                    approved_count = approve_corporate_attendees(request, attendees)
                    for attendee in attendees:
                        dashboard_log_action(request, attendee, CHANGE, 'Approved corporate attendee from Corporate Center dashboard.')
                    messages.success(request, f'{approved_count} attendee(s) approved, converted to participants, and emailed.')
                else:
                    affected_registrations = list({attendee.registration for attendee in attendees})
                    denied_count = attendees.update(review_status='denied')
                    from registration.admin import update_corporate_registration_status

                    for corporate_registration in affected_registrations:
                        update_corporate_registration_status(corporate_registration)
                    messages.success(request, f'{denied_count} attendee(s) denied.')

            elif action == 'create_invoice':
                invoice_attendee_ids = request.POST.getlist('invoice_attendee_ids')
                if not invoice_attendee_ids:
                    messages.error(request, 'Select at least one approved attendee first to generate an invoice.')
                    return redirect(redirect_url)
                
                from registration.admin import create_corporate_payment_for_registration
                
                attendees = CorporateEventAttendee.objects.filter(id__in=invoice_attendee_ids).select_related('registration__corporate_account', 'registration__event')
                registration_map = {}
                for att in attendees:
                    registration_map.setdefault(att.registration, []).append(att.id)

                created = 0
                skipped = 0
                for corporate_registration, selected_ids in registration_map.items():
                    corporate_payment, was_created, reason = create_corporate_payment_for_registration(
                        corporate_registration, request=request, selected_attendee_ids=selected_ids
                    )
                    if was_created:
                        dashboard_log_action(request, corporate_payment, ADDITION, 'Created corporate invoice from Corporate Center dashboard.')
                        created += 1
                    else:
                        skipped += 1
                        if reason:
                            messages.warning(request, f'{corporate_registration.corporate_account.company_name}: {reason}')
                messages.success(request, f'{created} corporate invoice(s) created. {skipped} skipped.')

            elif action == 'update_account':
                account_id = request.POST.get('account_id')
                corporate_account = get_object_or_404(CorporateAccount, pk=account_id)
                corporate_account.company_name = (request.POST.get('company_name') or corporate_account.company_name).strip()
                corporate_account.contact_name = (request.POST.get('contact_name') or corporate_account.contact_name).strip()
                corporate_account.contact_designation = (request.POST.get('contact_designation') or '').strip() or None
                corporate_account.email = (request.POST.get('email') or corporate_account.email).strip()
                updated_phone = (request.POST.get('phone') or corporate_account.phone).strip()
                try:
                    corporate_account.phone = normalize_phone_number(updated_phone, '')
                except ValidationError:
                    corporate_account.phone = updated_phone
                requested_status = request.POST.get('status')
                if requested_status in dict(CorporateAccount.APPROVAL_STATUS_CHOICES):
                    corporate_account.status = requested_status
                    if requested_status == 'approved' and not corporate_account.approved_at:
                        corporate_account.approved_at = timezone.now()
                corporate_account.save(update_fields=[
                    'company_name',
                    'contact_name',
                    'contact_designation',
                    'email',
                    'phone',
                    'status',
                    'approved_at',
                    'updated_at',
                ])
                dashboard_log_action(request, corporate_account, CHANGE, 'Updated corporate account from Corporate Center dashboard.')
                messages.success(request, f'{corporate_account.company_name} account details updated.')

            elif action in ('activate_account', 'suspend_account'):
                account_id = request.POST.get('account_id')
                corporate_account = get_object_or_404(CorporateAccount, pk=account_id)
                corporate_account.status = 'approved' if action == 'activate_account' else 'suspended'
                if corporate_account.status == 'approved' and not corporate_account.approved_at:
                    corporate_account.approved_at = timezone.now()
                    corporate_account.save(update_fields=['status', 'approved_at', 'updated_at'])
                else:
                    corporate_account.save(update_fields=['status', 'updated_at'])
                dashboard_log_action(request, corporate_account, CHANGE, 'Changed corporate account status from Corporate Center dashboard.')
                messages.success(request, f'{corporate_account.company_name} marked {corporate_account.get_status_display().lower()}.')

            elif action == 'set_quotas':
                if not event_filter:
                    messages.error(request, 'Select an event first to set complementary quotas.')
                    return redirect(redirect_url)
                
                updated_count = 0
                for account in CorporateAccount.objects.filter(status='approved'):
                    quota_val_str = request.POST.get(f'quota_{account.id}')
                    if quota_val_str is not None and quota_val_str.isdigit():
                        quota_val = int(quota_val_str)
                        CorporateEventComplementaryQuota.objects.update_or_create(
                            corporate_account=account,
                            event_id=event_filter,
                            defaults={'allocated_count': quota_val}
                        )
                        updated_count += 1
                messages.success(request, f'Complementary quotas updated for {updated_count} account(s).')

            else:
                messages.error(request, 'Choose a valid corporate workflow action.')
        except Exception as exc:
            logger.exception("Corporate center action failed: %s", exc)
            messages.error(request, str(exc))
        return redirect(redirect_url)

    events = Event.objects.order_by('-year', '-start_date', 'name')
    access_requests = CorporateAccountRequest.objects.order_by('-created_at')
    accounts = CorporateAccount.objects.select_related('user', 'source_request').order_by('company_name')
    registrations = CorporateEventRegistration.objects.select_related('corporate_account', 'event').prefetch_related('attendees', 'corporate_payments').order_by('-created_at')
    attendees = CorporateEventAttendee.objects.select_related('registration__corporate_account', 'registration__event', 'participant', 'matched_user').order_by('-created_at')

    if event_filter:
        registrations = registrations.filter(event_id=event_filter)
        attendees = attendees.filter(registration__event_id=event_filter)

    # For the quotas tab, fetch all approved accounts and attach their quotas
    quota_accounts = list(CorporateAccount.objects.filter(status='approved').order_by('company_name'))
    if event_filter:
        quotas_dict = {
            q.corporate_account_id: q.allocated_count 
            for q in CorporateEventComplementaryQuota.objects.filter(event_id=event_filter)
        }
        for acc in quota_accounts:
            acc.current_quota = quotas_dict.get(acc.id, 0)

    if request_status != 'all':
        access_requests = access_requests.filter(status=request_status)
    if account_status != 'all':
        accounts = accounts.filter(status=account_status)
    if attendee_status != 'all':
        attendees = attendees.filter(review_status=attendee_status)

    if search_query:
        access_requests = access_requests.filter(
            Q(company_name__icontains=search_query)
            | Q(contact_name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(phone__icontains=search_query)
        )
        accounts = accounts.filter(
            Q(company_name__icontains=search_query)
            | Q(contact_name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(user__email__icontains=search_query)
        )
        registrations = registrations.filter(
            Q(corporate_account__company_name__icontains=search_query)
            | Q(corporate_account__email__icontains=search_query)
            | Q(event__name__icontains=search_query)
        )
        attendees = attendees.filter(
            Q(name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(organization__icontains=search_query)
            | Q(registration__corporate_account__company_name__icontains=search_query)
            | Q(registration__event__name__icontains=search_query)
        )

    registration_page = Paginator(registrations, 8).get_page(request.GET.get('registrations_page'))
    for corporate_registration in registration_page.object_list:
        registration_attendees = corporate_registration.attendees.all()
        corporate_registration.pending_count = registration_attendees.filter(review_status='pending').count()
        corporate_registration.approved_count = registration_attendees.filter(review_status='approved').count()
        corporate_registration.denied_count = registration_attendees.filter(review_status='denied').count()
        corporate_registration.invoice_count = corporate_registration.corporate_payments.count()
        corporate_registration.open_invoice_count = corporate_registration.corporate_payments.filter(status__in=UNPAID_PAYMENT_STATUSES).count()

    event_scope = {'event_id': event_filter} if event_filter else {}
    attendee_event_scope = {'registration__event_id': event_filter} if event_filter else {}
    totals = {
        'pending_requests': CorporateAccountRequest.objects.filter(status='pending').count(),
        'approved_accounts': CorporateAccount.objects.filter(status='approved').count(),
        'pending_attendees': CorporateEventAttendee.objects.filter(**attendee_event_scope, review_status='pending').count(),
        'approved_attendees': CorporateEventAttendee.objects.filter(**attendee_event_scope, review_status='approved').count(),
        'open_invoices': CorporatePayment.objects.filter(**event_scope, status__in=UNPAID_PAYMENT_STATUSES).count(),
        'completed_invoices': CorporatePayment.objects.filter(**event_scope, status__in=['completed', 'paid']).count(),
    }

    context = {
        'site_settings': site_settings,
        'events': events,
        'request_page_obj': Paginator(access_requests, 6).get_page(request.GET.get('requests_page')),
        'account_page_obj': Paginator(accounts, 6).get_page(request.GET.get('accounts_page')),
        'registration_page_obj': registration_page,
        'attendee_page_obj': Paginator(attendees, 10).get_page(request.GET.get('attendees_page')),
        'quota_accounts': quota_accounts,
        'totals': totals,
        'current_filters': {
            'event': event_filter or '',
            'request_status': request_status,
            'attendee_status': attendee_status,
            'account_status': account_status,
            'q': search_query,
            'panel': active_panel,
        },
        'query_string': urlencode(query_params),
        'request_status_choices': [('pending', 'Pending requests'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('all', 'All requests')],
        'attendee_status_choices': [('pending', 'Pending attendees'), ('approved', 'Approved attendees'), ('denied', 'Denied attendees'), ('all', 'All attendees')],
        'account_status_choices': [('approved', 'Approved accounts'), ('suspended', 'Suspended accounts'), ('all', 'All accounts')],
    }
    return render(request, 'dashboard_corporate_center.html', context)


@dashboard_permission_required('payments')
def dashboard_payment_center(request):
    from website.models import MembershipPayment, MembershipType, SiteSettings
    from website.utils_membership import send_membership_invoice_email

    site_settings = SiteSettings.objects.first()
    source_filter = request.POST.get('source') if request.method == 'POST' else request.GET.get('source')
    status_filter = request.POST.get('status') if request.method == 'POST' else request.GET.get('status')
    event_filter = request.POST.get('event') if request.method == 'POST' else request.GET.get('event')
    search_query = ((request.POST.get('q') if request.method == 'POST' else request.GET.get('q', '')) or '').strip()
    source_filter = source_filter or 'all'
    status_filter = status_filter or 'open'
    event_filter_applies = source_filter in ('all', 'event', 'corporate')
    if not event_filter_applies:
        event_filter = ''

    query_params = {'source': source_filter, 'status': status_filter}
    if event_filter:
        query_params['event'] = event_filter
    if search_query:
        query_params['q'] = search_query
    redirect_url = f"{reverse('dashboard_payment_center')}?{urlencode(query_params)}"

    if request.method == 'POST':
        payment_source = request.POST.get('payment_source')
        payment_id = request.POST.get('payment_id')
        payment_action = request.POST.get('payment_action')

        try:
            if payment_source == 'event':
                payment_record = get_object_or_404(
                    PaymentStatus.objects.select_related('participant', 'event'),
                    pk=payment_id,
                )
                if payment_action == 'update':
                    previous_status = payment_record.status
                    payment_record.status = request.POST.get('manual_status') or payment_record.status
                    payment_record.amount = _normalize_payment_amount(request.POST.get('manual_amount'), payment_record.amount)
                    payment_record.transaction_id = (request.POST.get('manual_transaction_id') or '').strip() or None
                    payment_record.trxID = (request.POST.get('manual_trx_id') or '').strip() or None
                    invoice_number = (request.POST.get('manual_invoice_number') or '').strip()
                    if invoice_number:
                        payment_record.merchant_invoice_number = invoice_number
                    payment_record.save()
                    if payment_record.status in SUCCESS_PAYMENT_STATUSES and previous_status not in SUCCESS_PAYMENT_STATUSES:
                        queue_registration_payment_received_sms(payment_record, source='dashboard_event_payment_completed')
                    dashboard_log_action(request, payment_record, CHANGE, 'Updated event payment from Payment Center dashboard.')
                    messages.success(request, f'Event payment updated for {payment_record.participant.name}.')
                elif payment_action == 'generate_invoice':
                    if payment_record.invoice:
                        messages.info(request, f'Invoice already exists for {payment_record.participant.name}. Use View invoice.')
                    else:
                        _generate_event_payment_invoice(payment_record)
                        dashboard_log_action(request, payment_record, CHANGE, 'Generated event invoice from Payment Center dashboard.')
                        messages.success(request, f'Invoice generated for {payment_record.participant.name}.')
                elif payment_action == 'refresh_invoice_qr':
                    _generate_event_payment_invoice(payment_record)
                    dashboard_log_action(request, payment_record, CHANGE, 'Refreshed event invoice QR from Payment Center dashboard.')
                    messages.success(request, f'QR code created and invoice refreshed for {payment_record.participant.name}.')
                elif payment_action == 'email_invoice':
                    if not payment_record.invoice:
                        messages.error(request, 'Generate the invoice first, then email it.')
                    else:
                        _send_event_payment_invoice_email(payment_record)
                        dashboard_log_action(request, payment_record, CHANGE, 'Sent event invoice email from Payment Center dashboard.')
                        messages.success(request, f'Invoice email sent to {payment_record.participant.email}.')

            elif payment_source == 'membership':
                payment_record = get_object_or_404(
                    MembershipPayment.objects.select_related('user_profile', 'membership_type'),
                    pk=payment_id,
                )
                if payment_action == 'update':
                    previous_status = payment_record.status
                    payment_record.status = request.POST.get('manual_status') or payment_record.status
                    payment_record.amount = _normalize_payment_amount(request.POST.get('manual_amount'), payment_record.amount)
                    payment_record.transaction_id = (request.POST.get('manual_transaction_id') or '').strip() or None
                    payment_record.trxID = (request.POST.get('manual_trx_id') or '').strip() or None
                    invoice_number = (request.POST.get('manual_invoice_number') or '').strip()
                    if invoice_number:
                        payment_record.merchant_invoice_number = invoice_number
                    payment_record.save()
                    dashboard_log_action(request, payment_record, CHANGE, 'Updated membership payment from Payment Center dashboard.')
                    if payment_record.status == 'completed' and previous_status != 'completed':
                        activated = _activate_membership_for_completed_payment(payment_record)
                        if activated:
                            messages.success(request, f'Membership payment updated and membership activated for {payment_record.user_profile.name}.')
                        else:
                            messages.warning(request, f'Payment updated, but membership is not approved yet for {payment_record.user_profile.name}.')
                    else:
                        messages.success(request, f'Membership payment updated for {payment_record.user_profile.name}.')
                elif payment_action == 'generate_invoice':
                    if payment_record.invoice:
                        messages.info(request, f'Membership invoice already exists for {payment_record.user_profile.name}. Use View invoice.')
                    else:
                        _generate_membership_payment_invoice(payment_record)
                        dashboard_log_action(request, payment_record, CHANGE, 'Generated membership invoice from Payment Center dashboard.')
                        messages.success(request, f'Membership invoice generated for {payment_record.user_profile.name}.')
                elif payment_action == 'email_invoice':
                    if not payment_record.invoice:
                        messages.error(request, 'Generate the membership invoice first, then email it.')
                    elif send_membership_invoice_email(payment_record):
                        dashboard_log_action(request, payment_record, CHANGE, 'Sent membership invoice email from Payment Center dashboard.')
                        messages.success(request, f'Membership invoice email sent to {payment_record.user_profile.email}.')
                    else:
                        messages.error(request, 'Could not send membership invoice email. Check invoice file and email settings.')
            elif payment_source == 'corporate':
                payment_record = get_object_or_404(
                    CorporatePayment.objects.select_related('corporate_account', 'event', 'corporate_registration').prefetch_related('attendees__participant'),
                    pk=payment_id,
                )
                if payment_action == 'update':
                    previous_status = payment_record.status
                    payment_record.status = request.POST.get('manual_status') or payment_record.status
                    payment_record.amount = _normalize_payment_amount(request.POST.get('manual_amount'), payment_record.amount)
                    payment_record.transaction_id = (request.POST.get('manual_transaction_id') or '').strip() or None
                    payment_record.trxID = (request.POST.get('manual_trx_id') or '').strip() or None
                    invoice_number = (request.POST.get('manual_invoice_number') or '').strip()
                    if invoice_number:
                        payment_record.merchant_invoice_number = invoice_number
                    payment_record.save()
                    dashboard_log_action(request, payment_record, CHANGE, 'Updated corporate payment from Payment Center dashboard.')
                    if payment_record.status in ['completed', 'paid'] and previous_status not in ['completed', 'paid']:
                        updated_participant_payments = 0
                        for attendee in payment_record.attendees.select_related('participant'):
                            if not attendee.participant_id:
                                continue
                            participant_payment = PaymentStatus.objects.filter(
                                participant=attendee.participant,
                                event=payment_record.event,
                            ).first()
                            if participant_payment:
                                participant_payment.status = 'completed'
                                participant_payment.transaction_id = payment_record.transaction_id
                                participant_payment.trxID = payment_record.trxID
                                participant_payment.save(update_fields=['status', 'transaction_id', 'trxID', 'updated_at'])
                                updated_participant_payments += 1
                        messages.success(request, f'Corporate payment updated and {updated_participant_payments} participant payment row(s) marked completed.')
                    else:
                        messages.success(request, f'Corporate payment updated for {payment_record.corporate_account.company_name}.')
                elif payment_action == 'generate_invoice':
                    if payment_record.invoice:
                        messages.info(request, f'Corporate invoice already exists for {payment_record.corporate_account.company_name}. Use View invoice.')
                    else:
                        generate_corporate_invoice(payment_record)
                        dashboard_log_action(request, payment_record, CHANGE, 'Generated corporate invoice from Payment Center dashboard.')
                        messages.success(request, f'Corporate invoice generated for {payment_record.corporate_account.company_name}.')
                elif payment_action == 'email_invoice':
                    from registration.admin import send_corporate_invoice_email

                    if not payment_record.invoice:
                        generate_corporate_invoice(payment_record)
                    if send_corporate_invoice_email(payment_record, request):
                        dashboard_log_action(request, payment_record, CHANGE, 'Sent corporate invoice email from Payment Center dashboard.')
                        messages.success(request, f'Corporate invoice email sent to {payment_record.corporate_account.email}.')
                    else:
                        messages.error(request, 'Could not send corporate invoice email. Check invoice file and email settings.')
            else:
                messages.error(request, 'Choose a valid payment row.')
        except Exception as exc:
            logger.exception("Payment center action failed: %s", exc)
            messages.error(request, str(exc))
        return redirect(redirect_url)

    events = Event.objects.order_by('-year', '-start_date', 'name')
    event_payments = PaymentStatus.objects.select_related('participant', 'event').order_by('-updated_at')
    membership_payments = MembershipPayment.objects.select_related('user_profile', 'membership_type').order_by('-updated_at')
    corporate_payments = CorporatePayment.objects.select_related('corporate_account', 'event', 'corporate_registration').prefetch_related('attendees').order_by('-updated_at')

    if event_filter:
        event_payments = event_payments.filter(event_id=event_filter)
        corporate_payments = corporate_payments.filter(event_id=event_filter)

    if search_query:
        event_payments = event_payments.filter(
            Q(participant__name__icontains=search_query)
            | Q(participant__email__icontains=search_query)
            | Q(event__name__icontains=search_query)
            | Q(merchant_invoice_number__icontains=search_query)
            | Q(transaction_id__icontains=search_query)
            | Q(trxID__icontains=search_query)
        )
        membership_payments = membership_payments.filter(
            Q(user_profile__name__icontains=search_query)
            | Q(user_profile__email__icontains=search_query)
            | Q(merchant_invoice_number__icontains=search_query)
            | Q(transaction_id__icontains=search_query)
            | Q(trxID__icontains=search_query)
        )
        corporate_payments = corporate_payments.filter(
            Q(corporate_account__company_name__icontains=search_query)
            | Q(corporate_account__contact_name__icontains=search_query)
            | Q(corporate_account__email__icontains=search_query)
            | Q(event__name__icontains=search_query)
            | Q(merchant_invoice_number__icontains=search_query)
            | Q(transaction_id__icontains=search_query)
            | Q(trxID__icontains=search_query)
        )

    if status_filter == 'open':
        event_payments = event_payments.filter(status__in=UNPAID_PAYMENT_STATUSES)
        membership_payments = membership_payments.exclude(status='completed')
        corporate_payments = corporate_payments.filter(status__in=UNPAID_PAYMENT_STATUSES)
    elif status_filter == 'paid':
        event_payments = event_payments.filter(status__in=PAID_PAYMENT_STATUSES)
        membership_payments = membership_payments.filter(status='completed')
        corporate_payments = corporate_payments.filter(status__in=['completed', 'paid'])
    elif status_filter != 'all':
        event_payments = event_payments.filter(status=status_filter)
        membership_payments = membership_payments.filter(status=status_filter)
        corporate_payments = corporate_payments.filter(status=status_filter)

    event_rows = []
    membership_rows = []
    corporate_rows = []
    if source_filter in ('all', 'event'):
        event_rows = [
            {
                'source': 'event',
                'source_label': 'Event',
                'id': payment.id,
                'owner_name': payment.participant.name,
                'owner_email': payment.participant.email,
                'context': f'{payment.event.name} {payment.event.year}',
                'amount': payment.amount or 0,
                'status': payment.status,
                'status_label': payment.get_status_display(),
                'invoice_number': payment.merchant_invoice_number or '-',
                'transaction_id': payment.transaction_id or '',
                'trx_id': payment.trxID or '',
                'invoice_url': payment.invoice.url if payment.invoice else '',
                'invoice_ready': bool(payment.invoice),
                'qr_url': payment.qr_code.url if payment.qr_code else '',
                'qr_ready': bool(payment.qr_code),
                'email_sent': payment.email_sent,
                'email_trackable': True,
                'email_sent_at': payment.updated_at if payment.email_sent else None,
                'updated_at': payment.updated_at,
                'status_choices': PaymentStatus.STATUS_CHOICES,
            }
            for payment in event_payments[:350]
        ]
    if source_filter in ('all', 'membership'):
        membership_rows = [
            {
                'source': 'membership',
                'source_label': 'Membership',
                'id': payment.id,
                'owner_name': payment.user_profile.name,
                'owner_email': payment.user_profile.email,
                'context': payment.membership_type.name if payment.membership_type else 'Membership',
                'amount': payment.amount or 0,
                'status': payment.status,
                'status_label': payment.get_status_display(),
                'invoice_number': payment.merchant_invoice_number or '-',
                'transaction_id': payment.transaction_id or '',
                'trx_id': payment.trxID or '',
                'invoice_url': payment.invoice.url if payment.invoice else '',
                'invoice_ready': bool(payment.invoice),
                'qr_url': '',
                'qr_ready': False,
                'email_sent': False,
                'email_trackable': False,
                'email_sent_at': None,
                'updated_at': payment.updated_at,
                'status_choices': MembershipPayment.STATUS_CHOICES,
            }
            for payment in membership_payments[:350]
        ]
    if source_filter in ('all', 'corporate'):
        corporate_rows = [
            {
                'source': 'corporate',
                'source_label': 'Corporate',
                'id': payment.id,
                'owner_name': payment.corporate_account.company_name,
                'owner_email': payment.corporate_account.email,
                'context': f'{payment.event.name} {payment.event.year} - {payment.attendees.count()} attendee(s)',
                'amount': payment.amount or 0,
                'status': payment.status,
                'status_label': payment.get_status_display(),
                'invoice_number': payment.merchant_invoice_number or '-',
                'transaction_id': payment.transaction_id or '',
                'trx_id': payment.trxID or '',
                'invoice_url': payment.invoice.url if payment.invoice else '',
                'invoice_ready': bool(payment.invoice),
                'qr_url': '',
                'qr_ready': False,
                'email_sent': payment.email_sent,
                'email_trackable': True,
                'email_sent_at': payment.updated_at if payment.email_sent else None,
                'updated_at': payment.updated_at,
                'status_choices': CorporatePayment.STATUS_CHOICES,
            }
            for payment in corporate_payments[:350]
        ]

    payment_rows = sorted(event_rows + membership_rows + corporate_rows, key=lambda row: row['updated_at'] or timezone.now(), reverse=True)
    page_obj = Paginator(payment_rows, 15).get_page(request.GET.get('page'))

    include_event_totals = source_filter in ('all', 'event')
    include_membership_totals = source_filter in ('all', 'membership')
    include_corporate_totals = source_filter in ('all', 'corporate')
    totals = {
        'event_open': event_payments.filter(status__in=UNPAID_PAYMENT_STATUSES).count() if include_event_totals else 0,
        'event_paid': event_payments.filter(status__in=PAID_PAYMENT_STATUSES).count() if include_event_totals else 0,
        'membership_open': membership_payments.exclude(status='completed').count() if include_membership_totals else 0,
        'membership_paid': membership_payments.filter(status='completed').count() if include_membership_totals else 0,
        'corporate_open': corporate_payments.filter(status__in=UNPAID_PAYMENT_STATUSES).count() if include_corporate_totals else 0,
        'corporate_paid': corporate_payments.filter(status__in=['completed', 'paid']).count() if include_corporate_totals else 0,
        'event_revenue': (event_payments.filter(status__in=PAID_PAYMENT_STATUSES).aggregate(total=Sum('amount'))['total'] or 0) if include_event_totals else 0,
        'membership_revenue': (membership_payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0) if include_membership_totals else 0,
        'corporate_revenue': (corporate_payments.filter(status__in=['completed', 'paid']).aggregate(total=Sum('amount'))['total'] or 0) if include_corporate_totals else 0,
        'missing_event_invoices': event_payments.filter(Q(invoice='') | Q(invoice__isnull=True)).count() if include_event_totals else 0,
        'missing_membership_invoices': membership_payments.filter(Q(invoice='') | Q(invoice__isnull=True)).count() if include_membership_totals else 0,
        'missing_corporate_invoices': corporate_payments.filter(Q(invoice='') | Q(invoice__isnull=True)).count() if include_corporate_totals else 0,
    }
    totals['revenue'] = totals['event_revenue'] + totals['membership_revenue'] + totals['corporate_revenue']

    context = {
        'site_settings': site_settings,
        'events': events,
        'page_obj': page_obj,
        'totals': totals,
        'current_filters': {
            'source': source_filter,
            'status': status_filter,
            'event': event_filter or '',
            'q': search_query,
        },
        'event_filter_applies': event_filter_applies,
        'show_event_stats': source_filter in ('all', 'event'),
        'show_membership_stats': source_filter in ('all', 'membership'),
        'query_string': urlencode(query_params),
        'source_choices': [
            ('all', 'All sources'),
            ('event', 'Event payments'),
            ('membership', 'Membership payments'),
            ('corporate', 'Corporate payments'),
        ],
        'status_choices': [
            ('open', 'Needs payment / review'),
            ('paid', 'Paid / completed'),
            ('all', 'All statuses'),
            ('initiated', 'Initiated'),
            ('pending', 'Pending'),
            ('unpaid', 'Unpaid'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
            ('completed', 'Completed'),
            ('refunded', 'Refunded'),
        ],
        'membership_types': MembershipType.objects.filter(is_active=True).order_by('order', 'name'),
    }
    return render(request, 'dashboard_payment_center.html', context)


def _issue_registration_kit(payment_record):
    kit, _ = RegistrationKit.objects.get_or_create(
        event=payment_record.event,
        payment_status=payment_record,
        defaults={'status': 'not_issued'},
    )
    if kit.status == 'issued':
        return kit, False

    kit.status = 'issued'
    kit.issued_at = timezone.now()
    kit.save(update_fields=['status', 'issued_at'])
    return kit, True


def _registration_qr_zip(payment_records):
    from .qr_utils import ensure_registration_qr, registration_qr_filename

    buffer = io.BytesIO()
    added = 0
    used_names = set()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for payment in payment_records:
            try:
                ensure_registration_qr(payment)
                payment.refresh_from_db(fields=['qr_code'])
            except Exception as exc:
                logger.exception('Could not prepare registration QR for payment %s: %s', payment.pk, exc)
                continue

            qr_file = payment.qr_code
            if not qr_file or not qr_file.name or not qr_file.storage.exists(qr_file.name):
                continue

            archive_name = os.path.basename(registration_qr_filename(payment))
            if archive_name in used_names:
                base, extension = os.path.splitext(archive_name)
                archive_name = f'{base}_{payment.pk}{extension}'
            used_names.add(archive_name)
            with qr_file.storage.open(qr_file.name, 'rb') as source_file:
                archive.writestr(archive_name, source_file.read())
            added += 1

    buffer.seek(0)
    return buffer, added


@dashboard_permission_required('kits')
def dashboard_registration_kit_center(request):
    from website.models import SiteSettings

    site_settings = SiteSettings.objects.first()
    events = Event.objects.order_by('-year', '-start_date', 'name')
    default_event = events.filter(event_status='active').first() or events.first()
    event_filter = request.POST.get('event') if request.method == 'POST' else request.GET.get('event')
    if not event_filter and default_event:
        event_filter = str(default_event.id)
    search_query = ((request.POST.get('q') if request.method == 'POST' else request.GET.get('q', '')) or '').strip()
    kit_status_filter = request.POST.get('kit_status') if request.method == 'POST' else request.GET.get('kit_status')
    kit_status_filter = kit_status_filter or 'pending'

    query_params = {}
    if event_filter:
        query_params['event'] = event_filter
    if search_query:
        query_params['q'] = search_query
    if kit_status_filter:
        query_params['kit_status'] = kit_status_filter
    redirect_url = f"{reverse('dashboard_registration_kit_center')}?{urlencode(query_params)}"

    eligible_payments = PaymentStatus.objects.select_related('participant', 'event').filter(
        status='completed',
        participant__approved=True,
        participant__denied=False,
    )
    if event_filter:
        eligible_payments = eligible_payments.filter(event_id=event_filter)

    if request.method == 'POST':
        kit_action = request.POST.get('kit_action')
        qr_action = request.POST.get('qr_action')
        try:
            if qr_action in {'download_selected', 'download_all_filtered'}:
                qr_payments = eligible_payments
                if search_query:
                    qr_payments = qr_payments.filter(
                        Q(participant__name__icontains=search_query)
                        | Q(participant__email__icontains=search_query)
                        | Q(participant__phone__icontains=search_query)
                        | Q(participant__organization__icontains=search_query)
                        | Q(participant__BMDC_registration_number__icontains=search_query)
                        | Q(merchant_invoice_number__icontains=search_query)
                        | Q(transaction_id__icontains=search_query)
                        | Q(trxID__icontains=search_query)
                    )

                issued_payment_ids = RegistrationKit.objects.filter(
                    status='issued',
                    payment_status__in=qr_payments,
                ).values_list('payment_status_id', flat=True)
                if kit_status_filter == 'issued':
                    qr_payments = qr_payments.filter(pk__in=issued_payment_ids)
                elif kit_status_filter == 'pending':
                    qr_payments = qr_payments.exclude(pk__in=issued_payment_ids)

                selection_scope = request.POST.get('selection_scope', 'page')
                if qr_action == 'download_selected' and selection_scope != 'all_filtered':
                    selected_ids = request.POST.getlist('qr_payment_ids')
                    qr_payments = qr_payments.filter(pk__in=selected_ids)

                qr_payments = list(qr_payments.order_by('participant__name', 'participant__email'))
                if not qr_payments:
                    messages.error(request, 'Select at least one eligible participant QR code to download.')
                    return redirect(redirect_url)

                zip_buffer, added_count = _registration_qr_zip(qr_payments)
                if not added_count:
                    messages.error(request, 'No QR image files could be prepared for this selection.')
                    return redirect(redirect_url)

                event_label = 'event'
                if event_filter:
                    selected_event = events.filter(pk=event_filter).first()
                    if selected_event:
                        event_label = slugify(f'{selected_event.name}-{selected_event.year}') or f'event-{selected_event.pk}'
                response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
                response['Content-Disposition'] = f'attachment; filename="{event_label}-registration-qr-codes.zip"'
                return response
            elif kit_action == 'issue':
                payment_record = get_object_or_404(eligible_payments, pk=request.POST.get('payment_id'))
                kit, issued_now = _issue_registration_kit(payment_record)
                if issued_now:
                    dashboard_log_action(request, kit, CHANGE, 'Issued registration kit from Kit Center dashboard.')
                    messages.success(request, f'Registration kit issued to {payment_record.participant.name} at {kit.issued_at:%b %d, %Y %I:%M %p}.')
                else:
                    messages.info(request, f'Registration kit was already issued to {payment_record.participant.name}.')
            elif kit_action == 'scan_issue':
                scan_code = (request.POST.get('scan_code') or '').strip()
                if not event_filter:
                    messages.error(request, 'Choose an event before scanning.')
                elif not scan_code:
                    messages.error(request, 'Enter or scan a code first.')
                else:
                    token_candidate = scan_code.rstrip('/').rsplit('/', 1)[-1]
                    scan_filter = (
                        Q(merchant_invoice_number__iexact=scan_code)
                        | Q(participant__email__iexact=scan_code)
                        | Q(participant__phone__iexact=scan_code)
                    )
                    try:
                        from uuid import UUID
                        scan_filter |= Q(qr_token=UUID(token_candidate))
                    except (TypeError, ValueError, AttributeError):
                        pass
                    if scan_code.isdigit():
                        scan_filter |= Q(pk=int(scan_code)) | Q(participant_id=int(scan_code))
                    matches = list(eligible_payments.filter(scan_filter)[:2])
                    if not matches:
                        messages.error(request, 'No completed approved participant matched this scan for the selected event.')
                    elif len(matches) > 1:
                        messages.error(request, 'More than one participant matched this scan. Search manually and issue from the exact row.')
                    else:
                        payment_record = matches[0]
                        kit, issued_now = _issue_registration_kit(payment_record)
                        if issued_now:
                            dashboard_log_action(request, kit, CHANGE, 'Issued registration kit by QR scan from Kit Center dashboard.')
                            messages.success(request, f'Scanned and issued kit to {payment_record.participant.name} at {kit.issued_at:%b %d, %Y %I:%M %p}.')
                        else:
                            messages.info(request, f'{payment_record.participant.name} already received a kit at {kit.issued_at:%b %d, %Y %I:%M %p}.')
            else:
                messages.error(request, 'Choose a valid kit action.')
        except Exception as exc:
            logger.exception("Registration kit center action failed: %s", exc)
            messages.error(request, str(exc))
        return redirect(redirect_url)

    if search_query:
        eligible_payments = eligible_payments.filter(
            Q(participant__name__icontains=search_query)
            | Q(participant__email__icontains=search_query)
            | Q(participant__phone__icontains=search_query)
            | Q(participant__organization__icontains=search_query)
            | Q(participant__BMDC_registration_number__icontains=search_query)
            | Q(merchant_invoice_number__icontains=search_query)
            | Q(transaction_id__icontains=search_query)
            | Q(trxID__icontains=search_query)
        )

    issued_kit_ids = RegistrationKit.objects.filter(
        status='issued',
        payment_status__status='completed',
        payment_status__participant__approved=True,
        payment_status__participant__denied=False,
    )
    if event_filter:
        issued_kit_ids = issued_kit_ids.filter(event_id=event_filter)
    issued_payment_ids = issued_kit_ids.values_list('payment_status_id', flat=True)

    if kit_status_filter == 'issued':
        eligible_payments = eligible_payments.filter(pk__in=issued_payment_ids)
    elif kit_status_filter == 'pending':
        eligible_payments = eligible_payments.exclude(pk__in=issued_payment_ids)

    eligible_payments = eligible_payments.order_by('participant__name', 'participant__email')
    page_obj = Paginator(eligible_payments, 18).get_page(request.GET.get('page'))
    for payment in page_obj.object_list:
        try:
            kit = payment.registration_kit
        except RegistrationKit.DoesNotExist:
            kit = None
        payment.kit_status = kit.status if kit else 'not_issued'
        payment.kit_issued_at = kit.issued_at if kit else None
        payment.kit_id = kit.id if kit else None

    totals_scope = PaymentStatus.objects.filter(
        status='completed',
        participant__approved=True,
        participant__denied=False,
    )
    if event_filter:
        totals_scope = totals_scope.filter(event_id=event_filter)
    total_eligible = totals_scope.count()
    total_issued = RegistrationKit.objects.filter(
        event_id=event_filter,
        status='issued',
        payment_status__in=totals_scope,
    ).count() if event_filter else RegistrationKit.objects.filter(status='issued', payment_status__in=totals_scope).count()

    context = {
        'site_settings': site_settings,
        'events': events,
        'page_obj': page_obj,
        'totals': {
            'eligible': total_eligible,
            'issued': total_issued,
            'pending': max(total_eligible - total_issued, 0),
        },
        'current_filters': {
            'event': event_filter or '',
            'q': search_query,
            'kit_status': kit_status_filter,
        },
        'query_string': urlencode(query_params),
        'kit_status_choices': [
            ('pending', 'Not issued'),
            ('issued', 'Issued'),
            ('all', 'All eligible'),
        ],
    }
    return render(request, 'dashboard_registration_kit_center.html', context)


@staff_member_required
def registration_qr_checkin(request, token):
    payment_record = get_object_or_404(
        PaymentStatus.objects.select_related('participant', 'event'),
        qr_token=token,
    )
    query = urlencode({
        'event': payment_record.event_id,
        'q': payment_record.merchant_invoice_number,
        'kit_status': 'all',
    })
    return redirect(f"{reverse('dashboard_registration_kit_center')}?{query}")


def _bulk_email_valid_email(email):
    from django.core.validators import validate_email

    if not email:
        return None
    normalized = email.strip()
    try:
        validate_email(normalized)
    except ValidationError:
        return None
    return normalized


def _bulk_email_identity_for_email(email):
    normalized = _bulk_email_valid_email(email)
    if not normalized:
        return {}

    user = User.objects.filter(email__iexact=normalized).first()
    profile = UserProfile.objects.filter(email__iexact=normalized).first()
    if not profile and user:
        profile = UserProfile.objects.filter(user=user).first()

    name = ''
    if profile and profile.name:
        name = profile.name
    elif user:
        name = user.get_full_name() or user.username

    return {
        'name': name,
        'user': user,
        'user_profile': profile,
    }


def _bulk_email_upsert_recipient(bulk_email, email, name='', source_type=BulkEmailRecipient.SOURCE_MANUAL, **links):
    normalized = _bulk_email_valid_email(email)
    if not normalized:
        return False
    identity = _bulk_email_identity_for_email(normalized)
    for key in ['user', 'user_profile']:
        links.setdefault(key, identity.get(key))
    defaults = {
        'name': name or identity.get('name') or '',
        'source_type': source_type,
        **{key: value for key, value in links.items() if value is not None},
    }
    _, created = BulkEmailRecipient.objects.get_or_create(
        bulk_email=bulk_email,
        email=normalized,
        defaults=defaults,
    )
    return created


def _prepare_bulk_email_recipients(bulk_email):
    added = 0
    if bulk_email.audience_type == BulkEmail.AUDIENCE_ACTIVE_USERS:
        users = User.objects.filter(is_active=True).exclude(email='')
        for user in users:
            added += int(_bulk_email_upsert_recipient(
                bulk_email,
                user.email,
                name=user.get_full_name() or user.username,
                source_type=BulkEmailRecipient.SOURCE_USER,
                user=user,
            ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_EMAIL_GROUP:
        if not bulk_email.email_group:
            return 0
        for email in bulk_email.email_group.parsed_emails():
            added += int(_bulk_email_upsert_recipient(
                bulk_email,
                email,
                source_type=BulkEmailRecipient.SOURCE_EMAIL_GROUP,
            ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_EVENT_PARTICIPANTS and bulk_email.event:
        participants = Participant.objects.filter(event=bulk_email.event).exclude(email='')
        for participant in participants:
            added += int(_bulk_email_upsert_recipient(
                bulk_email,
                participant.email,
                name=participant.name,
                source_type=BulkEmailRecipient.SOURCE_PARTICIPANT,
                participant=participant,
            ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_EVENT_UNPAID and bulk_email.event:
        payments = PaymentStatus.objects.filter(
            event=bulk_email.event,
            status__in=UNPAID_PAYMENT_STATUSES,
            participant__isnull=False,
        ).select_related('participant')
        for payment in payments:
            participant = payment.participant
            if participant:
                added += int(_bulk_email_upsert_recipient(
                    bulk_email,
                    participant.email,
                    name=participant.name,
                    source_type=BulkEmailRecipient.SOURCE_PARTICIPANT,
                    participant=participant,
                ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_ABSTRACT_SUBMITTERS and bulk_email.event:
        abstracts = AbstractSubmission.objects.filter(event=bulk_email.event).select_related('user')
        for abstract in abstracts:
            email = abstract.user.email if abstract.user_id else ''
            name = abstract.user.get_full_name() or abstract.user.username if abstract.user_id else ''
            added += int(_bulk_email_upsert_recipient(
                bulk_email,
                email,
                name=name,
                source_type=BulkEmailRecipient.SOURCE_ABSTRACT,
                abstract_submission=abstract,
                user=abstract.user if abstract.user_id else None,
            ))
    elif bulk_email.audience_type == BulkEmail.AUDIENCE_CORPORATE_CONTACTS:
        accounts = CorporateAccount.objects.filter(status='approved').exclude(email='')
        for account in accounts:
            added += int(_bulk_email_upsert_recipient(
                bulk_email,
                account.email,
                name=account.contact_name,
                source_type=BulkEmailRecipient.SOURCE_CORPORATE,
                corporate_account=account,
            ))
        requests = CorporateAccountRequest.objects.filter(status='approved').exclude(email='')
        for account_request in requests:
            added += int(_bulk_email_upsert_recipient(
                bulk_email,
                account_request.email,
                name=account_request.contact_name,
                source_type=BulkEmailRecipient.SOURCE_CORPORATE,
                corporate_request=account_request,
            ))

    if bulk_email.recipient_count:
        bulk_email.status = BulkEmail.STATUS_RECIPIENTS_READY
        bulk_email.save(update_fields=['status', 'updated_at'])
    return added


def _send_bulk_email_recipient(request, bulk_email, recipient):
    try:
        from registration.tasks import send_bulk_email_recipient_task

        send_bulk_email_recipient_task.delay(
            bulk_email.id,
            recipient.id,
            sent_by_user_id=request.user.id if request.user.is_authenticated else None,
        )
        return True
    except Exception as exc:
        recipient.status = BulkEmailRecipient.STATUS_FAILED
        recipient.error_message = str(exc)
        recipient.save(update_fields=['status', 'error_message'])
        BulkEmailSendLog.objects.create(
            bulk_email=bulk_email,
            recipient=recipient,
            email=recipient.email,
            status=BulkEmailRecipient.STATUS_FAILED,
            message=str(exc),
            sent_by=request.user,
        )
        return False


@dashboard_permission_required('certificates')
def dashboard_certificate_center(request):
    from website.models import SiteSettings

    site_settings = SiteSettings.objects.first()
    events = Event.objects.order_by('-year', '-start_date', 'name')
    default_event = events.filter(event_status='active').first() or events.first()
    event_filter = request.POST.get('event') if request.method == 'POST' else request.GET.get('event')
    if not event_filter and default_event:
        event_filter = str(default_event.id)
    search_query = ((request.POST.get('q') if request.method == 'POST' else request.GET.get('q', '')) or '').strip()
    selected_event = events.filter(pk=event_filter).first() if event_filter else None
    edit_question_id = None
    if request.method == 'POST':
        edit_question_raw = request.POST.get('edit_question_id') or request.POST.get('question_id') or ''
    else:
        edit_question_raw = request.GET.get('edit_question') or ''
    if str(edit_question_raw).strip().isdigit():
        edit_question_id = int(str(edit_question_raw).strip())

    query_params = {}
    if selected_event:
        query_params['event'] = selected_event.id
    if search_query:
        query_params['q'] = search_query
    redirect_url = f"{reverse('dashboard_certificate_center')}?{urlencode(query_params)}"

    if request.method == 'POST':
        action = request.POST.get('certificate_action')
        try:
            if not selected_event:
                messages.error(request, 'Choose an event before updating certificates or feedback.')
                return redirect(reverse('dashboard_certificate_center'))

            certificate, certificate_created = Certificate.objects.get_or_create(event=selected_event)

            if action == 'save_certificate':
                design_mode = request.POST.get('design_mode') or Certificate.DESIGN_MODE_HTML
                if design_mode not in dict(Certificate.DESIGN_MODE_CHOICES):
                    design_mode = Certificate.DESIGN_MODE_HTML
                certificate.design_mode = design_mode
                certificate.speaker_title = (request.POST.get('speaker_title') or '').strip() or None
                certificate.speaker_body = (request.POST.get('speaker_body') or '').strip() or None
                certificate.speaker_require_feedback = bool(request.POST.get('speaker_require_feedback'))
                certificate.speaker_require_kit_issue = bool(request.POST.get('speaker_require_kit_issue'))
                file_fields = ['upload_image', 'speaker_upload_image', 'organizer_logo', 'co_organizer_logo', 'event_logo']
                for field_name in file_fields:
                    if request.POST.get(f'clear_{field_name}'):
                        setattr(certificate, field_name, None)
                        continue
                    uploaded_file = request.FILES.get(field_name)
                    if uploaded_file:
                        setattr(certificate, field_name, uploaded_file)
                certificate.save()
                dashboard_log_action(
                    request,
                    certificate,
                    ADDITION if certificate_created else CHANGE,
                    'Updated certificate design assets from Certificate Center dashboard.',
                )
                messages.success(request, f'Certificate setup updated for {selected_event.name}.')

            elif action == 'generate_speaker_certificate':
                person = get_object_or_404(ProgramPerson, pk=request.POST.get('program_person_id'))
                record, output_path = _generate_speaker_certificate_file(
                    request,
                    selected_event,
                    person,
                    certificate,
                    issued_by=request.user,
                )
                speaker_certificate_logger.info(
                    "Speaker certificate download prepared from dashboard: certificate_id=%s event_id=%s person_id=%s user_id=%s file=%s",
                    record.id,
                    selected_event.id,
                    person.id,
                    request.user.id if request.user.is_authenticated else None,
                    output_path,
                )
                dashboard_log_action(request, record, CHANGE, f'Generated speaker certificate for {person.name}.')
                return FileResponse(
                    open(output_path, 'rb'),
                    as_attachment=True,
                    filename=os.path.basename(output_path),
                )

            elif action == 'email_speaker_certificate':
                person = get_object_or_404(ProgramPerson, pk=request.POST.get('program_person_id'))
                record, output_path = _generate_speaker_certificate_file(
                    request,
                    selected_event,
                    person,
                    certificate,
                    issued_by=request.user,
                )
                recipient_email = (record.profile.email if record.profile_id else '') or person.email
                if not recipient_email:
                    speaker_certificate_logger.warning(
                        "Speaker certificate email could not be queued: missing recipient event_id=%s person_id=%s certificate_id=%s",
                        selected_event.id,
                        person.id,
                        record.id,
                    )
                    raise ValueError(f'{person.name} does not have an email address for certificate delivery.')
                email_log = None
                if speaker_certificate_email_log_table_ready():
                    email_log = SpeakerCertificateEmailLog.objects.create(
                        certificate=record,
                        event=selected_event,
                        person=person,
                        email=recipient_email,
                        status=SpeakerCertificateEmailLog.STATUS_QUEUED,
                        sent_by=request.user if request.user.is_authenticated else None,
                        message='Queued from Certificate Center speaker certificate section.',
                    )
                try:
                    speaker_certificate_logger.info(
                        "Speaker certificate email queue requested: event_id=%s person_id=%s certificate_id=%s recipient=%s user_id=%s",
                        selected_event.id,
                        person.id,
                        record.id,
                        recipient_email,
                        request.user.id if request.user.is_authenticated else None,
                    )
                    task = send_speaker_certificate_email.delay(
                        record.id,
                        log_id=email_log.id if email_log else None,
                        sent_by_user_id=request.user.id if request.user.is_authenticated else None,
                    )
                except Exception as exc:
                    if email_log:
                        email_log.status = SpeakerCertificateEmailLog.STATUS_FAILED
                        email_log.message = f'Could not queue email task: {exc}'
                        email_log.save(update_fields=['status', 'message', 'updated_at'])
                    speaker_certificate_logger.exception(
                        "Speaker certificate email queue failed: event_id=%s person_id=%s certificate_id=%s recipient=%s",
                        selected_event.id,
                        person.id,
                        record.id,
                        recipient_email,
                    )
                    raise
                if email_log:
                    email_log.task_id = getattr(task, 'id', '') or ''
                    email_log.save(update_fields=['task_id', 'updated_at'])
                speaker_certificate_logger.info(
                    "Speaker certificate email queued: event_id=%s person_id=%s certificate_id=%s recipient=%s task_id=%s",
                    selected_event.id,
                    person.id,
                    record.id,
                    recipient_email,
                    getattr(task, 'id', '') or '',
                )
                dashboard_log_action(
                    request,
                    record,
                    CHANGE,
                    f'Queued speaker certificate email to {recipient_email}.',
                )
                messages.success(request, f'Speaker certificate email queued for {recipient_email}.')

            elif action == 'add_signatory':
                name = (request.POST.get('signatory_name') or '').strip()
                if not name:
                    messages.error(request, 'Signatory name is required.')
                else:
                    try:
                        signatory_order = int(request.POST.get('signatory_order') or 1)
                    except (TypeError, ValueError):
                        signatory_order = certificate.signatories.count() + 1
                    signatory = CertificateSignatory.objects.create(
                        certificate=certificate,
                        name=name,
                        designation=(request.POST.get('signatory_designation') or '').strip() or None,
                        organization=(request.POST.get('signatory_organization') or '').strip() or None,
                        order=max(signatory_order, 1),
                        signature=request.FILES.get('signature') or None,
                    )
                    dashboard_log_action(request, signatory, ADDITION, 'Added certificate signatory from Certificate Center dashboard.')
                    messages.success(request, f'Added signatory {signatory.name}.')

            elif action == 'delete_signatory':
                signatory = get_object_or_404(CertificateSignatory, pk=request.POST.get('signatory_id'), certificate=certificate)
                signatory_name = signatory.name
                dashboard_log_action(request, signatory, DELETION, 'Removed certificate signatory from Certificate Center dashboard.')
                signatory.delete()
                messages.success(request, f'Removed signatory {signatory_name}.')

            elif action == 'clear_signatory_signature':
                signatory = get_object_or_404(CertificateSignatory, pk=request.POST.get('signatory_id'), certificate=certificate)
                signatory.signature = None
                signatory.save(update_fields=['signature'])
                dashboard_log_action(request, signatory, CHANGE, 'Removed certificate signatory signature image from Certificate Center dashboard.')
                messages.success(request, f'Removed signature image for {signatory.name}.')

            elif action in ('add_question', 'update_question'):
                question_text = (request.POST.get('question_text') or '').strip()
                question_type = request.POST.get('question_type') or FeedbackQuestion.TEXT
                if question_type not in dict(FeedbackQuestion.QUESTION_TYPES):
                    question_type = FeedbackQuestion.TEXT

                try:
                    question_order = int(request.POST.get('question_order') or 0)
                except (TypeError, ValueError):
                    question_order = 0

                editing_question = None
                if action == 'update_question':
                    editing_question = get_object_or_404(FeedbackQuestion, pk=request.POST.get('question_id'), event=selected_event)

                rows_value = None
                columns_value = None
                if question_type == FeedbackQuestion.RADIO:
                    columns_value = (request.POST.get('radio_choices') or request.POST.get('columns') or '').strip() or None
                    if not columns_value:
                        messages.error(request, 'Radio questions need comma-separated answer choices.')
                    elif not question_text:
                        messages.error(request, 'Feedback question text is required.')
                    else:
                        if editing_question:
                            editing_question.question_text = question_text
                            editing_question.question_type = question_type
                            editing_question.is_required = bool(request.POST.get('is_required'))
                            editing_question.rows = None
                            editing_question.columns = columns_value
                            editing_question.order = question_order
                            editing_question.save(update_fields=['question_text', 'question_type', 'is_required', 'rows', 'columns', 'order'])
                            dashboard_log_action(request, selected_event, CHANGE, f'Updated feedback question from Certificate Center dashboard: {question_text[:80]}')
                            messages.success(request, 'Feedback question updated.')
                        else:
                            question = FeedbackQuestion.objects.create(
                                question_text=question_text,
                                question_type=question_type,
                                is_required=bool(request.POST.get('is_required')),
                                rows=None,
                                columns=columns_value,
                                order=question_order,
                            )
                            question.event.add(selected_event)
                            dashboard_log_action(request, selected_event, CHANGE, f'Added feedback question from Certificate Center dashboard: {question_text[:80]}')
                            messages.success(request, 'Feedback question added.')
                elif question_type == FeedbackQuestion.MATRIX:
                    rows_value = (request.POST.get('matrix_rows') or request.POST.get('rows') or '').strip() or None
                    columns_value = (request.POST.get('matrix_columns') or request.POST.get('columns') or '').strip() or None
                    if not rows_value or not columns_value:
                        messages.error(request, 'Matrix questions need both rows and columns.')
                    elif not question_text:
                        messages.error(request, 'Feedback question text is required.')
                    else:
                        if editing_question:
                            editing_question.question_text = question_text
                            editing_question.question_type = question_type
                            editing_question.is_required = bool(request.POST.get('is_required'))
                            editing_question.rows = rows_value
                            editing_question.columns = columns_value
                            editing_question.order = question_order
                            editing_question.save(update_fields=['question_text', 'question_type', 'is_required', 'rows', 'columns', 'order'])
                            dashboard_log_action(request, selected_event, CHANGE, f'Updated feedback question from Certificate Center dashboard: {question_text[:80]}')
                            messages.success(request, 'Feedback question updated.')
                        else:
                            question = FeedbackQuestion.objects.create(
                                question_text=question_text,
                                question_type=question_type,
                                is_required=bool(request.POST.get('is_required')),
                                rows=rows_value,
                                columns=columns_value,
                                order=question_order,
                            )
                            question.event.add(selected_event)
                            dashboard_log_action(request, selected_event, CHANGE, f'Added feedback question from Certificate Center dashboard: {question_text[:80]}')
                            messages.success(request, 'Feedback question added.')
                elif not question_text:
                    messages.error(request, 'Feedback question text is required.')
                else:
                    if editing_question:
                        editing_question.question_text = question_text
                        editing_question.question_type = question_type
                        editing_question.is_required = bool(request.POST.get('is_required'))
                        editing_question.rows = None
                        editing_question.columns = None
                        editing_question.order = question_order
                        editing_question.save(update_fields=['question_text', 'question_type', 'is_required', 'rows', 'columns', 'order'])
                        dashboard_log_action(request, selected_event, CHANGE, f'Updated feedback question from Certificate Center dashboard: {question_text[:80]}')
                        messages.success(request, 'Feedback question updated.')
                    else:
                        question = FeedbackQuestion.objects.create(
                            question_text=question_text,
                            question_type=question_type,
                            is_required=bool(request.POST.get('is_required')),
                            rows=None,
                            columns=None,
                            order=question_order,
                        )
                        question.event.add(selected_event)
                        dashboard_log_action(request, selected_event, CHANGE, f'Added feedback question from Certificate Center dashboard: {question_text[:80]}')
                        messages.success(request, 'Feedback question added.')

            elif action == 'remove_question':
                question = get_object_or_404(FeedbackQuestion, pk=request.POST.get('question_id'), event=selected_event)
                question_text = question.question_text or 'Feedback question'
                dashboard_log_action(request, selected_event, CHANGE, f'Removed feedback question from Certificate Center dashboard: {question_text[:80]}')
                if question.event.count() <= 1:
                    question.delete()
                else:
                    question.event.remove(selected_event)
                messages.success(request, 'Feedback question removed from this event.')

            elif action == 'export_feedback_report_csv':
                report_data = _build_feedback_report_data(selected_event, search_query)
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = f'attachment; filename="feedback_report_event_{selected_event.id}.csv"'
                writer = csv.writer(response)
                headers = [
                    'Participant', 'Email', 'Phone', 'Organization', 'Invoice',
                    'Approved', 'Payment status', 'Kit status', 'Feedback submitted', 'Answered questions',
                ] + [question.question_text or f'Question {index}' for index, question in enumerate(report_data['questions'], start=1)]
                writer.writerow(headers)
                for row in report_data['rows']:
                    writer.writerow([
                        row['participant'].name,
                        row['participant'].email,
                        row['participant'].phone,
                        row['participant'].organization,
                        row['invoice_number'],
                        'Yes' if row['participant'].approved else 'No',
                        getattr(row['payment_status'], 'status', 'Unpaid') if row['payment_status'] else 'Unpaid',
                        'Issued' if row['kit_issued'] else 'Not issued',
                        'Yes' if row['feedback_submitted'] else 'No',
                        f"{row['answered_questions']}/{len(report_data['questions'])}",
                    ] + [answer['display_value'] for answer in row['question_answers']])
                return response

            elif action == 'export_feedback_report_pdf':
                from .pdf_utils import generate_feedback_report_pdf

                report_data = _build_feedback_report_data(selected_event, search_query)
                pdf_buffer = generate_feedback_report_pdf(selected_event, report_data, site_settings=site_settings)
                safe_event_name = slugify(f"{selected_event.name}-{selected_event.year}") or f"event-{selected_event.id}"
                response = HttpResponse(pdf_buffer, content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="feedback-report-{safe_event_name}.pdf"'
                return response

            elif action == 'save_thank_you_template':
                subject = (request.POST.get('thank_you_subject') or '').strip()
                body = (request.POST.get('thank_you_body') or '').strip()
                button_text, button_url = _read_email_button_fields(
                    request.POST,
                    text_key='thank_you_button_text',
                    url_key='thank_you_button_url',
                )
                if not subject or not body:
                    raise ValueError('Thank-you email subject and body are required before saving.')
                selected_event.email_subject = subject
                selected_event.email_body = body
                selected_event.email_button_text = button_text
                selected_event.email_button_url = button_url
                selected_event.save(update_fields=['email_subject', 'email_body', 'email_button_text', 'email_button_url', 'updated_at'])
                dashboard_log_action(request, selected_event, CHANGE, 'Updated thank-you email template from Certificate Center dashboard.')
                messages.success(request, f'Thank-you event email saved for {selected_event.name}.')

            elif action in ('send_selected_thank_you', 'resend_selected_thank_you'):
                subject = (selected_event.email_subject or '').strip()
                body = (selected_event.email_body or '').strip()
                button_text = (selected_event.email_button_text or '').strip() or None
                button_url = (selected_event.email_button_url or '').strip() or None
                if not subject or not body:
                    raise ValueError('Save the event email first before sending or resending participant thank-you emails.')

                select_all_matching = str(request.POST.get('select_all_matching_kits') or '').strip() == '1'
                if select_all_matching:
                    selected_kits = list(_certificate_center_kit_rows_queryset(selected_event, search_query))
                    if not selected_kits:
                        raise ValueError('No eligible issued-kit participants were found for the selected action.')
                else:
                    selected_kit_ids = [
                        int(value) for value in request.POST.getlist('selected_kit_ids')
                        if str(value).strip().isdigit()
                    ]
                    if not selected_kit_ids:
                        raise ValueError('Select at least one participant before sending or resending emails.')

                    selected_kits = list(
                        RegistrationKit.objects.select_related('payment_status__participant').filter(
                            event=selected_event,
                            status='issued',
                            id__in=selected_kit_ids,
                        )
                    )
                    if not selected_kits:
                        raise ValueError('No eligible issued-kit participants were found for the selected action.')

                force_resend = action == 'resend_selected_thank_you'
                counts = _queue_thank_you_emails_for_kits(
                    selected_kits,
                    selected_event,
                    subject,
                    body,
                    button_text=button_text,
                    button_url=button_url,
                    sent_by=request.user,
                    force_resend=force_resend,
                )
                action_label = 'resent' if force_resend else 'sent'
                selection_scope = 'all filtered issued-kit participants' if select_all_matching else 'selected issued-kit participants'
                dashboard_log_action(
                    request,
                    selected_event,
                    CHANGE,
                    f'Participant thank-you emails {action_label} from Certificate Center for {selection_scope}. queued={counts["queued"]}, already_sent={counts["already_sent"]}, missing_email={counts["missing_email"]}, failed={counts["failed"]}',
                )
                messages.success(
                    request,
                    f'Participant thank-you email action complete for {selection_scope}. Queued: {counts["queued"]}, already sent: {counts["already_sent"]}, missing email: {counts["missing_email"]}, failed: {counts["failed"]}.',
                )

            else:
                messages.error(request, 'Choose a valid certificate action.')
        except Exception as exc:
            logger.exception("Certificate center action failed: %s", exc)
            messages.error(request, str(exc))
        if action in ('add_signatory', 'delete_signatory', 'clear_signatory_signature'):
            redirect_url = f"{redirect_url}#signatories"
        elif action in ('add_question', 'update_question', 'remove_question', 'export_feedback_report_csv', 'export_feedback_report_pdf'):
            redirect_url = f"{redirect_url}#feedback"
        elif action in ('save_thank_you_template', 'send_selected_thank_you', 'resend_selected_thank_you'):
            redirect_url = f"{redirect_url}#thank-you-email"
        return redirect(redirect_url)

    certificate = None
    signatories = CertificateSignatory.objects.none()
    feedback_questions = FeedbackQuestion.objects.none()
    editing_question = None
    question_form_initial = {
        'action': 'add_question',
        'question_id': '',
        'question_text': '',
        'question_type': FeedbackQuestion.TEXT,
        'question_order': 1,
        'is_required': True,
        'radio_choices': '',
        'matrix_rows': '',
        'matrix_columns': '',
    }
    feedback_report = {
        'questions': [],
        'rows': [],
        'insights': [],
        'page_obj': None,
        'totals': {
            'participants': 0,
            'submitted': 0,
            'pending': 0,
            'approved': 0,
            'paid': 0,
            'issued': 0,
        },
    }
    kit_rows_qs = RegistrationKit.objects.none()
    feedback_participant_ids = set()
    thank_you_email_records = {}
    thank_you_latest_log_map = {}
    speaker_rows = []

    if selected_event:
        certificate = Certificate.objects.filter(event=selected_event).prefetch_related('signatories').first()
        signatories = certificate.signatories.all() if certificate else CertificateSignatory.objects.none()
        feedback_questions = selected_event.feedback_questions.all().order_by('order', 'id')
        if edit_question_id:
            editing_question = feedback_questions.filter(pk=edit_question_id).first()
            if editing_question:
                question_form_initial = {
                    'action': 'update_question',
                    'question_id': editing_question.id,
                    'question_text': editing_question.question_text or '',
                    'question_type': editing_question.question_type or FeedbackQuestion.TEXT,
                    'question_order': editing_question.order,
                    'is_required': editing_question.is_required,
                    'radio_choices': (editing_question.columns or '') if editing_question.question_type == FeedbackQuestion.RADIO else '',
                    'matrix_rows': (editing_question.rows or '') if editing_question.question_type == FeedbackQuestion.MATRIX else '',
                    'matrix_columns': (editing_question.columns or '') if editing_question.question_type == FeedbackQuestion.MATRIX else '',
                }
        if not editing_question:
            question_form_initial['question_order'] = feedback_questions.count() + 1
        feedback_report = _build_feedback_report_data(selected_event, search_query)
        feedback_report['page_obj'] = Paginator(feedback_report['rows'], 10).get_page(request.GET.get('feedback_page'))
        feedback_report['rows'] = feedback_report['page_obj'].object_list
        kit_rows_qs = _certificate_center_kit_rows_queryset(selected_event, search_query)
        feedback_participant_ids = set(
            FeedbackResponse.objects.filter(event=selected_event).values_list('participant_id', flat=True).distinct()
        )
        thank_you_email_records = {
            row.registration_kit_id: row
            for row in ThankYouEmail.objects.filter(registration_kit__event=selected_event).select_related('registration_kit')
        }
        if thank_you_email_log_table_ready():
            for log in ThankYouEmailLog.objects.filter(event=selected_event).select_related('sent_by').order_by('thank_you_email_id', '-created_at'):
                thank_you_latest_log_map.setdefault(log.thank_you_email_id, log)
        speaker_rows = _speaker_certificate_rows(selected_event, certificate, search_query)

    page_obj = Paginator(kit_rows_qs, 15).get_page(request.GET.get('page'))
    for kit in page_obj.object_list:
        participant = kit.payment_status.participant
        kit.feedback_submitted = participant.id in feedback_participant_ids
        kit.thank_you_email = thank_you_email_records.get(kit.id)
        kit.latest_thank_you_log = thank_you_latest_log_map.get(kit.thank_you_email.id) if getattr(kit, 'thank_you_email', None) else None

    signatory_count = signatories.count()
    html_assets_ready = False
    image_asset_ready = False
    speaker_image_asset_ready = False
    certificate_ready = False
    speaker_certificate_ready = False
    if certificate:
        html_assets_ready = bool(certificate.organizer_logo and certificate.event_logo and signatory_count > 0)
        image_asset_ready = bool(certificate.upload_image)
        speaker_image_asset_ready = bool(certificate.speaker_upload_image)
        certificate_ready = (
            certificate.design_mode == Certificate.DESIGN_MODE_HTML and html_assets_ready
        ) or (
            certificate.design_mode == Certificate.DESIGN_MODE_IMAGE and image_asset_ready
        )
        speaker_certificate_ready = (
            certificate.design_mode == Certificate.DESIGN_MODE_HTML and html_assets_ready
        ) or (
            certificate.design_mode == Certificate.DESIGN_MODE_IMAGE and speaker_image_asset_ready
        )

    issued_total = RegistrationKit.objects.filter(event=selected_event, status='issued').count() if selected_event else 0
    feedback_submitted_total = len(feedback_participant_ids) if selected_event else 0
    thank_you_total = len(thank_you_email_records) if selected_event else 0
    thank_you_sent_total = sum(1 for row in thank_you_email_records.values() if row.email_sent) if selected_event else 0
    thank_you_recipients_total = sum(1 for kit in RegistrationKit.objects.select_related('payment_status__participant').filter(event=selected_event, status='issued') if kit.payment_status.participant and kit.payment_status.participant.email) if selected_event else 0
    issued_speaker_total = sum(1 for row in speaker_rows if row['issued_record'])
    eligible_speaker_total = sum(1 for row in speaker_rows if row['eligible'])

    context = {
        'site_settings': site_settings,
        'events': events,
        'selected_event': selected_event,
        'certificate': certificate,
        'signatories': signatories,
        'feedback_questions': feedback_questions,
        'feedback_report': feedback_report,
        'speaker_rows': speaker_rows,
        'editing_question': editing_question,
        'question_form_initial': question_form_initial,
        'question_types': FeedbackQuestion.QUESTION_TYPES,
        'page_obj': page_obj,
        'query_string': urlencode(query_params),
        'feedback_query_string': urlencode(query_params),
        'current_filters': {
            'event': str(selected_event.id) if selected_event else '',
            'q': search_query,
        },
        'thank_you_subject': selected_event.email_subject if selected_event and selected_event.email_subject else '',
        'thank_you_body': selected_event.email_body if selected_event and selected_event.email_body else '',
        'thank_you_button_text': selected_event.email_button_text if selected_event and selected_event.email_button_text else '',
        'thank_you_button_url': selected_event.email_button_url if selected_event and selected_event.email_button_url else '',
        'totals': {
            'certificate_ready': certificate_ready,
            'html_assets_ready': html_assets_ready,
            'image_asset_ready': image_asset_ready,
            'speaker_image_asset_ready': speaker_image_asset_ready,
            'signatories': signatory_count,
            'feedback_questions': feedback_questions.count(),
            'issued_kits': issued_total,
            'feedback_submitted': feedback_submitted_total,
            'feedback_pending': max(issued_total - feedback_submitted_total, 0),
            'thank_you_recipients': thank_you_recipients_total,
            'thank_you_records': thank_you_total,
            'thank_you_sent': thank_you_sent_total,
            'thank_you_pending': max(thank_you_recipients_total - thank_you_sent_total, 0),
            'speaker_certificate_ready': speaker_certificate_ready,
            'eligible_speakers': eligible_speaker_total,
            'issued_speaker_certificates': issued_speaker_total,
        },
    }
    return render(request, 'dashboard_certificate_center.html', context)


def _parse_chest_card_decimal(request, key, default):
    raw_value = (request.POST.get(key) or '').strip()
    if not raw_value:
        return default
    try:
        return Decimal(raw_value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid number for {key.replace('_', ' ')}.")


def _parse_chest_card_int(request, key, default):
    raw_value = (request.POST.get(key) or '').strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        raise ValueError(f"Enter a valid whole number for {key.replace('_', ' ')}.")


def _chest_card_rows(event, query=''):
    rows = []
    query_text = (query or '').strip()
    payments = PaymentStatus.objects.select_related('participant', 'event').filter(
        event=event,
        participant__isnull=False,
        participant__approved=True,
        participant__denied=False,
        status__in=['paid', 'completed'],
    )
    if query_text:
        payments = payments.filter(
            Q(participant__name__icontains=query_text)
            | Q(participant__email__icontains=query_text)
            | Q(participant__phone__icontains=query_text)
            | Q(merchant_invoice_number__icontains=query_text)
            | Q(participant__organization__icontains=query_text)
        )
    for payment in payments.order_by('participant__name', 'participant__email'):
        participant = payment.participant
        rows.append({
            'payment': payment,
            'participant': participant,
            'invoice_number': payment.merchant_invoice_number or '-',
            'organization': participant.organization or '-',
            'qr_ready': bool(payment.qr_code),
            'payment_ready': payment.status in ['paid', 'completed'],
        })
    return rows


@dashboard_permission_required('chest_cards')
def dashboard_chest_card_center(request):
    from website.models import SiteSettings

    site_settings = SiteSettings.objects.first()
    events = Event.objects.order_by('-year', '-start_date', 'name')
    default_event = events.filter(event_status='active').first() or events.first()
    event_filter = request.POST.get('event') if request.method == 'POST' else request.GET.get('event')
    if not event_filter and default_event:
        event_filter = str(default_event.id)
    search_query = ((request.POST.get('q') if request.method == 'POST' else request.GET.get('q', '')) or '').strip()
    selected_event = events.filter(pk=event_filter).first() if event_filter else None

    query_params = {}
    if selected_event:
        query_params['event'] = selected_event.id
    if search_query:
        query_params['q'] = search_query
    redirect_url = f"{reverse('dashboard_chest_card_center')}?{urlencode(query_params)}"

    if request.method == 'POST':
        action = request.POST.get('chest_card_action')
        try:
            if not selected_event:
                raise ValueError('Choose an event before updating chest cards.')

            design, created = ChestCardDesign.objects.get_or_create(event=selected_event)

            if action == 'save_design':
                design_mode = request.POST.get('design_mode') or ChestCardDesign.MODE_HTML
                if design_mode not in dict(ChestCardDesign.MODE_CHOICES):
                    design_mode = ChestCardDesign.MODE_HTML
                design.design_mode = design_mode
                design.width_mm = _parse_chest_card_decimal(request, 'width_mm', design.width_mm)
                design.height_mm = _parse_chest_card_decimal(request, 'height_mm', design.height_mm)
                design.dpi = max(_parse_chest_card_int(request, 'dpi', design.dpi), 72)
                design.badge_title = (request.POST.get('badge_title') or '').strip() or None
                design.accent_color = (request.POST.get('accent_color') or '').strip() or '#1769c2'
                design.background_color = (request.POST.get('background_color') or '').strip() or '#f8fbff'
                design.name_x_mm = _parse_chest_card_decimal(request, 'name_x_mm', design.name_x_mm)
                design.name_y_mm = _parse_chest_card_decimal(request, 'name_y_mm', design.name_y_mm)
                design.name_width_mm = _parse_chest_card_decimal(request, 'name_width_mm', design.name_width_mm)
                design.name_height_mm = _parse_chest_card_decimal(request, 'name_height_mm', design.name_height_mm)
                design.qr_x_mm = _parse_chest_card_decimal(request, 'qr_x_mm', design.qr_x_mm)
                design.qr_y_mm = _parse_chest_card_decimal(request, 'qr_y_mm', design.qr_y_mm)
                design.qr_size_mm = _parse_chest_card_decimal(request, 'qr_size_mm', design.qr_size_mm)
                design.font_size_pt = max(_parse_chest_card_int(request, 'font_size_pt', design.font_size_pt), 10)
                design.font_color = (request.POST.get('font_color') or '').strip() or '#0f172a'
                text_align = request.POST.get('text_align') or ChestCardDesign.TEXT_ALIGN_CENTER
                if text_align not in dict(ChestCardDesign.TEXT_ALIGN_CHOICES):
                    text_align = ChestCardDesign.TEXT_ALIGN_CENTER
                design.text_align = text_align
                design.show_event_name = bool(request.POST.get('show_event_name'))
                design.show_organization = bool(request.POST.get('show_organization'))
                design.show_invoice_number = bool(request.POST.get('show_invoice_number'))
                for field_name in ('overlay_reference_image', 'html_background_image'):
                    if request.POST.get(f'clear_{field_name}'):
                        setattr(design, field_name, None)
                    elif request.FILES.get(field_name):
                        setattr(design, field_name, request.FILES[field_name])
                design.save()
                _mark_event_chest_cards_outdated(selected_event)
                dashboard_log_action(request, design, ADDITION if created else CHANGE, 'Updated chest card design from Chest Card Center dashboard.')
                messages.success(request, f'Chest card setup updated for {selected_event.name}.')

            elif action in ['download_chest_card_pdf', 'print_chest_card_pdf']:
                payment = get_object_or_404(PaymentStatus.objects.select_related('participant', 'event'), pk=request.POST.get('payment_id'), event=selected_event)
                output_path = _generate_chest_card_file(request, payment.participant, selected_event, design, output_format='pdf')
                dashboard_log_action(request, payment, CHANGE, f'Generated chest card PDF for {payment.participant.name}.')
                as_attachment = action != 'print_chest_card_pdf'
                response = FileResponse(open(output_path, 'rb'), as_attachment=as_attachment, filename=os.path.basename(output_path))
                response['Content-Type'] = 'application/pdf'
                if not as_attachment:
                    response['Content-Disposition'] = f'inline; filename="{os.path.basename(output_path)}"'
                return response

            elif action == 'scan_print':
                scan_code = (request.POST.get('scan_code') or '').strip()
                if not scan_code:
                    raise ValueError('Enter or scan a code first.')
                eligible_payments = PaymentStatus.objects.select_related('participant', 'event').filter(
                    event=selected_event,
                    participant__approved=True,
                    status__in=['paid', 'completed'],
                )
                token_candidate = scan_code.rstrip('/').rsplit('/', 1)[-1]
                scan_filter = (
                    Q(merchant_invoice_number__iexact=scan_code)
                    | Q(participant__email__iexact=scan_code)
                    | Q(participant__phone__iexact=scan_code)
                )
                try:
                    from uuid import UUID
                    scan_filter |= Q(qr_token=UUID(token_candidate))
                except (TypeError, ValueError, AttributeError):
                    pass
                if scan_code.isdigit():
                    scan_filter |= Q(pk=int(scan_code)) | Q(participant_id=int(scan_code))
                matches = list(eligible_payments.filter(scan_filter)[:2])
                if not matches:
                    raise ValueError('No completed approved participant matched this scan for the selected event.')
                if len(matches) > 1:
                    raise ValueError('More than one participant matched this scan. Search manually and print from the exact row.')
                payment = matches[0]
                if not payment.qr_code:
                    raise ValueError(f'{payment.participant.name} does not have a registration QR code yet.')
                output_path = _generate_chest_card_file(request, payment.participant, selected_event, design, output_format='pdf')
                dashboard_log_action(request, payment, CHANGE, f'Printed chest card by QR scan for {payment.participant.name}.')
                response = FileResponse(open(output_path, 'rb'), as_attachment=False, filename=os.path.basename(output_path))
                response['Content-Type'] = 'application/pdf'
                response['Content-Disposition'] = f'inline; filename="{os.path.basename(output_path)}"'
                return response

            elif action == 'download_bulk_chest_card_pdf':
                rows = _chest_card_rows(selected_event, search_query)
                ready_payments = [row['payment'] for row in rows if row['qr_ready']]
                output_path, generated_count = _build_chest_card_bulk_pdf(request, selected_event, design, ready_payments)
                dashboard_log_action(request, selected_event, CHANGE, f'Generated bulk chest card PDF ({generated_count} participants).')
                response = FileResponse(open(output_path, 'rb'), as_attachment=True, filename=os.path.basename(output_path))
                response['Content-Type'] = 'application/pdf'
                return response

            elif action == 'download_vendor_chest_card_zip':
                rows = _chest_card_rows(selected_event, search_query)
                ready_payments = [row['payment'] for row in rows if row['qr_ready']]
                zip_buffer, generated_count = _build_chest_card_vendor_zip(request, selected_event, design, ready_payments)
                dashboard_log_action(request, selected_event, CHANGE, f'Generated chest card vendor ZIP ({generated_count} participants).')
                response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
                response['Content-Disposition'] = f'attachment; filename="{_chest_card_vendor_zip_output_filename(selected_event)}"'
                return response

            else:
                messages.error(request, 'Choose a valid chest card action.')
        except Exception as exc:
            logger.exception('Chest card center action failed: %s', exc)
            messages.error(request, str(exc))
        return redirect(redirect_url)

    design = ChestCardDesign.objects.filter(event=selected_event).first() if selected_event else None
    rows = _chest_card_rows(selected_event, search_query) if selected_event else []
    ready_rows = [row for row in rows if row['qr_ready']]
    quick_match = rows[0] if len(rows) == 1 else None
    page_obj = Paginator(rows, 15).get_page(request.GET.get('page'))
    qr_ready_total = sum(1 for row in rows if row['qr_ready'])

    context = {
        'site_settings': site_settings,
        'events': events,
        'selected_event': selected_event,
        'design': design,
        'page_obj': page_obj,
        'ready_rows': ready_rows,
        'quick_match': quick_match,
        'current_filters': {
            'event': str(selected_event.id) if selected_event else '',
            'q': search_query,
        },
        'totals': {
            'design_ready': bool(design),
            'participants': len(rows),
            'qr_ready': qr_ready_total,
            'qr_pending': max(len(rows) - qr_ready_total, 0),
            'mode': design.get_design_mode_display() if design else 'Not set',
        },
    }
    return render(request, 'dashboard_chest_card_center.html', context)


def _presentation_file_exists(file_field):
    return bool(file_field and getattr(file_field, 'name', '') and file_field.storage.exists(file_field.name))


def _presentation_archive_name(row):
    file_field = row.get('file')
    extension = os.path.splitext(getattr(file_field, 'name', '') or '')[1] or '.pptx'
    event_label = _safe_presentation_filename(row.get('event_label'))
    presenter_label = _safe_presentation_filename(row.get('presenter'))
    title_label = _safe_presentation_filename(row.get('title'))[:80]
    return f"{event_label}/{presenter_label}_{title_label}{extension}"


def _write_presentation_zip(rows):
    buffer = io.BytesIO()
    added = 0
    used_names = set()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            file_field = row.get('file')
            if not _presentation_file_exists(file_field):
                continue
            archive_name = _presentation_archive_name(row)
            if archive_name in used_names:
                base, extension = os.path.splitext(archive_name)
                archive_name = f"{base}_{row.get('source_key')}{extension}"
            used_names.add(archive_name)
            with file_field.storage.open(file_field.name, 'rb') as source_file:
                archive.writestr(archive_name, source_file.read())
            added += 1
    buffer.seek(0)
    return buffer, added


def _presentation_upload_rows(event_filter='', source_filter='all', query=''):
    query_text = (query or '').strip()
    rows = []

    uploads = (
        PresentationUpload.objects.select_related(
            'event',
            'user',
            'program_person',
            'abstract_submission',
            'session',
            'session_item',
        )
        .order_by('-uploaded_at')
    )
    if event_filter:
        uploads = uploads.filter(event_id=event_filter)
    if source_filter != 'all':
        uploads = uploads.filter(source_type=source_filter)
    if query_text:
        uploads = uploads.filter(
            Q(title__icontains=query_text)
            | Q(presenter_name__icontains=query_text)
            | Q(user__email__icontains=query_text)
            | Q(program_person__name__icontains=query_text)
            | Q(program_person__email__icontains=query_text)
            | Q(event__name__icontains=query_text)
        )

    latest_assignment_keys = set()
    for upload in uploads:
        if upload.abstract_submission_id:
            assignment_key = ('abstract', upload.abstract_submission_id)
        elif upload.session_item_id:
            assignment_key = ('session_item', upload.session_item_id, upload.program_person_id or upload.user_id)
        elif upload.session_id:
            assignment_key = ('session', upload.session_id, upload.program_person_id or upload.user_id)
        else:
            assignment_key = ('upload', upload.id)

        if assignment_key in latest_assignment_keys:
            continue
        latest_assignment_keys.add(assignment_key)

        rows.append({
            'kind': 'upload',
            'source_key': f"upload:{upload.id}",
            'id': upload.id,
            'event': upload.event,
            'event_label': f"{upload.event.name} {upload.event.year}",
            'title': upload.title,
            'presenter': upload.presenter_name or upload.user.get_full_name() or upload.user.email,
            'email': upload.user.email,
            'source_type': upload.source_type,
            'source_label': upload.get_source_type_display(),
            'role_label': upload.role_label,
            'uploaded_at': upload.uploaded_at,
            'file': upload.file,
        })

    rows.sort(key=lambda row: row.get('uploaded_at') or timezone.now(), reverse=True)
    return rows


@dashboard_permission_required('media')
def dashboard_event_media_center(request):
    site_settings = SiteSettings.objects.first()
    events = Event.objects.order_by('-year', '-start_date', 'name')
    event_filter = (request.POST.get('event') if request.method == 'POST' else request.GET.get('event', '')).strip()
    media_filter = (request.POST.get('media_type') if request.method == 'POST' else request.GET.get('media_type', 'all')).strip() or 'all'
    search_query = (request.POST.get('q') if request.method == 'POST' else request.GET.get('q', '')).strip()

    query_params = {}
    if event_filter:
        query_params['event'] = event_filter
    if media_filter != 'all':
        query_params['media_type'] = media_filter
    if search_query:
        query_params['q'] = search_query
    redirect_url = reverse('dashboard_event_media_center')
    if query_params:
        redirect_url = f"{redirect_url}?{urlencode(query_params)}"

    if request.method == 'POST':
        action = (request.POST.get('media_action') or '').strip()
        selected_event = Event.objects.filter(pk=event_filter).first() if event_filter else None

        if action == 'upload_images':
            uploaded_files = [file for file in request.FILES.getlist('images') if file]
            image_titles = request.POST.getlist('image_titles')
            if not selected_event:
                messages.error(request, 'Choose an event before uploading images.')
            elif not uploaded_files:
                messages.error(request, 'Select one or more image files to upload.')
            else:
                created_count = 0
                for index, uploaded_file in enumerate(uploaded_files):
                    title = image_titles[index].strip() if index < len(image_titles) else ''
                    file_name = os.path.splitext(os.path.basename(uploaded_file.name))[0].replace('_', ' ').replace('-', ' ').strip()
                    fallback_title = f"{selected_event.name} {selected_event.year} - {file_name or ('Image ' + str(index + 1))}"
                    image = EventImage.objects.create(
                        event=selected_event,
                        image=uploaded_file,
                        caption=title or fallback_title,
                    )
                    dashboard_log_action(request, image, ADDITION, 'Uploaded event image from Event Media Center dashboard.')
                    created_count += 1
                dashboard_log_action(request, selected_event, CHANGE, f'Uploaded {created_count} event gallery image(s) from Event Media Center dashboard.')
                messages.success(request, f'{created_count} image(s) uploaded for {selected_event.name} {selected_event.year}.')
            return redirect(redirect_url)

        if action == 'add_video':
            youtube_url = (request.POST.get('youtube_url') or '').strip()
            caption = (request.POST.get('video_caption') or '').strip()
            if not selected_event:
                messages.error(request, 'Choose an event before adding a video.')
                return redirect(redirect_url)
            if not youtube_url:
                messages.error(request, 'Add a YouTube video URL first.')
                return redirect(redirect_url)
            try:
                URLValidator()(youtube_url)
            except ValidationError:
                messages.error(request, 'Enter a valid YouTube URL.')
                return redirect(redirect_url)
            if 'youtube.com' not in youtube_url and 'youtu.be' not in youtube_url:
                messages.error(request, 'Only YouTube links are supported for event videos.')
                return redirect(redirect_url)

            video = EventVideo.objects.create(
                event=selected_event,
                youtube_url=youtube_url,
                caption=caption,
            )
            dashboard_log_action(request, video, ADDITION, 'Added event video from Event Media Center dashboard.')
            dashboard_log_action(request, selected_event, CHANGE, 'Added event gallery video from Event Media Center dashboard.')
            messages.success(request, f'Video saved for {selected_event.name} {selected_event.year}.')
            return redirect(redirect_url)

        if action == 'delete_image':
            image = get_object_or_404(EventImage.objects.select_related('event'), pk=request.POST.get('image_id'))
            image_label = image.caption or image.image.name.rsplit('/', 1)[-1]
            event_label = f'{image.event.name} {image.event.year}'
            dashboard_log_action(request, image, DELETION, 'Deleted event image from Event Media Center dashboard.')
            image.delete()
            messages.success(request, f'Deleted image "{image_label}" from {event_label}.')
            return redirect(redirect_url)

        if action == 'delete_video':
            video = get_object_or_404(EventVideo.objects.select_related('event'), pk=request.POST.get('video_id'))
            event_label = f'{video.event.name} {video.event.year}'
            dashboard_log_action(request, video, DELETION, 'Deleted event video from Event Media Center dashboard.')
            video.delete()
            messages.success(request, f'Deleted video from {event_label}.')
            return redirect(redirect_url)

    images = EventImage.objects.select_related('event').order_by('-id')
    videos = EventVideo.objects.select_related('event').order_by('-id')

    if event_filter:
        images = images.filter(event_id=event_filter)
        videos = videos.filter(event_id=event_filter)

    if search_query:
        images = images.filter(
            Q(caption__icontains=search_query)
            | Q(event__name__icontains=search_query)
            | Q(image__icontains=search_query)
        )
        videos = videos.filter(
            Q(caption__icontains=search_query)
            | Q(event__name__icontains=search_query)
            | Q(youtube_url__icontains=search_query)
        )

    if media_filter == 'images':
        videos = EventVideo.objects.none()
    elif media_filter == 'videos':
        images = EventImage.objects.none()

    selected_event = Event.objects.filter(pk=event_filter).first() if event_filter else None
    image_page_obj = Paginator(images, 12).get_page(request.GET.get('images_page'))
    video_page_obj = Paginator(videos, 8).get_page(request.GET.get('videos_page'))

    totals = {
        'images': images.count(),
        'videos': videos.count(),
        'events_with_media': Event.objects.filter(
            Q(eventimage__isnull=False) | Q(eventvideo__isnull=False)
        ).distinct().count(),
        'selected_event_images': EventImage.objects.filter(event=selected_event).count() if selected_event else 0,
        'selected_event_videos': EventVideo.objects.filter(event=selected_event).count() if selected_event else 0,
    }

    return render(request, 'dashboard_event_media_center.html', {
        'site_settings': site_settings,
        'events': events,
        'selected_event': selected_event,
        'image_page_obj': image_page_obj,
        'video_page_obj': video_page_obj,
        'totals': totals,
        'current_filters': {
            'event': event_filter,
            'media_type': media_filter,
            'q': search_query,
        },
        'admin_links': {
            'images': reverse('admin:registration_eventimage_changelist'),
            'videos': reverse('admin:registration_eventvideo_changelist'),
        },
    })


@dashboard_permission_required('presentations')
def dashboard_presentation_center(request):
    site_settings = SiteSettings.objects.first()
    events = Event.objects.order_by('-start_date', '-year', 'name')
    event_filter = request.GET.get('event', '').strip()
    source_filter = request.GET.get('source', 'all').strip() or 'all'
    query = request.GET.get('q', '').strip()

    rows = _presentation_upload_rows(event_filter, source_filter, query)

    if request.method == 'POST':
        selected_keys = request.POST.getlist('selected_presentations')
        action = request.POST.get('presentation_action')
        if action == 'download_all_filtered':
            selected_rows = rows
        else:
            selected_rows = [row for row in rows if row['source_key'] in selected_keys]

        if not selected_rows:
            messages.error(request, 'Please select at least one presentation file to download.')
            redirect_params = {}
            if event_filter:
                redirect_params['event'] = event_filter
            if source_filter != 'all':
                redirect_params['source'] = source_filter
            if query:
                redirect_params['q'] = query
            redirect_url = reverse('dashboard_presentation_center')
            if redirect_params:
                redirect_url = f"{redirect_url}?{urlencode(redirect_params)}"
            return redirect(redirect_url)

        zip_buffer, added_count = _write_presentation_zip(selected_rows)
        if not added_count:
            messages.error(request, 'No stored presentation files were found for the selected rows.')
            return redirect(reverse('dashboard_presentation_center'))

        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="bsbcs_presentations.zip"'
        return response

    page_obj = Paginator(rows, 15).get_page(request.GET.get('page'))
    event_ids = {row['event'].id for row in rows if row.get('event')}
    presenter_keys = {
        (row.get('email') or row.get('presenter') or '').strip().lower()
        for row in rows
        if row.get('email') or row.get('presenter')
    }
    totals = {
        'all': len(rows),
        'files': sum(1 for row in rows if _presentation_file_exists(row.get('file'))),
        'presenters': len(presenter_keys),
        'events': len(event_ids),
    }

    return render(request, 'dashboard_presentation_center.html', {
        'site_settings': site_settings,
        'events': events,
        'page_obj': page_obj,
        'totals': totals,
        'source_choices': [
            ('all', 'All sources'),
            (PresentationUpload.SOURCE_ABSTRACT, 'Abstract submissions'),
            (PresentationUpload.SOURCE_SESSION_ITEM, 'Program talks'),
            (PresentationUpload.SOURCE_SESSION_ROLE, 'Session faculty'),
        ],
        'current_filters': {
            'event': event_filter,
            'source': source_filter,
            'q': query,
        },
    })


@dashboard_permission_required('program')
def dashboard_speaker_outreach_center(request):
    from website.models import SiteSettings

    site_settings = SiteSettings.objects.first()
    events = Event.objects.order_by('-year', '-start_date', '-id')
    selected_event = events.filter(pk=request.GET.get('event') or request.POST.get('event') or None).first()
    search_query = (request.GET.get('q') or request.POST.get('q') or '').strip()
    library_query = (request.GET.get('library_q') or request.POST.get('library_q') or '').strip()
    speaker_profile_query = (request.GET.get('speaker_profile_q') or request.POST.get('speaker_profile_q') or '').strip()
    selected_profile_id = request.GET.get('speaker_profile_id') or request.POST.get('profile_id')
    speaker_partial = (request.GET.get('speaker_partial') or '').strip()
    preview_person_id = request.GET.get('preview_person')
    edit_preset_id = request.GET.get('edit_preset') or request.POST.get('edit_preset')
    selected_profile = UserProfile.objects.select_related('member').filter(pk=selected_profile_id).first() if str(selected_profile_id or '').isdigit() else None
    selected_profile_person = ProgramPerson.objects.filter(profile=selected_profile).first() if selected_profile else None
    selected_profile_in_event = bool(selected_event and selected_profile_person and selected_profile_person.events.filter(pk=selected_event.pk).exists())
    person_form = ProgramPersonQuickCreateForm(initial=_speaker_outreach_profile_seed_data(selected_profile) if selected_profile else {'country': 'Bangladesh'})

    base_params = {}
    if selected_event:
        base_params['event'] = selected_event.id
    if search_query:
        base_params['q'] = search_query
    if library_query:
        base_params['library_q'] = library_query

    if request.method == 'POST':
        action = request.POST.get('speaker_action')
        redirect_params = dict(base_params)
        if not selected_event:
            messages.error(request, 'Choose an event before using the speaker outreach center.')
            return redirect(reverse('dashboard_speaker_outreach_center'))

        template = _speaker_outreach_template(selected_event)
        person_ids = [
            int(value) for value in request.POST.getlist('person_ids')
            if str(value).strip().isdigit()
        ]
        page_people = list(ProgramPerson.objects.filter(events=selected_event, id__in=person_ids).distinct()) if person_ids else []

        try:
            if action == 'add_person':
                person_form = ProgramPersonQuickCreateForm(request.POST)
                selected_profile = UserProfile.objects.select_related('member').filter(pk=request.POST.get('profile_id')).first() if str(request.POST.get('profile_id') or '').isdigit() else None
                if not person_form.is_valid():
                    raise ValueError('Please complete the global prospect form with at least name and a valid email if provided.')
                cleaned_data = person_form.cleaned_data
                add_to_event_now = bool(request.POST.get('add_to_event_now'))
                person = ProgramPerson.objects.filter(profile=selected_profile).first() if selected_profile else None
                if not person:
                    person = _speaker_outreach_existing_global_person(cleaned_data)
                event_added = False
                if person:
                    updated_fields = []
                    for field in ['degree', 'designation', 'institution', 'email', 'phone', 'country']:
                        incoming_value = cleaned_data.get(field)
                        if incoming_value and getattr(person, field) != incoming_value and not getattr(person, field):
                            setattr(person, field, incoming_value)
                            updated_fields.append(field)
                    if selected_profile and person.profile_id != selected_profile.id:
                        person.profile = selected_profile
                        updated_fields.append('profile')
                    if updated_fields := list(dict.fromkeys(updated_fields)):
                        person.save(update_fields=updated_fields)
                    if add_to_event_now and not person.events.filter(pk=selected_event.pk).exists():
                        person.events.add(selected_event)
                        event_added = True
                    dashboard_log_action(
                        request,
                        person,
                        CHANGE,
                        f'Updated global speaker prospect from Speaker Outreach Center dashboard for {selected_event.name}.',
                    )
                    if add_to_event_now and event_added:
                        messages.success(request, f'Existing prospect "{person.name}" was matched in the global library and added to {selected_event.name}.')
                    elif add_to_event_now:
                        messages.success(request, f'Existing prospect "{person.name}" is already in the global library and already linked to {selected_event.name}.')
                    else:
                        messages.success(request, f'Existing prospect "{person.name}" was matched in the global library, so we refreshed details without creating a duplicate.')
                else:
                    person = person_form.save(commit=False)
                    if selected_profile:
                        person.profile = selected_profile
                    person.save()
                    if add_to_event_now:
                        person.events.add(selected_event)
                        event_added = True
                    dashboard_log_action(request, person, ADDITION, 'Added global speaker prospect from Speaker Outreach Center dashboard.')
                    if event_added:
                        messages.success(request, f'Global prospect "{person.name}" created and added to {selected_event.name}.')
                    else:
                        messages.success(request, f'Global prospect "{person.name}" created in the shared speaker library.')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#builder")

            if action == 'add_selected_library_to_event':
                selected_library_ids = [
                    int(value) for value in request.POST.getlist('selected_library_person_ids')
                    if str(value).strip().isdigit()
                ]
                if not selected_library_ids:
                    raise ValueError('Select at least one person from the shared prospect library first.')
                selected_people = list(ProgramPerson.objects.filter(id__in=selected_library_ids).distinct())
                added = 0
                already = 0
                for person in selected_people:
                    if person.events.filter(pk=selected_event.pk).exists():
                        already += 1
                        continue
                    person.events.add(selected_event)
                    added += 1
                dashboard_log_action(request, selected_event, CHANGE, f'Added shared prospects into speaker outreach workflow. added={added}, already={already}.')
                messages.success(request, f'Added {added} prospect(s) into {selected_event.name}. Already there: {already}.')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#builder")

            if action == 'remove_from_event':
                person_id = request.POST.get('person_id')
                person = ProgramPerson.objects.filter(events=selected_event, pk=person_id).first()
                if not person:
                    raise ValueError('Choose a valid linked speaker to remove from this event workflow.')
                SpeakerOutreachCoordination.objects.filter(event=selected_event, person=person).delete()
                person.events.remove(selected_event)
                dashboard_log_action(request, selected_event, CHANGE, f'Removed {person.name} from speaker outreach workflow for {selected_event.name}.')
                messages.success(request, f'"{person.name}" was removed from {selected_event.name} only. The shared library record is still kept.')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#workflow")

            if action == 'remove_selected':
                selected_person_ids = [
                    int(value) for value in request.POST.getlist('selected_person_ids')
                    if str(value).strip().isdigit()
                ]
                if not selected_person_ids:
                    raise ValueError('Select at least one speaker before removing them from this event workflow.')
                selected_people = list(ProgramPerson.objects.filter(events=selected_event, id__in=selected_person_ids).distinct())
                if not selected_people:
                    raise ValueError('No valid linked speakers were found for the selected remove action.')
                removed = 0
                for person in selected_people:
                    SpeakerOutreachCoordination.objects.filter(event=selected_event, person=person).delete()
                    person.events.remove(selected_event)
                    removed += 1
                dashboard_log_action(request, selected_event, CHANGE, f'Removed {removed} speaker(s) from speaker outreach workflow for {selected_event.name}.')
                messages.success(request, f'Removed {removed} speaker(s) from {selected_event.name}. The shared library records are still kept.')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#workflow")

            if action == 'save_template':
                subject = (request.POST.get('subject') or '').strip()
                intro_body = (request.POST.get('intro_body') or '').strip()
                if not subject or not intro_body:
                    raise ValueError('Speaker invitation subject and introduction are required.')
                template.subject = subject
                template.intro_body = intro_body
                template.closing_body = (request.POST.get('closing_body') or '').strip() or None
                template.airfare_body = (request.POST.get('airfare_body') or '').strip() or None
                template.hotel_body = (request.POST.get('hotel_body') or '').strip() or None
                template.allowance_body = (request.POST.get('allowance_body') or '').strip() or None
                template.local_transport_body = (request.POST.get('local_transport_body') or '').strip() or None
                template.special_support_body = (request.POST.get('special_support_body') or '').strip() or None
                template.save()
                dashboard_log_action(request, template, CHANGE, 'Updated speaker outreach template from Speaker Outreach Center dashboard.')
                messages.success(request, f'Speaker outreach email pattern saved for {selected_event.name}.')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#templates")

            if action == 'save_template_preset':
                preset_name = (request.POST.get('preset_name') or '').strip()
                subject = (request.POST.get('subject') or '').strip()
                intro_body = (request.POST.get('intro_body') or '').strip()
                if not preset_name:
                    raise ValueError('Give the reusable template a short name before saving it.')
                if not subject or not intro_body:
                    raise ValueError('Save a subject and introduction before storing this reusable template.')
                preset = SpeakerOutreachTemplatePreset.objects.create(
                    name=preset_name,
                    subject=subject,
                    intro_body=intro_body,
                    closing_body=(request.POST.get('closing_body') or '').strip() or None,
                    airfare_body=(request.POST.get('airfare_body') or '').strip() or None,
                    hotel_body=(request.POST.get('hotel_body') or '').strip() or None,
                    allowance_body=(request.POST.get('allowance_body') or '').strip() or None,
                    local_transport_body=(request.POST.get('local_transport_body') or '').strip() or None,
                    special_support_body=(request.POST.get('special_support_body') or '').strip() or None,
                    created_by=request.user if request.user.is_authenticated else None,
                )
                dashboard_log_action(request, preset, ADDITION, 'Saved reusable speaker outreach template preset from dashboard.')
                messages.success(request, f'Reusable invitation template "{preset.name}" saved to the shared library.')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#templates")

            if action == 'apply_template_preset':
                preset_id = request.POST.get('preset_id')
                preset = SpeakerOutreachTemplatePreset.objects.filter(pk=preset_id).first()
                if not preset:
                    raise ValueError('Choose a valid reusable template to apply.')
                _apply_speaker_outreach_preset_to_template(preset, template)
                dashboard_log_action(request, template, CHANGE, f'Applied speaker outreach template preset "{preset.name}" to event template.')
                messages.success(request, f'Applied reusable template "{preset.name}" to {selected_event.name}.')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#templates")

            if action == 'update_template_preset':
                preset_id = request.POST.get('preset_id')
                preset = SpeakerOutreachTemplatePreset.objects.filter(pk=preset_id).first()
                if not preset:
                    raise ValueError('Choose a valid reusable template to update.')
                preset_name = (request.POST.get('preset_name') or '').strip()
                subject = (request.POST.get('subject') or '').strip()
                intro_body = (request.POST.get('intro_body') or '').strip()
                if not preset_name:
                    raise ValueError('Give the reusable template a short name before updating it.')
                if not subject or not intro_body:
                    raise ValueError('Subject and introduction are required before updating this reusable template.')
                preset.name = preset_name
                preset.subject = subject
                preset.intro_body = intro_body
                preset.closing_body = (request.POST.get('closing_body') or '').strip() or None
                preset.airfare_body = (request.POST.get('airfare_body') or '').strip() or None
                preset.hotel_body = (request.POST.get('hotel_body') or '').strip() or None
                preset.allowance_body = (request.POST.get('allowance_body') or '').strip() or None
                preset.local_transport_body = (request.POST.get('local_transport_body') or '').strip() or None
                preset.special_support_body = (request.POST.get('special_support_body') or '').strip() or None
                preset.save()
                dashboard_log_action(request, preset, CHANGE, f'Updated reusable speaker outreach template preset "{preset.name}" from dashboard.')
                messages.success(request, f'Reusable invitation template "{preset.name}" updated.')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#templates")

            if action == 'save_options':
                if not page_people:
                    raise ValueError('No visible speaker rows were submitted for saving.')
                saved = _save_speaker_outreach_row_options(selected_event, page_people, request.POST)
                dashboard_log_action(request, selected_event, CHANGE, f'Saved speaker outreach options for {saved} speaker row(s).')
                messages.success(request, f'Saved outreach options for {saved} speaker row(s).')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#workflow")

            if action == 'send_selected':
                if not page_people:
                    raise ValueError('No visible speaker rows were submitted.')
                _save_speaker_outreach_row_options(selected_event, page_people, request.POST)
                selected_person_ids = [
                    int(value) for value in request.POST.getlist('selected_person_ids')
                    if str(value).strip().isdigit()
                ]
                if not selected_person_ids:
                    raise ValueError('Select at least one speaker before sending invitations.')
                selected_people = list(ProgramPerson.objects.filter(events=selected_event, id__in=selected_person_ids).distinct())
                if not selected_people:
                    raise ValueError('No valid speakers were found for the selected invitation action.')

                counts = {'queued': 0, 'missing_email': 0, 'failed': 0}
                for person in selected_people:
                    coordination = _speaker_outreach_row(selected_event, person)
                    try:
                        result, _ = _queue_speaker_outreach_email(selected_event, template, person, coordination, sent_by=request.user)
                    except Exception:
                        counts['failed'] += 1
                        continue
                    if result in counts:
                        counts[result] += 1
                dashboard_log_action(request, selected_event, CHANGE, f'Speaker outreach invitations queued from dashboard. queued={counts["queued"]}, missing_email={counts["missing_email"]}, failed={counts["failed"]}.')
                messages.success(request, f'Speaker outreach action complete. Queued: {counts["queued"]}, missing email: {counts["missing_email"]}, failed: {counts["failed"]}.')
                return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}#workflow")

            messages.error(request, 'Choose a valid speaker outreach action.')
        except Exception as exc:
            logger.exception('Speaker outreach action failed: %s', exc)
            messages.error(request, str(exc))
        return redirect(f"{reverse('dashboard_speaker_outreach_center')}?{urlencode(redirect_params)}")

    template = _speaker_outreach_template(selected_event) if selected_event else None
    all_rows = _speaker_outreach_rows(selected_event, template, search_query) if selected_event and template else []
    workflow_page_obj = Paginator(all_rows, 12).get_page(request.GET.get('page'))

    global_people_qs = _speaker_outreach_library_queryset(library_query)
    event_person_ids = set(ProgramPerson.objects.filter(events=selected_event).values_list('id', flat=True)) if selected_event else set()
    library_rows = [
        {
            'person': person,
            'email': (person.email or (person.profile.email if person.profile_id and person.profile and person.profile.email else '') or '').strip(),
            'is_in_event': person.id in event_person_ids,
        }
        for person in global_people_qs
    ]
    library_page_obj = Paginator(library_rows, 10).get_page(request.GET.get('library_page'))
    template_presets = SpeakerOutreachTemplatePreset.objects.select_related('created_by').all().order_by('name', '-updated_at')
    editing_preset = template_presets.filter(pk=edit_preset_id).first() if str(edit_preset_id or '').isdigit() else None
    editor_template_source = editing_preset or template

    preview_row = None
    if selected_event and template and str(preview_person_id or '').isdigit():
        preview_person = ProgramPerson.objects.filter(events=selected_event, pk=int(preview_person_id)).first()
        if preview_person:
            coordination = SpeakerOutreachCoordination.objects.filter(event=selected_event, person=preview_person).first() or SpeakerOutreachCoordination(event=selected_event, person=preview_person)
            preview_row = {
                'person': preview_person,
                'role_label': _speaker_outreach_role_label(preview_person, selected_event),
                'email': (preview_person.email or (preview_person.profile.email if preview_person.profile_id and preview_person.profile else '') or '').strip(),
                'coordination': coordination,
                'preview_subject': (template.subject or '').strip() or _default_speaker_outreach_subject(selected_event),
                'preview_body': _speaker_outreach_compose_message(selected_event, preview_person, template, coordination),
            }

    totals = {
        'speakers': len(all_rows),
        'with_email': sum(1 for row in all_rows if row['email']),
        'sent': sum(1 for row in all_rows if row['coordination'].status == SpeakerOutreachCoordination.STATUS_SENT),
        'airfare': sum(1 for row in all_rows if row['coordination'].offer_airfare),
        'hotel': sum(1 for row in all_rows if row['coordination'].offer_hotel),
        'allowance': sum(1 for row in all_rows if row['coordination'].offer_allowance),
        'prospects': sum(1 for row in all_rows if row['role_label'] == 'Prospect'),
        'global_people': global_people_qs.count(),
        'global_available': sum(1 for row in library_rows if not row['is_in_event']),
        'template_presets': template_presets.count(),
    }

    speaker_profile_results = _speaker_outreach_profile_rows(speaker_profile_query, event=selected_event, selected_profile_id=selected_profile_id) if speaker_profile_query and not selected_profile else []

    context = {
        'site_settings': site_settings,
        'events': events,
        'selected_event': selected_event,
        'template_row': template,
        'editor_template_source': editor_template_source,
        'editing_preset': editing_preset,
        'workflow_page_obj': workflow_page_obj,
        'page_obj': workflow_page_obj,
        'library_page_obj': library_page_obj,
        'template_presets': template_presets,
        'preview_row': preview_row,
        'totals': totals,
        'current_filters': {
            'event': str(selected_event.id) if selected_event else '',
            'q': search_query,
            'library_q': library_query,
        },
        'query_string': urlencode(base_params),
        'person_form': person_form,
        'speaker_profile_query': speaker_profile_query,
        'speaker_profile_results': speaker_profile_results,
        'selected_profile': selected_profile,
        'selected_profile_person': selected_profile_person,
        'selected_profile_in_event': selected_profile_in_event,
    }
    if request.method == 'GET' and request.headers.get('HX-Request'):
        if speaker_partial == 'add':
            return render(request, 'partials/dashboard_speaker_outreach_add_card.html', context)
        return render(request, 'partials/dashboard_speaker_outreach_library_panel.html', context)
    return render(request, 'dashboard_speaker_outreach_center.html', context)


@dashboard_permission_required('bulk_email')
def dashboard_bulk_email_center(request):
    from website.models import SiteSettings

    today = timezone.localdate()
    audit_start_raw = (request.GET.get('audit_start') or '').strip()
    audit_end_raw = (request.GET.get('audit_end') or '').strip()

    def _parse_audit_date(value, fallback):
        if not value:
            return fallback
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return fallback

    audit_start_date = _parse_audit_date(audit_start_raw, today)
    audit_end_date = _parse_audit_date(audit_end_raw, audit_start_date)
    if audit_end_date < audit_start_date:
        audit_end_date = audit_start_date

    audit_start_at = timezone.make_aware(datetime.combine(audit_start_date, datetime.min.time()))
    audit_end_at = timezone.make_aware(datetime.combine(audit_end_date + timedelta(days=1), datetime.min.time()))
    audit_queryset = EmailAuditLog.objects.filter(
        status=EmailAuditLog.STATUS_SENT,
        sent_at__gte=audit_start_at,
        sent_at__lt=audit_end_at,
    )
    audit_totals_by_category = {
        row['category']: row['total'] or 0
        for row in audit_queryset.values('category').annotate(total=Sum('recipient_count'))
    }
    audit_total_sent = sum(audit_totals_by_category.values())
    audit_total_events = audit_queryset.count()
    audit_category_cards = [
        {
            'key': value,
            'label': label,
            'count': audit_totals_by_category.get(value, 0),
        }
        for value, label in EmailAuditLog.CATEGORY_CHOICES
    ]

    if request.method == 'POST':
        action = request.POST.get('bulk_email_action')
        selected_campaign_id = request.POST.get('campaign_id')
        redirect_campaign_id = selected_campaign_id

        if action == 'create_campaign':
            subject = (request.POST.get('subject') or '').strip()
            body = (request.POST.get('body') or '').strip()
            button_error = None
            try:
                button_text, button_url = _read_email_button_fields(request.POST)
            except ValueError as exc:
                button_text, button_url = None, None
                button_error = str(exc)
            audience_type = request.POST.get('audience_type') or BulkEmail.AUDIENCE_MANUAL
            event = Event.objects.filter(pk=request.POST.get('event') or None).first()
            email_group = EmailGroup.objects.filter(pk=request.POST.get('email_group') or None).first()

            if button_error:
                messages.error(request, button_error)
            elif not subject or not body:
                messages.error(request, 'Subject and message body are required.')
            elif audience_type not in dict(BulkEmail.AUDIENCE_CHOICES):
                messages.error(request, 'Choose a valid audience.')
            elif audience_type in [
                BulkEmail.AUDIENCE_EVENT_PARTICIPANTS,
                BulkEmail.AUDIENCE_EVENT_UNPAID,
                BulkEmail.AUDIENCE_ABSTRACT_SUBMITTERS,
            ] and not event:
                messages.error(request, 'Choose an event for this audience.')
            elif audience_type == BulkEmail.AUDIENCE_EMAIL_GROUP and not email_group:
                messages.error(request, 'Choose an email group for this audience.')
            else:
                campaign = BulkEmail.objects.create(
                    subject=subject,
                    body=body,
                    button_text=button_text,
                    button_url=button_url,
                    attachment=request.FILES.get('attachment'),
                    audience_type=audience_type,
                    event=event if audience_type in [
                        BulkEmail.AUDIENCE_EVENT_PARTICIPANTS,
                        BulkEmail.AUDIENCE_EVENT_UNPAID,
                        BulkEmail.AUDIENCE_ABSTRACT_SUBMITTERS,
                    ] else None,
                    email_group=email_group if audience_type == BulkEmail.AUDIENCE_EMAIL_GROUP else None,
                    created_by=request.user,
                )
                redirect_campaign_id = campaign.id
                dashboard_log_action(request, campaign, ADDITION, 'Created bulk email campaign from Bulk Email Center dashboard.')
                messages.success(request, f'Campaign "{campaign.subject}" created. Prepare recipients when ready.')

        elif action == 'create_group':
            group_id = request.POST.get('group_id')
            name = (request.POST.get('name') or '').strip()
            email_addresses = (request.POST.get('email_addresses') or '').strip()
            if not name or not email_addresses:
                messages.error(request, 'Group name and email addresses are required.')
            else:
                group = EmailGroup.objects.filter(pk=group_id).first() if group_id else None
                if group:
                    group.name = name
                    group.email_addresses = email_addresses
                    group.save(update_fields=['name', 'email_addresses'])
                    dashboard_log_action(request, group, CHANGE, 'Updated email group from Bulk Email Center dashboard.')
                    messages.success(request, f'Email group "{group.name}" updated.')
                else:
                    group, created = EmailGroup.objects.get_or_create(
                        name=name,
                        defaults={'email_addresses': email_addresses},
                    )
                    if created:
                        dashboard_log_action(request, group, ADDITION, 'Created email group from Bulk Email Center dashboard.')
                        messages.success(request, f'Email group "{group.name}" created.')
                    else:
                        group.email_addresses = email_addresses
                        group.save(update_fields=['email_addresses'])
                        dashboard_log_action(request, group, CHANGE, 'Updated email group from Bulk Email Center dashboard.')
                        messages.success(request, f'Email group "{group.name}" updated.')

        elif action == 'prepare_recipients':
            campaign = BulkEmail.objects.filter(pk=selected_campaign_id).first()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            else:
                added = prepare_bulk_email_recipients(campaign)
                dashboard_log_action(request, campaign, CHANGE, f'Prepared bulk email recipients from dashboard. New recipients added: {added}.')
                messages.success(request, f'Recipient preparation complete. New recipients added: {added}.')

        elif action == 'add_manual_recipient':
            campaign = BulkEmail.objects.filter(pk=selected_campaign_id).first()
            email = request.POST.get('recipient_email')
            name = (request.POST.get('recipient_name') or '').strip()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            elif upsert_bulk_email_recipient(
                campaign,
                email,
                name=name,
                source_type=BulkEmailRecipient.SOURCE_MANUAL,
            ):
                campaign.status = BulkEmail.STATUS_RECIPIENTS_READY
                campaign.save(update_fields=['status', 'updated_at'])
                dashboard_log_action(request, campaign, CHANGE, f'Added manual recipient {email} from Bulk Email Center dashboard.')
                messages.success(request, f'{email} added to this campaign.')
            else:
                messages.warning(request, 'That email is invalid or already exists in this campaign.')

        elif action == 'send_pending':
            campaign = BulkEmail.objects.filter(pk=selected_campaign_id).first()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            else:
                if not campaign.recipients.filter(status=BulkEmailRecipient.STATUS_PENDING).exists():
                    prepare_bulk_email_recipients(campaign)
                pending_recipients = campaign.recipients.filter(status=BulkEmailRecipient.STATUS_PENDING).order_by('id')
                if not pending_recipients.exists():
                    messages.warning(request, 'No pending recipients are available for this campaign.')
                else:
                    quota_snapshot = get_email_quota_snapshot()
                    send_plan = plan_bulk_email_send(pending_recipients, quota_snapshot=quota_snapshot)
                    if not send_plan['allowed_count']:
                        messages.warning(
                            request,
                            f"Bulk email quota reached for the last {quota_snapshot['window_hours']} hours. Bulk used: {quota_snapshot['bulk_used']}/{quota_snapshot['bulk_limit']}, total used: {quota_snapshot['total_used']}/{quota_snapshot['total_limit']}. Pending recipients remain queued.",
                        )
                    else:
                        campaign.status = BulkEmail.STATUS_SENDING
                        campaign.save(update_fields=['status', 'updated_at'])
                        task = send_pending_bulk_email_campaign.delay(campaign.id, request.user.id)
                        chunk_size = max(int(getattr(settings, 'BULK_EMAIL_CHUNK_SIZE', 50) or 50), 1)
                        dashboard_log_action(request, campaign, CHANGE, f"Queued bulk email send from dashboard for {send_plan['allowed_count']} quota-eligible pending recipients in chunked processing.")
                        queued_message = f"Bulk email send queued for {send_plan['allowed_count']} quota-eligible pending recipients. The worker will process them in chunks of {chunk_size}. Task ID: {task.id}."
                        if send_plan['blocked_count']:
                            queued_message += f" {send_plan['blocked_count']} recipient(s) remain pending until 24-hour quota becomes available."
                        messages.success(request, queued_message)
        elif action == 'send_failed':
            campaign = BulkEmail.objects.filter(pk=selected_campaign_id).first()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            else:
                failed_recipients = campaign.recipients.filter(status=BulkEmailRecipient.STATUS_FAILED).order_by('id')
                failed_count = failed_recipients.count()
                if not failed_count:
                    messages.warning(request, 'No failed recipients are available for retry in this campaign.')
                else:
                    quota_snapshot = get_email_quota_snapshot()
                    send_plan = plan_bulk_email_send(failed_recipients, quota_snapshot=quota_snapshot)
                    if not send_plan['allowed_count']:
                        messages.warning(
                            request,
                            f"Bulk email quota reached for the last {quota_snapshot['window_hours']} hours. Failed recipients remain queued for retry until quota becomes available.",
                        )
                    else:
                        campaign.status = BulkEmail.STATUS_SENDING
                        campaign.save(update_fields=['status', 'updated_at'])
                        task = send_pending_bulk_email_campaign.delay(
                            campaign.id,
                            request.user.id,
                            [BulkEmailRecipient.STATUS_FAILED],
                        )
                        chunk_size = max(int(getattr(settings, 'BULK_EMAIL_CHUNK_SIZE', 50) or 50), 1)
                        dashboard_log_action(request, campaign, CHANGE, f"Queued bulk email retry from dashboard for {send_plan['allowed_count']} quota-eligible failed recipients in chunked processing.")
                        queued_message = f"Bulk email retry queued for {send_plan['allowed_count']} quota-eligible failed recipients. The worker will process them in chunks of {chunk_size}. Task ID: {task.id}."
                        if send_plan['blocked_count']:
                            queued_message += f" {send_plan['blocked_count']} failed recipient(s) remain queued until 24-hour quota becomes available."
                        messages.success(request, queued_message)
        elif action == 'stop_campaign':
            campaign = BulkEmail.objects.filter(pk=selected_campaign_id).first()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            elif campaign.status != BulkEmail.STATUS_SENDING:
                messages.warning(request, 'This campaign is not currently sending.')
            else:
                new_status = BulkEmail.STATUS_PARTIAL if campaign.recipients.filter(
                    status__in=[BulkEmailRecipient.STATUS_SENT, BulkEmailRecipient.STATUS_FAILED]
                ).exists() else BulkEmail.STATUS_RECIPIENTS_READY
                campaign.status = new_status
                campaign.save(update_fields=['status', 'updated_at'])
                dashboard_log_action(request, campaign, CHANGE, 'Stopped bulk email campaign from dashboard. Pending recipients were kept for later retry.')
                messages.success(request, 'Campaign stop requested. The worker will halt after the current email cycle and keep pending recipients for later resend.')

        url = reverse('dashboard_bulk_email_center')
        query = {}
        if redirect_campaign_id:
            query['campaign'] = redirect_campaign_id
        scroll_to = (request.POST.get('scroll_to') or '').strip()
        if scroll_to:
            query['scroll_to'] = scroll_to
        if query:
            url = f'{url}?{urlencode(query)}'
        return redirect(url)

    campaigns = BulkEmail.objects.select_related('event', 'email_group', 'created_by').order_by('-created_at')
    selected_campaign = campaigns.filter(pk=request.GET.get('campaign')).first()
    if not selected_campaign:
        selected_campaign = campaigns.first()
    recent_logs = BulkEmailSendLog.objects.select_related('bulk_email', 'recipient', 'sent_by').order_by('-created_at')[:12]
    groups = EmailGroup.objects.order_by('name')
    events = Event.objects.order_by('-year', 'name')
    selected_recipients_qs = selected_campaign.recipients.order_by('status', 'email') if selected_campaign else BulkEmailRecipient.objects.none()
    selected_logs_qs = selected_campaign.send_logs.select_related('recipient', 'sent_by').order_by('-created_at') if selected_campaign else BulkEmailSendLog.objects.none()
    selected_recipients_page = Paginator(selected_recipients_qs, 15).get_page(request.GET.get('recipient_page'))
    selected_logs_page = Paginator(selected_logs_qs, 10).get_page(request.GET.get('log_page'))
    email_quota_snapshot = get_email_quota_snapshot()
    selected_campaign_progress = None
    if selected_campaign:
        progress_snapshot = sync_bulk_email_status(selected_campaign)
        recipient_total = progress_snapshot['total']
        sent_total = progress_snapshot['sent']
        failed_total = progress_snapshot['failed']
        pending_total = progress_snapshot['pending']
        completed_total = sent_total + failed_total
        pending_send_plan = plan_bulk_email_send(
            selected_campaign.recipients.filter(status=BulkEmailRecipient.STATUS_PENDING).order_by('id'),
            quota_snapshot=email_quota_snapshot,
        )
        selected_campaign_progress = {
            'total': recipient_total,
            'sent': sent_total,
            'failed': failed_total,
            'pending': pending_total,
            'completed': completed_total,
            'percent': int((completed_total / recipient_total) * 100) if recipient_total else 0,
            'is_sending': progress_snapshot['status'] == BulkEmail.STATUS_SENDING,
            'quota_blocked_count': pending_send_plan['blocked_count'],
        }
    base_query = {}
    filter_query = {
        'audit_start': audit_start_date.isoformat(),
        'audit_end': audit_end_date.isoformat(),
    }
    if selected_campaign:
        base_query['campaign'] = selected_campaign.id
    base_query.update(filter_query)
    group_data_json = json.dumps([
        {
            'id': group.id,
            'name': group.name,
            'email_addresses': group.email_addresses,
            'emails': group.parsed_emails(),
        }
        for group in groups
    ]).replace('</', '<\\/')
    totals = {
        'campaigns': BulkEmail.objects.count(),
        'drafts': BulkEmail.objects.filter(status=BulkEmail.STATUS_DRAFT).count(),
        'ready': BulkEmail.objects.filter(status=BulkEmail.STATUS_RECIPIENTS_READY).count(),
        'recipients': BulkEmailRecipient.objects.count(),
        'pending': BulkEmailRecipient.objects.filter(status=BulkEmailRecipient.STATUS_PENDING).count(),
        'sent': BulkEmailRecipient.objects.filter(status=BulkEmailRecipient.STATUS_SENT).count(),
        'failed': BulkEmailRecipient.objects.filter(status=BulkEmailRecipient.STATUS_FAILED).count(),
        'groups': EmailGroup.objects.count(),
    }
    workflow_steps = [
        {
            'label': 'Create campaign',
            'detail': 'Write the subject, message body, attachment, and choose an audience source.',
        },
        {
            'label': 'Prepare recipients',
            'detail': 'Select a campaign and generate individual recipient rows from the chosen audience.',
        },
        {
            'label': 'Review recipient rows',
            'detail': 'Check pending, failed, skipped, and sent recipient rows before sending.',
        },
        {
            'label': 'Send and audit',
            'detail': 'Send pending recipients individually and inspect per-recipient delivery logs here.',
        },
    ]
    context = {
        'site_settings': SiteSettings.objects.first(),
        'campaigns': campaigns,
        'selected_campaign': selected_campaign,
        'selected_campaign_progress': selected_campaign_progress,
        'selected_recipients': selected_recipients_page,
        'selected_logs': selected_logs_page,
        'recipient_page_obj': selected_recipients_page,
        'log_page_obj': selected_logs_page,
        'bulk_email_base_query': urlencode(base_query),
        'recent_logs': recent_logs,
        'groups': groups,
        'group_data_json': group_data_json,
        'events': events,
        'audience_choices': BulkEmail.AUDIENCE_CHOICES,
        'totals': totals,
        'workflow_steps': workflow_steps,
        'audit_start': audit_start_date.isoformat(),
        'audit_end': audit_end_date.isoformat(),
        'audit_total_sent': audit_total_sent,
        'audit_total_events': audit_total_events,
        'audit_category_cards': audit_category_cards,
        'bulk_email_filter_query': urlencode(filter_query),
        'email_quota': email_quota_snapshot,
    }
    if request.GET.get('bulk_email_partial') == 'active_campaign':
        return render(request, 'partials/dashboard_bulk_email_active_campaign.html', context)
    if request.GET.get('bulk_email_partial') == 'audit_summary':
        return render(request, 'partials/dashboard_bulk_email_audit.html', context)
    return render(request, 'dashboard_bulk_email_center.html', context)


@dashboard_permission_required('bulk_sms')
def dashboard_bulk_sms_center(request):
    from website.models import SiteSettings

    today = timezone.localdate()
    audit_start_raw = (request.GET.get('audit_start') or '').strip()
    audit_end_raw = (request.GET.get('audit_end') or '').strip()

    def _parse_audit_date(value, fallback):
        if not value:
            return fallback
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return fallback

    audit_start_date = _parse_audit_date(audit_start_raw, today)
    audit_end_date = _parse_audit_date(audit_end_raw, audit_start_date)
    if audit_end_date < audit_start_date:
        audit_end_date = audit_start_date

    audit_start_at = timezone.make_aware(datetime.combine(audit_start_date, datetime.min.time()))
    audit_end_at = timezone.make_aware(datetime.combine(audit_end_date + timedelta(days=1), datetime.min.time()))
    audit_queryset = BulkSMSSendLog.objects.filter(
        status=BulkSMSRecipient.STATUS_SENT,
        created_at__gte=audit_start_at,
        created_at__lt=audit_end_at,
    ).select_related('bulk_sms')
    audit_totals_by_category = {
        row['bulk_sms__audience_type']: row['total'] or 0
        for row in audit_queryset.values('bulk_sms__audience_type').annotate(total=Count('id'))
    }
    audit_total_sent = audit_queryset.count()
    audit_total_events = audit_queryset.values('bulk_sms_id').distinct().count()
    audit_category_cards = [
        {
            'key': value,
            'label': label,
            'count': audit_totals_by_category.get(value, 0),
        }
        for value, label in BulkSMS.AUDIENCE_CHOICES
    ]

    provider_tools = {
        'requested_action': (request.GET.get('provider_action') or '').strip(),
        'status_message_id': (request.GET.get('status_message_id') or '').strip(),
        'multi_status_message_ids': (request.GET.get('multi_status_message_ids') or '').strip(),
        'balance_requested': request.GET.get('provider_balance') == '1',
        'status_result': None,
        'multi_status_result': None,
        'balance_result': None,
        'status_summary': None,
        'multi_status_summary': None,
        'balance_summary': None,
        'latest_message_id': '',
        'campaign_message_ids': [],
        'campaign_message_ids_text': '',
        'message_id_count': 0,
        'dlr_url': getattr(settings, 'SMS_GATEWAY_DLR_URL', ''),
        'multi_status_url': getattr(settings, 'SMS_GATEWAY_MULTI_STATUS_URL', ''),
        'balance_url': getattr(settings, 'SMS_GATEWAY_BALANCE_URL', ''),
        'client_id': getattr(settings, 'SMS_GATEWAY_CLIENT_ID', ''),
        'multi_status_query': (request.GET.get('multi_status_query') or '').strip(),
        'multi_status_page': request.GET.get('multi_status_page') or '1',
        'multi_status_page_obj': None,
        'multi_status_query_string': '',
    }

    if request.method == 'POST':
        action = request.POST.get('bulk_sms_action')
        selected_campaign_id = request.POST.get('campaign_id')
        redirect_campaign_id = selected_campaign_id

        if action == 'create_campaign':
            subject = (request.POST.get('subject') or '').strip()
            body = (request.POST.get('body') or '').strip()
            audience_type = request.POST.get('audience_type') or BulkSMS.AUDIENCE_MANUAL
            sms_type = request.POST.get('sms_type') or BulkSMS.SMS_TYPE_NON_MASKING
            event = Event.objects.filter(pk=request.POST.get('event') or None).first()
            phone_group = PhoneGroup.objects.filter(pk=request.POST.get('phone_group') or None).first()

            if not subject or not body:
                messages.error(request, 'Campaign title and message body are required.')
            elif sms_type not in dict(BulkSMS.SMS_TYPE_CHOICES):
                messages.error(request, 'Choose a valid SMS type.')
            elif audience_type not in dict(BulkSMS.AUDIENCE_CHOICES):
                messages.error(request, 'Choose a valid audience.')
            elif audience_type in [
                BulkSMS.AUDIENCE_EVENT_PARTICIPANTS,
                BulkSMS.AUDIENCE_EVENT_UNPAID,
                BulkSMS.AUDIENCE_ABSTRACT_SUBMITTERS,
            ] and not event:
                messages.error(request, 'Choose an event for this audience.')
            elif audience_type == BulkSMS.AUDIENCE_PHONE_GROUP and not phone_group:
                messages.error(request, 'Choose a phone group for this audience.')
            else:
                campaign = BulkSMS.objects.create(
                    subject=subject,
                    body=body,
                    sms_type=sms_type,
                    audience_type=audience_type,
                    event=event if audience_type in [
                        BulkSMS.AUDIENCE_EVENT_PARTICIPANTS,
                        BulkSMS.AUDIENCE_EVENT_UNPAID,
                        BulkSMS.AUDIENCE_ABSTRACT_SUBMITTERS,
                    ] else None,
                    phone_group=phone_group if audience_type == BulkSMS.AUDIENCE_PHONE_GROUP else None,
                    created_by=request.user,
                )
                redirect_campaign_id = campaign.id
                dashboard_log_action(request, campaign, ADDITION, 'Created bulk SMS campaign from Bulk SMS Center dashboard.')
                messages.success(request, f'Campaign "{campaign.subject}" created. Prepare recipients when ready.')

        elif action == 'create_group':
            group_id = request.POST.get('group_id')
            name = (request.POST.get('name') or '').strip()
            phone_numbers = (request.POST.get('phone_numbers') or '').strip()
            if not name or not phone_numbers:
                messages.error(request, 'Group name and phone numbers are required.')
            else:
                group = PhoneGroup.objects.filter(pk=group_id).first() if group_id else None
                if group:
                    group.name = name
                    group.phone_numbers = phone_numbers
                    group.save(update_fields=['name', 'phone_numbers'])
                    dashboard_log_action(request, group, CHANGE, 'Updated phone group from Bulk SMS Center dashboard.')
                    messages.success(request, f'Phone group "{group.name}" updated.')
                else:
                    group, created = PhoneGroup.objects.get_or_create(
                        name=name,
                        defaults={'phone_numbers': phone_numbers},
                    )
                    if created:
                        dashboard_log_action(request, group, ADDITION, 'Created phone group from Bulk SMS Center dashboard.')
                        messages.success(request, f'Phone group "{group.name}" created.')
                    else:
                        group.phone_numbers = phone_numbers
                        group.save(update_fields=['phone_numbers'])
                        dashboard_log_action(request, group, CHANGE, 'Updated phone group from Bulk SMS Center dashboard.')
                        messages.success(request, f'Phone group "{group.name}" updated.')

        elif action == 'prepare_recipients':
            campaign = BulkSMS.objects.filter(pk=selected_campaign_id).first()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            else:
                added = prepare_bulk_sms_recipients(campaign)
                dashboard_log_action(request, campaign, CHANGE, f'Prepared bulk SMS recipients from dashboard. New recipients added: {added}.')
                messages.success(request, f'Recipient preparation complete. New recipients added: {added}.')

        elif action == 'add_manual_recipient':
            campaign = BulkSMS.objects.filter(pk=selected_campaign_id).first()
            phone = (request.POST.get('recipient_phone') or '').strip()
            name = (request.POST.get('recipient_name') or '').strip()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            elif upsert_bulk_sms_recipient(
                campaign,
                phone,
                country=DEFAULT_COUNTRY,
                raw_phone=phone,
                name=name,
                source_type=BulkSMSRecipient.SOURCE_MANUAL,
            ):
                campaign.status = BulkSMS.STATUS_RECIPIENTS_READY
                campaign.save(update_fields=['status', 'updated_at'])
                dashboard_log_action(request, campaign, CHANGE, f'Added manual SMS recipient {phone} from Bulk SMS Center dashboard.')
                messages.success(request, f'{phone} added to this campaign.')
            else:
                messages.warning(request, 'That phone number is invalid, not Bangladesh-eligible, or already exists in this campaign.')

        elif action == 'send_pending':
            campaign = BulkSMS.objects.filter(pk=selected_campaign_id).first()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            else:
                if not campaign.recipients.filter(status=BulkSMSRecipient.STATUS_PENDING).exists():
                    prepare_bulk_sms_recipients(campaign)
                pending_recipients = campaign.recipients.filter(status=BulkSMSRecipient.STATUS_PENDING).order_by('id')
                if not pending_recipients.exists():
                    messages.warning(request, 'No pending recipients are available for this campaign.')
                else:
                    campaign.status = BulkSMS.STATUS_SENDING
                    campaign.save(update_fields=['status', 'updated_at'])
                    task = send_pending_bulk_sms_campaign.delay(campaign.id, request.user.id)
                    chunk_size = max(int(getattr(settings, 'BULK_SMS_CHUNK_SIZE', 100) or 100), 1)
                    dashboard_log_action(request, campaign, CHANGE, f'Queued bulk SMS send from dashboard for pending recipients in chunked processing.')
                    messages.success(request, f'Bulk SMS send queued. The worker will process recipients in chunks of {chunk_size}. Task ID: {task.id}.')

        elif action == 'send_failed':
            campaign = BulkSMS.objects.filter(pk=selected_campaign_id).first()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            else:
                failed_recipients = campaign.recipients.filter(status=BulkSMSRecipient.STATUS_FAILED).order_by('id')
                if not failed_recipients.exists():
                    messages.warning(request, 'No failed recipients are available for retry in this campaign.')
                else:
                    campaign.status = BulkSMS.STATUS_SENDING
                    campaign.save(update_fields=['status', 'updated_at'])
                    task = send_pending_bulk_sms_campaign.delay(
                        campaign.id,
                        request.user.id,
                        [BulkSMSRecipient.STATUS_FAILED],
                    )
                    chunk_size = max(int(getattr(settings, 'BULK_SMS_CHUNK_SIZE', 100) or 100), 1)
                    dashboard_log_action(request, campaign, CHANGE, 'Queued bulk SMS retry from dashboard for failed recipients in chunked processing.')
                    messages.success(request, f'Bulk SMS retry queued. The worker will process recipients in chunks of {chunk_size}. Task ID: {task.id}.')

        elif action == 'stop_campaign':
            campaign = BulkSMS.objects.filter(pk=selected_campaign_id).first()
            if not campaign:
                messages.error(request, 'Choose a valid campaign first.')
            elif campaign.status != BulkSMS.STATUS_SENDING:
                messages.warning(request, 'This campaign is not currently sending.')
            else:
                new_status = BulkSMS.STATUS_PARTIAL if campaign.recipients.filter(
                    status__in=[BulkSMSRecipient.STATUS_SENT, BulkSMSRecipient.STATUS_FAILED]
                ).exists() else BulkSMS.STATUS_RECIPIENTS_READY
                campaign.status = new_status
                campaign.save(update_fields=['status', 'updated_at'])
                dashboard_log_action(request, campaign, CHANGE, 'Stopped bulk SMS campaign from dashboard. Pending recipients were kept for later retry.')
                messages.success(request, 'Campaign stop requested. The worker will halt after the current SMS batch and keep pending recipients for later resend.')

        url = reverse('dashboard_bulk_sms_center')
        query = {}
        if redirect_campaign_id:
            query['campaign'] = redirect_campaign_id
        scroll_to = (request.POST.get('scroll_to') or '').strip()
        if scroll_to:
            query['scroll_to'] = scroll_to
        if query:
            url = f'{url}?{urlencode(query)}'
        return redirect(url)

    campaigns = BulkSMS.objects.select_related('event', 'phone_group', 'created_by').order_by('-created_at')
    selected_campaign = campaigns.filter(pk=request.GET.get('campaign')).first()
    if not selected_campaign:
        selected_campaign = campaigns.first()
    recent_logs = BulkSMSSendLog.objects.select_related('bulk_sms', 'recipient', 'sent_by').order_by('-created_at')[:12]
    groups = PhoneGroup.objects.order_by('name')
    events = Event.objects.order_by('-year', 'name')
    selected_recipients_qs = selected_campaign.recipients.order_by('status', 'phone') if selected_campaign else BulkSMSRecipient.objects.none()
    selected_logs_qs = selected_campaign.send_logs.select_related('recipient', 'sent_by').order_by('-created_at') if selected_campaign else BulkSMSSendLog.objects.none()
    selected_recipients_page = Paginator(selected_recipients_qs, 15).get_page(request.GET.get('recipient_page'))
    selected_logs_page = Paginator(selected_logs_qs, 10).get_page(request.GET.get('log_page'))

    if selected_campaign:
        campaign_message_ids = [
            message_id for message_id in selected_campaign.send_logs.exclude(provider_message_id__isnull=True).exclude(provider_message_id='')
            .order_by('-created_at').values_list('provider_message_id', flat=True)
        ]
        unique_campaign_message_ids = []
        seen_campaign_message_ids = set()
        for message_id in campaign_message_ids:
            if message_id in seen_campaign_message_ids:
                continue
            seen_campaign_message_ids.add(message_id)
            unique_campaign_message_ids.append(message_id)
        provider_tools['campaign_message_ids'] = unique_campaign_message_ids
        provider_tools['latest_message_id'] = unique_campaign_message_ids[0] if unique_campaign_message_ids else ''
        provider_tools['campaign_message_ids_text'] = ','.join(unique_campaign_message_ids)
        provider_tools['message_id_count'] = len(unique_campaign_message_ids)

        if provider_tools['requested_action'] == 'latest_status' and provider_tools['latest_message_id']:
            provider_tools['status_message_id'] = provider_tools['latest_message_id']
        elif provider_tools['requested_action'] == 'campaign_multi_status' and provider_tools['campaign_message_ids_text']:
            provider_tools['multi_status_message_ids'] = provider_tools['campaign_message_ids_text']
        elif provider_tools['requested_action'] == 'balance':
            provider_tools['balance_requested'] = True

        if provider_tools['status_message_id']:
            provider_tools['status_result'] = query_sms_status(
                provider_tools['status_message_id'],
                context={'source': 'dashboard_bulk_sms_provider_tools', 'tool': 'status', 'campaign_id': selected_campaign.id},
            )
            provider_tools['status_summary'] = _build_provider_result_summary(provider_tools['status_result'], kind='status')
        if provider_tools['multi_status_message_ids']:
            provider_tools['multi_status_result'] = query_sms_multi_status(
                provider_tools['multi_status_message_ids'],
                context={'source': 'dashboard_bulk_sms_provider_tools', 'tool': 'multi_status', 'campaign_id': selected_campaign.id},
            )
            provider_tools['multi_status_summary'] = _build_provider_result_summary(provider_tools['multi_status_result'], kind='multi_status')
            if provider_tools['multi_status_summary'] and provider_tools['multi_status_summary'].get('rows'):
                query_value = provider_tools['multi_status_query'].lower()
                filtered_rows = provider_tools['multi_status_summary']['rows']
                if query_value:
                    filtered_rows = [
                        row for row in filtered_rows
                        if query_value in str(row.get('message_id', '')).lower()
                        or query_value in str(row.get('status_text', '')).lower()
                        or query_value in str(row.get('detail_text', '')).lower()
                    ]
                provider_tools['multi_status_summary']['total_row_count'] = len(provider_tools['multi_status_summary']['rows'])
                provider_tools['multi_status_summary']['filtered_row_count'] = len(filtered_rows)
                multi_status_page_obj = Paginator(filtered_rows, 10).get_page(provider_tools['multi_status_page'])
                provider_tools['multi_status_page_obj'] = multi_status_page_obj
                provider_tools['multi_status_summary']['rows'] = list(multi_status_page_obj.object_list)
                multi_status_query_params = {
                    'campaign': selected_campaign.id,
                    'scroll_to': 'campaign-provider-tools',
                    'provider_action': 'campaign_multi_status',
                }
                if provider_tools['multi_status_query']:
                    multi_status_query_params['multi_status_query'] = provider_tools['multi_status_query']
                provider_tools['multi_status_query_string'] = urlencode(multi_status_query_params)
        if provider_tools['balance_requested']:
            provider_tools['balance_result'] = query_sms_balance(
                context={'source': 'dashboard_bulk_sms_provider_tools', 'tool': 'balance', 'campaign_id': selected_campaign.id},
            )
            provider_tools['balance_summary'] = _build_provider_result_summary(provider_tools['balance_result'], kind='balance')

    selected_campaign_progress = None
    if selected_campaign:
        progress_snapshot = sync_bulk_sms_status(selected_campaign)
        recipient_total = progress_snapshot['total']
        sent_total = progress_snapshot['sent']
        failed_total = progress_snapshot['failed']
        pending_total = progress_snapshot['pending']
        completed_total = sent_total + failed_total
        sms_unit_summary = estimate_sms_units(selected_campaign.body, recipient_total, sms_type=selected_campaign.sms_type)
        selected_campaign_progress = {
            'total': recipient_total,
            'sent': sent_total,
            'failed': failed_total,
            'pending': pending_total,
            'completed': completed_total,
            'percent': int((completed_total / recipient_total) * 100) if recipient_total else 0,
            'is_sending': progress_snapshot['status'] == BulkSMS.STATUS_SENDING,
            'characters': sms_unit_summary['characters'],
            'segment_char_limit': sms_unit_summary['segment_char_limit'],
            'segments_per_recipient': sms_unit_summary['segments'],
            'estimated_total_units': sms_unit_summary['estimated_total_units'],
            'sms_caller_id': resolve_sms_caller_id(selected_campaign.sms_type),
            'gateway_mode_label': 'Provider campaign endpoint',
            'gateway_url': resolve_sms_url(is_bulk=True),
        }
    base_query = {}
    filter_query = {
        'audit_start': audit_start_date.isoformat(),
        'audit_end': audit_end_date.isoformat(),
    }
    if selected_campaign:
        base_query['campaign'] = selected_campaign.id
    base_query.update(filter_query)
    group_data_json = json.dumps([
        {
            'id': group.id,
            'name': group.name,
            'phone_numbers': group.phone_numbers,
            'phones': group.parsed_phone_numbers(),
        }
        for group in groups
    ]).replace('</', '<\/')
    totals = {
        'campaigns': BulkSMS.objects.count(),
        'drafts': BulkSMS.objects.filter(status=BulkSMS.STATUS_DRAFT).count(),
        'ready': BulkSMS.objects.filter(status=BulkSMS.STATUS_RECIPIENTS_READY).count(),
        'recipients': BulkSMSRecipient.objects.count(),
        'pending': BulkSMSRecipient.objects.filter(status=BulkSMSRecipient.STATUS_PENDING).count(),
        'sent': BulkSMSRecipient.objects.filter(status=BulkSMSRecipient.STATUS_SENT).count(),
        'failed': BulkSMSRecipient.objects.filter(status=BulkSMSRecipient.STATUS_FAILED).count(),
        'groups': PhoneGroup.objects.count(),
    }
    workflow_steps = [
        {
            'label': 'Create campaign',
            'detail': 'Write the SMS campaign title, message body, and choose an audience source.',
        },
        {
            'label': 'Prepare recipients',
            'detail': 'Select a campaign and generate Bangladesh-eligible phone rows from the chosen audience.',
        },
        {
            'label': 'Review recipient rows',
            'detail': 'Check who will receive this campaign. Invalid or failed rows stay visible for correction.',
        },
        {
            'label': 'Send and audit',
            'detail': 'Send pending recipients in bulk batches and inspect per-recipient delivery logs here.',
        },
    ]
    context = {
        'site_settings': SiteSettings.objects.first(),
        'campaigns': campaigns,
        'selected_campaign': selected_campaign,
        'selected_campaign_progress': selected_campaign_progress,
        'selected_recipients': selected_recipients_page,
        'selected_logs': selected_logs_page,
        'recipient_page_obj': selected_recipients_page,
        'log_page_obj': selected_logs_page,
        'bulk_sms_base_query': urlencode(base_query),
        'recent_logs': recent_logs,
        'groups': groups,
        'group_data_json': group_data_json,
        'events': events,
        'audience_choices': BulkSMS.AUDIENCE_CHOICES,
        'sms_type_choices': BulkSMS.SMS_TYPE_CHOICES,
        'totals': totals,
        'workflow_steps': workflow_steps,
        'audit_start': audit_start_date.isoformat(),
        'audit_end': audit_end_date.isoformat(),
        'audit_total_sent': audit_total_sent,
        'audit_total_events': audit_total_events,
        'audit_category_cards': audit_category_cards,
        'bulk_sms_filter_query': urlencode(filter_query),
        'default_sms_type': BulkSMS.SMS_TYPE_NON_MASKING,
        'provider_tools': provider_tools,
        'sms_type_limits': {
            BulkSMS.SMS_TYPE_MASKING: get_sms_segment_char_limit(BulkSMS.SMS_TYPE_MASKING),
            BulkSMS.SMS_TYPE_NON_MASKING: get_sms_segment_char_limit(BulkSMS.SMS_TYPE_NON_MASKING),
        },
    }
    if request.GET.get('bulk_sms_partial') == 'active_campaign':
        return render(request, 'partials/dashboard_bulk_sms_active_campaign.html', context)
    if request.GET.get('bulk_sms_partial') == 'audit_summary':
        return render(request, 'partials/dashboard_bulk_sms_audit.html', context)
    return render(request, 'dashboard_bulk_sms_center.html', context)


@dashboard_permission_required('bulk_sms')
def dashboard_sms_template_center(request):
    from website.models import SiteSettings
    from .sms import ensure_system_sms_templates, get_system_sms_template_defaults

    ensure_system_sms_templates()
    defaults_map = get_system_sms_template_defaults()
    templates = list(SystemSMSTemplate.objects.all().order_by('label', 'id'))
    template_map = {template.template_key: template for template in templates}

    selected_key = (request.GET.get('template') or request.POST.get('template_key') or '').strip()
    if not selected_key and templates:
        selected_key = templates[0].template_key
    selected_template = template_map.get(selected_key) if selected_key else (templates[0] if templates else None)

    if request.method == 'POST' and selected_template:
        action = (request.POST.get('sms_template_action') or '').strip()
        default_template = defaults_map.get(selected_template.template_key, {})
        if action == 'save':
            selected_template.body = (request.POST.get('body') or '').strip()
            selected_template.sms_type = SystemSMSTemplate.SMS_TYPE_MASKING
            if not selected_template.body:
                messages.error(request, 'SMS body cannot be empty.')
            else:
                selected_template.save(update_fields=['body', 'sms_type', 'updated_at'])
                messages.success(request, f'SMS template updated: {selected_template.label}.')
            return redirect(f"{reverse('dashboard_sms_template_center')}?template={selected_template.template_key}")
        if action == 'reset':
            selected_template.body = default_template.get('body', selected_template.body)
            selected_template.sms_type = SystemSMSTemplate.SMS_TYPE_MASKING
            selected_template.save(update_fields=['body', 'sms_type', 'updated_at'])
            messages.success(request, f'SMS template reset to default: {selected_template.label}.')
            return redirect(f"{reverse('dashboard_sms_template_center')}?template={selected_template.template_key}")

    def _template_group_label(template_key):
        if template_key.startswith('registration_'):
            return 'Registration SMS'
        if template_key.startswith('abstract_'):
            return 'Abstract SMS'
        if template_key.startswith('membership_'):
            return 'Membership SMS'
        if 'payment_' in template_key:
            return 'Payment SMS'
        return 'Other SMS'

    grouped_template_rows = []
    group_order = ['Registration SMS', 'Abstract SMS', 'Membership SMS', 'Payment SMS', 'Other SMS']
    grouped_map = {label: [] for label in group_order}
    for template in templates:
        row = {
            'template': template,
            'is_selected': bool(selected_template and template.id == selected_template.id),
        }
        group_label = _template_group_label(template.template_key)
        if 'payment_' in template.template_key:
            group_label = 'Payment SMS'
        grouped_map.setdefault(group_label, []).append(row)

    for label in group_order:
        rows = grouped_map.get(label) or []
        if rows:
            grouped_template_rows.append({'label': label, 'rows': rows})

    return render(request, 'dashboard_sms_template_center.html', {
        'site_settings': SiteSettings.objects.first(),
        'grouped_template_rows': grouped_template_rows,
        'selected_template': selected_template,
        'default_template': defaults_map.get(selected_template.template_key, {}) if selected_template else {},
        'current_filters': {'event': ''},
        'template_seed_ok': True,
    })


@dashboard_permission_required('payments')
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


@dashboard_permission_required('participants')
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


@dashboard_permission_required('dashboard')
def dashboard_journey_lookup(request):
    from website.models import SiteSettings

    search_query = (request.GET.get('q') or '').strip()
    selected_candidate_key = (request.GET.get('candidate') or '').strip()
    candidates = _journey_candidates(search_query) if search_query else []
    selected_candidates = _select_journey_candidates(candidates, selected_candidate_key)
    records = [_build_journey_record(candidate) for candidate in selected_candidates]
    context = {
        'site_settings': SiteSettings.objects.first(),
        'search_query': search_query,
        'selected_candidate_key': selected_candidate_key,
        'journey_records': records,
        'result_count': len(records),
        'candidate_count': len(candidates),
        'needs_candidate_selection': bool(search_query and not selected_candidates and len(candidates) > 1),
        'current_filters': {'q': search_query, 'event': ''},
    }
    return render(request, 'dashboard_journey_lookup.html', context)


@dashboard_permission_required('dashboard')
def dashboard_journey_lookup_search(request):
    search_query = (request.GET.get('q') or '').strip()
    candidates = _journey_candidates(search_query) if len(search_query) >= 2 else []
    return render(request, 'partials/dashboard_journey_lookup_search_results.html', {
        'search_query': search_query,
        'candidate_results': candidates[:8],
    })


@dashboard_permission_required('staff_activity')
def dashboard_staff_activity(request):
    activity_page_number = request.GET.get('activity_page')
    activity_filters = get_staff_activity_filters(request)
    query_params = staff_activity_query_params(request, activity_filters)

    if request.GET.get('export') == 'csv':
        timestamp = timezone.localtime().strftime('%Y%m%d_%H%M')
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="staff_activity_{timestamp}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Time', 'Staff', 'Action', 'Model', 'Record', 'Change', 'Admin URL'])
        for entry in staff_activity_queryset(activity_filters)[:5000]:
            row = staff_activity_row(entry)
            writer.writerow([
                timezone.localtime(row['time']).strftime('%Y-%m-%d %H:%M:%S'),
                row['staff'],
                row['action'],
                row['model'],
                row['object'],
                row['message'] or '',
                request.build_absolute_uri(row['detail_url']) if row['detail_url'] else '',
            ])
        return response

    return render(request, 'partials/dashboard_staff_activity.html', {
        'staff_activity_page_obj': build_staff_activity(activity_page_number, filters=activity_filters),
        'activity_query_string': urlencode(query_params),
        'activity_filter_context': staff_activity_filter_context(activity_filters),
        'current_filters': {
            'event': request.GET.get('event'),
            'event_status': request.GET.get('event_status'),
        },
    })


@dashboard_permission_required('program')
def dashboard_program_session_builder(request):
    from website.models import SiteSettings

    active_builder_events = Event.objects.filter(event_status='active').order_by('-year', 'name')
    selected_event = None
    event_id = request.POST.get('event') if request.method == 'POST' else request.GET.get('event')
    if event_id:
        selected_event = active_builder_events.filter(pk=event_id).first()

    program_days = ProgramDay.objects.none()
    hall_rooms = HallRoom.objects.none()
    time_slots = TimeSlot.objects.none()
    if selected_event:
        program_days = ProgramDay.objects.filter(event=selected_event).order_by('date', 'name')
        hall_rooms = HallRoom.objects.filter(event=selected_event).order_by('name')
        time_slots = TimeSlot.objects.filter(event=selected_event).select_related(
            'program_day',
            'hall_room',
        ).prefetch_related(
            'talk_slots',
            'program_sessions__faculty_roles__person',
            'program_sessions__items__faculty_roles__person',
            'program_sessions__items__abstract_submission',
            'program_sessions__items__talk_slot',
        ).order_by('program_day__date', 'start_time')

    setup_status = {
        'has_event': bool(selected_event),
        'has_program_days': program_days.exists(),
        'has_hall_rooms': hall_rooms.exists(),
        'has_time_slots': time_slots.filter(slot_type=TimeSlot.SLOT_SESSION).exists(),
    }
    setup_complete = all(setup_status.values())

    day_form = ProgramDayQuickCreateForm()
    day_edit_form = None
    editing_day = None
    hall_form = HallRoomQuickCreateForm()
    hall_edit_form = None
    editing_room = None
    slot_form = TimeSlotQuickCreateForm(event=selected_event)
    slot_edit_form = None
    editing_slot = None
    slot_generator_form = TimeSlotGeneratorForm(event=selected_event)
    generated_slot_formset = GeneratedTimeSlotPreviewFormSet(prefix='generated')
    generated_slot_scope = {}
    generated_slot_warnings = []
    generated_preview_open = False
    person_form = ProgramPersonQuickCreateForm(initial={'country': 'Bangladesh'})
    event_program_people = ProgramPerson.objects.none()
    assigned_event_program_people = ProgramPerson.objects.none()
    program_email_people = []
    if selected_event:
        event_program_people = event_program_people_for(selected_event)
        assigned_event_program_people = ProgramPerson.objects.filter(
            Q(session_roles__session__event=selected_event)
            | Q(item_roles__item__session__event=selected_event)
        ).distinct().order_by('name')
        program_email_log_map = {
            log.person_id: log
            for log in ProgramPersonEmailLog.objects.filter(
                event=selected_event,
                person__in=assigned_event_program_people,
            )
        }
        for person in assigned_event_program_people:
            assignments = build_program_assignment_summary(person, event=selected_event)
            email_log = program_email_log_map.get(person.id)
            program_email_people.append({
                'person': person,
                'assignments': assignments,
                'session_count': len(assignments),
                'talk_count': count_program_assignment_talks(assignments),
                'is_sendable': bool(person.email and assignments),
                'email_log': email_log,
                'email_sent': bool(email_log and email_log.last_sent_at),
            })
    program_email_sendable_count = sum(
        candidate['is_sendable']
        for candidate in program_email_people
    )
    program_email_sent_count = sum(
        candidate['email_sent']
        for candidate in program_email_people
    )
    program_email_missing_email_count = sum(
        not candidate['person'].email
        for candidate in program_email_people
    )
    profile_search_query = (request.GET.get('profile_query') or '').strip()
    profile_search_results = UserProfile.objects.none()
    if len(profile_search_query) >= 2:
        profile_search_results = UserProfile.objects.select_related('user').filter(
            Q(name__icontains=profile_search_query)
            | Q(email__icontains=profile_search_query)
            | Q(user__email__icontains=profile_search_query)
        ).order_by('name')[:8]

    def collect_generated_slot_warnings(program_day, hall_room, slots):
        if not program_day or not hall_room:
            return []

        warnings = []
        stored_slots = TimeSlot.objects.filter(
            event=selected_event,
            program_day=program_day,
            hall_room=hall_room,
        ).order_by('start_time', 'end_time')
        for slot in slots:
            start_time = slot.get('start_time')
            end_time = slot.get('end_time')
            if not start_time or not end_time:
                continue
            exact_match = stored_slots.filter(
                start_time=start_time,
                end_time=end_time,
            ).first()
            overlapping_slot = stored_slots.filter(
                start_time__lt=end_time,
                end_time__gt=start_time,
            ).exclude(pk=exact_match.pk if exact_match else None).first()
            if exact_match:
                warnings.append({
                    'kind': 'duplicate',
                    'start_time': start_time,
                    'end_time': end_time,
                    'stored_slot': exact_match,
                })
            elif overlapping_slot:
                warnings.append({
                    'kind': 'overlap',
                    'start_time': start_time,
                    'end_time': end_time,
                    'stored_slot': overlapping_slot,
                })
        return warnings

    def create_talk_slots(parent_slot, talk_slot_minutes):
        if parent_slot.slot_type != TimeSlot.SLOT_SESSION or not talk_slot_minutes:
            return

        start_at = datetime.combine(parent_slot.program_day.date, parent_slot.start_time)
        end_at = datetime.combine(parent_slot.program_day.date, parent_slot.end_time)
        duration = timedelta(minutes=talk_slot_minutes)
        talk_slots = []
        order = 1
        while start_at < end_at and len(talk_slots) < 240:
            next_end = min(start_at + duration, end_at)
            talk_slots.append(ProgramTalkSlot(
                time_slot=parent_slot,
                start_time=start_at.time(),
                end_time=next_end.time(),
                order=order,
            ))
            start_at = next_end
            order += 1
        ProgramTalkSlot.objects.bulk_create(talk_slots, ignore_conflicts=True)

    generated_preview_session_key = 'program_session_builder_generated_slot_preview'

    if request.method == 'GET' and selected_event:
        preview_state = request.session.pop(generated_preview_session_key, None)
        if preview_state and preview_state.get('event_id') == selected_event.id:
            preview_program_day = ProgramDay.objects.filter(
                pk=preview_state.get('program_day_id'),
                event=selected_event,
            ).first()
            preview_hall_room = HallRoom.objects.filter(
                pk=preview_state.get('hall_room_id'),
                event=selected_event,
            ).first()
            if preview_program_day and preview_hall_room:
                generated_initial = []
                for slot in preview_state.get('slots') or []:
                    try:
                        generated_initial.append({
                            'start_time': datetime.strptime(slot['start_time'], '%H:%M:%S').time(),
                            'end_time': datetime.strptime(slot['end_time'], '%H:%M:%S').time(),
                            'slot_type': slot['slot_type'],
                            'talk_slot_minutes': slot.get('talk_slot_minutes'),
                        })
                    except (KeyError, TypeError, ValueError):
                        continue
                generated_slot_formset = GeneratedTimeSlotPreviewFormSet(
                    initial=generated_initial,
                    prefix='generated',
                )
                generated_slot_scope = {
                    'program_day': preview_program_day,
                    'hall_room': preview_hall_room,
                }
                generated_slot_warnings = collect_generated_slot_warnings(
                    preview_program_day,
                    preview_hall_room,
                    generated_initial,
                )
                generated_preview_open = True

    if request.method == 'POST':
        setup_action = request.POST.get('setup_action')

        if setup_action:
            if not selected_event:
                messages.error(request, 'Choose an event before adding setup details.')
                return redirect('dashboard_program_session_builder')

            if setup_action == 'add_day':
                day_form = ProgramDayQuickCreateForm(request.POST)
                if day_form.is_valid():
                    duplicate_day = ProgramDay.objects.filter(
                        event=selected_event,
                        name__iexact=day_form.cleaned_data['name'],
                        date=day_form.cleaned_data['date'],
                    ).exists()
                    if duplicate_day:
                        day_form.add_error(None, 'This program day name and date already exist for the selected event.')
                    else:
                        program_day = day_form.save(commit=False)
                        program_day.event = selected_event
                        program_day.save()
                        dashboard_log_action(request, program_day, ADDITION, 'Added program day from Program builder dashboard.')
                        messages.success(request, f'Program day "{program_day.name}" added.')
                        return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'edit_day':
                editing_day = ProgramDay.objects.filter(
                    pk=request.POST.get('program_day_id'),
                    event=selected_event,
                ).first()
                if not editing_day:
                    messages.error(request, 'Choose a valid program day to edit.')
                else:
                    day_edit_form = ProgramDayQuickCreateForm(request.POST, instance=editing_day)
                    if day_edit_form.is_valid():
                        duplicate_day = ProgramDay.objects.filter(
                            event=selected_event,
                            name__iexact=day_edit_form.cleaned_data['name'],
                            date=day_edit_form.cleaned_data['date'],
                        ).exclude(pk=editing_day.pk).exists()
                        if duplicate_day:
                            day_edit_form.add_error(None, 'Another program day already uses this name and date.')
                        else:
                            program_day = day_edit_form.save()
                            dashboard_log_action(request, program_day, CHANGE, 'Updated program day from Program builder dashboard.')
                            messages.success(request, f'Program day "{program_day.name}" updated.')
                            return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'delete_day':
                deleting_day = ProgramDay.objects.filter(
                    pk=request.POST.get('program_day_id'),
                    event=selected_event,
                ).first()
                if not deleting_day:
                    messages.error(request, 'Choose a valid program day to remove.')
                elif TimeSlot.objects.filter(program_day=deleting_day).exists() or ProgramSession.objects.filter(program_day=deleting_day).exists():
                    messages.error(request, 'This program day already has slots or sessions. Edit it instead, or clear those schedule records first.')
                else:
                    dashboard_log_action(request, deleting_day, DELETION, 'Removed program day from Program builder dashboard.')
                    day_name = deleting_day.name
                    deleting_day.delete()
                    messages.success(request, f'Program day "{day_name}" removed.')
                return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'add_room':
                hall_form = HallRoomQuickCreateForm(request.POST)
                if hall_form.is_valid():
                    duplicate_room = HallRoom.objects.filter(
                        event=selected_event,
                        name__iexact=hall_form.cleaned_data['name'],
                    ).exists()
                    if duplicate_room:
                        hall_form.add_error(None, 'This hall room name already exists for the selected event.')
                    else:
                        hall_room = hall_form.save(commit=False)
                        hall_room.event = selected_event
                        hall_room.location = (selected_event.location or selected_event.name)[:50]
                        hall_room.save()
                        dashboard_log_action(request, hall_room, ADDITION, 'Added hall room from Program builder dashboard.')
                        messages.success(request, f'Hall room "{hall_room.name}" added.')
                        return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'edit_room':
                editing_room = HallRoom.objects.filter(
                    pk=request.POST.get('hall_room_id'),
                    event=selected_event,
                ).first()
                if not editing_room:
                    messages.error(request, 'Choose a valid hall room to edit.')
                else:
                    hall_edit_form = HallRoomQuickCreateForm(request.POST, instance=editing_room)
                    if hall_edit_form.is_valid():
                        duplicate_room = HallRoom.objects.filter(
                            event=selected_event,
                            name__iexact=hall_edit_form.cleaned_data['name'],
                        ).exclude(pk=editing_room.pk).exists()
                        if duplicate_room:
                            hall_edit_form.add_error(None, 'Another hall room already uses this name.')
                        else:
                            hall_room = hall_edit_form.save()
                            dashboard_log_action(request, hall_room, CHANGE, 'Updated hall room from Program builder dashboard.')
                            messages.success(request, f'Hall room "{hall_room.name}" updated.')
                            return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'delete_room':
                deleting_room = HallRoom.objects.filter(
                    pk=request.POST.get('hall_room_id'),
                    event=selected_event,
                ).first()
                if not deleting_room:
                    messages.error(request, 'Choose a valid hall room to remove.')
                elif TimeSlot.objects.filter(hall_room=deleting_room).exists() or ProgramSession.objects.filter(hall_room=deleting_room).exists():
                    messages.error(request, 'This hall room already has slots or sessions. Edit it instead, or clear those schedule records first.')
                else:
                    dashboard_log_action(request, deleting_room, DELETION, 'Removed hall room from Program builder dashboard.')
                    room_name = deleting_room.name
                    deleting_room.delete()
                    messages.success(request, f'Hall room "{room_name}" removed.')
                return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'add_slot':
                slot_form = TimeSlotQuickCreateForm(request.POST, event=selected_event)
                if slot_form.is_valid():
                    time_slot = slot_form.save(commit=False)
                    time_slot.event = selected_event
                    try:
                        time_slot.full_clean()
                    except ValidationError as exc:
                        slot_form.add_error(None, exc)
                    else:
                        time_slot.save()
                        dashboard_log_action(request, time_slot, ADDITION, 'Added time slot from Program builder dashboard.')
                        messages.success(request, f'Time slot "{time_slot}" added.')
                        return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'edit_slot':
                editing_slot = TimeSlot.objects.filter(
                    pk=request.POST.get('slot_id'),
                    event=selected_event,
                ).first()
                if not editing_slot:
                    messages.error(request, 'Choose a valid event time slot to edit.')
                else:
                    slot_edit_form = TimeSlotQuickCreateForm(
                        request.POST,
                        instance=editing_slot,
                        event=selected_event,
                    )
                    if slot_edit_form.is_valid():
                        time_slot = slot_edit_form.save(commit=False)
                        time_slot.event = selected_event
                        try:
                            time_slot.full_clean()
                        except ValidationError as exc:
                            slot_edit_form.add_error(None, exc)
                        else:
                            time_slot.save()
                            dashboard_log_action(request, time_slot, CHANGE, 'Updated time slot from Program builder dashboard.')
                            messages.success(request, f'Time slot "{time_slot}" updated.')
                            return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'generate_slots':
                slot_generator_form = TimeSlotGeneratorForm(request.POST, event=selected_event)
                if slot_generator_form.is_valid():
                    start_at = datetime.combine(slot_generator_form.cleaned_data['program_day'].date, slot_generator_form.cleaned_data['start_time'])
                    end_at = datetime.combine(slot_generator_form.cleaned_data['program_day'].date, slot_generator_form.cleaned_data['end_time'])
                    duration = timedelta(minutes=slot_generator_form.cleaned_data['slot_minutes'])
                    generated_initial = []
                    while start_at < end_at and len(generated_initial) < 240:
                        next_end = min(start_at + duration, end_at)
                        generated_initial.append({
                            'start_time': start_at.time(),
                            'end_time': next_end.time(),
                            'slot_type': TimeSlot.SLOT_SESSION,
                            'talk_slot_minutes': slot_generator_form.cleaned_data.get('talk_slot_minutes'),
                        })
                        start_at = next_end
                    generated_slot_formset = GeneratedTimeSlotPreviewFormSet(initial=generated_initial, prefix='generated')
                    generated_slot_scope = {
                        'program_day': slot_generator_form.cleaned_data['program_day'],
                        'hall_room': slot_generator_form.cleaned_data['hall_room'],
                    }
                    generated_slot_warnings = collect_generated_slot_warnings(
                        generated_slot_scope['program_day'],
                        generated_slot_scope['hall_room'],
                        generated_initial,
                    )
                    request.session[generated_preview_session_key] = {
                        'event_id': selected_event.id,
                        'program_day_id': generated_slot_scope['program_day'].id,
                        'hall_room_id': generated_slot_scope['hall_room'].id,
                        'slots': [
                            {
                                'start_time': slot['start_time'].isoformat(),
                                'end_time': slot['end_time'].isoformat(),
                                'slot_type': slot['slot_type'],
                                'talk_slot_minutes': slot.get('talk_slot_minutes'),
                            }
                            for slot in generated_initial
                        ],
                    }
                    return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'save_generated_slots':
                program_day = ProgramDay.objects.filter(
                    pk=request.POST.get('generated_program_day'),
                    event=selected_event,
                ).first()
                hall_room = HallRoom.objects.filter(
                    pk=request.POST.get('generated_hall_room'),
                    event=selected_event,
                ).first()
                generated_slot_formset = GeneratedTimeSlotPreviewFormSet(request.POST, prefix='generated')
                generated_slot_scope = {'program_day': program_day, 'hall_room': hall_room}
                generated_preview_open = True

                if not program_day or not hall_room:
                    messages.error(request, 'Choose a valid program day and hall room before saving generated slots.')
                elif generated_slot_formset.is_valid():
                    generated_slot_warnings = collect_generated_slot_warnings(
                        program_day,
                        hall_room,
                        [
                            form.cleaned_data
                            for form in generated_slot_formset
                            if not form.cleaned_data.get('DELETE')
                        ],
                    )
                    pending_slots = []
                    for form in generated_slot_formset:
                        if form.cleaned_data.get('DELETE'):
                            continue
                        time_slot = TimeSlot(
                            event=selected_event,
                            program_day=program_day,
                            hall_room=hall_room,
                            start_time=form.cleaned_data['start_time'],
                            end_time=form.cleaned_data['end_time'],
                            slot_type=form.cleaned_data['slot_type'],
                            label=form.cleaned_data.get('label'),
                        )
                        try:
                            time_slot.full_clean()
                        except ValidationError as exc:
                            form.add_error(None, exc)
                        else:
                            pending_slots.append((time_slot, form.cleaned_data.get('talk_slot_minutes')))

                    if pending_slots and not any(form.errors for form in generated_slot_formset):
                        with transaction.atomic():
                            for time_slot, talk_slot_minutes in pending_slots:
                                time_slot.save()
                                create_talk_slots(time_slot, talk_slot_minutes)
                                dashboard_log_action(request, time_slot, ADDITION, 'Generated time slot from Program builder dashboard.')
                        messages.success(request, f'{len(pending_slots)} generated time slot(s) saved.')
                        return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
                    if not pending_slots and not any(form.errors for form in generated_slot_formset):
                        messages.info(request, 'No generated time slots were selected to save.')
            elif setup_action == 'add_person':
                person_form = ProgramPersonQuickCreateForm(request.POST)
                if person_form.is_valid():
                    person = person_form.save()
                    person.events.add(selected_event)
                    dashboard_log_action(request, person, ADDITION, f'Added program person to {selected_event.name} from Program builder dashboard.')
                    messages.success(request, f'Program person "{person.name}" added to {selected_event.name}.')
                    return redirect(
                        f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}&program_person_modal=1"
                    )
            elif setup_action == 'add_profile_person':
                profile = UserProfile.objects.filter(pk=request.POST.get('profile_id')).first()
                if not profile:
                    messages.error(request, 'Choose a valid website profile to add as a program person.')
                else:
                    person, created, error = add_profile_to_program_person(profile)
                    if error:
                        messages.error(request, error)
                    elif person:
                        person.events.add(selected_event)
                        action = 'added from profile' if created else 'ready from profile'
                        dashboard_log_action(request, person, ADDITION if created else CHANGE, f'Added profile-linked program person to {selected_event.name} from Program builder dashboard.')
                        messages.success(request, f'Program person "{person.name}" is {action} for {selected_event.name}.')
                        return redirect(
                            f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}&program_person_modal=1"
                        )
            elif setup_action == 'remove_person':
                removing_person = ProgramPerson.objects.filter(
                    pk=request.POST.get('program_person_id'),
                ).first()
                if not removing_person:
                    messages.error(request, 'Choose a valid program person to remove from this event.')
                else:
                    removed_roles = remove_program_person_from_event(removing_person, selected_event)
                    if removed_roles:
                        dashboard_log_action(request, removing_person, CHANGE, f'Removed program person roles from {selected_event.name} in Program builder dashboard.')
                        messages.success(
                            request,
                            f'{removing_person.name} removed from {selected_event.name} program roles. '
                            'The reusable program person record is still available.',
                        )
                    else:
                        messages.info(request, f'{removing_person.name} has no program role in {selected_event.name}.')
                return redirect(
                    f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}&program_person_modal=1"
                )
            elif setup_action == 'send_program_person_emails':
                recipient_ids = request.POST.getlist('program_person_ids')
                recipients = ProgramPerson.objects.filter(
                    pk__in=recipient_ids,
                ).filter(
                    Q(session_roles__session__event=selected_event)
                    | Q(item_roles__item__session__event=selected_event)
                ).distinct()
                sent_count = 0
                missing_email_count = 0
                missing_assignment_count = 0
                failed_count = 0

                if not recipient_ids:
                    messages.warning(request, 'Choose at least one program person with event details before sending email.')
                for person in recipients:
                    try:
                        sent, reason = send_program_assignment_email(person, event=selected_event)
                    except Exception as exc:
                        failed_count += 1
                        messages.error(request, f'Program email failed for {person.name}: {exc}')
                    else:
                        if sent:
                            sent_count += 1
                            email_log, _ = ProgramPersonEmailLog.objects.get_or_create(
                                event=selected_event,
                                person=person,
                            )
                            email_log.last_sent_at = timezone.now()
                            email_log.last_sent_by = request.user
                            email_log.send_count = (email_log.send_count or 0) + 1
                            email_log.last_session_count = len(reason)
                            email_log.last_talk_count = count_program_assignment_talks(reason)
                            email_log.save(update_fields=[
                                'last_sent_at',
                                'last_sent_by',
                                'send_count',
                                'last_session_count',
                                'last_talk_count',
                            ])
                        elif reason == 'missing_email':
                            missing_email_count += 1
                        else:
                            missing_assignment_count += 1

                if sent_count:
                    dashboard_log_action(request, selected_event, CHANGE, f'Sent program details email to {sent_count} program person(s) from Program builder dashboard.')
                    messages.success(request, f'Program details email sent to {sent_count} person(s) for {selected_event.name}.')
                if missing_email_count:
                    messages.warning(request, f'{missing_email_count} selected program person(s) were skipped because email is missing.')
                if missing_assignment_count:
                    messages.warning(request, f'{missing_assignment_count} selected program person(s) were skipped because this event has no program participation detail for them.')
                if failed_count:
                    messages.error(request, f'{failed_count} program details email(s) failed.')
                return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")
            elif setup_action == 'delete_session':
                session_id = request.POST.get('session_id')
                if session_id:
                    deleting_session = ProgramSession.objects.filter(pk=session_id, event=selected_event).first()
                    if deleting_session:
                        dashboard_log_action(request, deleting_session, DELETION, 'Deleted program session from Program builder dashboard.')
                        deleting_session.delete()
                    messages.success(request, 'Program session successfully deleted.')
                return redirect(f"{reverse('dashboard_program_session_builder')}?event={selected_event.id}")

            initial = {'event': selected_event} if selected_event else None
            session_form = ProgramSessionBuilderForm(initial=initial, event=selected_event)
            item_formset = ProgramSessionItemBuilderFormSet(
                prefix='items',
                form_kwargs={'event': selected_event},
            )
        else:
            session_id = request.POST.get('session_id')
            session_instance = None
            if session_id:
                session_instance = ProgramSession.objects.filter(pk=session_id, event=selected_event).first()

            session_form = ProgramSessionBuilderForm(request.POST, instance=session_instance, event=selected_event)
            item_formset = ProgramSessionItemBuilderFormSet(
                request.POST,
                prefix='items',
                form_kwargs={'event': selected_event},
            )

            if not selected_event:
                session_form.add_error('event', 'Choose an event before creating a program session.')
            if selected_event and not setup_complete:
                session_form.add_error(None, 'Complete program day, hall room, and time slot setup before creating a session.')

            session_valid = session_form.is_valid()
            items_valid = item_formset.is_valid()
            if session_valid and items_valid:
                parent_time_slot = session_form.cleaned_data.get('time_slot')
                for form in item_formset:
                    talk_slot = form.cleaned_data.get('talk_slot')
                    if talk_slot and (not parent_time_slot or talk_slot.time_slot_id != parent_time_slot.id):
                        form.add_error('talk_slot', 'Choose a talk slot inside this session time slot.')
                items_valid = not any(form.errors for form in item_formset)

            if session_valid and items_valid:
                selected_people = set()
                for field_name in ('chairpersons', 'moderators', 'panelists'):
                    selected_people.update(
                        person.id
                        for person in session_form.cleaned_data.get(field_name) or []
                    )
                for form in item_formset:
                    if not form.cleaned_data.get('title') and not form.cleaned_data.get('abstract_submission'):
                        continue
                    selected_people.update(
                        person.id
                        for person in form.cleaned_data.get('speakers') or []
                    )
                    selected_people.update(
                        person.id
                        for person in form.cleaned_data.get('presenters') or []
                    )

                parallel_conflicts = session_form.instance.conflicting_parallel_people(selected_people)
                if parallel_conflicts:
                    people_by_id = {
                        person.id: person
                        for person in ProgramPerson.objects.filter(pk__in=parallel_conflicts)
                    }
                    for person_id, sessions in parallel_conflicts.items():
                        person = people_by_id.get(person_id)
                        session_labels = ', '.join(
                            f'"{session.title}" in {session.hall_room.name if session.hall_room else "another hall"}'
                            for session in sessions
                        )
                        session_form.add_error(
                            None,
                            f'Scheduling conflict: {person.name if person else "A selected person"} is already assigned to {session_labels} during this parallel time window.',
                        )
                    session_valid = False

            if session_valid and items_valid:
                with transaction.atomic():
                    session = session_form.save()

                    if session_instance:
                        ProgramSessionFaculty.objects.filter(session=session).delete()
                        ProgramSessionItem.objects.filter(session=session).delete()

                    role_map = [
                        (ProgramSessionFaculty.ROLE_CHAIRPERSON, session_form.cleaned_data.get('chairpersons')),
                        (ProgramSessionFaculty.ROLE_MODERATOR, session_form.cleaned_data.get('moderators')),
                        (ProgramSessionFaculty.ROLE_PANELIST, session_form.cleaned_data.get('panelists')),
                    ]
                    for role, people in role_map:
                        for order, person in enumerate(people or [], start=1):
                            ProgramSessionFaculty.objects.create(
                                session=session,
                                person=person,
                                role=role,
                                order=order,
                            )

                    item_count = 0
                    for form in item_formset:
                        if not form.cleaned_data.get('title') and not form.cleaned_data.get('abstract_submission'):
                            continue
                        item = ProgramSessionItem.objects.create(
                            session=session,
                            talk_slot=form.cleaned_data.get('talk_slot'),
                            abstract_submission=form.cleaned_data.get('abstract_submission'),
                            title=form.cleaned_data.get('title'),
                            start_time=form.cleaned_data.get('start_time'),
                            end_time=form.cleaned_data.get('end_time'),
                            order=form.cleaned_data.get('order') or item_count + 1,
                        )
                        for order, person in enumerate(form.cleaned_data.get('speakers') or [], start=1):
                            ProgramItemFaculty.objects.create(
                                item=item,
                                person=person,
                                role=ProgramItemFaculty.ROLE_SPEAKER,
                                order=order,
                            )
                        for order, person in enumerate(form.cleaned_data.get('presenters') or [], start=1):
                            ProgramItemFaculty.objects.create(
                                item=item,
                                person=person,
                                role=ProgramItemFaculty.ROLE_PRESENTER,
                                order=order,
                            )
                        item_count += 1

                action_label = 'updated' if session_instance else 'created'
                dashboard_log_action(
                    request,
                    session,
                    CHANGE if session_instance else ADDITION,
                    f'Program session {action_label} from Program builder dashboard with {item_count} item(s).',
                )
                messages.success(request, f'Program session "{session.title}" {action_label} with {item_count} item(s).')
                return redirect(f"{reverse('dashboard_program_session_builder')}?event={session.event_id}")
    else:
        initial = {'event': selected_event} if selected_event else None
        session_form = ProgramSessionBuilderForm(initial=initial, event=selected_event)
        item_formset = ProgramSessionItemBuilderFormSet(
            prefix='items',
            form_kwargs={'event': selected_event},
        )

    recent_sessions = ProgramSession.objects.select_related(
        'event',
        'program_day',
        'hall_room',
    ).prefetch_related(
        'faculty_roles__person',
        'items__faculty_roles__person',
        'items__abstract_submission',
        'items__talk_slot',
        'time_slot__talk_slots',
    )
    if selected_event:
        recent_sessions = recent_sessions.filter(event=selected_event)
    recent_sessions = recent_sessions.order_by('-id')[:8]

    return render(request, 'dashboard_program_session_builder.html', {
        'site_settings': SiteSettings.objects.first(),
        'session_form': session_form,
        'item_formset': item_formset,
        'selected_event': selected_event,
        'events': active_builder_events,
        'people_count': ProgramPerson.objects.count(),
        'event_program_people': event_program_people,
        'assigned_event_program_people': assigned_event_program_people,
        'recent_sessions': recent_sessions,
        'program_days': program_days,
        'hall_rooms': hall_rooms,
        'time_slots': time_slots,
        'time_slot_type_choices': TimeSlot.SLOT_TYPE_CHOICES,
        'setup_status': setup_status,
        'setup_complete': setup_complete,
        'day_form': day_form,
        'day_edit_form': day_edit_form,
        'editing_day': editing_day,
        'hall_form': hall_form,
        'hall_edit_form': hall_edit_form,
        'editing_room': editing_room,
        'slot_form': slot_form,
        'slot_edit_form': slot_edit_form,
        'editing_slot': editing_slot,
        'slot_generator_form': slot_generator_form,
        'generated_slot_formset': generated_slot_formset,
        'generated_slot_scope': generated_slot_scope,
        'generated_slot_warnings': generated_slot_warnings,
        'generated_preview_open': generated_preview_open,
        'person_form': person_form,
        'program_email_people': program_email_people,
        'program_email_sendable_count': program_email_sendable_count,
        'program_email_sent_count': program_email_sent_count,
        'program_email_missing_email_count': program_email_missing_email_count,
        'profile_search_query': profile_search_query,
        'profile_search_results': profile_search_results,
    })


def event_program_people_for(event):
    if not event:
        return ProgramPerson.objects.none()
    return ProgramPerson.objects.filter(events=event).distinct().order_by('name')


def remove_program_person_from_event(person, event):
    was_available_in_event = person.events.filter(pk=event.pk).exists()
    session_role_count, _ = ProgramSessionFaculty.objects.filter(
        person=person,
        session__event=event,
    ).delete()
    item_role_count, _ = ProgramItemFaculty.objects.filter(
        person=person,
        item__session__event=event,
    ).delete()
    person.events.remove(event)
    return session_role_count + item_role_count + int(was_available_in_event)


def add_profile_to_program_person(profile):
    person = ProgramPerson.objects.filter(profile=profile).first()
    created = False
    if person:
        return person, created, None

    person = ProgramPerson.objects.filter(email__iexact=profile.email).first()
    if person and person.profile_id and person.profile_id != profile.id:
        return None, created, 'Another website profile is already linked to the matching program person.'
    if person:
        person.profile = profile
        update_fields = ['profile']
        for field_name in ('name', 'email', 'phone', 'country'):
            if not getattr(person, field_name):
                setattr(person, field_name, getattr(profile, field_name))
                update_fields.append(field_name)
        person.save(update_fields=update_fields)
        return person, created, None

    person = ProgramPerson.objects.create(
        profile=profile,
        name=profile.name,
        email=profile.email,
        phone=profile.phone,
        country=profile.country or 'Bangladesh',
    )
    return person, True, None


@dashboard_permission_required('program')
def dashboard_program_profile_search(request):
    selected_event = Event.objects.filter(pk=request.GET.get('event')).first()
    profile_search_query = (request.GET.get('profile_query') or '').strip()
    profile_search_results = UserProfile.objects.none()
    if len(profile_search_query) >= 2:
        profile_search_results = UserProfile.objects.select_related('user').filter(
            Q(name__icontains=profile_search_query)
            | Q(email__icontains=profile_search_query)
            | Q(user__email__icontains=profile_search_query)
        ).order_by('name')[:8]
    return render(request, 'partials/dashboard_program_profile_search_results.html', {
        'selected_event': selected_event,
        'profile_search_query': profile_search_query,
        'profile_search_results': profile_search_results,
    })


@dashboard_permission_required('program')
def dashboard_program_profile_add(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    selected_event = Event.objects.filter(pk=request.POST.get('event')).first()
    profile_search_query = (request.POST.get('profile_query') or '').strip()
    profile = UserProfile.objects.filter(pk=request.POST.get('profile_id')).first()
    profile_add_message = None
    profile_add_error = None
    person = None
    error = None
    if not profile:
        profile_add_error = 'Choose a valid website profile to add as a program person.'
    else:
        person, created, error = add_profile_to_program_person(profile)
        if error:
            profile_add_error = error
        else:
            if selected_event:
                person.events.add(selected_event)
            action = 'added to' if created else 'already ready in'
            event_suffix = f' for {selected_event.name}' if selected_event else ''
            profile_add_message = f'{person.name} is {action} the program person library{event_suffix}.'

    profile_search_results = UserProfile.objects.none()
    if len(profile_search_query) >= 2:
        profile_search_results = UserProfile.objects.select_related('user').filter(
            Q(name__icontains=profile_search_query)
            | Q(email__icontains=profile_search_query)
            | Q(user__email__icontains=profile_search_query)
        ).order_by('name')[:8]
    response = render(request, 'partials/dashboard_program_profile_search_results.html', {
        'selected_event': selected_event,
        'profile_search_query': profile_search_query,
        'profile_search_results': profile_search_results,
        'profile_add_message': profile_add_message,
        'profile_add_error': profile_add_error,
        'event_program_people': event_program_people_for(selected_event),
        'program_people_oob': bool(selected_event and person and not error),
        'program_person_remove_oob': bool(selected_event and person and not error),
    })
    if selected_event and person and not error:
        response['HX-Trigger'] = json.dumps({
            'programPersonAdded': {
                'id': str(person.id),
                'label': str(person),
            }
        })
    return response


@dashboard_permission_required('program')
def dashboard_program_person_remove(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    selected_event = Event.objects.filter(pk=request.POST.get('event')).first()
    person = ProgramPerson.objects.filter(pk=request.POST.get('program_person_id')).first()
    remove_message = None
    remove_error = None
    if not selected_event:
        remove_error = 'Choose a valid event before removing a program person.'
    elif not person:
        remove_error = 'Choose a person who is currently in this event program.'
    else:
        removed_roles = remove_program_person_from_event(person, selected_event)
        if removed_roles:
            remove_message = (
                f'{person.name} was removed from {selected_event.name} program roles. '
                'The person record stays available for other events.'
            )
        else:
            remove_error = f'{person.name} is not attached to this event program.'

    return render(request, 'partials/dashboard_program_person_remove_panel.html', {
        'selected_event': selected_event,
        'event_program_people': event_program_people_for(selected_event),
        'program_person_remove_message': remove_message,
        'program_person_remove_error': remove_error,
        'program_people_oob': bool(selected_event and removed_roles) if selected_event and person else False,
    })


@dashboard_permission_required('dashboard')
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














