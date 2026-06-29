# SMS, Phone Validation, And Country Dropdown Plan

## Objective

Prepare the live Django project for SMS integration by fixing phone-number quality, standardizing country input, and defining a safe rollout for existing live data.

The immediate business goal is:

- allow SMS only for Bangladesh mobile numbers that the gateway accepts
- stop new invalid phone and country data from entering the system
- clean existing live records without breaking current user and registration flows

## Why This Matters

The SMS gateway expects Bangladesh numbers in a strict format such as:

- `8801911269258`

The current app allows:

- arbitrary phone text
- inconsistent number formats
- free-text country names
- direct view-level saves that bypass form validation in some flows

That means SMS sending will be unreliable unless we first harden the data model and input flows.

## Current State

Observed issues in the codebase:

- `phone` and `country` are plain text fields in multiple models.
- country is still rendered as free text in key forms.
- phone uniqueness checks exist in some forms, but there is no centralized normalization.
- some views save raw `request.POST` values directly, which bypasses form-level cleanup.
- live data likely already contains:
  - text in phone fields
  - random or incomplete numbers
  - mixed Bangladesh formats like `017...`, `+880...`, `880...`
  - duplicate logical numbers after normalization

## Business Rules

### 1. Why We Keep Both `phone` And `country`

- `country` is profile and reporting data.
  - useful for attendee stats, filters, exports, and UI
- `phone` is contact-routing data.
  - used for SMS delivery and duplicate detection

We should keep both fields, but they serve different purposes.

### 2. SMS Eligibility Rule

For the first version, SMS should be allowed only when:

- `country == Bangladesh`
- normalized phone matches Bangladesh mobile format accepted by the gateway

Recommended canonical SMS format:

- `8801XXXXXXXXX`

### 3. Non-Bangladesh Users

Non-Bangladesh users should still be allowed in the system unless product policy says otherwise.

They can:

- register
- keep a country value
- keep a phone value

But they should be marked as:

- not SMS eligible

## Target State

After this work:

- country is selected from a dropdown, not typed freely
- Bangladesh phone numbers are normalized before save
- invalid phone input is rejected on all main entry flows
- existing live records are audited and grouped by fixability
- SMS sending logic relies on normalized phone data and eligibility checks

## Technical Decisions

### 1. Country Library

Install `django-countries` and use it for country choices in forms and UI.

Planned package:

- `django-countries`

Initial use:

- dropdown choice list in forms
- normalized country storage behavior

Decision note:

- we do not have to convert every existing model field to `CountryField` on day one
- we can first use dropdown choices and normalization on existing `CharField`s
- after data is stable, we can decide whether a later migration to `CountryField` is worth it

This staged approach reduces live migration risk.

### 2. Canonical Phone Strategy

We need one shared normalization rule for Bangladesh mobile numbers.

Accepted user input examples:

- `01911269258`
- `+8801911269258`
- `8801911269258`
- `880 1911 269258`
- `880-1911-269258`

Stored canonical value:

- `8801911269258`

Rejected examples:

- alphabetic text
- mixed text and digits
- too short or too long numbers
- numbers not matching Bangladesh mobile structure
- empty values where phone is required

### 3. Shared Validation Layer

Do not rely only on form `clean_phone()`.

Create a shared helper layer for:

- phone normalization
- Bangladesh phone validation
- country normalization
- SMS eligibility checks

Likely helper functions:

- `normalize_country_value(raw_country)`
- `normalize_bd_phone(raw_phone)`
- `is_valid_bd_mobile(phone)`
- `is_sms_eligible(country, phone)`

This helper must be used in:

- forms
- views that currently save raw POST values
- CSV import/manual attendee creation
- future SMS service code

## Rollout Plan

## Phase 1: Freeze New Bad Data

Goal:

- stop future bad records from entering the system before bulk cleanup starts

Tasks:

- add `django-countries` to `requirements.txt`
- create a shared country and phone normalization helper module
- replace free-text country inputs with dropdowns in key forms
- validate and normalize phone values in key forms
- patch direct-save views to use the same normalization rules
- show clear validation messages to users and admins

Success criteria:

- new or edited records cannot save junk phone values
- new or edited records cannot save arbitrary country text

## Phase 2: Audit Live Data

Goal:

- understand the current database quality before changing stored values

Create a management command or admin-safe report that scans relevant models and classifies records into:

- valid Bangladesh SMS-ready
- convertible Bangladesh numbers
- non-Bangladesh valid profiles
- invalid phone values
- missing phone or country
- duplicates after normalization

Relevant models likely include:

- `UserProfile`
- `Participant`
- `CorporateEventAttendee`
- `CorporateAccount`
- `CorporateAccountRequest`
- `ProgramPerson`
- any other model used as an SMS source later

Audit output should include:

- model name
- record id
- display name
- email if present
- raw phone
- normalized candidate phone
- country
- issue category

Success criteria:

- we have a complete cleanup report before mutating live records

## Phase 3: Safe Auto-Fix Pass

Goal:

- auto-correct only records that are clearly fixable

Auto-fix examples:

- `01712345678` -> `8801712345678`
- `+8801712345678` -> `8801712345678`
- remove spaces, dashes, and wrapping punctuation
- normalize country variants that clearly mean Bangladesh

Do not auto-fix:

- textual garbage
- ambiguous foreign numbers
- records that would collide with another record after normalization

For collision cases:

- keep them for manual review
- never silently overwrite or merge

Success criteria:

- obvious cases are corrected safely
- risky rows remain untouched for manual resolution

## Phase 4: Manual Review Queue

Goal:

- resolve the hard cases without hidden data loss

Manual-review buckets:

- duplicates after normalization
- invalid phone text
- impossible digit lengths
- country missing but phone looks Bangladeshi
- country says Bangladesh but phone is foreign or junk

Recommended admin actions:

- edit and correct phone
- mark phone unavailable
- confirm country
- choose the winning record in duplicate cases

Success criteria:

- remaining rows are either corrected or explicitly excluded from SMS

## Phase 5: SMS Readiness Layer

Goal:

- make SMS sending depend on clean rules rather than raw fields

Add an SMS eligibility rule used by the future gateway integration:

- send only if country is Bangladesh
- send only if normalized phone is valid and present

For all other cases:

- skip SMS
- log or surface a reason

Possible future flags:

- `sms_eligible`
- `sms_block_reason`

This can be implemented later either as:

- computed helper logic
- stored fields updated during cleanup/save

Recommendation:

- start with computed logic first
- add stored flags only if reporting or bulk SMS tools need them

## Country Dropdown Plan

### Short-Term Recommendation

Use `django-countries` for dropdown choices in all relevant forms while keeping existing model fields as `CharField` initially.

Why:

- faster rollout
- lower migration risk
- allows us to stabilize input first

### Later Option

If the first rollout is stable, consider migrating selected high-value models to `CountryField`.

Candidate models for later migration:

- `UserProfile`
- `Participant`

Not recommended in the first pass:

- convert every country field in every model immediately

## Data Model Strategy

### Phone

Short term:

- keep current `CharField`
- enforce canonical normalized value before save

Long term:

- if needed, introduce explicit helper methods or audit fields for original vs normalized values

### Country

Short term:

- keep current `CharField`
- restrict values through form dropdowns and normalization

Long term:

- optionally migrate selected models to `CountryField`

## Validation Rules

### Bangladesh Phone Validation

Recommended rules:

- strip whitespace and separators
- accept `017...` style local mobile input and convert to `88017...`
- accept `+880...` and convert to `880...`
- final stored value must match:
  - starts with `8801`
  - total length 13 digits

Examples that should pass:

- `01700000000`
- `+8801700000000`
- `8801700000000`

Stored result for all three:

- `8801700000000`

### Country Validation

Recommended rules:

- country must come from a predefined choice list
- store a consistent display value
- normalize known variants during cleanup

For Bangladesh:

- store as `Bangladesh`

## Entry Points To Update

The following areas need review during implementation because phone/country values are collected or saved there:

- user profile create flow
- user profile edit flow
- participant registration flow
- dashboard participant create flow
- corporate attendee manual entry
- corporate attendee CSV import
- program person quick-create flow
- any admin edit forms that expose phone/country

Also patch view logic that currently does direct `request.POST` saves.

## Testing Plan

### Unit Tests

Add tests for:

- Bangladesh phone normalization
- invalid phone rejection
- duplicate detection after normalization
- country dropdown validation
- SMS eligibility logic

### Flow Tests

Add tests for:

- profile creation with Bangladesh number
- profile update with invalid phone
- participant registration with `017...` saved as `88017...`
- country dropdown enforcing valid choices
- CSV/manual entry handling bad phone values safely

### Live Safety Checks

Before production cleanup:

- run audit command in report-only mode
- review collision cases
- back up database

Before enabling SMS sending:

- confirm at least one end-to-end record has clean Bangladesh phone data
- confirm skip behavior for ineligible records

## Risks And How To Reduce Them

### Risk 1: Duplicate Collisions After Normalization

Example:

- one row stores `01712345678`
- another row stores `8801712345678`

Both normalize to the same number.

Mitigation:

- detect collisions during audit
- do not auto-merge
- resolve manually

### Risk 2: Form Validation Alone Misses Some Saves

Mitigation:

- use shared normalization helpers
- patch direct-save views
- add tests for those flows

### Risk 3: Large Migration Scope

Mitigation:

- do input hardening first
- do audit second
- do targeted cleanup third
- postpone broad model-field migration until stable

## Recommended Implementation Order

1. Add `django-countries` dependency.
2. Create shared country and phone helper utilities.
3. Update country inputs to dropdowns in key forms.
4. Update phone validation and normalization in forms.
5. Patch direct-save views to reuse the same helper logic.
6. Add tests for normalization and blocked invalid inputs.
7. Build audit management command in report-only mode.
8. Review live data categories and duplicate collisions.
9. Run safe auto-fix mode for clearly convertible records.
10. Manually resolve remaining invalid or duplicate rows.
11. Add SMS eligibility logic to the SMS integration layer.

## Decisions We Should Confirm Before Coding

1. Should non-Bangladesh users still be allowed to save phone numbers normally, while simply being excluded from SMS?
2. Should Bangladesh phone be mandatory everywhere, or only on flows where phone is already required?
3. Should country continue to store the display label `Bangladesh`, or do we want ISO-style values under the hood later?
4. Which models will be used as SMS recipient sources first:
   - `UserProfile`
   - `Participant`
   - corporate attendee/contact tables
5. Do we want an admin dashboard report for invalid phone data, or is a management command enough for the first pass?

## Recommended First Resume Point

When implementation starts, begin with:

1. add `django-countries`
2. build shared normalization helpers
3. patch the highest-risk phone/country input flows
4. add the live audit command before any large cleanup
