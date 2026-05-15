from django.contrib.auth.decorators import user_passes_test
from .models import Participant

def approved_user_required(function=None):
    """
    Decorator for views that checks that the user is logged in and approved.
    """
    actual_decorator = user_passes_test(
        lambda u: Participant.objects.filter(email=u.email, approved=True).exists(),
        login_url='/login/',
        redirect_field_name=None,
    )
    if function:
        return actual_decorator(function)
    return actual_decorator


