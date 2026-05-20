# Manual Test Issue Log

Use this file as the shared place for bugs, abrupt behavior, and verification notes.

## Open Issues

| ID | Date/Time | Flow | Severity | Summary | Evidence | Status | Retest |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 001 | 2026-05-20 11:44-11:46 | U1 Public Website Browse | low | Local-only missing media files return 404. | User confirmed media exists on live but is not present in local test workspace. Functional pages returned 200. | closed | Ignore for local manual testing unless it appears on live. |
| 002 | 2026-05-20 11:50-11:53 | U2 Account Login, Logout, Password | medium | Password change page used old Bootstrap-era template instead of current BSBCS/Tailwind account style. | `/accounts/password_change/` returned 200 but rendered `change_password.html` with Bootstrap CDN and `form.as_p`; success page also used old Bootstrap card. | fixed | Retest `/accounts/password_change/` and successful password change done page. |
| 003 | 2026-05-20 11:55-11:56 | U2 Account Login, Logout, Password | medium | Password reset flow used old Bootstrap-era templates instead of current BSBCS/Tailwind account style. | `/accounts/password_reset/` and related reset templates used Bootstrap CDN, `main.css`, and old card markup. | fixed | Retest reset request, email-sent page, reset-token form, invalid token state, and completion page. |
| 004 | 2026-05-20 12:11-12:18 | U5 Regular Event Registration | medium | Event homepage showed separate Register Now and Register as Member CTAs; logged-out registration prompt did not present the expected regular/member fee choice cards. | Event homepage contained direct member-registration links. `/event/7/registration/` rendered a generic attention screen instead of prominent registration option cards. | fixed | Retest logged-out event homepage, click Register Now, verify regular/member fee cards and login/profile/member actions. |

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
- What happened: User found the event homepage showed both `Register Now` and `Register as Member`, and the logged-out registration attempt needed the expected regular/member fee cards.
- Expected: Event homepage should expose one `Register Now` entry point. The registration entry screen should explain regular and member registration fees with clear cards and actions.
- Finding: Confirmed. Homepage had direct member registration CTAs, and the logged-out prompt was too generic.
- Fix needed: Collapsed event homepage active registration CTAs to one `Register Now` link. Rebuilt the logged-out registration prompt with member/regular fee cards, login/create-profile actions, member login, and membership application intent link. Switched the prompt page from Tailwind CDN to the project `site_main.css` system and placed member registration first.
- Retest steps: Open `/event/7/home/` logged out, confirm no `Register as Member` button appears, click `Register Now`, and confirm `/event/7/registration/` shows the member card first, regular card second, and correct actions.

### Template

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
