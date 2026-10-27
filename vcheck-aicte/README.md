# V-Check AICTE — AI-Powered Application Validation, Document Authentication & Compliance Assistant

> **V-Check AICTE is an independent demonstration prototype developed for Smart India Hackathon (problem statement SIH26261). It is not an official AICTE portal and does not issue government approvals or official verification.**
> All data is synthetic. Nothing here is affiliated with, or integrated into, AICTE, DigiLocker or any government system. Existing government systems are acknowledged in `RESEARCH_AND_GAP_ANALYSIS.md`; V-Check is a review-assistance layer, not a replacement.

An explainable, rule-driven document-validation and evidence platform. It **assists human reviewers**; it never makes an approval decision, and "approved/rejected" outcomes are recorded as *demonstration only*.

## Honest status (read this first)

| Area | Status |
|---|---|
| Validation engine: upload checks, OCR/text read, field extraction with page/line evidence, classification, 34 versioned rules, cross-document checks, duplicate/reuse signals, metadata signals | **Built, tested** (112 engine tests + 43 synthetic scenarios) |
| **REST API**: auth, RBAC, applications, documents, pipeline, findings, review workflow, rule versioning, analytics, audit, settings, notifications | **Built, tested** (59 API tests + a live-server run) |
| **Web UI**: landing, login, dashboard, applications, 5-step wizard with real upload progress, document viewer, Verification Center, reviewer workspace, rules, analytics, audit trail, settings | **Built, tested in real Chromium** (31 browser tests, zero console errors) |
| Database: SQLite, 18 tables, survives restarts | **Built, tested** |
| Background processing with measured per-stage timings; demo mode with six scenario applications generated through the real pipeline | **Built, tested** |
| Security basics: scrypt hashing, expiring/revocable tokens, login throttling, server-side RBAC, content-sniffed uploads, generated storage names, path-traversal guard, strict CSP, safe errors, append-only audit | **Built, tested** |
| UI technology | **Plain ES modules, no build step, no npm.** Not React/TypeScript/Vite/Tailwind: those could not be installed in the build environment. See `docs/FRONTEND_NOTES.md` |
| FastAPI / PostgreSQL | **Not used.** The API is stdlib WSGI + SQLite. The contract in `docs/API.md` is framework-independent |
| Trusted-source verification | **Simulation only**, always labelled, never reported as "verified". Off by default |
| Digital-signature validity, visual-forgery detection | **Not implemented** (see `KNOWN_LIMITATIONS.md`) |
| Browsers | Tested in **Chromium only**. Firefox/Safari/Edge untested. Windows execution **not yet run** |

## Requirements

* Python 3.12 (3.11+ works) and `pip`
* Tesseract OCR (only needed for scanned PDFs/images; the synthetic demo documents have a text layer and run without it)
* No database server (SQLite is a single file in `storage/`) and **no Node.js**: the UI is served by the API.
* Optional, to run the browser tests: `pip install -r backend\requirements-dev.txt` then `playwright install chromium`.

## Install (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1            # if blocked:  Set-ExecutionPolicy -Scope Process Bypass
pip install -r backend\requirements.txt
copy .env.example .env                  # optional; defaults work. Set TESSERACT_CMD in .env if tesseract is not on PATH
```

Tesseract: install the UB Mannheim Windows build, then either add it to PATH or set
`TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` in `.env`.

## Run the backend

```powershell
cd backend
python -m vcheck_api
```

**Open `http://127.0.0.1:8000` in Chrome or Edge.** The API is at `/api/v1` (`GET /health`, `GET /meta`). On first start it creates `storage\vcheck.db`, auto-generates a JWT secret
in `storage\.jwt_secret` (never committed) and builds the six demo applications by running synthetic PDFs through the real pipeline (about a second).
Set `SEED_DEMO=0` for an empty system. Stop with Ctrl+C. Data persists between runs.

## Demo accounts (synthetic)

| Role | Email | Password |
|---|---|---|
| Applicant | `applicant@demo.vcheck` (owns the six demo applications) | `Applicant@Demo2026` |
| Applicant #2 (empty; shows isolation) | `applicant2@demo.vcheck` | `Applicant@Demo2026` |
| Reviewer | `reviewer@demo.vcheck` | `Reviewer@Demo2026` |
| Reviewer #2 | `reviewer2@demo.vcheck` | `Reviewer@Demo2026` |
| Administrator | `admin@demo.vcheck` | `Admin@Demo2026` |

These are public demo credentials for synthetic data. Never reuse them anywhere real. Change them via `POST /auth/change-password`.

## Demo applications (real database records)

| ID | Scenario | What the engine actually reports |
|---|---|---|
| APP-001 | Clean | No findings. Simulated registry match, labelled as simulation |
| APP-002 | Missing document | `REQ-DOC-001` occupancy certificate missing |
| APP-003 | Inconsistent | `XD-002` affiliation letter institution ID ≠ application |
| APP-004 | Expired | `DATE-002` affiliation letter expired |
| APP-005 | Duplicate evidence | `XD-001` name mismatch + `DUP-002` same file as another institution (reviewer-only) |
| APP-006 | Review required | `VER-001` verification source unavailable (never a failure, never "forged") |

## The 3–5 minute judge demo

Story to open with: *"Instead of just storing institutional documents, V-Check builds an evidence-driven validation pipeline. Every finding points to the exact rule and the exact line in the document."*

1. **Sign in** at `/login` as the **Applicant** (one-click demo button). Dashboard shows live numbers from the database.
2. **New application** → fill Institution (name, ID `1-9000000808`, state, address) → Application (category, a course with intake) → **Save and continue**.
3. **Documents**: choose scenario *Institution ID mismatch* → **Load sample documents**. Watch each file go Uploaded → File check → Text layer read → Fields extracted. Open **Extracted data** on the affiliation letter: every value shows page, line and confidence.
4. **Review** → **Run pre-check**: the mismatch is caught *before* submitting. Continue → tick the declaration → **Submit**.
5. The application page shows processing, then **Review required**. Open **Findings**: Application value vs Document value, source page and line, the exact rule (`XD-002`, a *demonstration* rule), plain-language reason, recommended action. **Pipeline** tab: ten stages with measured timings.
6. Sign out, sign in as the **Reviewer** → **Review Queue**. Select the case. Click **Show evidence in viewer** to jump to the offending field. Try **Approve (demo)**: the workflow blocks it while a high-severity finding is unreviewed.
7. Resolve the finding (a note is required), or **Request correction** with remarks. Approve with confirmation: the outcome is labelled *demonstration only*.
8. Sign in as **Administrator** → **Audit Trail**: the complete trace, including the blocked approval. **Rules** → disable a rule → a new ruleset version is created; old findings keep the version they were produced with.

Pre-built cases for the live walkthrough: APP-001 clean · APP-002 missing document · APP-003 inconsistent · APP-004 expired · APP-005 duplicate evidence · APP-006 source unavailable.
Terminal-only version of the same story (no browser): `python scripts\api_demo.py`.

## Tests

```powershell
cd backend
python -m unittest discover -s tests -t .          # engine: 112 tests (~45 s)
python -m unittest tests_api.test_api              # API: 59 tests (~25 s)
python -m unittest tests_ui.test_ui                # browser: 31 tests (~80 s; needs Playwright + Chromium)
cd ..
python scripts\run_evaluation.py                   # 43 synthetic scenarios -> docs\evaluation_results.json
```

The browser tests drive the real server in headless Chromium: landing/login, session expiry and sign-out, per-role navigation and restrictions, dashboard numbers
equal API numbers, search/filter/pagination, the full 5-step wizard with real uploads, replace/remove/rejected-file handling, the reviewer workflow with its blocked and
confirmed actions, field correction, rule versioning, admin settings, audit filtering, hostile-text rendering, CSP, keyboard operation, and tablet layout (no horizontal overflow).
They fail on any console or page error.

## Layout

```
backend/vcheck/        engine: files, ocr, fields, rules, engine, duplicates, metadata, verification, workflow, audit, pipeline, models
backend/vcheck_api/    API: app (WSGI routes + static serving), services_*, processing, db (schema), security, seed, demo, config
frontend/              web UI (ES modules, CSS design system): served by the API at /
backend/rules/         versioned ruleset (JSON; rules are data, never edited by an LLM)
backend/tests/         112 engine tests          backend/tests_api/   59 API tests          backend/tests_ui/   31 browser tests
data/synthetic/        synthetic document renderer + 43-case dataset
scripts/               api_demo.py (live walkthrough), demo.py (engine CLI), run_evaluation.py
docs/                  API.md (contract), FRONTEND_NOTES.md, evaluation_results.json
storage/               created at run time: SQLite DB, uploaded files (outside any public directory), JWT secret
```

## Configuration

All via environment variables or `.env` (see `.env.example`). No secret is in source control. `VCHECK_TODAY=2026-10-22` pins "today" so date rules behave
identically on stage. Administrators can change the verification provider, upload limits and demo mode at run time (`PUT /settings/admin`).

## Documents

`RESEARCH_AND_GAP_ANALYSIS.md` · `ARCHITECTURE.md` · `TESTING_AND_EVALUATION.md` · `KNOWN_LIMITATIONS.md` · `DEMO_SCRIPT.md` · `PRESENTATION_OUTLINE.md` · `docs/API.md`

## Next steps (not done)

1. Run the whole thing on Windows and in Firefox/Edge/Safari; fix whatever differs.
2. Optional: port the UI to React/TypeScript (see `docs/FRONTEND_NOTES.md`), and/or the API to FastAPI + PostgreSQL with Alembic.
3. Ask the SIH coordinator the open questions in the research report (official problem text, hardware eligibility).
4. Validate thresholds on authorised realistic documents.

## Putting it online

GitHub Pages **cannot** host this (it only serves static files; V-Check needs its Python server and database). Use GitHub for the code and a host that runs containers:

1. Create a GitHub repository and push this folder (`git init`, `git add .`, `git commit`, `git remote add origin ...`, `git push`). The included workflow runs the tests on every push.
2. **Render (free)**: render.com → *New* → *Blueprint* → choose the repository. `render.yaml` and the `Dockerfile` do the rest; you get a public `https://….onrender.com` link. Alternatives: Railway, Fly.io, or Hugging Face Spaces (Docker).
3. **Or, no hosting account:** open the repository in a GitHub Codespace, run `cd backend && python -m vcheck_api`, and make forwarded port 8000 public.

Before sharing a public link: the demo passwords are public and the data is synthetic, so anyone can sign in. That is acceptable for a demo only. Keep `JWT_SECRET` set (the blueprint generates one), do not upload real documents, and note that free hosts have ephemeral disks: the demo data is rebuilt on each restart and free instances sleep when idle, so open the link once before presenting. The Dockerfile and Render blueprint were written but **not built or deployed** in my environment.
