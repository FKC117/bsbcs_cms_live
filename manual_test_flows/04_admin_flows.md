# Admin Manual Test Flows

Role: Django staff/admin operating event, membership, payment, corporate, content, and communication workflows.

## A1. Admin Access and Dashboard

- [ ] Open `/admin/`.
- [ ] Login as staff.
- [ ] Open `/admin/workflow-guide/`.
- [ ] Open `/dashboard/`.
- [ ] Test dashboard partials:
  - [ ] `/dashboard/attention-queue/`
  - [ ] `/dashboard/event-ledger/`
  - [ ] `/dashboard/participant-preview/`
  - [ ] `/dashboard/staff-activity/`

Expected:

- Staff pages require login.
- Dashboard loads without tracebacks.
- Attention queue links open correct admin/workflow targets.

Test notes:

- Result:
- Time:
- Admin account:
- Bugs/odd behavior:

## A2. Event Setup

- [ ] Create event under `Registration > Events`.
- [ ] Set active/upcoming/closed status.
- [ ] Set registration open/closed.
- [ ] Test all-users vs members-only audience.
- [ ] Test paid vs free event.
- [ ] Test member fee/free settings.
- [ ] Add logo/hero/modal images.

Expected:

- Public event cards/pages reflect admin settings.
- Registration buttons match event state.
- Fee rules match regular/member/corporate flows.

Test notes:

- Result:
- Time:
- Event:
- Bugs/odd behavior:

## A3. Participant Approval

- [ ] Open `Registration > Participants`.
- [ ] Filter pending participant.
- [ ] Approve selected participant.
- [ ] Deny selected participant.
- [ ] Confirm approval/payment email behavior.
- [ ] Confirm payment record creation for paid/free events.

Expected:

- Approved and denied flags remain mutually sane.
- Paid participant receives payment path.
- Free participant gets completed/zero payment or confirmation according to policy.

Test notes:

- Result:
- Time:
- Participant:
- Bugs/odd behavior:

## A4. Payment Admin

- [ ] Open `Registration > Payment Statuses`.
- [ ] Search by participant, invoice, transaction ID.
- [ ] Open related invoice.
- [ ] Open `Registration > Bkash Data`.
- [ ] Compare bKash status to app payment status.
- [ ] Open `Registration > Pending Payment Reminders`.
- [ ] Refresh and send reminder.

Expected:

- Payment status, bKash data, reminders, and invoice records are consistent.
- Reminder emails do not send to paid/completed participants.

Test notes:

- Result:
- Time:
- Payment:
- Bugs/odd behavior:

## A5. Registration Kit

- [ ] Open `Registration > Registration Kits`.
- [ ] Run populate kits action.
- [ ] Issue selected kits.
- [ ] Confirm kit status/date.

Expected:

- Kits are created only for eligible paid/free-completed participants.
- Re-running populate does not duplicate kits.

Test notes:

- Result:
- Time:
- Event:
- Bugs/odd behavior:

## A6. Membership Admin

- [ ] Open `Website > Membership Types`.
- [ ] Add/edit active membership type.
- [ ] Open `Website > Members`.
- [ ] Approve member.
- [ ] Reject member.
- [ ] Open `Website > Membership Payments`.
- [ ] Verify payment state.
- [ ] Open `Website > Pending Event Intents`.

Expected:

- Approval sends expected email.
- Rejection stores/communicates rejection reason if configured.
- Member active/expiry/payment state remains consistent.
- Pending event intent is visible and actionable.

Test notes:

- Result:
- Time:
- Member:
- Bugs/odd behavior:

## A7. Corporate Admin

- [ ] Open `Registration > Corporate Account Requests`.
- [ ] Approve request.
- [ ] Reject request.
- [ ] Open `Registration > Corporate Accounts`.
- [ ] Confirm linked user/account.
- [ ] Open `Registration > Corporate Event Registrations`.
- [ ] Approve all pending attendees.
- [ ] Open `Registration > Corporate Event Attendees`.
- [ ] Approve selected attendees.
- [ ] Deny selected attendees.
- [ ] Create corporate invoice/payment.
- [ ] Open `Registration > Corporate Payments`.
- [ ] Regenerate invoice PDF.
- [ ] Resend invoice email.

Expected:

- Corporate request approval creates/links account safely.
- Attendee approval creates/links participants.
- Denied attendees are excluded from invoice.
- Invoice totals and emails match approved attendees.

Test notes:

- Result:
- Time:
- Corporate account:
- Registration/payment:
- Bugs/odd behavior:

## A8. Abstract Admin

- [ ] Open `Registration > Abstract Submissions`.
- [ ] Approve for presentation.
- [ ] Approve for poster.
- [ ] Export as PDF.
- [ ] Upload abstract book.
- [ ] Upload notebook.

Expected:

- Approval flags update correctly.
- Approval email sends correct type.
- Uploaded books appear on event public page.

Test notes:

- Result:
- Time:
- Abstract:
- Bugs/odd behavior:

## A9. Program, Speaker, Sponsor, Media

- [ ] Add hall room.
- [ ] Add program day.
- [ ] Add time slot.
- [ ] Add program schedule.
- [ ] Add program person/session/session item.
- [ ] Add chairperson/moderator/panelist/featured speaker.
- [ ] Add sponsor.
- [ ] Add event image/video.
- [ ] Export/send schedule.

Expected:

- Public schedule and speaker pages render correctly.
- Export/email actions work after content is saved.
- Missing optional people/assets do not break pages.

Test notes:

- Result:
- Time:
- Event:
- Bugs/odd behavior:

## A10. Certificate and Feedback Admin

- [ ] Create certificate config.
- [ ] Add certificate signatories.
- [ ] Create feedback questions.
- [ ] Review feedback responses.
- [ ] Export responses.

Expected:

- Certificate generation has necessary event/signatory data.
- Feedback question ordering and required settings work.
- Export includes useful participant/event details.

Test notes:

- Result:
- Time:
- Event:
- Bugs/odd behavior:

## A11. Communication Admin

- [ ] Create email group.
- [ ] Create bulk email.
- [ ] Send to active users.
- [ ] Send to selected email group.
- [ ] Check bulk email reporting.
- [ ] Populate thank-you emails.
- [ ] Send thank-you emails.

Expected:

- Bulk send reports recipients and failures.
- Failed recipient handling is visible.
- Thank-you emails are not duplicated unexpectedly.

Test notes:

- Result:
- Time:
- Email/group:
- Bugs/odd behavior:

## A12. Website Content Admin

- [ ] Update site settings.
- [ ] Update navigation links.
- [ ] Update homepage hero/carousel/news/quick access/statistics.
- [ ] Update member directory supporting content.
- [ ] Create past event archive.
- [ ] Create publications/resources.
- [ ] Create webinar.
- [ ] Create media gallery item.

Expected:

- Public pages reflect active/order settings.
- Inactive content is hidden.
- Images/files show fallbacks when absent.

Test notes:

- Result:
- Time:
- Content record:
- Bugs/odd behavior:

## A13. Deployment/Emergency Checks

- [ ] `python manage.py check`
- [ ] `python manage.py showmigrations`
- [ ] `python manage.py migrate` if needed.
- [ ] `python manage.py collectstatic --noinput` if deploying static changes.
- [ ] Restart web server if deploying.
- [ ] Check `django.log`.
- [ ] Check web server error log if available.

Expected:

- Checks pass.
- Migrations are applied intentionally.
- No new tracebacks after restart.

Test notes:

- Result:
- Time:
- Commands:
- Bugs/odd behavior:
