# registration/sitemaps.py

from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Event, AbstractSubmission

# Import website models for sitemap entries
try:
    from website.models import Webinar, PastEvent
except ImportError:
    Webinar = None
    PastEvent = None

class EventSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Event.objects.order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, item):
        return reverse('registration:home', args=[item.id])
# registration/sitemaps.py

class StaticViewSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        events = Event.objects.all()
        static_urls = [
            'about', 'invitation', 'speakers', 'schedule', 'participant_list',
            'registration', 'abstract_submission', 'sponsor_list', 'event_gallery',
            'publication_list'
        ]
        return [(url, event.id) for event in events for url in static_urls]

    def location(self, item):
        return reverse(f'registration:{item[0]}', args=[item[1]])
# registration/sitemaps.py

class PublicationSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        return AbstractSubmission.objects.filter(approved_for_presentation=True) | AbstractSubmission.objects.filter(approved_for_poster=True)

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, item):
        return reverse('registration:publication_detail', args=[item.event.id, item.id])


class WebsiteStaticSitemap(Sitemap):
    """Static pages exposed by the `website` app."""
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        # Use the URL names (namespaced) so `location` can reverse them
        return [
            'website:homepage',
            'website:about',
            'website:member_directory',
            'website:research_and_publications',
            'website:knowledge_center',
            'website:events',
            'website:past_events_list',
            'website:webinars',
        ]

    def location(self, item):
        return reverse(item)


class WebinarSitemap(Sitemap):
    """Sitemap for individual webinar detail pages."""
    changefreq = 'monthly'
    priority = 0.5

    def items(self):
        if Webinar is None:
            return []
        return Webinar.objects.all().order_by('-id')

    def lastmod(self, obj):
        # If Webinar has updated timestamp, use it; otherwise skip
        return getattr(obj, 'updated_at', None)

    def location(self, item):
        return reverse('website:webinar_detail', args=[item.pk])


class PastEventSitemap(Sitemap):
    """Sitemap for individual past event detail pages."""
    changefreq = 'monthly'
    priority = 0.5

    def items(self):
        if PastEvent is None:
            return []
        return PastEvent.objects.all().order_by('-year', 'order')

    def lastmod(self, obj):
        return getattr(obj, 'updated_at', None)

    def location(self, item):
        return reverse('website:past_event_detail', args=[item.slug])
