# Corporate User Manual Test Flows

Role: company contact requesting access, logging in, registering attendees, and paying corporate invoice.

## C1. Corporate Access Request

- [ ] Open `/corporate-access/`.
- [ ] Submit company/contact details.
- [ ] Confirm `/corporate-access/received/`.
- [ ] Try duplicate request with same email.

Expected:

- `CorporateAccountRequest` is created as pending.
- Required fields validate cleanly.
- Duplicate request behavior is clear.

Test notes:

- Result:
- Time:
- Corporate email:
- Request record:
- Bugs/odd behavior:

## C2. Corporate Login Before and After Approval

- [ ] Try `/corporate/login/` before admin approval.
- [ ] Admin approves corporate request.
- [ ] Check approval email.
- [ ] Login at `/corporate/login/`.
- [ ] Open `/corporate/dashboard/`.

Expected:

- Unapproved corporate user cannot access dashboard.
- Approved request creates/links `User` and `CorporateAccount`.
- Corporate dashboard shows allowed events/actions.

Test notes:

- Result:
- Time:
- Corporate email:
- Corporate account:
- Bugs/odd behavior:

## C3. Corporate Event Registration Page

Use open event ID: `________`.

- [ ] Login as approved corporate user.
- [ ] Open `/corporate/events/<event_id>/registration/`.
- [ ] Download template `/corporate/events/<event_id>/template.csv`.
- [ ] Submit a small manual attendee list.
- [ ] Submit CSV attendee list.

Expected:

- Template downloads with correct headers.
- Manual rows and CSV rows parse correctly.
- Bad CSV rows show useful validation errors.
- Submission creates `CorporateEventRegistration` and attendees.

Test notes:

- Result:
- Time:
- Corporate account:
- Event:
- Registration:
- Bugs/odd behavior:

## C4. Attendee Detection Rules

Use attendee rows covering:

- [ ] Existing normal user.
- [ ] Active member.
- [ ] Pending member.
- [ ] New user.
- [ ] Duplicate email in same list.
- [ ] Already registered participant.

Expected:

- Matched user/member detection is visible to admin.
- Active members receive member fee/free logic.
- Duplicate/conflict notes are clear.
- No attendee silently disappears.

Test notes:

- Result:
- Time:
- Corporate account:
- Event:
- Attendees:
- Bugs/odd behavior:

## C5. Corporate Invoice and Email

This flow starts after admin approves selected attendees.

- [ ] Confirm approved attendees appear in corporate dashboard.
- [ ] Confirm denied attendees are excluded.
- [ ] Open corporate payment URL from email/dashboard.
- [ ] Open invoice URL `/corporate/payments/<payment_id>/invoice/`.

Expected:

- Invoice includes approved attendees only.
- Total amount equals attendee fee sum.
- Corporate contact receives invoice/payment email.
- Participant confirmation emails are sent without individual payment links.

Test notes:

- Result:
- Time:
- Corporate account:
- Event:
- Corporate payment:
- Bugs/odd behavior:

## C6. Corporate Payment

Use corporate payment ID: `________`.

- [ ] Open `/corporate/payments/<payment_id>/`.
- [ ] Start bKash payment.
- [ ] Complete success callback if possible.
- [ ] Try failure/cancel path if possible.
- [ ] Confirm `/corporate/payments/<payment_id>/finalize/`.

Expected:

- Payment amount matches invoice.
- Success updates `CorporatePayment`.
- Failed payment gives retry path.
- Related attendees/participants remain consistent.

Test notes:

- Result:
- Time:
- Corporate account:
- Corporate payment:
- Transaction:
- Bugs/odd behavior:

## C7. Corporate Dashboard Regression

- [ ] Open `/corporate/dashboard/` with no registrations.
- [ ] Open after one submitted registration.
- [ ] Open after partial approvals.
- [ ] Open after invoice created.
- [ ] Open after payment completed.

Expected:

- Dashboard state changes are clear.
- No broken links for invoice/payment/event actions.
- Counts match admin records.

Test notes:

- Result:
- Time:
- Corporate account:
- Bugs/odd behavior:
