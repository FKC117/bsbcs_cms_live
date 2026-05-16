from django.urls import reverse, NoReverseMatch
from django.db import DatabaseError, OperationalError, ProgrammingError
from .models import SiteSettings, NavigationLink, MembershipBenefitModal


def site_settings(request):
    settings = SiteSettings.objects.first()
    membership_benefit_modal_displayable = False
    try:
        membership_benefit_modal = (
            MembershipBenefitModal.objects.filter(is_active=True)
            .prefetch_related('benefit_items')
            .first()
        )
        if membership_benefit_modal:
            has_image = bool(membership_benefit_modal.image)
            has_content = any([
                bool((membership_benefit_modal.title or '').strip()),
                bool((membership_benefit_modal.subtitle or '').strip()),
                bool((membership_benefit_modal.description or '').strip()),
                membership_benefit_modal.benefit_items.filter(is_active=True).exists(),
            ])
            membership_benefit_modal_displayable = has_image or has_content
    except (DatabaseError, OperationalError, ProgrammingError):
        membership_benefit_modal = None

    # Build navigation links with resolved URLs when possible
    navigation_links = []
    for nav in NavigationLink.objects.filter(is_active=True).order_by('order'):
        url = nav.url_name or ''
        try:
            # Try to reverse as a Django URL name
            url = reverse(nav.url_name)
        except (NoReverseMatch, TypeError):
            # Try with underscores if kebab-case
            try:
                url = reverse(nav.url_name.replace('-', '_'))
            except (NoReverseMatch, TypeError):
                # If reversing fails, assume the field contains a direct URL or path
                url = nav.url_name
        
        # Ensure path starts with / if it's not a full URL or already absolute
        if url and not url.startswith(('http://', 'https://', '/', '#')):
            url = f"/{url}"
        
        navigation_links.append({'label': nav.label, 'url': url})

    return {
        'site_settings': settings,
        'navigation_links': navigation_links,
        'membership_benefit_modal': membership_benefit_modal,
        'membership_benefit_modal_displayable': membership_benefit_modal_displayable,
    }
