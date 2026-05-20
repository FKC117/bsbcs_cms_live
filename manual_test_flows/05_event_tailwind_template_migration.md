# Event Template Tailwind Migration Checklist

Goal: bring the event website onto the same compiled Tailwind/design-system path as the main site while manual testing continues.

## T0 Shared Event Shell

- [x] Use `static/css/site_main.css` from `gene_base.html`.
- [x] Add Django templates to Tailwind content scanning.
- [x] Keep required third-party assets only when still used, such as Font Awesome icons.
- [x] Add temporary `legacy_event_styles` block so templates can opt out one by one without breaking current manual testing.
- [x] Rebuild `static/css/site_main.css` after adding Django templates to Tailwind scanning.
- [x] Verify event home loads without Tailwind CDN.

## T1 Public Event Pages

- [x] `home.html`: remove old/duplicate CTA patterns and align hero/primary CTA to design-system spacing.
- [ ] `about.html`: remove inline CSS and normalize content layout.
- [ ] `invitation.html`: normalize invitation grid/cards.
- [ ] `speakers.html`: normalize cards and modal styling.
- [ ] `schedule.html`: normalize tables/cards and mobile behavior.
- [ ] `sponsor_list.html`: normalize sponsor cards.
- [ ] `event_gallery.html`: normalize gallery grid and image cards.
- [ ] `participant_list.html`: normalize list/table/card views.
- [ ] `publication_list.html` and `publication_detail.html`: normalize publication views.

## T2 Registration And Account-Adjacent Event Pages

- [ ] `registration_login_prompt.html`: confirm it uses compiled CSS only.
- [x] `registration.html`: remove Bootstrap-style `container`, custom CSS, and mixed form layout.
- [x] `registration.html`: redesign regular registration form as a symmetrical design-system card.
- [x] `registration.html`: add starts-with suggestions for organization and department fields.
- [ ] `registration_submitted.html`: normalize success/pending state.
- [ ] `registration_message.html`: normalize message state.
- [ ] `registration_error.html`: normalize error state.
- [ ] `registration_badge_download.html`: normalize badge/certificate download state.

## T3 Feedback And Abstract Flow

- [ ] `event_feedback.html`: replace Bootstrap grid/form/table classes with Tailwind classes.
- [ ] `abstract_submission.html`: remove Bootstrap CDN and Bootstrap grid/card/form classes.

## T4 Corporate Event Registration

- [ ] `corporate_event_registration.html`: migrate custom card/button/table CSS to compiled Tailwind classes.
- [ ] Verify corporate user flow after migration.

## Verification Rhythm

- [ ] Run `python manage.py check` after each slice.
- [ ] HTTP-check the changed route(s).
- [ ] Check `django.log` for template/runtime errors.
- [ ] Record bugs/fixes in `99_issue_log.md`.
