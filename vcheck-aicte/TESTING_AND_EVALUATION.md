# Testing and Evaluation — V-Check AICTE

*Independent demonstration prototype. Not an official AICTE portal. All results are on **synthetic** data; nothing here is a claim about real AICTE documents.*

Generated from `docs/evaluation_results.json` (run on 2026-10-22) and the unit-test run. Every number below was measured by the scripts in this repository. No accuracy, precision, recall or time-saving figure has been estimated or borrowed.

## 1. Methodology

**Environment.** Python 3.12.3, Tesseract 5.3.4 (English), pypdf 5.9.0, OpenCV 4.13.0, Pillow 12.1.1, NumPy 2.4.4, on a single-CPU Linux VM. Not yet run on Windows.

**Two layers of testing.**
1. **Unit/integration tests** (`python -m unittest discover -s tests -t .` from `backend/`): 112 tests.
2. **Scenario evaluation** (`python scripts/run_evaluation.py`): 43 synthetic applications (165 files) run through the full pipeline (upload validation → text/OCR → extraction → rules → findings), each compared with an expected set of rule IDs **declared in `data/synthetic/dataset.py` before running**.

**Case kinds.** *Deterministic* cases (digital PDFs and known-bad files) must trigger **exactly** the expected rule IDs. *OCR-dependent* cases (scans) must include the expected IDs and, where stated, produce **no hard failure** that a misread could cause.

**Fixed clock.** Date rules use 22 Oct 2026 as "today" so results are reproducible.

## 2. Dataset

Fictional institutions (Greenfield Institute of Technology, Riverbend College of Engineering), fictional identifiers, banner on every document: *SYNTHETIC DEMONSTRATION DOCUMENT - NOT AN OFFICIAL RECORD*. Document layouts are invented; they are not copies of any official template. Formats generated: digital PDF, scanned PDF, PNG, JPEG, with optional blur, noise, rotation and low resolution. A "prior application" of a second institution forms the corpus against which duplicate/reuse checks run, so **every case also tests false-positive resistance on shared templates**.

## 3. Unit-test results

| Module | Tests | Covers |
|---|---|---|
| test_normalize_matching | 18 | date validation, intake parsing, name/ID matching outcomes |
| test_upload_security | 15 | content sniffing, extension mismatch, corrupt/encrypted/oversize files, pixel limit, safe names, pipeline never crashing |
| test_ocr_extraction | 13 | digital and OCR extraction, source locations, classification, unreadable scans, OCR timeout, missing Tesseract |
| test_rules_engine | 32 | ruleset validation, rule versioning, checklists per application type, date rules, cross-document comparison, OCR downgrade policy, finding contract |
| test_duplicates_verification | 17 | exact/near duplicates, reuse across institutions, perceptual hash, simulated verification never "verified" |
| test_workflow_audit_access | 17 | status transitions, role permissions, confirmation/remarks, applicant visibility, audit redaction and access |
| **Total** | **112** | **112 passed, 0 failed** (about 49 s on one CPU) |

## 4. Scenario-evaluation results

**Deterministic cases: 37/37 passed. OCR-dependent cases: 6/6 passed.** These are pass counts on a hand-built set, **not** accuracy rates, and the set is small and partly shaped by what we found (section 6).

| Case | Scenario | Kind | Expected rule IDs | Actual rule IDs | Result |
|---|---|---|---|---|---|
| C01 | Complete, consistent application (digital PDFs) | deterministic | none | none | PASS |
| C02 | Complete application, all four documents as scanned PDFs | OCR-dependent | none | none | PASS |
| C03 | Complete application in mixed formats (PNG, JPEG, scanned PDF, digital PDF) | OCR-dependent | none | none | PASS |
| C04 | Abbreviated institution name on documents ('Inst. of Tech.') must NOT raise a flag | deterministic | none | none | PASS |
| C05 | Missing occupancy certificate | deterministic | REQ-DOC-001 | REQ-DOC-001 | PASS |
| C06 | Missing affiliation letter | deterministic | REQ-DOC-003 | REQ-DOC-003 | PASS |
| C07 | Missing government approval | deterministic | REQ-DOC-004 | REQ-DOC-004 | PASS |
| C08 | Only the approval letter uploaded | deterministic | REQ-DOC-001, REQ-DOC-003, REQ-DOC-004 | REQ-DOC-001, REQ-DOC-003, REQ-DOC-004 | PASS |
| C09 | Expired affiliation letter | deterministic | DATE-002 | DATE-002 | PASS |
| C10 | Contradictory dates (issued after validity end) | deterministic | DATE-002, DATE-003 | DATE-002, DATE-003 | PASS |
| C11 | Issue date in the future | deterministic | DATE-004 | DATE-004 | PASS |
| C12 | Impossible calendar date (31-02-2026) | deterministic | DATE-001 | DATE-001 | PASS |
| C13 | Different institution name on occupancy certificate | deterministic | XD-001 | XD-001 | PASS |
| C14 | Near-identical institution name (spelling variant) -> review, not failure | deterministic | XD-001 | XD-001 | PASS |
| C15 | Institution identifier mismatch | deterministic | XD-002 | XD-002 | PASS |
| C16 | Identifier differs only by OCR-confusable characters (O vs 0) | deterministic | XD-002 | XD-002 | PASS |
| C17 | Intake conflict (document 120 vs application 180) | deterministic | XD-005 | XD-005 | PASS |
| C18 | Course on affiliation letter not in application | deterministic | XD-004 | XD-004 | PASS |
| C19 | Two occupancy certificates with different numbers | deterministic | DUP-004, XD-006 | DUP-004, XD-006 | PASS |
| C20 | Approval letter refers to a different application | deterministic | XD-003 | XD-003 | PASS |
| C21 | Same occupancy certificate file uploaded twice | deterministic | DUP-001 | DUP-001 | PASS |
| C22 | Exact file reused from another institution's application | deterministic | DUP-002, XD-001 | DUP-002, XD-001 | PASS |
| C23 | Another institution's certificate re-saved as an image (different bytes, same content) | OCR-dependent | DUP-003, DUP-004, XD-001 | DUP-003, DUP-004, XD-001 | PASS |
| C25 | Executable renamed to .pdf | deterministic | REQ-DOC-001, SYS-001 | REQ-DOC-001, SYS-001 | PASS |
| C26 | PNG image named .pdf (extension mismatch) | deterministic | REQ-DOC-001, SYS-001 | REQ-DOC-001, SYS-001 | PASS |
| C27 | Truncated (corrupt) PDF | deterministic | REQ-DOC-001, SYS-001 | REQ-DOC-001, SYS-001 | PASS |
| C28 | File larger than the upload limit | deterministic | REQ-DOC-001, SYS-001 | REQ-DOC-001, SYS-001 | PASS |
| C29 | Empty file | deterministic | REQ-DOC-001, SYS-001 | REQ-DOC-001, SYS-001 | PASS |
| C30 | Unreadable scan (heavy blur and noise) | OCR-dependent | SYS-002 | SYS-002 | PASS |
| C31 | Slightly rotated, noisy scan | OCR-dependent | none | FLD-002, FLD-006, XD-004 | PASS |
| C32 | Low-resolution blurry JPEG | OCR-dependent | none | SYS-002 | PASS |
| C33 | Verification source unavailable | deterministic | VER-001 | VER-001×4 | PASS |
| C34 | Simulated registry holds a different identifier for the affiliation letter | deterministic | VER-001 | VER-001 | PASS |
| C35 | Simulated registry confirms every document (labelled simulation, not 'verified') | deterministic | none | none | PASS |
| C36 | PDF produced by an image editor (metadata anomaly) | deterministic | META-001 | META-001 | PASS |
| C37 | PDF containing JavaScript | deterministic | META-002 | META-002 | PASS |
| C38 | Application has no institution identifier | deterministic | APP-001 | APP-001 | PASS |
| C39 | Negative intake entered in the application | deterministic | NUM-001 | NUM-001 | PASS |
| C40 | Institution identifier in the wrong format (consistently) | deterministic | APP-002 | APP-002 | PASS |
| C41 | Certificate number missing on a digital certificate | deterministic | FLD-003 | FLD-003 | PASS |
| C42 | Occupancy and affiliation documents uploaded under each other's category | deterministic | FLD-002, FLD-005, FLD-006, SYS-004 | FLD-002, FLD-005, FLD-006, SYS-004×2 | PASS |
| C43 | Several problems at once (wrong id + expired + missing document) | deterministic | DATE-002, REQ-DOC-001, XD-002 | DATE-002, REQ-DOC-001, XD-002×2 | PASS |
| C44 | Different checklist for a 'new institution' application (only two documents required) | deterministic | none | none | PASS |

### 4.1 Field-extraction measurement by scan quality

Four documents (27 ground-truth fields) rendered each way. "Wrong" means a value was extracted but differs from the truth, the dangerous case.

| Rendering | Correct | Wrong value | Not found | In unreadable docs | Unreadable docs | Mean OCR confidence |
|---|---|---|---|---|---|---|
| digital PDF (text layer) | 27 | 0 | 0 | 0 | 0/4 | n/a (text layer) |
| scanned PDF, clean 150 dpi | 27 | 0 | 0 | 0 | 0/4 | 0.951 |
| PNG, clean 150 dpi | 27 | 0 | 0 | 0 | 0/4 | 0.951 |
| JPEG q70, clean 150 dpi | 27 | 0 | 0 | 0 | 0/4 | 0.953 |
| PNG rotated 2 deg + noise | 16 | 6 | 5 | 0 | 0/4 | 0.855 |
| JPEG 70 dpi + blur 1.2 | 0 | 0 | 9 | 18 | 2/4 | 0.399 |

**What this shows**
- Clean renders (digital, scanned, PNG, JPEG at 150 dpi): 27/27 fields correct. This is the *easy* case on a clean synthetic font, not evidence for real-world scans.
- Slight rotation plus noise: 16 of 27 correct, 6 wrong, 5 not found. Wrong values carried OCR confidence of 0.52, 0.6, 0.82, 0.82, 0.83, 0.88, so **confidence does not reliably flag a misread**. This is why OCR-read values can only raise *review required* in this system.
- Low-resolution blurry JPEG: 2 of 4 documents were routed to manual review as unreadable; the other two yielded no correct fields. The mean confidence (0.399) sits right at the 0.40 unreadable threshold, which is a sign that threshold is fragile.

## 5. What the evaluation demonstrates

- The engine reproduces every deliberately introduced inconsistency on digital documents and never raised a finding on the clean applications, including against a corpus of same-template documents from another institution.
- Scans that cannot be read are sent to manual review with a recorded reason rather than producing a confident wrong answer.
- Spelling variants, abbreviations and OCR-confusable identifiers become *review required*, never a hard failure.

## 6. Changes made after seeing results (disclosed deliberately)

These make the pass counts look better than a blind test would, so they are listed here:

1. **C30 initially failed.** A heavily blurred scan produced garbage text at 26% OCR confidence, which was processed as if readable and generated six noisy field findings. We added a rule treating mean OCR confidence below 0.40 as unreadable. **The 0.40 value was chosen after seeing this one case.**
2. **Near-duplicate threshold changed from 0.90 to 0.80.** Measured text similarity: different institutions sharing a template scored 0.59–0.68; a certificate with one number changed, or re-saved and OCR'd, scored 0.855. The a-priori 0.90 would have missed both. **0.80 was set from the same synthetic data it is evaluated on**, and the C19/C23 expectations were amended to include DUP-004 accordingly (noted in the dataset file).
3. **OCR values can no longer cause hard failures.** After measuring wrong values at confidence up to 0.88, any cross-document mismatch involving an OCR-read value is *review required*.
4. **Real bugs found by the tests:** an intake of "1,20" was parsed as 120 (now rejected); the audit redactor wrongly hid a harmless `filename` field (now word-based matching); the blur detector was fooled by noise (now median-filtered); OCR timeouts on slow machines were silent (now an explicit warning).

## 7. Known limitations of this evaluation

- **Synthetic, clean, English-only, invented layouts.** Real certificates have stamps, logos, tables, signatures, handwriting, regional languages and varied scan quality. Real-world accuracy is **unknown** and is likely lower.
- 43 cases is small; thresholds (0.80 similarity, 0.40 unreadable) are tuned on the data they are tested on and need validation on independent samples.
- Template-heavy real documents (long boilerplate, few variable fields) may exceed the similarity threshold between *different* genuine documents. DUP-004 is review-only for that reason.
- **Not tested yet:** the REST API and its error handling, the database layer, the web UI, the Windows setup path, concurrency, large-scale performance, digital-signature verification (not implemented), and any real government service (none is called).
- Timings were measured on a one-CPU VM and will differ on other machines.

## 8. Proposed future evaluation

1. Collect a small set of **authorised, anonymised** real or realistic documents from a faculty mentor and measure extraction accuracy per document type, reporting wrong-value rate separately.
2. Hold out a blind test set that is never used to tune thresholds.
3. Have two reviewers use the tool on the same applications and compare time and agreement against manual review (a user study, not an assumed saving).
4. Add API, authorisation-bypass and file-upload fuzz tests once the API layer exists.
5. Re-run on Windows with a clean install following the README.


## Addendum: API layer (second build)

`backend/tests_api/test_api.py`: **59 tests, all passing** (about 20 s), run alongside the original **112 engine tests** (about 45 s). They drive the real
WSGI app through a test client (no mocking of routes, database, or pipeline) and additionally a real `python -m vcheck_api` process over sockets.

| Area | Examples of what is asserted |
|---|---|
| Authentication | 401 without/with garbage/expired/wrongly signed token; logout revokes; identical message for unknown user vs wrong password; 5-failure throttle returns 429 + Retry-After; passwords stored as scrypt, never plaintext; password change rules |
| Authorisation | applicant cannot see others' applications/documents/files (404); applicant 403 on audit/queue/analytics/rules/decisions; reviewer cannot file applications or change rules; admin-only settings; drafts invisible to staff; submitted applications not editable |
| Upload security | executable renamed `.pdf` rejected and **bytes not stored**; traversal filename sanitised and never used on disk; 413 on oversize; unknown type 422; empty upload; PNG named `.pdf`; no filesystem paths in any response |
| Scenarios | the six demo applications produce exactly the expected rule IDs from the real engine; reviewer-only duplicate finding hidden from applicants; simulation never labelled "verified" |
| Journey | create → rule-derived checklist → upload → asynchronous processing → mismatch finding with page/line evidence → blocked approvals → field correction + re-validation → correction request → resubmission → confirmed demonstration approval → complete audit trail |
| Rules | 34 rules, all `demonstration`; admin toggle creates version 1.0.1; old findings keep 1.0.0; provenance fields cannot be edited; invalid severity/unknown rule/duplicate version rejected |
| Persistence | new process on the same storage keeps users, applications, findings, history, files and audit; seeding does not duplicate; pre-restart tokens still valid |
| OCR path | a scanned (image-only) PDF is read by Tesseract through the API, fields tagged `ocr` with bounding boxes, OCR time measured, and the OCR'd ID triggers the cross-document rule |
| Data honesty | dashboard metrics equal direct SQL counts; analytics shows an empty state on an empty system |

Defects found and fixed while testing: administrators could not assign reviewers (permission missing); a malformed `reviewer_id` filter could desynchronise SQL parameters; the audit query used a fragile string rewrite (replaced). Three test expectations were wrong and corrected after checking the engine's actual, correct behaviour (changes listed here for transparency).

**Not tested**: any browser UI (does not exist yet), Windows execution, load beyond 12 concurrent requests, hostile PDFs beyond the engine's own tests.


## Addendum: browser tests (UI)

`backend/tests_ui/test_ui.py`: **31 tests, all passing** (about 80 s) in headless Chromium against the real server with real background processing. Every test fails on any
browser console error or uncaught page exception, and the app runs under its strict CSP (which is itself tested: injected inline script does not execute).

| Area | Examples of what is asserted |
|---|---|
| Public + auth | landing explains the product and carries the disclaimer and no affiliation claim; login validation and wrong-password message; protected routes redirect and return after sign-in; invalid token returns to login; sign-out clears storage; unknown route is friendly |
| Roles | nav items per role; restricted pages render "Access restricted"; the server independently returns 403; SPA navigation without full reload |
| Data honesty | every dashboard metric equals the API value; pagination arithmetic; filter state in the URL; empty states with an action |
| Journey | 5-step wizard end to end: field validation, draft id in URL, sample documents through the real pipeline, per-file step states, extracted-data drawer with page/line, pre-check catches the mismatch before submit, declaration required, background processing, finding with evidence |
| Uploads | client-side type check, type guessed from filename, replace, remove with confirmation, a disguised executable shown as Rejected |
| Reviewer | evidence jump highlights the field; approval **blocked** by the workflow with an unreviewed high finding; triage needs a note; approval needs remarks and a confirmation dialog that states it is not official; final decisions lock the case; correction request reaches the applicant (banner + alert); field correction clears a finding; admin can assign but not decide; audit shows the blocked attempt |
| Rules/settings | disabling a rule creates v1.0.1 (history, active/superseded); reviewer sees no toggles; DigiLocker shown as not configured and cannot be selected; provider change is reflected on the Verification page with the "not a government verification" text; notification preference persists |
| Safety/layout | hostile institution name (`<img onerror>`, `<script>`) renders as literal text and executes nothing; no horizontal overflow at 820 px on nine pages; collapsible navigation; keyboard operation of finding cards; no unlabeled controls |

Defects found and fixed by these tests/screenshots: the dashboard never rendered (loader refused to paint into a not-yet-mounted node), a syntax error in the audit page, the evidence block
mis-wrapping in narrow panes, the reviewer centre pane too cramped for preview + fields (now Preview / Extracted fields / Text modes), tables clipping on 1440 px screens, and the wizard calling rule-required fields
(Institution ID, Address) optional. Several test expectations were also wrong and corrected after checking the actual (correct) behaviour.

**Not tested**: Firefox/Safari/Edge, Windows, a real PDF viewer (headless Chromium has none), screen readers, Lighthouse, load beyond a few concurrent users, phones.
