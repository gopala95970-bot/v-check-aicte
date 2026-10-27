# SIH presentation outline — V-Check AICTE (SIH26261)

*Keep the disclaimer on every slide: "Independent demonstration prototype. Not an official AICTE portal."*

1. **Title.** V-Check AICTE: explainable document validation for approval applications. Team, mentor, problem statement ID.
2. **The problem.** Applications fail or stall when documents are missing or inconsistent. *Evidence:* AICTE's own 2021 letter says institutions often omit mandatory documents, causing avoidable delay and rejection. Cite it; note it is 2021.
3. **What already exists (we did the research).** Online portal, scrutiny, expert visits, hearing committees, self-disclosure deficiencies, DigiLocker for student awards. State plainly: **AICTE already has an online system.**
4. **Where we think there is room (candidate gaps).** Cross-document consistency, reuse detection, plain-language evidence-linked reasons. Label these *hypotheses to validate with reviewers*, not proven deficiencies.
5. **Our innovation.** Not "AI that decides". An **explainable, rule-driven evidence layer**: versioned rules, evidence lines, three honest states (passed / failed / review required), never claiming proof of forgery.
6. **How it works.** Pipeline diagram from `ARCHITECTURE.md`: validate upload → text/OCR → extract with locations → rules → findings → human review → audit.
7. **Live demo.** `DEMO_SCRIPT.md`: one clean case, three problems, one "I cannot read this", one simulated verification.
8. **Responsible design.** Humans decide; OCR can only raise review items; simulated verification is labelled; reviewer-only findings; audit trail with redaction; synthetic data; DPDP awareness.
9. **Feasibility at ₹0.** Open-source stack, works offline, no paid API; runs on a laptop. Roadmap: API → database → web UI.
10. **Testing, honestly.** 112 unit tests and 43 synthetic scenarios, all passing. Extraction: 27/27 on clean renders; on degraded scans wrong values appeared (up to 0.88 confidence), which shaped the design. Say what changed after seeing results.
11. **Expected impact.** Qualitative only: fewer avoidable back-and-forths, faster triage, traceability. **Do not state time or cost savings.** Describe how we would measure them (reviewer study on authorised documents).
12. **Limitations and next steps.** Illustrative rules, no real integrations, no signature verification, real-document accuracy unknown. Questions for the coordinator and AICTE reviewers.

**Do not say:** "AICTE has no online system", "integrated with AICTE/DigiLocker", "detects forgery", "X% accuracy" on real documents, or "saves N% time".
