from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


DASHBOARD_PERMISSION_GROUPS = {
    "events": {
        "read": ("registration.view_event",),
        "write": ("registration.add_event", "registration.change_event"),
    },
    "program": {
        "read": (
            "registration.view_programsession",
            "registration.view_programschedule",
            "registration.view_programperson",
        ),
        "write": (
            "registration.add_programsession",
            "registration.change_programsession",
            "registration.add_programschedule",
            "registration.change_programschedule",
            "registration.add_programperson",
            "registration.change_programperson",
        ),
    },
    "participants": {
        "read": ("registration.view_participant",),
        "write": (
            "registration.add_participant",
            "registration.change_participant",
            "registration.delete_participant",
        ),
    },
    "payments": {
        "read": (
            "registration.view_paymentstatus",
            "registration.view_corporatepayment",
            "website.view_membershippayment",
        ),
        "write": (
            "registration.add_paymentstatus",
            "registration.change_paymentstatus",
            "registration.add_corporatepayment",
            "registration.change_corporatepayment",
            "website.add_membershippayment",
            "website.change_membershippayment",
        ),
    },
    "membership": {
        "read": (
            "website.view_member",
            "website.view_membershiptype",
            "website.view_membershipbenefitmodal",
        ),
        "write": (
            "website.add_member",
            "website.change_member",
            "website.delete_member",
            "website.add_membershiptype",
            "website.change_membershiptype",
            "website.add_membershipbenefitmodal",
            "website.change_membershipbenefitmodal",
        ),
    },
    "corporate": {
        "read": (
            "registration.view_corporateaccountrequest",
            "registration.view_corporateaccount",
            "registration.view_corporateeventregistration",
            "registration.view_corporateeventattendee",
        ),
        "write": (
            "registration.change_corporateaccountrequest",
            "registration.change_corporateaccount",
            "registration.change_corporateeventregistration",
            "registration.change_corporateeventattendee",
        ),
    },
    "kits": {
        "read": ("registration.view_registrationkit",),
        "write": (
            "registration.add_registrationkit",
            "registration.change_registrationkit",
        ),
    },
    "abstracts": {
        "read": ("registration.view_abstractsubmission",),
        "write": (
            "registration.add_abstractsubmission",
            "registration.change_abstractsubmission",
        ),
    },
    "presentations": {
        "read": ("registration.view_presentationupload",),
        "write": (
            "registration.add_presentationupload",
            "registration.change_presentationupload",
        ),
    },
    "certificates": {
        "read": (
            "registration.view_certificate",
            "registration.view_feedbackquestion",
            "registration.view_feedbackresponse",
        ),
        "write": (
            "registration.add_certificate",
            "registration.change_certificate",
            "registration.add_feedbackquestion",
            "registration.change_feedbackquestion",
        ),
    },
    "chest_cards": {
        "read": (
            "registration.view_chestcarddesign",
            "registration.view_paymentstatus",
            "registration.view_participant",
        ),
        "write": (
            "registration.add_chestcarddesign",
            "registration.change_chestcarddesign",
        ),
    },
    "bulk_email": {
        "read": (
            "registration.view_bulkemail",
            "registration.view_emailgroup",
        ),
        "write": (
            "registration.add_bulkemail",
            "registration.change_bulkemail",
            "registration.add_emailgroup",
            "registration.change_emailgroup",
        ),
    },
    "bulk_sms": {
        "read": (
            "registration.view_bulksms",
            "registration.view_phonegroup",
        ),
        "write": (
            "registration.add_bulksms",
            "registration.change_bulksms",
            "registration.add_phonegroup",
            "registration.change_phonegroup",
        ),
    },
    "staff_activity": {
        "read": ("admin.view_logentry",),
        "write": (),
    },
}

DASHBOARD_PERMISSION_GROUPS["dashboard"] = {
    "read": tuple(
        permission
        for area, permission_group in DASHBOARD_PERMISSION_GROUPS.items()
        for permission in permission_group["read"]
        if area != "staff_activity"
    ),
    # The main dashboard itself does not mutate business records.
    # POST is used for export-style actions like PDF generation, so it should
    # follow the same access gate as the read-only dashboard view.
    "write": tuple(
        permission
        for area, permission_group in DASHBOARD_PERMISSION_GROUPS.items()
        for permission in permission_group["read"]
        if area != "staff_activity"
    ),
}


def user_has_any_permission(user, permissions):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return False
    return user.is_superuser or any(user.has_perm(permission) for permission in permissions)


def user_can_access_dashboard_area(user, area, write=False):
    permission_group = DASHBOARD_PERMISSION_GROUPS[area]
    key = "write" if write else "read"
    permissions = permission_group[key]
    if write and not permissions:
        return False
    return user_has_any_permission(user, permissions)


def dashboard_permission_required(area):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), login_url="admin:login")

            write = request.method not in ("GET", "HEAD", "OPTIONS")
            if not user_can_access_dashboard_area(request.user, area, write=write):
                raise PermissionDenied

            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator


def dashboard_access_map(user):
    return {
        area: user_can_access_dashboard_area(user, area)
        for area in DASHBOARD_PERMISSION_GROUPS
    }
