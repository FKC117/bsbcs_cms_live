from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .forms import RegistrationForm, AbstractSubmissionForm, UserProfileForm
from .models import *
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
import time
import json
import logging
from django.utils import timezone


# Payment logger (writes to payment.log via settings)
logger = logging.getLogger('payment')


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


# User Profile View STARTS ---------------------------------------------------------------###
def create_profile(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = UserProfileForm()
    return render(request, 'create_profile.html', {'form': form})

# User profile Views START-----------------------------------------------------###

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from .models import UserProfile, AbstractSubmission, ProgramSchedule, Event
from website.models import SiteSettings

@login_required
def user_profile(request):
    # Fetch the user's profile
    user_profile = get_object_or_404(UserProfile, user=request.user)

    # Fetch related submissions and schedules
    abstract_submissions = AbstractSubmission.objects.filter(user=request.user)
    program_schedules = ProgramSchedule.objects.filter(abstract_submission__in=abstract_submissions)

    # Fetch active, upcoming, and closed events
    active_events = Event.objects.filter(event_status='active').order_by('-start_date')
    upcoming_events = Event.objects.filter(event_status='upcoming').order_by('start_date')
    closed_events = Event.objects.filter(event_status='closed').order_by('-end_date')

    # Fetch payment Status for the user's in registered events
    payment_statuses = PaymentStatus.objects.filter(participant__user=request.user).select_related('event', 'participant')
    payment_data = []
    for payment in payment_statuses:
        payment_data.append({
            'event': f"{payment.event.name} {payment.event.year}",  # Assuming the event name and year are stored in the Event modelpayment.event.name,
            'trxID': payment.trxID,
            'amount': payment.event.amount,  # Assuming the event amount is stored in the Event model
            'status': payment.status,
            'updated_at': payment.updated_at,  # Assuming there's an updated_at field in PaymentStatus
        })

    if request.method == 'POST':
        user_profile.name = request.POST.get('name')
        user_profile.email = request.POST.get('email')
        user_profile.phone = request.POST.get('phone')
        user_profile.save()
        message = "Profile updated successfully"
    else:
        message = ""

    return render(request, 'user_profile.html', {
        'user': request.user,
        'user_profile': user_profile,
        'abstract_submissions': abstract_submissions,
        'program_schedules': program_schedules,
        'message': message,
        'active_events': active_events,
        'upcoming_events': upcoming_events,
        'closed_events': closed_events,
        'payment_data': payment_data,
        'site_settings': SiteSettings.objects.first(),
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

    context = {
        'user_profile': user_profile,
        'event': event,
        'speakers': speakers,
        'about_conference': about_conference,
        'invitations': invitations,
        'modal_image': modal_image_path,
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
    # Check if the user is authenticated
    if not request.user.is_authenticated:
        return render(request, 'registration_login_prompt.html', {
            'message': 'You need to log in to be able to register for this event.',
            'login_url': '/login/',  # Replace with your login URL name or path
            'signup_url': '/create_profile/'  # Replace with your signup URL name or path
        })

    event = get_object_or_404(Event, id=event_id)

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

    user_profile = UserProfile.objects.get(user=request.user)

    # Check if the user has already registered for the event
    try:
        participant = Participant.objects.get(user=request.user, event=event)
        return render(request, 'registration_error.html', {
            'message': 'You have already submitted your registration or already registered for this event. Please check your email for further details.',
            'event': event,
            'participant': participant
        })
    except Participant.DoesNotExist:
        pass  # User has not registered yet, proceed with registration 

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
                merchant_invoice_number = f"REG-{event.id}-{request.user.id}-{int(time.time())}"  # type: ignore[attr-defined]
                
                # Create payment status based on event payment requirement
                if event.payment_required and event.amount:
                    PaymentStatus.objects.create(
                        participant=participant, 
                        event=event, 
                        status='unpaid',
                        amount=event.amount,
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
                return redirect('registration:registration_submitted', event_id=event.id)  # type: ignore[attr-defined]
            except IntegrityError as e:
                logger.exception("IntegrityError: %s", e)  # Debugging line
                messages.error(request, 'A participant with this email or phone number already exists for this event.')
        else:
            messages.error(request, 'There are errors in your form. Registration failed. Please check the form.')
    else:
        form = RegistrationForm(initial=initial_data, event=event)

    return render(request, 'registration.html', {'form': form, 'event': event})

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
    payment_url = reverse('payment', kwargs={
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
            'login_url': '/login/',  # Replace with your login URL name or path
            'signup_url': '/create_profile/'  # Replace with your signup URL name or path
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

    if request.method == 'POST':
        try:
            # Step 1: Get token
            token = get_bkash_token()
            if not token:
                messages.error(request, "Failed to get token.")
                return redirect('index')

            # Step 2: Create payment
            amount = event.amount
            payer_reference = str(getattr(request.user.userprofile, 'phone', None))
            if not payer_reference:
                messages.error(request, "Phone number not found.")
                return redirect('index')

            merchant_invoice_number = f"INV-{event.id}-{request.user.id}-{int(time.time())}"  # type: ignore[attr-defined]
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

    return render(request, 'payment.html', {'participant': participant, 'event': event})

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
from registration.pdf_utils import generate_invoice
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
    participant_email = participant.email

    # Fetch the certificate template for the event
    event = get_object_or_404(Event, id=event_id)
    certificate = get_object_or_404(Certificate, event=event)  # Fetch certificate for the event
    template_path = certificate.upload_image.path  # Get the full path to the uploaded image

    # Define paths for font and output
    # TODO: The font path is hardcoded to a Linux path. This will not work on other systems.
    # Consider adding a font to the project and using a path relative to settings.BASE_DIR
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    output_filename = f"BBCC_Certificate_{participant_name.replace(' ', '_')}.jpg"
    output_path = os.path.join(settings.MEDIA_ROOT, 'certificates', output_filename)

    # Ensure the output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        # Load the image
        image = Image.open(template_path)
        draw = ImageDraw.Draw(image)

        # Define the font and size
        font_size = 40
        font = ImageFont.truetype(font_path, font_size)

        # Define the text and position
        text_position = (520, 470)  # Adjust the position as needed
        draw.text(text_position, participant_name, font=font, fill="black")

        # Save the modified image
        image.save(output_path)

        # Send the certificate via email
        email = EmailMessage(
            subject=f"Your Certificate for {event.name} {event.year}",
            body=f"Dear {participant_name},\n\nPlease find your certificate attached.\n\nBest regards,\nThe Event Team",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[participant_email],
        )
        email.attach_file(output_path)
        email.send()

        # Return success response
        return JsonResponse({
            'success': True,
            'message': 'Certificate has been sent to your email.',
        })

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
from django.db.models import Sum
from django.conf import settings
import os
import matplotlib
matplotlib.use('Agg')  # Set backend before importing pyplot
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from registration.models import Participant, PaymentStatus, Event
from datetime import datetime
from django.core.cache import cache
from django.core.paginator import Paginator
from urllib.parse import urlencode


def generate_chart(event_metrics):
    cache_key = f"chart_{hash(str(event_metrics))}"
    cached_chart = cache.get(cache_key)
    if cached_chart:
        return cached_chart
    if not event_metrics:
        return None

    try:
        df = pd.DataFrame(event_metrics)
        df = df.rename(columns={
            'approved_participants': 'Approved Participants',
            'pending_payments': 'Pending Payments',
            'revenue_collected': 'Revenue Collected'
        })

        df_melted = df.melt(
            id_vars=['name'],
            value_vars=['Approved Participants', 'Pending Payments'],
            var_name='Metric',
            value_name='Count'
        )

        plt.figure(figsize=(12, 7))
        sns.set_style("whitegrid")
        ax = sns.barplot(
            x='name',
            y='Count',
            hue='Metric',
            data=df_melted,
            palette="viridis"
        )
        plt.title('Event Metrics Comparison', fontsize=14)
        plt.xlabel('Events', fontsize=12)
        plt.ylabel('Count', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.legend(title='Metrics', bbox_to_anchor=(1.05, 1), loc='upper left')

        chart_dir = os.path.join(settings.MEDIA_ROOT, 'charts')
        os.makedirs(chart_dir, exist_ok=True)
        chart_filename = f'metrics_{datetime.now().timestamp()}.png'
        chart_path = os.path.join(chart_dir, chart_filename)

        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close()

        chart_url = f'charts/{chart_filename}'
        cache.set(cache_key, chart_url, timeout=3600)
        return chart_url

    except Exception as e:
        logger.exception("Chart Error: %s", e)
        return None


@staff_member_required
def global_dashboard(request):
    event_filter = request.GET.get('event')
    event_status_filter = request.GET.get('event_status')
    page_number = request.GET.get('page')
    event_page_number = request.GET.get('event_page')
    org_page_number = request.GET.get('org_page')

    events = Event.objects.all()
    if event_status_filter:
        events = events.filter(event_status=event_status_filter)

    event_metrics = []
    for event in events:
        if event_filter and str(event.id) != event_filter:  # type: ignore[attr-defined]
            continue
        metrics = {
            'name': event.name,
            'approved_participants': Participant.objects.filter(event=event).count(),
            'pending_payments': PaymentStatus.objects.filter(
                event=event, status__in=['unpaid', 'pending', 'failed', 'initiated']
            ).count(),
            'revenue_collected': PaymentStatus.objects.filter(
                event=event, status__in=['paid', 'completed']
            ).aggregate(total=Sum('amount'))['total'] or 0,
        }
        event_metrics.append(metrics)

    event_paginator = Paginator(event_metrics, 10)
    event_page_obj = event_paginator.get_page(event_page_number)
    chart_path = generate_chart(event_metrics.copy()) if event_metrics else None

    totals = {
        'participants': sum(m['approved_participants'] for m in event_metrics),
        'pending_payments': sum(m['pending_payments'] for m in event_metrics),
        'revenue': sum(m['revenue_collected'] for m in event_metrics)
    }

    participant_summary, participant_totals, participant_chart_path, organization_page_obj, organization_chart_path = get_participant_summary(request)

    paginator = Paginator(participant_summary, 10)
    page_obj = paginator.get_page(page_number)

    query_params = {}
    if event_filter: query_params['event'] = event_filter
    if event_status_filter: query_params['event_status'] = event_status_filter
    query_string = urlencode(query_params)

    context = {
        'all_events': Event.objects.all(),
        'event_page_obj': event_page_obj,
        'totals': totals,
        'chart_path': chart_path,
        'page_obj': page_obj,
        'participant_totals': participant_totals,
        'participant_chart_path': participant_chart_path,
        'organization_page_obj': organization_page_obj,
        'organization_chart_path': organization_chart_path,
        'current_filters': {
            'event': event_filter,
            'event_status': event_status_filter
        },
        'query_string': query_string,
        'MEDIA_URL': settings.MEDIA_URL,  # 👈 Add this
    }

    if request.headers.get('HX-Request'):
        return render(request, 'partials/dashboard_content.html', context)
    return render(request, 'dashboard.html', context)


def get_participant_summary(request, org_page_number=None):
    event_filter = request.GET.get('event')
    event_status_filter = request.GET.get('event_status')

    events = Event.objects.all()
    if event_status_filter:
        events = events.filter(event_status=event_status_filter)
    if event_filter:
        events = events.filter(id=event_filter)

    if not events.exists():
        return [], {}, None, [], None

    event_ids = events.values_list('id', flat=True)

    participant_qs = Participant.objects.filter(event_id__in=event_ids).values(
        'name', 'email', 'approved', 'denied', 'event__name', 'country', 'organization'
    )

    df = pd.DataFrame(list(participant_qs))
    if df.empty:
        return [], {}, None, [], None

    df = df.rename(columns={'event__name': 'event_name'})

    totals = {
        'total_participants': len(df),
        'approved_participants': df['approved'].sum(),
        'denied_participants': df['denied'].sum(),
        'pending_participants': len(df) - df['approved'].sum() - df['denied'].sum(),
        'local_participants': df['country'].fillna('').str.contains('Bangladesh', case=False).sum(),
        'foreign_participants': len(df) - df['country'].fillna('').str.contains('Bangladesh', case=False).sum(),
    }

    organization_summary = df.groupby('organization').size().reset_index(name='participant_count')
    organization_paginator = Paginator(organization_summary.to_dict(orient='records'), 10)
    organization_page_obj = organization_paginator.get_page(org_page_number)

    chart_path = generate_participant_summary_chart(df)
    org_chart_path = generate_organization_chart(organization_summary)

    return df.to_dict(orient='records'), totals, chart_path, organization_page_obj, org_chart_path


def generate_participant_summary_chart(df):
    if df.empty:
        return None

    cache_key = f"participant_summary_chart_{hash(pd.util.hash_pandas_object(df).sum())}"
    cached_chart = cache.get(cache_key)
    if cached_chart:
        return cached_chart

    summary_df = df.groupby('event_name').agg({
        'approved': 'sum',
        'denied': 'sum',
    }).reset_index()
    summary_df['pending'] = df.groupby('event_name').apply(
        lambda x: len(x) - x['approved'].sum() - x['denied'].sum()
    ).values

    summary_df = summary_df.rename(columns={
        'approved': 'Approved Participants',
        'denied': 'Denied Participants',
        'pending': 'Pending Participants'
    })

    df_melted = summary_df.melt(
        id_vars=['event_name'],
        value_vars=['Approved Participants', 'Denied Participants', 'Pending Participants'],
        var_name='Status',
        value_name='Count'
    )

    plt.figure(figsize=(12, 7))
    sns.set_style("whitegrid")
    sns.barplot(
        x='event_name',
        y='Count',
        hue='Status',
        data=df_melted,
        palette='pastel'
    )
    plt.title('Participant approval status per event', fontsize=16)
    plt.xlabel('Event', fontsize=14)
    plt.ylabel('Count', fontsize=14)
    plt.xticks(rotation=45, ha='right', fontsize=12)
    plt.yticks(fontsize=12)
    plt.tight_layout()

    chart_dir = os.path.join(settings.MEDIA_ROOT, 'charts')
    os.makedirs(chart_dir, exist_ok=True)
    chart_filename = f'participant_summary_status_{datetime.now().timestamp()}.png'
    chart_path = os.path.join(chart_dir, chart_filename)
    plt.savefig(chart_path)
    plt.close()

    chart_url = f'charts/{chart_filename}'
    cache.set(cache_key, chart_url, timeout=3600)
    return chart_url


def generate_organization_chart(organization_summary):
    if organization_summary.empty:
        return None

    try:
        cache_key = f"organization_chart_{hash(pd.util.hash_pandas_object(organization_summary).sum())}"
        cached_chart = cache.get(cache_key)
        if cached_chart:
            return cached_chart

        plt.figure(figsize=(12, 7))
        sns.set_style("whitegrid")
        sns.barplot(
            x="participant_count",
            y="organization",
            data=organization_summary.sort_values('participant_count', ascending=False),
            hue="organization",
            palette="pastel",
            legend=False
        )

        plt.title("Participants Per Organization", fontsize=16)
        plt.xlabel("Number of Participants", fontsize=14)
        plt.ylabel("Organization", fontsize=14)
        plt.tight_layout()

        chart_dir = os.path.join(settings.MEDIA_ROOT, 'charts')
        os.makedirs(chart_dir, exist_ok=True)
        chart_filename = f'organization_participant_chart_{datetime.now().timestamp()}.png'
        chart_path = os.path.join(chart_dir, chart_filename)
        plt.savefig(chart_path)
        plt.close()

        chart_url = f'charts/{chart_filename}'
        cache.set(cache_key, chart_url, timeout=3600)
        return chart_url
    except Exception as e:
        logger.exception("Chart Error: %s", e)
        return None
