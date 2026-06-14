from .models import UserProfile
from .dashboard_permissions import dashboard_access_map


def user_profile(request):
    """Context processor that adds `user_profile` to the template context if available."""
    profile = None
    try:
        if request.user.is_authenticated:
            profile = UserProfile.objects.filter(user=request.user).first()
    except Exception:
        profile = None
    return {
        'user_profile': profile,
        'dashboard_access': dashboard_access_map(request.user),
    }
