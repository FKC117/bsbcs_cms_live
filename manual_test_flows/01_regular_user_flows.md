# Regular User Manual Test Flows

Role: public visitor, registered user, normal event participant.

## U1. Public Website Browse

- [ ] Open homepage `/`.
- [ ] Open About `/about/`.
- [ ] Open Events `/events/`.
- [ ] Open Media Gallery `/media-gallery/`.
- [ ] Open Research and Publications `/research-and-publications/`.
- [ ] Open Webinars `/webinars/`.
- [ ] Open Past Events `/past-events/`.
- [ ] Open Sitemap `/sitemap/`.

Expected:

- Pages load without 500/404 errors.
- Header, footer, navigation, images, and links are usable on desktop/mobile.
- Empty content sections show graceful fallback, not broken layout.

Test notes:

- Result:
- Time:
- Account:
- Bugs/odd behavior:

## U2. Account Login, Logout, Password

- [ ] Open login `/accounts/login/`.
- [ ] Login with valid user.
- [ ] Logout `/accounts/logout/`.
- [ ] Try wrong password.
- [ ] Open password reset `/accounts/password_reset/`.
- [ ] Open password change `/accounts/password_change/` after login.

Expected:

- Valid login redirects correctly.
- Invalid login shows safe error message.
- Password reset sends email or shows expected success screen.
- Password change requires login and redirects to done page.

Test notes:

- Result:
- Time:
- Account:
- Bugs/odd behavior:

## U3. Profile Creation

- [ ] Login with a user without profile.
- [ ] Open `/create-profile/`.
- [ ] Submit required profile fields.
- [ ] Upload profile image if available.
- [ ] Open `/profile/`.

Expected:

- Profile saves successfully.
- Required fields are validated.
- Profile page shows saved user data.
- Redirect with `next=` works when profile creation is required before registration.

Test notes:

- Result:
- Time:
- Account:
- Bugs/odd behavior:

## U4. Event Public Pages

Use one active event ID: `________`.

- [ ] Open `/event/<event_id>/home/`.
- [ ] Open `/event/<event_id>/about/`.
- [ ] Open `/event/<event_id>/speakers/`.
- [ ] Open `/event/<event_id>/schedule/`.
- [ ] Open `/event/<event_id>/sponsors/`.
- [ ] Open `/event/<event_id>/participants/`.
- [ ] Open `/event/<event_id>/gallery/`.
- [ ] Open `/event/<event_id>/publication_list/`.
- [ ] Try `/event/<event_id>/download-abstract/`.

Expected:

- Event details, images, schedule, sponsors, gallery, publications, and participants load correctly.
- Missing optional content does not break the page.
- Downloads either work or show a friendly error.

Test notes:

- Result:
- Time:
- Account:
- Event:
- Bugs/odd behavior:

## U5. Regular Event Registration

Use one open regular event ID: `________`.

- [ ] Open `/event/<event_id>/registration/` while logged out.
- [ ] Confirm login/profile guidance.
- [ ] Login and open registration again.
- [ ] Submit registration form.
- [ ] Confirm submitted page `/event/<event_id>/registration_submitted/`.
- [ ] Try duplicate registration with same account/email.

Expected:

- Logged out user is guided to login/create profile.
- Registration creates one `Participant`.
- Duplicate registration shows correct existing registration state.
- Admin can later approve/deny this participant.

Test notes:

- Result:
- Time:
- Account:
- Event:
- Participant:
- Bugs/odd behavior:

## U6. Individual Payment

Use approved paid participant ID: `________`.

- [ ] Open `/event/<event_id>/payment/<participant_id>/`.
- [ ] Start bKash payment.
- [ ] Complete success callback if test credentials are available.
- [ ] Try failure/cancel path if possible.
- [ ] Open finalize URL `/event/<event_id>/finalize-payment/<participant_id>/`.

Expected:

- Payment amount matches event fee.
- Payment success updates `PaymentStatus` and creates invoice.
- Failed payment leaves clear retry path.
- `payment.log` and `django.log` contain no traceback.

Test notes:

- Result:
- Time:
- Account:
- Event:
- Participant:
- Payment ID/invoice:
- Bugs/odd behavior:

## U7. Abstract Submission

Use event ID with abstract submission enabled: `________`.

- [ ] Open `/event/<event_id>/abstract_submission/` while logged out.
- [ ] Login and submit abstract.
- [ ] Upload image/file if applicable.
- [ ] Confirm `/event/<event_id>/submission_success/`.

Expected:

- Logged out user receives login/signup guidance.
- Abstract saves once.
- User receives submission confirmation email if configured.

Test notes:

- Result:
- Time:
- Account:
- Event:
- Abstract:
- Bugs/odd behavior:

## U8. Feedback and Certificate

Use approved/paid participant account.

- [ ] Open `/event/<event_id>/feedback/`.
- [ ] Submit required feedback.
- [ ] Try duplicate feedback if policy blocks duplicates.
- [ ] Open `/event/<event_id>/generate_certificate/`.

Expected:

- Feedback questions render by type.
- Required validation works.
- Certificate generates only for eligible participant.
- Ineligible user sees access denied/friendly error.

Test notes:

- Result:
- Time:
- Account:
- Event:
- Participant:
- Bugs/odd behavior:
