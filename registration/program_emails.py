from datetime import time as empty_time

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags


def build_program_assignment_summary(person, event=None):
    assignments = {}

    def get_assignment(session):
        return assignments.setdefault(session.pk, {
            'session': session,
            'session_roles': [],
            'talks': {},
        })

    session_roles = person.session_roles.select_related(
        'session__event',
        'session__program_day',
        'session__hall_room',
    )
    talk_roles = person.item_roles.select_related(
        'item__session__event',
        'item__session__program_day',
        'item__session__hall_room',
        'item__abstract_submission',
    )
    if event:
        session_roles = session_roles.filter(session__event=event)
        talk_roles = talk_roles.filter(item__session__event=event)

    for role in session_roles:
        assignment = get_assignment(role.session)
        assignment['session_roles'].append(role.get_role_display())

    for role in talk_roles:
        item = role.item
        assignment = get_assignment(item.session)
        talk = assignment['talks'].setdefault(item.pk, {
            'item': item,
            'roles': [],
        })
        talk['roles'].append(role.get_role_display())

    summarized_assignments = []
    for assignment in assignments.values():
        assignment['session_roles'] = sorted(set(assignment['session_roles']))
        assignment['talks'] = sorted(
            assignment['talks'].values(),
            key=lambda talk: (
                talk['item'].order,
                talk['item'].start_time or empty_time.min,
                talk['item'].pk,
            ),
        )
        for talk in assignment['talks']:
            talk['roles'] = sorted(set(talk['roles']))
        summarized_assignments.append(assignment)

    summarized_assignments.sort(key=lambda assignment: (
        assignment['session'].event.start_date or timezone.localdate(),
        assignment['session'].event.name,
        assignment['session'].program_day.date if assignment['session'].program_day else timezone.localdate(),
        assignment['session'].start_time or empty_time.min,
        assignment['session'].order,
        assignment['session'].pk,
    ))
    return summarized_assignments


def count_program_assignment_talks(assignments):
    return sum(len(assignment['talks']) for assignment in assignments)


def program_assignment_email_subject(assignments):
    events = {
        assignment['session'].event
        for assignment in assignments
    }
    if len(events) == 1:
        event = events.pop()
        return f"Program Participation Details - {event.name} {event.year}"
    return f"{getattr(settings, 'SITE_NAME', 'BSBCS')} Program Participation Details"


def send_program_assignment_email(person, event=None):
    if not person.email:
        return False, 'missing_email'

    assignments = build_program_assignment_summary(person, event=event)
    if not assignments:
        return False, 'missing_assignment'

    context = {
        'person': person,
        'assignments': assignments,
        'session_count': len(assignments),
        'talk_count': count_program_assignment_talks(assignments),
        'site_name': getattr(settings, 'SITE_NAME', 'BSBCS'),
        'support_email': getattr(settings, 'CONTACT_EMAIL', settings.DEFAULT_FROM_EMAIL),
    }
    html_message = render_to_string('emails/program_person_assignment_email.html', context)
    send_mail(
        subject=program_assignment_email_subject(assignments),
        message=strip_tags(html_message),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[person.email],
        html_message=html_message,
        fail_silently=False,
    )
    return True, assignments
