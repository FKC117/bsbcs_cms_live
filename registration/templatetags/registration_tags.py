from django import template
from registration.models import Participant

register = template.Library()

@register.simple_tag(takes_context=True)
def is_registered_for_event(context, event):
    user = context['request'].user
    try:
        Participant.objects.get(email=user.email, event=event)
        return True
    except Participant.DoesNotExist:
        return False
