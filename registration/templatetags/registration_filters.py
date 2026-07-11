from django import template
import re

register = template.Library()


@register.filter
def get_by_abstract(schedules, abstract):
    return schedules.filter(abstract_submission=abstract).first()


@register.filter
def youtube_embed(url):
    if not url:
        return ''

    patterns = [
        r'youtu\.be/([^?&/]+)',
        r'youtube\.com/watch\?.*v=([^&]+)',
        r'youtube\.com/embed/([^?&/]+)',
        r'youtube\.com/shorts/([^?&/]+)',
        r'youtube\.com/live/([^?&/]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return f'https://www.youtube.com/embed/{match.group(1)}'

    if 'watch?v=' in url:
        return url.replace('watch?v=', 'embed/')
    return url
