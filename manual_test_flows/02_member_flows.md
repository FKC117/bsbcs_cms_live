# Member Manual Test Flows

Role: user applying for membership, active member, member event participant.

## M1. Membership Page and Benefits Modal

- [ ] Open `/membership-form/`.
- [ ] Confirm membership types are visible.
- [ ] Confirm membership benefit modal appears only when configured.
- [ ] Check homepage membership CTA/modal if enabled.

Expected:

- Active membership types show correct amount/duration.
- Disabled membership types do not appear.
- Benefit modal does not block the page incorrectly.

Test notes:

- Result:
- Time:
- Account:
- Bugs/odd behavior:

## M2. Membership Application

- [ ] Login as non-member.
- [ ] Open `/membership-form/`.
- [ ] Submit membership application.
- [ ] Confirm application received/success state.
- [ ] Try resubmitting with same account.

Expected:

- `Member` record is created or updated correctly.
- Duplicate submission is handled gracefully.
- Pending state is clear to user.

Test notes:

- Result:
- Time:
- Account:
- Member record:
- Bugs/odd behavior:

## M3. Membership Payment

- [ ] Start membership payment at `/membership/pay/`.
- [ ] Complete success callback if possible.
- [ ] Try failure/cancel path if possible.
- [ ] Confirm `/membership/payment-finalize/` behavior.

Expected:

- `MembershipPayment` amount matches selected membership type.
- Successful payment updates payment status.
- Failed payment gives retry path.
- No mismatch between payment and member activation state.

Test notes:

- Result:
- Time:
- Account:
- Membership payment:
- Bugs/odd behavior:

## M4. Admin Approval Effect on Member

This flow starts from admin action, then validates member-facing behavior.

- [ ] Admin approves pending member.
- [ ] Login as that member.
- [ ] Open `/profile/`.
- [ ] Open `/member-directory/`.
- [ ] Confirm member directory behavior if profile should be public.

Expected:

- Approved member has `approval_status=approved`.
- Active member has `is_active_member=True`.
- Expiry display is friendly when expiry is blank.

Test notes:

- Result:
- Time:
- Account:
- Member record:
- Bugs/odd behavior:

## M5. Member Event Registration

Use event with member registration enabled: `________`.

- [ ] Login as active member.
- [ ] Open `/event/<event_id>/member-registration/`.
- [ ] Submit member registration.
- [ ] Confirm amount/free status.
- [ ] Try duplicate member registration.

Expected:

- Active member can register.
- Fee uses `member_registration_fee` or free member setting.
- Duplicate registration shows existing state.
- If free, payment should be zero/completed or skipped according to event policy.

Test notes:

- Result:
- Time:
- Account:
- Event:
- Participant:
- Bugs/odd behavior:

## M6. Members-Only Event

Use members-only event ID: `________`.

- [ ] Open regular registration as non-member.
- [ ] Open member registration as non-member.
- [ ] Open member registration as pending member.
- [ ] Open member registration as active member.

Expected:

- Non-member is guided to membership.
- Pending member sees pending state, not a crash.
- Active member can register if event is open.
- Closed registration shows closed message.

Test notes:

- Result:
- Time:
- Accounts:
- Event:
- Bugs/odd behavior:

## M7. Pending Event Intent

- [ ] Start member event registration as a user who is not active member.
- [ ] Submit/apply for membership from the redirected flow.
- [ ] Admin approves membership.
- [ ] Check whether pending event intent resolves or remains pending.

Expected:

- `PendingEventIntent` records the user/event intent.
- After membership approval, participant creation/next action is clear.
- No silent failure if event registration closes before approval.

Test notes:

- Result:
- Time:
- Account:
- Event:
- Pending intent:
- Bugs/odd behavior:
