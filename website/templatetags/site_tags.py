from django import template
from django.urls import reverse, NoReverseMatch
from django.core.cache import cache
import re

from website.models import SiteSettings, NavigationLink, HeroSection, CallToAction, Member

register = template.Library()

# Cache timeout (in seconds): 1 hour
CACHE_TIMEOUT = 3600


@register.simple_tag
def get_site_settings():
    """Return the first SiteSettings instance or None.
    
    Results are cached for 1 hour to reduce database queries.
    """
    cached = cache.get('site_settings')
    if cached is not None:
        return cached
    
    settings = SiteSettings.objects.first()
    cache.set('site_settings', settings, CACHE_TIMEOUT)
    return settings


@register.simple_tag
def get_navigation_links():
    """Return a hierarchical list of navigation link dicts.
    
    Structure: [
        {'label':..., 'url':..., 'is_dropdown':..., 'sub_links': [...]},
        ...
    ]
    """
    links = NavigationLink.objects.filter(is_active=True).order_by('order')
    tree = []
    
    # Pre-resolve URLs
    resolved_links = []
    for nav in links:
        url_name = (nav.url_name or '').strip()
        url = url_name
        if url_name and url_name != '#':
            try:
                url = reverse(url_name)
            except (NoReverseMatch, TypeError):
                # Try with underscores if kebab-case
                try:
                    url = reverse(url_name.replace('-', '_'))
                except (NoReverseMatch, TypeError):
                    # Try with website: prefix if not present
                    if ':' not in url_name:
                        try:
                            url = reverse(f'website:{url_name}')
                        except (NoReverseMatch, TypeError):
                            # Try website: with underscores
                            try:
                                url = reverse(f'website:{url_name.replace("-", "_")}')
                            except (NoReverseMatch, TypeError):
                                url = url_name
                        except (NoReverseMatch, TypeError):
                            url = url_name
                    else:
                        url = url_name
            
            # Ensure path starts with / if it's not a full URL or already absolute
            if url and not url.startswith(('http://', 'https://', '/', '#')):
                url = f"/{url}"
        
        resolved_links.append({
            'id': nav.id,
            'label': nav.label,
            'url': url,
            'parent_id': nav.parent_id,
            'is_dropdown': nav.is_dropdown,
            'sub_links': []
        })

    lookup = {link['id']: link for link in resolved_links}
    
    for link in resolved_links:
        if link['parent_id']:
            parent = lookup.get(link['parent_id'])
            if parent:
                parent['sub_links'].append(link)
        else:
            tree.append(link)
    
    return tree


@register.simple_tag
def get_hero_section(page_name):
    """Return the HeroSection instance for a specific page.
    
    Results are cached for 1 hour to reduce database queries.
    """
    cache_key = f'hero_section_{page_name}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    
    hero = HeroSection.objects.filter(page=page_name).first()
    cache.set(cache_key, hero, CACHE_TIMEOUT)
    return hero


@register.simple_tag
def get_call_to_action(page_name):
    """Return the CallToAction instance for a specific page.
    
    Results are cached for 1 hour to reduce database queries.
    """
    cache_key = f'call_to_action_{page_name}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    
    cta = CallToAction.objects.filter(page=page_name).first()
    cache.set(cache_key, cta, CACHE_TIMEOUT)
    return cta


@register.simple_tag(takes_context=True)
def get_call_to_action_current(context):
    """Return a CallToAction for the current request's view name (if any),
    otherwise fall back to the most recent CTA.

    This tag requires request to be available in the template context (Django
    provides it when you use RequestContext or render shortcuts which pass
    the request). Results are cached per view name for CACHE_TIMEOUT seconds.
    
    Aliases like 'homepage_alias' are normalized to their primary names ('homepage')
    to ensure consistent CTA rendering across aliased routes.
    """
    request = context.get('request')
    view_name = None
    if request is not None:
        resolver = getattr(request, 'resolver_match', None)
        if resolver:
            view_name = resolver.url_name

    # Normalize URL aliases to their primary page names
    # 'homepage_alias' -> 'homepage', etc.
    page_name = view_name
    if page_name == 'homepage_alias':
        page_name = 'homepage'

    cache_key = f'call_to_action_current_{page_name or "__latest"}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    cta = None
    if page_name:
        cta = CallToAction.objects.filter(page=page_name).order_by('-id').first()

    # Do not fall back to the most-recent CTA for other pages.
    # If there is no CTA for the current view, return None so templates
    # can choose to render nothing when appropriate.

    cache.set(cache_key, cta, CACHE_TIMEOUT)
    return cta


@register.filter
def extract_youtube_id(url):
    """Extract YouTube video ID from various URL formats."""
    if not url:
        return None
    
    url = url.strip()
    
    # List of regex patterns for different YouTube URL formats
    patterns = [
        r'youtu\.be/([^?&\s]+)',
        r'youtube\.com/watch\?.*v=([^&\s]+)',
        r'youtube\.com/embed/([^?&\s]+)',
        r'youtube\.com/v/([^?&\s]+)',
        r'youtube\.com/shorts/([^?&\s]+)',
        r'youtube\.com/live/([^?&\s]+)',
        r'(?:youtube\.com/)?embed/([^?&\s]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # Final fallback for raw 11-character IDs
    match = re.search(r'^([a-zA-Z0-9_-]{11})$', url)
    if match:
        return match.group(1)
    
    return None


@register.filter
def youtube_thumbnail(url):
    """Extract YouTube video ID and return thumbnail URL."""
    video_id = extract_youtube_id(url)
    if video_id:
        # Use medium quality thumbnail (320x180)
        return f'https://img.youtube.com/vi/{video_id}/mqdefault.jpg'
    return None
@register.filter
def is_active_member(user):
    """Check if the given user is an active (paid) member.
    
    Usage: {% if user|is_active_member %}...{% endif %}
    """
    if not user.is_authenticated:
        return False
    
    try:
        # UserProfile is related to User via OneToOne (lowercase model name by default)
        user_profile = getattr(user, 'userprofile', None)
        if not user_profile:
            return False
        
        # Member is related to UserProfile via OneToOne
        member = getattr(user_profile, 'member', None)
        if not member:
            return False
            
        return member.is_active_member
    except Exception:
        return False
