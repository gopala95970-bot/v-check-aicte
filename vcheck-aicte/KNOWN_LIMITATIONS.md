# Known limitations

*Independent demonstration prototype. Not an official AICTE portal.*

**Scope**
- No REST API, database, authentication or web UI exists yet. The engine is tested in-process only.
- No Windows run has been performed; the Windows instructions are unverified.

**Rules and regulation**
- All rules are **illustrative**. Four are modelled on one Kerala state circular and one AICTE letter from 2021; none was checked against the current Approval Process Handbook (not read). Do not describe them as AICTE requirements.
- The `1-<8–12 digits>` identifier pattern is inferred from public sample letters and unconfirmed.
- Document types and layouts are invented. Fire-safety certificates, building plans and other documents AICTE lists as commonly required are not modelled.

**Extraction and OCR**
- Measured only on clean, English, synthetic renders. Real stamps, logos, tables, handwriting and regional languages are untested; real accuracy is unknown and likely lower.
- Extraction is label-driven ("Certificate No: …"). Documents without clear labels will yield missing fields (reported as review items on scans, failures on digital text).
- OCR confidence is a heuristic and **does not reliably flag misreads** (wrong values reached 0.88).
- The 0.40 "unreadable" threshold was chosen after one failing case and sits close to the confidence of a borderline test image.
- Sharpness thresholds are heuristic. A scan that is OCR-able but poor is reported through confidence, not through a reliable quality score.
- On slow machines OCR can time out (30 s per call); the document is then routed to manual review with an explicit `OCR_TIMEOUT` warning.

**Authenticity checks**
- Duplicate and similarity signals are review prompts, not proof. Genuine documents from one issuer share templates; real boilerplate-heavy documents may exceed the 0.80 similarity threshold. The threshold was tuned on the same synthetic data it is tested on.
- Metadata is editable and often absent; metadata signals are informational.
- **Digital-signature verification is not implemented.** Presence of a signature field is reported as "present, not verified".
- Visual forgery detection (image-editing traces) is **not implemented**.
- **Verification is simulated.** There is no real DigiLocker or government integration; the AICTE–DigiLocker circular found concerns student awards, not institutional documents, so institutional verification through DigiLocker is itself unconfirmed.

**Privacy and operations**
- `reviewer_only` findings (those that mention another institution) are filtered out for applicants in every API path that returns findings, including counts, and by direct id (tested).
- Cross-application duplicate detection needs a corpus of other institutions' documents. In production this raises its own access-control and privacy questions that a stakeholder must settle.
- Synthetic data only. Real institutional documents must not be used without authorisation. DPDP Rules obligations commence on 12 May 2027 (secondary source); a production system needs a proper legal review.
- Hardware kiosk: not built. SIH26261 is listed as Software; confirm eligibility with the SIH coordinator before spending anything.

**API / application layer (added in the second build)**
- The API is a stdlib WSGI server with SQLite, chosen because FastAPI/SQLAlchemy could not be installed in the offline build sandbox. It is suitable for a demo and light single-site use; it is **not** hardened for internet exposure (no TLS termination, no reverse-proxy awareness, in-memory login throttling that resets on restart and is per-process, single-writer SQLite).
- Background processing uses an in-process thread pool. If the process stops mid-run, an application can stay in "Processing"; restarting does not resume it (re-submit or use *validate*). There is no job queue.
- Tokens are bearer JWTs (HS256) held by the client; there is no refresh-token flow, MFA, password reset or account management UI. Demo passwords are public by design.
- Uploaded files are scanned only by this project's checks (content sniffing, size/page limits, PDF structure and active-content flags). There is **no antivirus engine**.
- Uploaded files are stored unencrypted on local disk, outside public directories. Disk encryption and backups are the operator's responsibility.
- `verification_mode` defaults to **off**. In *simulation* the lookup is against a local synthetic registry seeded only for the demo certificate numbers, so any newly invented certificate number reports `not_found` and goes to human review. That behaviour is deliberate and labelled, and it is not evidence about real documents.
- "Critical" findings are defined here as severity `high` and outcome `failed`; the rule engine has no separate "critical" severity.
- Audit rows are append-only by convention (the API never updates or deletes them); the SQLite file itself is not tamper-evident.

**Web UI**
- Plain ES modules rather than React/TypeScript/Vite/Tailwind (those could not be installed in the build environment). No static typing; responses are checked at run time only where the UI depends on them.
- Verified in headless **Chromium only**. Firefox, Safari and Edge were not tested. Phones are not a target (tablet and up).
- PDF preview relies on the browser's built-in PDF viewer in an `<iframe>` (a blob URL created from an authorised fetch). Headless Chromium has no such viewer, so previews could not be screenshot-tested; the Extracted fields and Text views, which do not depend on it, are tested. If a browser has its PDF viewer disabled the preview is blank and the page says so.
- No highlighting of extracted values on the page image (page, line, snippet and confidence are shown instead; OCR bounding boxes exist in the API but are not drawn).
- English only; no localisation. Accessibility was checked by automated spot checks (labels, keyboard operation of finding cards, focus styles, no colour-only status), not by an audit with assistive technology or Lighthouse.
- Charts are simple hand-drawn SVG; they have titles and tooltips but no data-table alternative.
- Notifications are in-app only (polled every 20 s); there is no email/SMS and no push.
