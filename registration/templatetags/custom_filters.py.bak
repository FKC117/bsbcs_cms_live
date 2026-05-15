# registration/templatetags/custom_filters.py

from django import template

register = template.Library()

@register.filter
def get_by_abstract(schedules, abstract):
    return schedules.filter(abstract_submission=abstract).first()

@register.filter
def youtube_embed(url):
    if "watch?v=" in url:
        return url.replace("watch?v=", "embed/")
    return url