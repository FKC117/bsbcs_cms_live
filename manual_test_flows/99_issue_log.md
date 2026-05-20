# Manual Test Issue Log

Use this file as the shared place for bugs, abrupt behavior, and verification notes.

## Open Issues

| ID | Date/Time | Flow | Severity | Summary | Evidence | Status | Retest |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 001 | 2026-05-20 11:44-11:46 | U1 Public Website Browse | low | Local-only missing media files return 404. | User confirmed media exists on live but is not present in local test workspace. Functional pages returned 200. | closed | Ignore for local manual testing unless it appears on live. |
| 002 | 2026-05-20 11:50-11:53 | U2 Account Login, Logout, Password | medium | Password change page used old Bootstrap-era template instead of current BSBCS/Tailwind account style. | `/accounts/password_change/` returned 200 but rendered `change_password.html` with Bootstrap CDN and `form.as_p`; success page also used old Bootstrap card. | fixed | Retest `/accounts/password_change/` and successful password change done page. |
| 003 | 2026-05-20 11:55-11:56 | U2 Account Login, Logout, Password | medium | Password reset flow used old Bootstrap-era templates instead of current BSBCS/Tailwind account style. | `/accounts/password_reset/` and related reset templates used Bootstrap CDN, `main.css`, and old card markup. | fixed | Retest reset request, email-sent page, reset-token form, invalid token state, and completion page. |
| 004 | 2026-05-20 12:11-12:18 | U5 Regular Event Registration | medium | Event homepage showed separate Register Now and Register as Member CTAs; logged-out registration prompt did not present the expected regular/member fee choice cards. Mobile homepage CTA also sat awkwardly inside the hero color band. | Event homepage contained direct member-registration links. `/event/7/registration/` rendered a generic attention screen instead of prominent registration option cards. Hero/mobile CTA placement was visually abrupt. | fixed | Retest logged-out event homepage on desktop and mobile, confirm one centered CTA section appears directly below the hero image, click `Register Now`, verify regular/member fee cards and login/profile/member actions. |
| 005 | 2026-05-20 12:30-12:40 | Event Template Tailwind Migration | medium | Event website was still using Tailwind CDN and several legacy Bootstrap-style templates instead of the compiled BSBCS Tailwind system. | `gene_base.html` loaded Tailwind 2.2 CDN. Tailwind config did not scan Django templates. Several event templates still use Bootstrap-style classes and custom CSS. | in progress | Test `/event/7/home/` first as the migrated pure compiled-CSS event page; then migrate remaining event templates one by one. |
| 006 | 2026-05-20 13:45-13:53 | Public Website Membership Modal | medium | Membership benefits modal overlapped the fixed navbar on desktop and mobile. | Modal container centered against full viewport with insufficient top clearance for the fixed site header; on mobile the bottom-sheet style panel could start underneath the mobile header. | fixed | Retest homepage Join Society modal on desktop and mobile; confirm the modal starts below the header and actions remain visible. |
| 007 | 2026-05-20 14:20-14:35 | U5 Regular Event Registration | medium | Regular event registration form needed a cleaner design-system layout and suggestions for organization/department fields. | `/event/7/registration/?mode=regular` used generic crispy rendering and department was a model dropdown. Organization had no suggestion support despite existing historical data. | fixed | Retest authenticated regular registration form; type `a` in organization to see starts-with suggestions and type a department prefix to see department suggestions. |
| 008 | 2026-05-20 21:00-21:05 | Abstract Submission | medium | Abstract submission page used Bootstrap-era layout and had inconsistent word-limit validation. | Template loaded Bootstrap CDN and used `row`, `col-lg-*`, `card`, `btn` classes. Client limited total abstract body to 600 words, but server validation only checked Methods + Results against 400 words. | fixed | Retest authenticated approved participant abstract submission, word counter, over-limit block, and successful under-limit submission. |

## Verification Notes

### U1 Public Website Browse - 2026-05-20

- Flow: U1 Public Website Browse
- Tester/account: user, public browse
- Test time: approx. 2026-05-20 11:44-11:46 Asia/Dhaka
- Log window checked: `django.log` tail and recent warning/error scan; `payment.log` tail and error scan
- Related records: website/homepage/media/webinar/past-event/event image records
- What happened: User reported all pages seemed OK.
- Expected: Public pages return successfully with no 500/traceback and no broken critical assets.
- Finding: Functional pass. No `ERROR`, `Traceback`, or `Internal Server Error` found for this test window. Payment log had no new activity. Media 404 warnings are expected in the local workspace because live media files were not provided here.
- Fix needed: None for local manual testing.
- Retest steps: Ignore local media 404s unless the same missing files appear on live.

### U2 Account Login, Logout, Password - 2026-05-20

- Flow: U2 Account Login, Logout, Password
- Tester/account: user-tested authenticated account
- Test time: approx. 2026-05-20 11:50-11:53 Asia/Dhaka
- Log window checked: `django.log` for `/accounts/password_change/`; Django template render and `manage.py check`
- Related records: `templates/change_password.html`, `templates/password_change_done.html`
- What happened: User found `/accounts/password_change/` was visually inconsistent with the current Tailwind/account theme.
- Expected: Password change and success pages should match the current BSBCS account/profile styling.
- Finding: Confirmed. The password change and success templates were old Bootstrap-style pages.
- Fix needed: Replaced both templates with BSBCS account security pages; then adjusted the password change form to match the centered login-card layout for visual consistency.
- Retest steps: Reload `/accounts/password_change/`, confirm it visually matches the login card, submit invalid data to check validation styling, then complete a password change and verify `/accounts/password_change/done/`.

### U2 Password Reset Template Follow-up - 2026-05-20

- Flow: U2 Account Login, Logout, Password
- Tester/account: user-tested password reset page
- Test time: approx. 2026-05-20 11:55-11:56 Asia/Dhaka
- Log window checked: Django template render and `manage.py check`
- Related records: `templates/password_reset_form.html`, `templates/password_reset_done.html`, `templates/password_reset_confirm.html`, `templates/password_reset_complete.html`
- What happened: User found `/accounts/password_reset/` also used an old template.
- Expected: Password reset request, sent, confirm, invalid-link, and complete states should match current BSBCS account security styling.
- Finding: Confirmed. All password reset templates were Bootstrap-era.
- Fix needed: Replaced the full reset template set with BSBCS account security pages; then adjusted the reset request form to match the centered login-card layout for visual consistency.
- Retest steps: Open `/accounts/password_reset/`, confirm it visually matches the login card, submit an email, check `/accounts/password_reset/done/`, test a valid/invalid reset token if available, and confirm `/accounts/reset/done/`.

### U2-U4 Manual Test Pass - 2026-05-20

- Flow: U2 Account Login/Logout/Password, U3 Profile Creation/Profile, U4 Event Public Pages
- Tester/account: user-tested regular account
- Test time: approx. 2026-05-20 12:00-12:11 Asia/Dhaka
- Log window checked: `django.log` tail and targeted scan for account/profile/event URLs, `payment.log` tail and error scan
- Related records: account templates, profile views, event public views
- What happened: User reported U2 through U4 are done.
- Expected: Login/logout/password/profile/event pages should return 200/302 as appropriate without application errors.
- Finding: Functional pass. Recent account/profile/event requests returned normal 200/302 responses. No new `ERROR`, `Traceback`, `Internal Server Error`, `NoReverseMatch`, or `TemplateDoesNotExist` entries were found for this test window. `payment.log` had no new activity. Local media 404s are expected because media files are not present in this workspace. Browser probe `/.well-known/appspecific/com.chrome.devtools.json` returned 404 and is harmless.
- Fix needed: None from U2-U4 logs at this point.
- Retest steps: Continue with U5 Regular Event Registration.

### U5 Registration Entry Fix - 2026-05-20

- Flow: U5 Regular Event Registration
- Tester/account: logged-out visitor
- Test time: approx. 2026-05-20 12:11-12:18 Asia/Dhaka
- Log window checked: `django.log` for `/event/7/home/`, `/event/7/registration/`, and related account/profile redirects
- Related records: `templates/home.html`, `templates/registration_login_prompt.html`
- What happened: User found the event homepage showed both `Register Now` and `Register as Member`, the logged-out registration attempt needed the expected regular/member fee cards, and the mobile `Register Now` placement was awkward inside the hero color band.
- Expected: Event homepage should expose one centered `Register Now` entry point in its own section immediately below the hero image on desktop and mobile. The registration entry screen should explain regular and member registration fees with clear cards and actions.
- Finding: Confirmed. Homepage had direct member registration CTAs, duplicate registration button placements, and the logged-out prompt was too generic.
- Fix needed: Collapsed event homepage active registration CTAs to one `Register Now` link in a dedicated centered `event-primary-action` section below the hero. Removed the hero overlay/mobile strip CTA and the lower duplicate registration section. Rebuilt the logged-out registration prompt with member/regular fee cards, login/create-profile actions, member login, and membership application intent link. Switched the prompt page from Tailwind CDN to the project `site_main.css` system and placed member registration first.
- Retest steps: Open `/event/7/home/` logged out on desktop and mobile, confirm no `Register as Member` button appears, confirm `Register Now` is centered directly below the hero image, click `Register Now`, and confirm `/event/7/registration/` shows the member card first, regular card second, and correct actions.

### Template

### Event Tailwind Migration - 2026-05-20

- Flow: Event template migration alongside U5 registration testing
- Related records: `templates/gene_base.html`, `templates/home.html`, `templates/registration.html`, `static/js/tailwind.config.js`, `manual_test_flows/05_event_tailwind_template_migration.md`
- What happened: User noted the event website was not using the same Tailwind system as the rest of the site.
- Finding: Confirmed. The shared event base used Tailwind CDN, Tailwind config did not scan Django templates, and event registration templates mixed old Bootstrap-style classes/custom CSS.
- Fix in progress: Added Django templates to Tailwind content scanning. Updated `gene_base.html` to load `site_main.css` and added a temporary `legacy_event_styles` block so templates can opt out one by one. Migrated `home.html` and `registration.html` to opt out of the CDN and use compiled design-system classes.
- Verification: `npm run build:css` now succeeds and regenerated `static/css/site_main.css`. `python manage.py check` passes. `/event/7/home/` returns 200, uses `site_main.css`, does not load Tailwind CDN, and has one `Register Now`. `/event/7/registration/` returns 200, uses `site_main.css`, does not load Tailwind CDN, and shows the registration path choice.
- Retest steps: Test `/event/7/home/` and `/event/7/registration/` on desktop/mobile first. Remaining event templates will stay on the legacy fallback until migrated.

### Membership Modal Navbar Overlap - 2026-05-20

- Flow: Public website homepage membership CTA
- Related record: `templates/partials/membership_benefits_modal.html`
- What happened: User found the membership benefits modal overlapped with the fixed navbar on desktop and mobile.
- Finding: Confirmed from screenshots. The modal used full-viewport centering/bottom alignment without reserving header space.
- Fix: Increased modal z-index, aligned the modal panel from the top with explicit top padding for desktop and mobile, reduced max-height calculations to account for the header, and kept the action buttons visible inside the panel.
- Verification: `python manage.py check` passes. `/` returns 200 and includes the updated modal CSS. Desktop and mobile headless screenshots confirm the modal starts below the navbar instead of overlapping it.
- Retest steps: Open homepage, trigger `Join Society`, verify desktop and mobile modal clearance, close button, `Apply for Membership`, and `Maybe Later`.

### Regular Registration Form Redesign - 2026-05-20

- Flow: U5 Regular Event Registration
- Related records: `templates/registration.html`, `registration/forms.py`, `registration/views.py`, `static/css/site_main.css`
- What happened: User asked for the regular registration form to match the newer form style and provide suggestions for organization and department.
- Finding: Confirmed. The regular form relied on generic crispy output and had no autocomplete. Department was a model relation rendered as a standard form field.
- Fix: Rebuilt the regular form template as a design-system card with explicit field rows and error display. Added starts-with autocomplete dropdowns for organization and department. Organization suggestions come from existing participant organizations. Department suggestions come from existing department names. Typed departments are saved back to the event as `Department` records only during successful form save.
- Verification: `npm run build:css` passes. `python manage.py check` passes. Authenticated test-client request for `/event/7/registration/?mode=regular` returns 200 and includes `Participant Details`, organization suggestion JSON, department suggestion JSON, autocomplete markup, and starts-with filtering code.
- Note: A self-induced test-client `DisallowedHost: testserver` log entry occurred during verification before rerunning the client with `HTTP_HOST='127.0.0.1:8000'`; it is not a user-facing route error.
- Retest steps: Log in as a regular non-member user, open `/event/7/registration/?mode=regular`, type `a` in Organization, type a department prefix, select suggestions, and submit with valid data.

### Abstract Submission Redesign - 2026-05-20

- Flow: Abstract Submission
- Related records: `templates/abstract_submission.html`, `registration/forms.py`, `static/css/site_main.css`
- What happened: User flagged Bootstrap/design issues and possible word-count problems on `/event/7/abstract_submission/`.
- Finding: Confirmed. The page loaded Bootstrap CDN and used Bootstrap grid/card/button classes. Client-side validation enforced 600 total words across Introduction, Methods, Results, and Conclusion, while server-side validation only checked Methods + Results over 400 words.
- Fix: Rebuilt the page as a wider operational design-system layout. The writing form now gets the primary wide column, with guidelines, word counter, and review note in a right-side support column. Removed Bootstrap CDN/classes. Added a live 600-word total counter with section counts, progress bar, remaining words, and disabled submit when over limit. Updated server validation to enforce the same 600-word total rule.
- Verification: `npm run build:css` passes. `python manage.py check` passes. Authenticated approved participant request to `/event/7/abstract_submission/` returns 200, uses `site_main.css`, has no Tailwind/Bootstrap CDN, and includes `Abstract Details`, `abstract-word-progress`, and `Total: 0 / 600`. Server form test rejects 601 words with the matching 600-word error.
- Retest steps: Log in as an approved/paid participant, open `/event/7/abstract_submission/`, check desktop/mobile layout, confirm live counts update, confirm submit disables beyond 600 words, then submit a valid abstract under the limit.

- Flow:
- Tester/account:
- Test time:
- Log window checked:
- Related records:
- What happened:
- Expected:
- Finding:
- Fix needed:
- Retest steps:

## Log Review Commands

From project root:

```powershell
Get-Content django.log -Tail 200
Get-Content payment.log -Tail 200
Select-String -Path django.log -Pattern "ERROR","Traceback","Internal Server Error" -Context 3
Select-String -Path payment.log -Pattern "ERROR","Traceback","failed","exception" -Context 3
```

When you give me a test timestamp, I will inspect the relevant log window and match it against the flow, account, event, and payment/member/corporate records.
