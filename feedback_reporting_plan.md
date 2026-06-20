# Feedback Reporting And Admin Insights Plan

## Goal
Build a proper admin-facing feedback reporting flow for event feedback forms, while also improving how question options are stored and rendered for participants.

## Current State
- Participant feedback form is now styled with the local Tailwind/site design system.
- Participant certificate download currently depends on feedback submission plus approval, payment completion, and issued kit status.
- Feedback questions are created from Certificate Center.
- Feedback responses are stored in `FeedbackResponse`.
- Radio and matrix questions currently depend on `columns` and `rows`, but radio options are not collected explicitly in the builder UX.

## Main Problems To Solve
1. Radio question options are not clearly modeled in the builder workflow.
2. Matrix and radio question data can be incomplete, which makes the public form brittle.
3. Admins do not have a useful event-level report showing who submitted feedback and what they answered.
4. There is no strong extraction layer for summarizing, exporting, or analyzing feedback results.

## Workstreams

### 1. Question Builder Hardening
- Add explicit builder support for radio choices.
- Keep matrix rows and columns as separate structured inputs.
- Validate question data before saving.
- Prevent saving radio questions without choices.
- Prevent saving matrix questions without both rows and columns.
- Preserve compatibility with old saved questions.

### 2. Participant Feedback Form Reliability
- Remove fallback-only dependence over time by improving saved data quality.
- Keep safe display fallbacks for legacy questions.
- Show question type-specific UI consistently for text, radio, and matrix questions.
- Add clearer empty-state messaging if a malformed question is encountered.

### 3. Admin Feedback Report Screen
- Create a dedicated admin/dashboard report view per event.
- Show participant-level submission status:
  - participant name
  - email
  - invoice / registration reference
  - approval status
  - payment status
  - kit status
  - feedback submitted or not
  - submission time
- Show answer drill-down for each participant.
- Allow filtering by submitted / pending / issued-kit / approved / paid.
- Allow searching by participant name, email, phone, invoice.

### 4. Answer Review UX
- For text questions: show the full answer cleanly.
- For radio questions: show the selected option.
- For matrix questions: show row-by-row selections in a readable table.
- Add a participant details drawer/modal or expandable row for quick review.
- Keep the first version simple and tabular.

### 5. Reporting Aggregation
- Add per-question summary blocks for admins.
- Text questions:
  - response count
  - raw answer list
- Radio questions:
  - option counts
  - percentages
- Matrix questions:
  - row/column distribution table
  - counts per score/column
- Scope aggregation by event.

### 6. Export / Data Extraction
- Add CSV export for participant-level responses.
- Add summary export for aggregated question results.
- Consider XLSX export later if needed.
- Make exports filter-aware if possible.

## Recommended Delivery Phases

### Phase 1: Data Integrity
- Update feedback question builder to support radio options explicitly.
- Normalize legacy rendering logic.
- Add validation rules for malformed question setup.

### Phase 2: Admin Report MVP
- Create an event feedback report page in Certificate Center or a linked dashboard page.
- Show participant submission table.
- Show participant answers in expandable detail.
- Add filters and search.

### Phase 3: Aggregated Insights
- Add per-question stats cards / tables.
- Add radio and matrix summaries.
- Add text answer review area.

### Phase 4: Export Layer
- Add CSV export for participant-level answers.
- Add summarized export for event organizers.

## Suggested Data / Backend Changes
- Keep using `FeedbackQuestion` and `FeedbackResponse` initially.
- Short term:
  - treat radio options as `columns` internally, but expose them clearly in the builder.
- Medium term option:
  - introduce a structured related model for question options if needed.
- Consider adding `submitted_at` to feedback submission tracking if per-response timestamps are not enough.
- Consider a grouped submission concept if we need a single submission record per participant/event.

## Suggested UI Placement
- Keep the participant feedback builder inside Certificate Center.
- Add a new admin subsection or linked page named something like `Feedback reports` or `Feedback responses`.
- Keep question-building and response-review separate to avoid crowding the builder UI.

## Open Questions For Later
- Should admins review feedback only inside Certificate Center, or from a separate dashboard page?
- Do we need downloadable PDF reports, or are CSV/XLSX exports enough?
- Should we show only eligible participants in the report, or all registered participants?
- Do we need charts, or is tabular summary enough for v1?
- Should resubmission be allowed for feedback, or remain single-submit only?

## Recommended First Resume Point
When we return to this task, start with:
1. Add explicit radio-choice input support in the feedback builder.
2. Build the admin participant response table for one event.
3. Add expandable participant answer review.
4. Add CSV export.

## Files Likely To Change Later
- `registration/models.py`
- `registration/views.py`
- `registration/admin.py`
- `templates/dashboard_certificate_center.html`
- new template for feedback reporting page
- optional export helper/service file
