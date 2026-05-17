from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import get_template
from django.template import TemplateDoesNotExist
from pathlib import Path
import os
from django.http import FileResponse, Http404
from django.conf import settings
import re
from django.core.paginator import Paginator
from .models import (
    HeroSection, CarouselItem, NewsTickerItem, QuickAccessCard, StatisticCounter,
    MemberSpotlight, ResearchHighlight, Event, PastEvent, PastEventSpeaker, PastEventSession, PastEventActivity, PastEventSponsor, CallToAction, BoardMember,
    Committee, Partnership, Award, AnnualReport, ResourceCategory, ResourceItem,
    Webinar, Member, PendingEventIntent, MembershipPayment, NavigationLink, OrganizationalValue, TimelineSection, Media, SiteSettings, MembershipType
)
from .models import ResearchInterestArea, Speciality
from .forms import MembershipForm
from registration.views import (
    get_bkash_token, create_bkash_payment, 
    execute_payment, payment_query
)
import time
import json
import logging
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from datetime import timedelta

logger = logging.getLogger('payment')

from registration.models import (
    Event as RegistrationEvent, FeatureSpeaker, AboutTheConference, 
    Invitation, ProgramDay, TimeSlot, ProgramSchedule
)
from django.shortcuts import get_object_or_404
from .utils_membership import generate_membership_invoice, send_membership_invoice_email, complete_membership_payment


def favicon(request):
    site_settings = SiteSettings.objects.first()
    if site_settings and site_settings.favicon:
        try:
            return FileResponse(open(site_settings.favicon.path, 'rb'))
        except (FileNotFoundError, ValueError):
            pass
            
    # Fallback to static location or root
    favicon_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'favicon.ico')
    if not os.path.exists(favicon_path):
         # Try another common location
         favicon_path = os.path.join(settings.BASE_DIR, 'website', 'static', 'img', 'favicon.ico')

    try:
        return FileResponse(open(favicon_path, 'rb'))
    except FileNotFoundError:
        # Final fallback: return 404 but clean
        raise Http404("favicon not found")


def extract_youtube_id(url):
    """Extract YouTube video ID from various URL formats."""
    if not url:
        return None
    
    # Handle youtu.be format
    match = re.search(r'youtu\.be/([^?&]+)', url)
    if match:
        return match.group(1)
    
    # Handle youtube.com format
    match = re.search(r'youtube\.com/watch\?v=([^&]+)', url)
    if match:
        return match.group(1)
    
    # Handle youtube.com/embed format
    match = re.search(r'youtube\.com/embed/([^?&]+)', url)
    if match:
        return match.group(1)
    
    return None

def homepage(request):
    hero = HeroSection.objects.filter(page='homepage').first()
    carousel_items = CarouselItem.objects.filter(hero_section=hero) if hero else []
    news_tickers = NewsTickerItem.objects.filter(is_active=True).order_by('order')
    quick_access_cards = QuickAccessCard.objects.filter(page='homepage').order_by('order')
    stats_counters = StatisticCounter.objects.filter(page='homepage').order_by('order')
    member_spotlights = MemberSpotlight.objects.filter(is_featured=True).order_by('order')
    # Only show highlights flagged for homepage (highlight=True)
    research_highlights = ResearchHighlight.objects.filter(highlight=True).order_by('order')
    # Prefer registration app's Event model for upcoming events display on homepage
    try:
        from registration.models import Event as RegEvent
    except Exception:
        RegEvent = Event  # fallback to local Event model

    # Query only upcoming events from the registration app and order by start_date
    try:
        events = RegEvent.objects.filter(event_status='upcoming').order_by('start_date')
    except Exception:
        # Fallback to the existing local events list if RegEvent doesn't support these fields
        events = Event.objects.all().order_by('order', 'date')
    # Use the latest CallToAction entry for homepage (most recent).
    # We keep the model's order field available but prefer the latest DB entry
    # so content managers can update the hero CTA by creating a new entry.
    call_to_action = CallToAction.objects.filter(page='homepage').order_by('-id').first()
    navigation_links = NavigationLink.objects.filter(is_active=True).order_by('order')

    context = {
        'hero': hero,
        'carousel_items': carousel_items,
        'news_tickers': news_tickers,
        'quick_access_cards': quick_access_cards,
        'stats_counters': stats_counters,
        'member_spotlights': member_spotlights,
        'research_highlights': research_highlights,
        'events': events,
        'call_to_action': call_to_action,
        'navigation_links': navigation_links,
    }
    return render(request, 'pages/homepage.html', context)


def about(request):
    hero = HeroSection.objects.filter(page='about').first()
    stats_counters = StatisticCounter.objects.filter(page='about').order_by('order')
    board_members = BoardMember.objects.all().order_by('order')
    committees = Committee.objects.all().order_by('order')
    partnerships = Partnership.objects.all().order_by('order')
    awards = Award.objects.all().order_by('order', '-year')
    call_to_action = CallToAction.objects.filter(page='about').first()
    navigation_links = NavigationLink.objects.filter(is_active=True).order_by('order')
    
    # Fetch timeline section with ordered items
    timeline_section = TimelineSection.objects.order_by('order').first()
    timeline_items = []
    if timeline_section:
        timeline_items = list(timeline_section.items.all())  # type: ignore
    
    # Fetch organizational values grouped by type
    mission = OrganizationalValue.objects.filter(value_type='mission').first()
    vision = OrganizationalValue.objects.filter(value_type='vision').first()
    values = OrganizationalValue.objects.filter(value_type='value').order_by('order')

    # Prepare values_items for the template. If there are multiple `value` rows,
    # use each row's title as an item. If there is a single `value` row which
    # contains a multi-line description (e.g. authors pasted a list into the
    # description field), split it into list items for rendering.
    import re
    values_items = []
    if values.count() > 1:
        for v in values:
            # prefer the title for short list items, fallback to description
            text = v.title or (v.description or '').strip()
            if text:
                values_items.append(text)
    elif values.count() == 1:
        single = values.first()
        desc = (single.description or '').strip()  # type: ignore
        if desc:
            # split on newlines first
            parts = [p.strip() for p in re.split(r'[\r\n]+', desc) if p.strip()]
            if len(parts) == 1:
                # if still single, try splitting on common separators
                parts = [p.strip() for p in re.split(r'[;\u2022,]+', desc) if p.strip()]
            values_items = parts
        else:
            # no description, use the title as a single item
            if single.title:  # type: ignore
                values_items = [single.title]  # type: ignore
    
    # Determine a header title and icon for the Values card.
    # Prefer an explicit "Values" meta row when present (title like 'Values' or 'Our Values').
    values_header_title = 'Values'
    values_header_icon_url = None
    if values.exists():
        # try to find a meta/header row
        header = values.filter(title__iregex=r'^(values|our values?)$').first()
        if header:
            values_header_title = header.title  # type: ignore
            if header.icon_svg:  # type: ignore
                values_header_icon_url = header.icon_svg.url  # type: ignore
        else:
            # no explicit header row: if there's a single row, use its title/icon as header
            if values.count() == 1:
                single = values.first()
                values_header_title = single.title or values_header_title  # type: ignore
                if single.icon_svg:  # type: ignore
                    values_header_icon_url = single.icon_svg.url  # type: ignore
            else:
                # multiple rows and no header candidate: leave generic title and no icon
                values_header_title = 'Values'

    context = {
        'hero': hero,
        'stats_counters': stats_counters,
        'board_members': board_members,
        'committees': committees,
        'partnerships': partnerships,
        'awards': awards,
        'call_to_action': call_to_action,
        'navigation_links': navigation_links,
        'mission': mission,
        'vision': vision,
        'values': values,
        'values_items': values_items,
        'values_header_title': values_header_title,
        'values_header_icon_url': values_header_icon_url,
        'timeline_section': timeline_section,
        'timeline_items': timeline_items,
    }
    return render(request, 'pages/about_site.html', context)


def knowledge_center(request):
    hero = HeroSection.objects.filter(page='knowledge_center').first()
    resource_categories = ResourceCategory.objects.all().order_by('order')
    # Featured Resources section: only featured items
    featured_resources = ResourceItem.objects.filter(is_featured=True).order_by('order')
    # Clinical Guidelines section: all items (regardless of is_featured)
    all_resources = ResourceItem.objects.all().order_by('order')
    webinars = Webinar.objects.all().order_by('order')
    call_to_action = CallToAction.objects.filter(page='knowledge_center').first()
    navigation_links = NavigationLink.objects.filter(is_active=True).order_by('order')

    context = {
        'hero': hero,
        'resource_categories': resource_categories,
        'featured_resources': featured_resources,
        'all_resources': all_resources,
        'webinars': webinars,
        'call_to_action': call_to_action,
        'navigation_links': navigation_links,
    }
    return render(request, 'pages/knowledge_center.html', context)


def member_directory(request):
    hero = HeroSection.objects.filter(page='member_directory').first()
    # Only show members with 'approved' status AND active payment (paid) in the directory
    members = Member.objects.filter(approval_status='approved', is_active_member=True).order_by('order')
    # Fetch specialties and research interest areas for the advanced filter dropdowns
    specialities = Speciality.objects.all().order_by('name')
    research_areas = ResearchInterestArea.objects.all().order_by('name')
    call_to_action = CallToAction.objects.filter(page='member_directory').first()
    navigation_links = NavigationLink.objects.filter(is_active=True).order_by('order')

    context = {
        'hero': hero,
        'members': members,
        'specialities': specialities,
        'research_areas': research_areas,
        'call_to_action': call_to_action,
        'navigation_links': navigation_links,
    }
    return render(request, 'pages/member_directory.html', context)


def events(request):
    # Render the legacy registration index at /events/
    # Use the registration app's Event model (has fields like start_date, end_date, event_status)
    try:
        from registration.models import Event as RegEvent, UserProfile as RegUserProfile
    except Exception:
        RegEvent = Event  # fallback to local Event model
        RegUserProfile = None

    user_profile = None
    if request.user.is_authenticated and RegUserProfile:
        try:
            user_profile = RegUserProfile.objects.get(user=request.user)
        except RegUserProfile.DoesNotExist:  # type: ignore[name-defined]
            user_profile = None

    hero = HeroSection.objects.filter(page='events').first()
    news_tickers = NewsTickerItem.objects.filter(is_active=True).order_by('order')

    # Mirror registration.index view behavior: group events by status
    active_events = RegEvent.objects.filter(event_status='active').order_by('-start_date')
    upcoming_events = RegEvent.objects.filter(event_status='upcoming').order_by('start_date')
    closed_events = RegEvent.objects.filter(event_status='closed').order_by('-end_date')

    call_to_action = CallToAction.objects.filter(page='events').first()
    navigation_links = NavigationLink.objects.filter(is_active=True).order_by('order')

    context = {
        'user_profile': user_profile,
        'hero': hero,
        'news_tickers': news_tickers,
        'active_events': active_events,
        'upcoming_events': upcoming_events,
        'closed_events': closed_events,
        'call_to_action': call_to_action,
        'navigation_links': navigation_links,
    }
    # Render the shared index template so /events/ behaves like the old index page
    return render(request, 'index.html', context)


def research_and_publications(request):
    hero = HeroSection.objects.filter(page='research_and_publications').first()
    stats_counters = StatisticCounter.objects.filter(page='research_and_publications').order_by('order')
    # Only include research highlights that are explicitly flagged as highlighted
    research_highlights = ResearchHighlight.objects.filter(highlight=True).order_by('order')
    # Also provide a full list of research highlights (regardless of the `highlight` flag)
    research_highlights_all = ResearchHighlight.objects.all().order_by('order')
    annual_reports = AnnualReport.objects.all().order_by('-year')
    call_to_action = CallToAction.objects.filter(page='research_and_publications').first()
    navigation_links = NavigationLink.objects.filter(is_active=True).order_by('order')

    context = {
        'hero': hero,
        'stats_counters': stats_counters,
        'research_highlights': research_highlights,
        'research_highlights_all': research_highlights_all,
        'annual_reports': annual_reports,
        'call_to_action': call_to_action,
        'navigation_links': navigation_links,
    }
    return render(request, 'pages/research_and_publications.html', context)

def webinars(request):
    hero = HeroSection.objects.filter(page='webinars').first()
    resource_categories = ResourceCategory.objects.all().order_by('order')
    resources = ResourceItem.objects.all().order_by('order')
    
    # Pagination settings: 6 items per page for each section
    items_per_page = 6
    
    # Get webinars and paginate
    webinars_all = Webinar.objects.filter(type='webinar').order_by('order')
    webinars_paginator = Paginator(webinars_all, items_per_page)
    webinars_page = request.GET.get('webinars_page', 1)
    try:
        webinars = webinars_paginator.page(webinars_page)
    except:
        webinars = webinars_paginator.page(1)
    
    # Get preceptorship webinars and paginate
    preceptorship_all = Webinar.objects.filter(type='perceptorship').order_by('order')
    preceptorship_paginator = Paginator(preceptorship_all, items_per_page)
    preceptorship_page = request.GET.get('preceptorship_page', 1)
    try:
        preceptorship_webinars = preceptorship_paginator.page(preceptorship_page)
    except:
        preceptorship_webinars = preceptorship_paginator.page(1)
    
    # Get GCI webinars and paginate
    gci_all = Webinar.objects.filter(type='gci').order_by('order')
    gci_paginator = Paginator(gci_all, items_per_page)
    gci_page = request.GET.get('gci_page', 1)
    try:
        gci_webinars = gci_paginator.page(gci_page)
    except:
        gci_webinars = gci_paginator.page(1)
    
    call_to_action = CallToAction.objects.filter(page='webinars').first()
    navigation_links = NavigationLink.objects.filter(is_active=True).order_by('order')

    context = {
        'hero': hero,
        'resource_categories': resource_categories,
        'resources': resources,
        'webinars': webinars,
        'preceptorship_webinars': preceptorship_webinars,
        'gci_webinars': gci_webinars,
        'call_to_action': call_to_action,
        'navigation_links': navigation_links,
    }
    return render(request, 'pages/webinars.html', context)


def webinar_detail(request, pk):
    """Display full webinar details including video and panelists."""
    webinar = Webinar.objects.get(pk=pk)
    navigation_links = NavigationLink.objects.filter(is_active=True).order_by('order')
    
    context = {
        'webinar': webinar,
        'navigation_links': navigation_links,
    }
    return render(request, 'pages/webinar_detail.html', context)


def sitemap_table(request):
    """Render a human-friendly, tabular sitemap page.

    Collects entries from the existing sitemap classes in
    `registration.sitemaps` and builds a list of rows with the
    following columns: URL, Title, Last modified, Changefreq, Priority.
    """
    from registration.sitemaps import (
        EventSitemap,
        StaticViewSitemap,
        PublicationSitemap,
        WebsiteStaticSitemap,
        WebinarSitemap,
        PastEventSitemap,
    )

    sitemap_instances = [
        WebsiteStaticSitemap(),
        EventSitemap(),
        PastEventSitemap(),
        WebinarSitemap(),
        PublicationSitemap(),
        StaticViewSitemap(),
    ]

    rows = []

    # Friendly titles for well-known static names
    static_title_map = {
        'website:homepage': 'Home',
        'website:about': 'About',
        'website:member_directory': 'Members',
        'website:research_and_publications': 'Research & Publications',
        'website:knowledge_center': 'Resources',
        'website:events': 'Events',
        'website:past_events_list': 'Past Events Archives',
        'website:webinars': 'Webinars',
    }

    for sm in sitemap_instances:
        changefreq = getattr(sm, 'changefreq', '')
        priority = getattr(sm, 'priority', '')
        try:
            items = list(sm.items())
        except Exception:
            items = []

        for item in items:
            # location may raise, guard it
            try:
                loc = sm.location(item)
            except Exception:
                # fallback: try str()
                try:
                    loc = str(item)
                except Exception:
                    loc = ''

            # lastmod if provided
            lastmod = None
            if hasattr(sm, 'lastmod'):
                try:
                    lastmod = sm.lastmod(item)
                except Exception:
                    lastmod = None

            # Determine a human-friendly title
            title = None
            # If the sitemap item is a named URL (string)
            if isinstance(item, str):
                title = static_title_map.get(item, item.replace('website:', '').replace('_', ' ').title())
            # If tuple used by StaticViewSitemap (('about', event_id))
            elif isinstance(item, (list, tuple)):
                try:
                    url_name = item[0]
                    arg = item[1] if len(item) > 1 else ''
                    title = f"{url_name.replace('_', ' ').title()} (Event {arg})"
                except Exception:
                    title = str(item)
            else:
                # Model instances: try common fields
                title = getattr(item, 'title', None) or getattr(item, 'name', None) or getattr(item, 'get_short_name', None)
                if callable(title):
                    try:
                        title = title()
                    except Exception:
                        title = None
                if not title:
                    try:
                        title = str(item)
                    except Exception:
                        title = ''

            rows.append({
                'loc': loc,
                'title': title,
                'lastmod': lastmod,
                'changefreq': changefreq,
                'priority': priority,
            })

    context = {
        'rows': rows,
    }
    return render(request, 'pages/sitemap_table.html', context)


def membership_form(request):
    """View for membership form submission and creation.
    
    Requires:
    1. User must be logged in (redirects to login if not)
    2. User must have a UserProfile (redirects to create_profile if not)
    3. Once both requirements are met, display membership form
    """
    from django.shortcuts import redirect
    from django.urls import reverse
    from urllib.parse import quote
    from registration.models import Event as RegistrationEventModel, UserProfile
    next_path = quote(request.get_full_path())

    # Check if user is logged in
    if not request.user.is_authenticated:
        # Redirect to login with next parameter pointing back to membership form
        return redirect(f'{reverse("login")}?next={next_path}')

    # Check if user has a UserProfile
    try:
        user_profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        # If logged in but no profile, show a more specific error or redirect to a profile completion view
        # Instead of just Sending them to the 'signup' style create_profile, we can send them to
        # an edit/complete profile view that doesn't ask for a new account.
        messages.warning(request, "Please complete your profile details before joining the society.")
        return redirect(f'{reverse("user_profile")}?next={next_path}')

    event_intent_id = request.POST.get('event_intent') or request.GET.get('event_intent')
    event_intent = None
    if event_intent_id:
        event_intent = RegistrationEventModel.objects.filter(id=event_intent_id).first()
        if event_intent and (
            event_intent.registration != 'Open'
            or not (event_intent.member_registration_enabled or event_intent.registration_audience == 'members_only')
        ):
            messages.warning(request, "This event is no longer accepting member registration intents.")
            event_intent = None

    def save_event_intent(member):
        if not event_intent:
            return None
        intent, _ = PendingEventIntent.objects.update_or_create(
            user_profile=user_profile,
            event=event_intent,
            intent_type='member_registration',
            defaults={
                'status': 'pending',
                'participant': None,
                'note': 'Saved from membership application during event registration.',
                'completed_at': None,
            }
        )
        return intent
    
    # Check if a Member record already exists for this UserProfile
    existing_member = Member.objects.filter(user_profile=user_profile).first()
    
    # If member already exists and is approved or pending, redirect them
    if existing_member:
        if existing_member.approval_status == 'approved':
            save_event_intent(existing_member)
            # Redirect to home, or perhaps to the payment page if they haven't paid
            if not existing_member.is_active_member:
                return redirect('website:membership_payment_init')
            if event_intent:
                from .utils_membership import process_pending_event_intents
                process_pending_event_intents(existing_member)
            messages.info(request, "You are already an approved member.")
            return redirect('website:homepage')
        elif existing_member.approval_status == 'pending':
            save_event_intent(existing_member)
            # They already applied, show them the success/thank you page again
            return render(request, 'pages/membership_application_received.html', {
                'member': existing_member,
                'event_intent': event_intent,
            })
        # If 'rejected', we allow them to re-submit/edit their form below
    
    if request.method == 'POST':
        # Pass the existing instance if it exists, otherwise a new one is created
        form = MembershipForm(request.POST, request.FILES, instance=existing_member)
        if form.is_valid():
            member = form.save(commit=False)
            # Link Member to the user's UserProfile
            member.user_profile = user_profile
            # Set approval_status to pending (will be reviewed by admin)
            member.approval_status = 'pending'
            # Set order if it's a new member
            if not existing_member:
                member.order = Member.objects.count() + 1
            member.save()
            form.save_m2m()  # Save many-to-many relationships
            save_event_intent(member)

            # Render success message for application submission (not payment)
            return render(request, 'pages/membership_application_received.html', {
                'member': member,
                'event_intent': event_intent,
            })
    else:
        # Pass the existing instance to prepopulate the form if they were rejected
        form = MembershipForm(instance=existing_member)
    
    hero = HeroSection.objects.filter(page='member_directory').first()
    call_to_action = CallToAction.objects.filter(page='member_directory').first()
    navigation_links = NavigationLink.objects.filter(is_active=True).order_by('order')
    
    context = {
        'form': form,
        'hero': hero,
        'call_to_action': call_to_action,
        'navigation_links': navigation_links,
        'user_profile': user_profile,
        'event_intent': event_intent,
    }
    return render(request, 'pages/membership_form.html', context)


def get_navigation_tree():
    """Helper to fetch navigation links in a hierarchical structure."""
    links = NavigationLink.objects.filter(is_active=True).order_by('order')
    tree = []
    lookup = {link.id: link for link in links}
    
    for link in links:
        link.sub_links = [] # Temporary attribute for template
        if link.parent_id:
            parent = lookup.get(link.parent_id)
            if parent:
                if not hasattr(parent, 'sub_links'):
                    parent.sub_links = []
                parent.sub_links.append(link)
        else:
            tree.append(link)
    return tree


def media_gallery(request):
    """Display photos and videos grouped by event."""
    media_items = Media.objects.all().order_by('order', '-created_at')
    
    # Grouping logic
    gallery = {} # {event_name: {'photos': [], 'videos': []}}
    
    for item in media_items:
        event_name = item.custom_event_name
        if not event_name and item.registration_event:
            event_name = f"{item.registration_event.name} {item.registration_event.year}"
        if not event_name:
            event_name = "General Gallery"
            
        if event_name not in gallery:
            gallery[event_name] = {'photos': [], 'videos': []}
            
        if item.media_type == 'image':
            gallery[event_name]['photos'].append(item)
        else:
            gallery[event_name]['videos'].append(item)
            
    context = {
        'gallery': gallery,
    }
    return render(request, 'pages/media_gallery.html', context)

def past_events_list(request):
    """List all closed events from registration and manual past events."""
    reg_events = RegistrationEvent.objects.filter(event_status='closed').order_by('-end_date')
    manual_events = PastEvent.objects.all().order_by('-year', 'order')
    
    context = {
        'reg_events': reg_events,
        'manual_events': manual_events,
        'navigation_tree': get_navigation_tree(),
    }
    return render(request, 'pages/past_events_list.html', context)


def past_event_detail(request, slug):
    """Display a lush landing page for a specific manual PastEvent.
    
    RegistrationEvents (closed) are handled by registration:home.
    """
    event = get_object_or_404(PastEvent, slug=slug)
    is_manual = True
    speakers = event.speakers.all()
    about_conference = event
    invitations = []
    
    # Structure sessions for manual events
    sessions = event.sessions.all().order_by('order')
    scientific_program = []
    days_names = sessions.values_list('day_name', flat=True).distinct()
    for d_name in days_names:
        scientific_program.append({
            'day_name': d_name,
            'sessions': sessions.filter(day_name=d_name)
        })

    context = {
        'event': event,
        'is_manual': is_manual,
        'speakers': speakers,
        'about_conference': about_conference,
        'invitations': invitations,
        'scientific_program': scientific_program,
        'navigation_tree': get_navigation_tree(),
    }
    return render(request, 'pages/past_event_detail.html', context)


@login_required
def membership_payment_init(request):
    """Initialize membership payment."""
    site_settings = SiteSettings.objects.first()
    if not site_settings or not site_settings.membership_subscription_enabled:
        messages.error(request, "Membership subscription is currently disabled.")
        return redirect('website:homepage')

    user_profile = getattr(request.user, 'userprofile', None)
    if not user_profile:
        messages.error(request, "User profile not found. Please complete your profile first.")
        return redirect('website:homepage')

    # Ensure Member object exists
    member, created = Member.objects.get_or_create(user_profile=user_profile)

    if request.method == 'POST':
        token = get_bkash_token()
        if not token:
            messages.error(request, "Failed to connect to payment gateway. Please try again later.")
            return redirect('website:homepage')

        # Get membership type and duration
        type_id = request.POST.get('membership_type')
        years = int(request.POST.get('years', 1))
        
        try:
            membership_type = MembershipType.objects.get(id=type_id)
        except (MembershipType.DoesNotExist, ValueError):
            messages.error(request, "Invalid membership type selected.")
            return redirect('website:membership_payment_init') # Corrected redirect

        # Calculate amount
        amount = membership_type.amount * years
        
        # Generate unique invoice number
        invoice_number = f"MEM-{member.id}-{int(timezone.now().timestamp())}"
        
        # Create payment record
        payment = MembershipPayment.objects.create(
            user_profile=member.user_profile,
            membership_type=membership_type,
            duration_years=years,
            amount=amount,
            merchant_invoice_number=invoice_number,
            status='initiated'
        )
        
        payer_reference = user_profile.phone or "NoPhone"
        
        # Unique invoice number for membership
        merchant_invoice_number = payment.merchant_invoice_number # Use the one from the created payment record
        
        callback_url = request.build_absolute_uri(
            reverse('website:membership_payment_callback')
        ) + f"?merchant_invoice_number={merchant_invoice_number}"

        payment_response = create_bkash_payment(
            token, amount, payer_reference, callback_url, merchant_invoice_number
        )

        if payment_response and payment_response.get("statusCode") == "0000":
            # Update the payment record with the bkash payment ID
            payment.transaction_id = payment_response.get("paymentID")
            payment.save()
            return redirect(payment_response["bkashURL"])
        else:
            msg = payment_response.get('statusMessage') if payment_response else "Unknown error"
            messages.error(request, f"Payment initialization failed: {msg}")
            payment.status = 'failed'
            payment.save()
            return redirect('website:homepage')

    membership_types = MembershipType.objects.filter(is_active=True)
    return render(request, 'pages/membership_payment.html', {
        'member': member,
        'site_settings': site_settings,
        'membership_types': membership_types
    })


@login_required
def membership_payment_callback(request):
    """Callback for membership payment."""
    payment_id = request.GET.get('paymentID')
    status = request.GET.get('status')
    merchant_invoice_number = request.GET.get('merchant_invoice_number')

    if status == 'cancel' or status == 'failure':
        MembershipPayment.objects.filter(
            merchant_invoice_number=merchant_invoice_number
        ).update(status='cancelled' if status == 'cancel' else 'failed')
        messages.error(request, f"Membership payment {status}ed.")
        return redirect('website:homepage')

    if not payment_id:
        messages.error(request, "Invalid payment session.")
        return redirect('website:homepage')

    # Update payment record with tokenized payment ID
    MembershipPayment.objects.filter(
        merchant_invoice_number=merchant_invoice_number
    ).update(transaction_id=payment_id, status='pending')

    return redirect(reverse('website:membership_payment_finalize') + f"?paymentID={payment_id}")


@login_required
def membership_payment_finalize(request):
    """Finalize membership payment and update member status."""
    payment_id = request.GET.get('paymentID')
    if not payment_id:
        messages.error(request, "Payment ID missing.")
        return redirect('website:homepage')

    payment_record = get_object_or_404(MembershipPayment, transaction_id=payment_id)
    
    token = get_bkash_token()
    if not token:
        messages.error(request, "Session expired. Please contact support.")
        return redirect('website:homepage')

    execute_response = execute_payment(token, payment_id)

    if execute_response and execute_response.get('statusCode') == '0000':
        # Success!
        payment_record.trxID = execute_response.get('trxID')
        # This helper handles activation, invoice generation and emailing
        complete_membership_payment(payment_record)

        # Fetch updated member for template
        member = Member.objects.get(user_profile=payment_record.user_profile)

        messages.success(request, f"Your {payment_record.membership_type.name if payment_record.membership_type else ''} membership has been successfully activated!")
        return render(request, 'pages/membership_success.html', {
            'payment': payment_record,
            'member': member
        })
    else:
        payment_record.status = 'failed'
        payment_record.save()
        msg = execute_response.get('statusMessage') if execute_response else "Finalization failed."
        messages.error(request, f"Payment failed: {msg}")
        return redirect('website:homepage')
