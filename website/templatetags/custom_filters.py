from django import template
import re

register = template.Library()


@register.filter
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
