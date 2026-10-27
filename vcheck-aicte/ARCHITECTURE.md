# Architecture

*Independent demonstration prototype. Not an official AICTE portal.*

## Principle

The engine is a **framework-independent Python library**. Every rule, comparison, workflow check and audit redaction is pure code that runs without a server or database, so it is fully testable on its own. The planned API and UI are thin layers over it.

## Data flow

```
upload bytes
   |
   v
files.validate_upload      sniff magic bytes, extension match, size/page/pixel limits,
   |                       corrupt/encrypted check, SHA-256, safe display name
   v   (rejected -> ProcessedDocument(status="rejected") with clear reason; never raises)
ocr.read_pdf / read_image  PDF text layer (pypdf) -> else OCR of embedded page images
   |                       (OpenCV deskew + two preprocessing variants + Tesseract, with timeout)
   v
fields.extract_fields      label-driven extraction; each value keeps page, line, bbox, confidence
fields.classify_document   keyword scoring against configured document types
metadata.inspect_pdf       review-only signals (editor producer, modified-after-created, revisions,
                           signature present-but-unverified)
duplicates                 SHA-256, text fingerprint + 4-gram shingles, dHash for images
   |
   v
engine.validate_application(application, documents, ruleset, corpus, verifications, today)
   |   for each enabled, applicable rule -> check function -> Findings
   v
ValidationReport           findings + rules_run + rules_skipped + suggested_status
   |
   v
workflow.transition        legal status moves, role checks, confirmation, remarks
audit.AuditLog             who/what/when, redacted details, role-restricted search
```

## Key design decisions

| Decision | Why |
|---|---|
| Rules are JSON data with id, version, severity, source reference and **source status** | Rules can change without code changes; every finding records the rule version; demo rules cannot pose as official ones (an `official_confirmed` rule must cite a URL) |
| `RuleSet` is immutable; edits derive a new version | Old results stay explainable; admins cannot silently alter history |
| Outcomes are only `failed` or `review_required` | "Verified" is reserved for a real trusted-source check; a simulated check is never "verified" |
| OCR-read values cannot cause a hard failure | Measured: misreads reached 0.88 confidence, so confidence cannot gate this |
| Comparators return match / probable / mismatch / unavailable | Spelling variants and OCR-confusable IDs go to a human instead of being auto-accepted or auto-rejected |
| `reviewer_only` findings | Findings that mention other institutions' applications are never shown to applicants |
| Roles enforced in `workflow.py` (not the UI) | The API will call the same functions on every route |
| pypdf instead of PyMuPDF for now | Pure Python, installs on Windows with no build tools, and it was available offline; PyMuPDF can be added for vector-page rendering |
| No LLM in the core | Works at ₹0 with no API key; the spec forbids AI from making legal or compliance determinations |

## Planned layers (not yet built)

FastAPI routes calling `workflow.require(role, action)` and the engine; SQLAlchemy models (Users, Institutions, Applications, ApplicationDocuments with version history, ExtractedFields with corrections, ValidationRules/RuleVersions, ValidationRuns, ValidationFindings, VerificationAttempts, ReviewAssignments, ReviewActions, AuditLogs); Alembic migrations; React + TypeScript + Vite UI; files stored outside public directories under generated names (`files.storage_name`) and served through authorised endpoints.

## Security posture of what exists

Content-based type checks; generated storage names; uploaded files never executed or rendered; PDF scripts and embedded files only flagged; decompression-bomb pixel limit; audit redaction of passwords, tokens, secrets and document text. **Not yet covered** (needs the API): authentication, session handling, HTTP error hygiene, rate limiting, CSRF/CORS.
