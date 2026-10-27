# V-Check AICTE — REST API contract (v1)

> Independent demonstration prototype. Not an official AICTE portal. All data is synthetic.

Base URL: `http://127.0.0.1:8000/api/v1` · JSON everywhere (UTF-8) · Auth: `Authorization: Bearer <token>`.
This contract is implemented by `backend/vcheck_api` (stdlib WSGI + SQLite) and covered by `backend/tests_api`.
The web UI in `frontend/` uses it as-is; any later port (React, FastAPI) must keep it identical.

## Conventions

* **Errors**: `{"error": {"code": "...", "message": "human readable", "details": {...}?, "request_id": "..."}}`.
  Codes you will handle: `unauthorized`, `invalid_credentials`, `token_expired`, `token_revoked`, `invalid_token`, `forbidden`,
  `not_found`, `validation_error` (422, `details.fields`), `invalid_json`, `payload_too_large` (413), `not_editable`,
  `invalid_transition`, `confirmation_required` (409: resend with `"confirm": true`), `workflow_error` (422),
  `too_many_attempts` (429 + `Retry-After`), `internal_error` (500, never leaks internals).
* **Pagination**: `?page=1&page_size=10` → `{items, page, page_size, total}`.
* **Hidden resources return 404, not 403** (an applicant cannot learn that another applicant's application exists).
* **Time**: ISO-8601 UTC strings. **IDs**: applications `APP-007`, documents `DOC-…`, findings `VF-1010`.
* **Token expiry**: default 8 h (`TOKEN_TTL_MINUTES`). `POST /auth/logout` revokes the token server-side.
* **Document preview**: `GET /documents/{id}/file` needs the Bearer header, so fetch it with `fetch()` → `Blob` → `URL.createObjectURL()`
  and show that in an `<iframe>`/`<img>`. Files are never publicly addressable.
* **Upload**: `multipart/form-data` with `file` (+ optional `document_type`, `replaces`), or a raw body with `?filename=&document_type=`.
* **Async processing**: uploads return immediately (`status: queued`). Poll `GET /applications/{id}/documents` and
  `GET /applications/{id}` (`status: processing` → `review_required | validation_complete`) every 500–1000 ms.

## Roles

| Role | Can |
|---|---|
| `applicant` | create/edit own draft or corrections-requested applications, upload/replace/remove documents, submit/resubmit, pre-check, see own non-reviewer-only findings |
| `reviewer` | see all submitted applications, queue, triage findings, correct extracted fields, assign, comment, escalate, request correction, record **demonstration** decisions, audit, analytics, rules (read) |
| `admin` | everything a reviewer can see + assign reviewers, rule versions/enable-disable, system settings, demo reset. Cannot file applications or record decisions |

## Endpoints

| Method & path | Roles | Notes |
|---|---|---|
| `GET /health` · `GET /meta` | public | `meta` = disclaimer, application/document types, statuses, pipeline stage names, ruleset info, limits |
| `POST /auth/login` | public | `{email,password}` → `{token, expires_at, user{role,permissions[]}}`; 5 failures / 5 min → 429 |
| `POST /auth/logout` · `GET /auth/me` · `POST /auth/change-password` | any | password ≥ 10 chars, mixed case, digit |
| `GET /dashboard` | any | role-scoped `metrics`, `charts`, `recent_applications` (all from the DB) |
| `GET /analytics` | reviewer, admin | `sufficient_data=false` ⇒ show the empty state |
| `GET /applications` | any | filters: `q, status(csv), institution, application_type, severity, date_from, date_to, reviewer_id, sort(submitted\|oldest\|institution\|status), page, page_size` |
| `POST /applications` | applicant | `{institution{name,institution_id,state,district,address,contact_*}, application_type, academic_year, courses[{name,intake}], notes}` |
| `GET/PATCH /applications/{id}` | owner / staff | detail includes `required_documents[]` (from the rules), `allowed_transitions`, `decision`, `reviewed` |
| `POST /applications/{id}/submit` | applicant | 202; also used to **resubmit** after corrections |
| `POST /applications/{id}/validate` | applicant (editable only: pre-check) / reviewer / admin | re-runs the rules; status unchanged |
| `GET /applications/{id}/pipeline` | owner / staff | the 10 stages with status, **measured** `duration_ms`, result, evidence, errors; per-document stages; `verification[]` |
| `GET /applications/{id}/documents` · `POST …/documents` | owner / staff · applicant | |
| `POST /applications/{id}/demo-documents` | applicant | `{scenario}`; synthetic documents through the real pipeline; needs demo mode |
| `GET /applications/{id}/findings` · `GET /findings` · `GET /findings/{id}` | owner (no reviewer-only) / staff | filters `severity,status,outcome,rule_id,q` |
| `PATCH /findings/{id}` | reviewer | `{status: open\|under_review\|resolved\|accepted_with_explanation, note}`; note ≥ 5 chars to close |
| `GET /documents` · `GET /documents/{id}` · `GET /documents/{id}/file` · `DELETE /documents/{id}` | owner / staff | detail has `fields[]` with `page, line_no, snippet, confidence, bbox`; staff also get page text |
| `PATCH /documents/{id}/fields/{fid}` | reviewer | `{value}` (or `null` to reset). Original is kept; rules re-run |
| `GET /review/queue` | reviewer, admin | `scope=open\|mine\|unassigned\|corrections\|decided`, `q` |
| `GET /review/reviewers` | reviewer, admin | assignable reviewers |
| `POST /applications/{id}/review/actions` | reviewer (admin: assign only) | `{action: assign\|comment\|mark_reviewed\|escalate\|request_correction\|approve_demo\|reject_demo, remarks, confirm, reviewer_id}` |
| `GET /applications/{id}/review/history` | reviewer, admin | |
| `GET /verification` | reviewer, admin | per-application run summary + simulated-verification tally |
| `GET /rules` · `GET /rules/{id}` · `GET /rules/versions` | reviewer, admin | every rule has `kind: official \| demonstration` |
| `PATCH /rules/{id}` `{enabled, note}` · `POST /rules/versions` `{changes, new_version?, note}` | admin | creates a new immutable ruleset version (deterministic; only whitelisted fields) |
| `GET /audit` · `GET /audit/facets` | reviewer, admin | filters `user, role, action, object_type, application_id, result, q, date_from, date_to` |
| `GET/PUT /settings/profile` · `PUT /settings/notifications` · `GET /settings/system` | any | |
| `GET/PUT /settings/admin` | admin | `verification_mode (off\|simulation\|unavailable)`, `max_upload_mb`, `max_pdf_pages`, `demo_mode`; DigiLocker is listed as **not configured** |
| `GET /notifications` · `POST /notifications/read` | any | `{id?}` omitted = mark all read |
| `GET /demo/scenarios` · `POST /demo/reset` | any · admin | reset rebuilds only the six seeded scenarios |

## Vocabulary

* **Application status**: `draft, submitted, processing, validation_complete, review_required, corrections_requested, resubmitted, approved_demo, rejected_demo` — the last two are **demonstration outcomes**, always labelled "(demonstration only)".
* **Finding**: `outcome` = `failed | review_required`; `severity` = `high | medium | low | info`; `critical` = `high AND failed`; `status` = `open | under_review | resolved | accepted_with_explanation`;
  `reviewer_only` findings mention other institutions and are never returned to applicants.
* **Stage / document-step state**: `passed | review | failed | skipped | pending | running` (stages) and `done | review | failed | skipped | pending | running` (per-file steps). Never rely on colour alone: every state has a label.
* **Verification**: `display_status` is `simulated_match | not_found | mismatch | unavailable | error`. **`verified` is never produced for a simulation.**
* **Demo scenarios**: `clean, missing_occupancy, institution_id_mismatch, expired_affiliation, intake_conflict, duplicate_reuse`.
