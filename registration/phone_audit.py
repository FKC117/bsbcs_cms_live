from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable

from django.core.exceptions import ValidationError

from .forms import DEFAULT_COUNTRY, normalize_country_name, normalize_phone_number
from .models import (
    Chairperson,
    CorporateAccount,
    CorporateAccountRequest,
    CorporateEventAttendee,
    Moderator,
    Panelist,
    Participant,
    ProgramPerson,
    UserProfile,
)


@dataclass(frozen=True)
class AuditSpec:
    key: str
    model: type
    label: str
    phone_attr: str
    country_attr: str
    name_getter: Callable[[object], str]
    email_getter: Callable[[object], str]
    scope_getter: Callable[[object], str]


COUNTRY_AUDIT_ALIASES = {
    'bd': DEFAULT_COUNTRY,
    'b.d.': DEFAULT_COUNTRY,
    'b d': DEFAULT_COUNTRY,
    'bangla': DEFAULT_COUNTRY,
}


def normalize_country_for_audit(raw_country):
    value = (raw_country or '').strip()
    normalized = normalize_country_name(value)
    if normalized:
        return normalized, ''
    alias_match = COUNTRY_AUDIT_ALIASES.get(value.casefold())
    if alias_match:
        return alias_match, 'convertible_country'
    if value:
        return '', 'invalid_country'
    return '', 'missing_country'


AUDIT_SPECS = (
    AuditSpec(
        key='user_profile',
        model=UserProfile,
        label='UserProfile',
        phone_attr='phone',
        country_attr='country',
        name_getter=lambda obj: obj.name or '',
        email_getter=lambda obj: obj.email or '',
        scope_getter=lambda obj: 'global',
    ),
    AuditSpec(
        key='participant',
        model=Participant,
        label='Participant',
        phone_attr='phone',
        country_attr='country',
        name_getter=lambda obj: obj.name or '',
        email_getter=lambda obj: obj.email or '',
        scope_getter=lambda obj: f'event:{obj.event_id}',
    ),
    AuditSpec(
        key='corporate_attendee',
        model=CorporateEventAttendee,
        label='CorporateEventAttendee',
        phone_attr='phone',
        country_attr='country',
        name_getter=lambda obj: obj.name or '',
        email_getter=lambda obj: obj.email or '',
        scope_getter=lambda obj: f'event:{obj.registration.event_id}',
    ),
    AuditSpec(
        key='corporate_account',
        model=CorporateAccount,
        label='CorporateAccount',
        phone_attr='phone',
        country_attr='phone',
        name_getter=lambda obj: obj.contact_name or obj.company_name or '',
        email_getter=lambda obj: obj.email or '',
        scope_getter=lambda obj: 'global',
    ),
    AuditSpec(
        key='corporate_account_request',
        model=CorporateAccountRequest,
        label='CorporateAccountRequest',
        phone_attr='phone',
        country_attr='phone',
        name_getter=lambda obj: obj.contact_name or obj.company_name or '',
        email_getter=lambda obj: obj.email or '',
        scope_getter=lambda obj: 'global',
    ),
    AuditSpec(
        key='program_person',
        model=ProgramPerson,
        label='ProgramPerson',
        phone_attr='phone',
        country_attr='country',
        name_getter=lambda obj: obj.name or '',
        email_getter=lambda obj: obj.email or '',
        scope_getter=lambda obj: 'global',
    ),
    AuditSpec(
        key='chairperson',
        model=Chairperson,
        label='Chairperson',
        phone_attr='phone',
        country_attr='country',
        name_getter=lambda obj: obj.name or '',
        email_getter=lambda obj: obj.email or '',
        scope_getter=lambda obj: f'event:{obj.event_id}',
    ),
    AuditSpec(
        key='panelist',
        model=Panelist,
        label='Panelist',
        phone_attr='phone',
        country_attr='country',
        name_getter=lambda obj: obj.name or '',
        email_getter=lambda obj: obj.email or '',
        scope_getter=lambda obj: f'event:{obj.event_id}',
    ),
    AuditSpec(
        key='moderator',
        model=Moderator,
        label='Moderator',
        phone_attr='phone',
        country_attr='country',
        name_getter=lambda obj: obj.name or '',
        email_getter=lambda obj: obj.email or '',
        scope_getter=lambda obj: f'event:{obj.event_id}',
    ),
)

SPEC_BY_KEY = {spec.key: spec for spec in AUDIT_SPECS}


def _selected_specs(selected_models=None):
    selected = set(selected_models or [])
    if not selected:
        return AUDIT_SPECS
    return tuple(spec for spec in AUDIT_SPECS if spec.key in selected)


def _classify_row(spec, obj):
    raw_phone = (getattr(obj, spec.phone_attr, '') or '').strip()
    raw_country = (getattr(obj, spec.country_attr, '') or '').strip()
    issues = []
    normalized_phone = ''
    status = 'valid'

    if spec.country_attr == 'phone':
        normalized_country = ''
        country_issue = ''
        raw_country = ''
    else:
        normalized_country, country_issue = normalize_country_for_audit(raw_country)
        if country_issue:
            issues.append(country_issue)

    if not raw_phone:
        issues.append('missing_phone')

    audit_country = normalized_country if spec.country_attr != 'phone' else ''
    if raw_phone:
        try:
            normalized_phone = normalize_phone_number(raw_phone, audit_country)
        except ValidationError as exc:
            issues.append('invalid_phone')
            phone_error = exc.messages[0] if exc.messages else str(exc)
        else:
            phone_error = ''
            if normalized_country == DEFAULT_COUNTRY:
                status = 'sms_ready_bd' if raw_phone == normalized_phone else 'convertible_bd'
            elif spec.country_attr == 'phone':
                status = 'valid_generic'
            else:
                status = 'non_bd_valid'
    else:
        phone_error = ''

    if issues:
        status = 'needs_review'

    return {
        'model_key': spec.key,
        'model_label': spec.label,
        'id': obj.pk,
        'scope': spec.scope_getter(obj),
        'name': spec.name_getter(obj),
        'email': spec.email_getter(obj),
        'raw_country': raw_country,
        'normalized_country': normalized_country,
        'raw_phone': raw_phone,
        'normalized_phone': normalized_phone,
        'status': status,
        'issues': issues,
        'phone_error': phone_error,
    }


def run_phone_audit(selected_models=None, include_valid=False):
    rows = []
    duplicates = defaultdict(list)

    for spec in _selected_specs(selected_models):
        queryset = spec.model.objects.all().order_by('pk')
        if spec.key == 'corporate_attendee':
            queryset = queryset.select_related('registration__event')
        elif spec.key in {'participant', 'chairperson', 'panelist', 'moderator'}:
            queryset = queryset.select_related('event')

        for obj in queryset.iterator():
            row = _classify_row(spec, obj)
            rows.append(row)
            if row['normalized_phone']:
                duplicate_key = (row['model_key'], row['scope'], row['normalized_phone'])
                duplicates[duplicate_key].append(row)

    duplicate_groups = []
    for duplicate_key, duplicate_rows in duplicates.items():
        if len(duplicate_rows) < 2:
            continue
        duplicate_groups.append({
            'model_key': duplicate_key[0],
            'scope': duplicate_key[1],
            'normalized_phone': duplicate_key[2],
            'record_ids': [row['id'] for row in duplicate_rows],
        })
        for row in duplicate_rows:
            if 'duplicate_normalized_phone' not in row['issues']:
                row['issues'].append('duplicate_normalized_phone')
                row['status'] = 'needs_review'

    issue_counter = Counter()
    status_counter = Counter()
    model_counter = Counter()
    filtered_rows = []
    for row in rows:
        status_counter[row['status']] += 1
        model_counter[row['model_label']] += 1
        for issue in row['issues']:
            issue_counter[issue] += 1
        if include_valid or row['issues']:
            filtered_rows.append(row)

    return {
        'summary': {
            'total_records': len(rows),
            'returned_records': len(filtered_rows),
            'status_counts': dict(status_counter),
            'issue_counts': dict(issue_counter),
            'model_counts': dict(model_counter),
            'duplicate_group_count': len(duplicate_groups),
        },
        'rows': filtered_rows,
        'duplicate_groups': duplicate_groups,
    }


def build_phone_fix_report(selected_models=None):
    audit_report = run_phone_audit(selected_models=selected_models, include_valid=True)
    fix_candidates = []
    skipped_due_to_duplicate = 0

    for row in audit_report['rows']:
        if row['model_key'] not in SPEC_BY_KEY:
            continue
        if row['normalized_country'] != DEFAULT_COUNTRY:
            continue
        if not row['normalized_phone'] or row['raw_phone'] == row['normalized_phone']:
            continue
        if 'invalid_phone' in row['issues'] or 'missing_phone' in row['issues']:
            continue
        if 'duplicate_normalized_phone' in row['issues']:
            skipped_due_to_duplicate += 1
            continue
        fix_candidates.append({
            'model_key': row['model_key'],
            'model_label': row['model_label'],
            'id': row['id'],
            'scope': row['scope'],
            'name': row['name'],
            'email': row['email'],
            'country': row['normalized_country'],
            'raw_phone': row['raw_phone'],
            'normalized_phone': row['normalized_phone'],
            'issues': list(row['issues']),
        })

    return {
        'summary': {
            'candidate_count': len(fix_candidates),
            'skipped_due_to_duplicate': skipped_due_to_duplicate,
        },
        'candidates': fix_candidates,
    }


def apply_phone_fixes(selected_models=None):
    report = build_phone_fix_report(selected_models=selected_models)
    updated = []

    for candidate in report['candidates']:
        spec = SPEC_BY_KEY[candidate['model_key']]
        obj = spec.model.objects.get(pk=candidate['id'])
        setattr(obj, spec.phone_attr, candidate['normalized_phone'])
        obj.save(update_fields=[spec.phone_attr])
        updated.append(candidate)

    return {
        'summary': {
            **report['summary'],
            'updated_count': len(updated),
        },
        'updated': updated,
    }
