# Manual Test Flow Tracker

Use these files to test the application one flow at a time. After each test, add your result, screenshots if any, and the time you tested. I will use that timestamp to inspect `django.log`, `payment.log`, related database records, and code paths for abrupt behavior or bugs.

## Files

- `01_regular_user_flows.md` - public visitor and normal participant flows.
- `02_member_flows.md` - membership application, payment, member event registration, and member benefits.
- `03_corporate_user_flows.md` - corporate access, corporate dashboard, attendee upload, invoice, and payment.
- `04_admin_flows.md` - admin setup, approvals, payments, content, communication, and monitoring.
- `99_issue_log.md` - shared issue list and verification notes.

## Test Note Format

For each flow, record:

- Test date/time:
- Tester/account:
- URL:
- Input used:
- Expected result:
- Actual result:
- Screenshot/video:
- Severity: blocker / high / medium / low
- Notes:

## Log Capture Targets

Primary logs:

- `django.log`
- `payment.log`

Useful timestamps:

- Start time of test.
- Exact time of error or strange behavior.
- User email/phone used.
- Event ID/name.
- Participant/member/corporate account/payment ID if visible.

## Verification Workflow

1. You test one checklist item.
2. You report pass/fail with the time and what happened.
3. I inspect logs, affected records, and code paths.
4. I update `99_issue_log.md` with findings.
5. If there is a bug, I fix it and note what to retest.
