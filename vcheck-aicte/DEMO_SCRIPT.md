> **Browser demo (recommended):** the step-by-step 3–5 minute script for the web UI is in `README.md` ("The 3–5 minute judge demo"). The terminal version of the same story is `python scripts/api_demo.py`. The engine-level CLI script below is kept for reference.

# Demo script (about 6 minutes)

*Independent demonstration prototype. Not an official AICTE portal. Say this in the first ten seconds.*

All commands run from the project root. The demo is a command-line view of exactly what the reviewer interface will show; the web UI is not built yet, so do not describe it as built.

## Opening (30 s)
"AICTE approval is already online. We are not replacing it. We built an explainable layer that checks whether an application's documents agree with each other and with the application, and tells a reviewer exactly why something was flagged. It assists reviewers; it never decides."

## 1. A clean application (45 s)
```
python scripts/demo.py C01
```
Point out: four documents processed from their text layer, correct types detected, **zero findings**, suggested status "validation complete". "A human still decides."

## 2. Three different validation problems (3 min)
```
python scripts/demo.py C15 C17 C09
```
- **C15, identifier mismatch** (`FAILED VALIDATION`, XD-002): show *Observed vs Expected*, then the **evidence line** with page and line number. "Every flag points at the exact line."
- **C17, intake conflict** (XD-005): the approval letter says 120, the application says 180. Evidence shows both the course line and the intake line.
- **C09, expired document** (DATE-002): the check uses a fixed demo date of 22 Oct 2026. Show the remediation text.

## 3. The system knows what it does not know (1.5 min)
```
python scripts/demo.py C14 C30 C35
```
- **C14**, spelling variant "Greenfeld": **REVIEW REQUIRED, not failed**. "We never call a near-match fraud."
- **C30**, unreadable scan: routed to manual review with a recorded reason. "We would rather say 'I can't read this' than guess."
- **C35**, simulated verification: all pass, but the output says **simulated, not a government verification**. "We never present a mock as real."

## 4. Reuse across institutions (45 s)
```
python scripts/demo.py C22
```
Show DUP-002 marked **reviewer-only** with its stated limitation (a shared file can be legitimate). "Applicants never see another institution's application."

## Questions to expect, with honest answers
- *"Doesn't AICTE already have this?"* It has an online process (verified). Whether its scrutiny runs automated cross-document checks is **unknown to us**; we list it as a question for a domain expert.
- *"Is it accurate?"* On clean synthetic documents, yes (27/27 fields). On degraded scans, **no**: wrong values appeared with confidence up to 0.88, so we only allow OCR to raise *review required*. Real-document accuracy is unmeasured.
- *"Does it verify with DigiLocker?"* No. That path is simulated and labelled. The AICTE–DigiLocker circular we found concerns student awards, so institutional verification there is unconfirmed.
- *"Are the rules official?"* No. They are illustrative and cite their sources; the handbook itself has not yet been mapped.
- *"What does it cost?"* ₹0: Python, Tesseract, OpenCV, pypdf, all open source, no paid API.
- *"What's missing?"* API, database, web UI, signature verification. See `README.md`.

## Planned UI walkthrough (once built, not yet available)
Login as applicant → create application → upload documents → see findings → login as reviewer → open finding with evidence → request correction → login as admin → view audit log and rule versions.
