# Research and Gap Analysis — V-Check AICTE (SIH26261)

*Independent demonstration prototype. Not an official AICTE portal. No real government approval or verification is issued.*
*Research date: 22 October 2026. First-pass report, produced alongside implementation as the brief requires.*

## 0. How to read this report

Every claim carries an **evidence level**. Nothing here is presented as stronger than it is.

| Tag | Meaning |
|---|---|
| **[V]** | **Verified**: I opened the primary document and read the statement. |
| **[S]** | **Snippet only**: seen in a search-result excerpt or secondary article; the primary document was not opened by me. |
| **[T]** | **Title only**: I saw the document's title/URL in results but did not read it. |
| **[A]** | **Assumption / unverified**: needs stakeholder confirmation. |

**Access limits that shaped this report.** The AICTE website refused automated access to the 2026-27 public notice (bot detection), so I could not read it. I did not read the Approval Process Handbook (APH) text itself, so **no demo rule is labelled an official AICTE rule**. The official SIH portal listing for SIH26261 was not retrieved; only a third-party aggregator page for a different problem statement was seen, so the problem-statement text used here is the one you supplied.

## 1. Executive summary

- AICTE approval is **already an online, portal-based process**, with scrutiny, expert visit committees and hearing committees. The APH 2020-21 describes approval "through online application" including "Extension of Approval based on Self-Disclosure" **[S]**. V-Check therefore must **not** be pitched as "AICTE has no online system".
- There is **official evidence of a document-completeness problem**: an AICTE letter (ref. AICTE/Adv/AB/APH/2022-23, dated 06.12.2021) says institutions often submit applications without the mandatory documents, causing avoidable delay and rejections, and lists commonly required documents **[V]**. That is the best-supported problem V-Check targets. It is 2021 evidence and does not prove the problem persists in 2026.
- A separate AICTE letter shows the portal generates **deficiencies from self-disclosure** and that many institutions had not submitted compliance reports; non-compliance can lead to no extension of approval or reduced intake **[V]**. This shows compliance evidence matters, but it concerns infrastructure and faculty compliance rather than document consistency.
- **DigiLocker is not confirmed as a route for verifying institutional approval documents.** The AICTE–DigiLocker/NAD circular I read concerns linking **students' academic awards** **[V]**. Using DigiLocker for institutional documents is an unconfirmed assumption **[A]**, and any real integration needs authorised onboarding.
- Realistic contribution without any government integration: an **explainable, rule-driven cross-document consistency and evidence layer** (name/ID/intake/date consistency, duplicate and reuse signals, versioned rules, reviewer workflow, audit trail). Whether AICTE reviewers lack this today is **[A]** and needs a stakeholder.

## 2. Existing-system map

| Component | What the evidence says | Level |
|---|---|---|
| Online application via AICTE web portal | A Kerala DTE circular (12.01.2024) tells institutions to apply online on the AICTE portal, then submit hard copies with listed documents to the state directorate | **[V]** |
| Approval Process Handbook (APH) | Annual handbook; 2020-21 edition describes online applications and self-disclosure-based extension; a 2026-27 handbook update was reported in the press | **[S]** |
| Scrutiny, EVC, Standing Hearing / Appellate Committees | Named in the 2021 AICTE letter as stages where missing documents cause delay or rejection | **[V]** |
| Digital Signature Certificate | The same letter lists a DSC for filing and attesting uploaded documents | **[V]** |
| Self-disclosure deficiencies and compliance reports | Portal-generated deficiencies; failure to comply can mean no EoA or reduced intake | **[V]** |
| 2026-27 cycle details (portal timeline, single-window system, corrigendum) | Search excerpts mention a 2026-27 handbook, a corrigendum and use of a national single-window portal | **[S]** (primary notice not opened) |
| AICTE–DigiLocker / NAD | AICTE asked institutions to link **student academic awards** to DigiLocker (circular 25.06.2021) | **[V]** |
| DigiLocker APIs | Public "Requester" (v1.12) and "Authorized Partner" (v1.13) API specifications exist; onboarding terms not read | **[T]** |
| Earlier SIH problem on this theme | An official sih.gov.in page lists an AICTE problem asking for an AI-supported approval portal with automatic document verification | **[S]** |
| Earlier SIH/AICTE verification work | A third-party listing mentions AICTE OCR and student-verification projects from earlier SIH editions | **[S]** |

## 3. Feature comparison

| Capability | Existing in official process? | V-Check prototype | Notes |
|---|---|---|---|
| Online application and document upload | Yes **[V]** | Yes (synthetic) | Not a differentiator |
| Scrutiny by human committees | Yes **[V]** | Reviewer workspace | Assists, never decides |
| Completeness check against a checklist | Unknown whether automated **[A]** | Yes (configurable, versioned) | Checklists are **illustrative** |
| Cross-document consistency (name, ID, intake, dates) | Unknown **[A]** | Yes, with evidence links | Core differentiator |
| Duplicate / reuse detection across institutions | Unknown **[A]** | Exact, text-near and image-hash signals | Review-only signals |
| Trusted-source verification | Not confirmed for institutional documents | **Simulated only**, labelled | Real connector needs authorisation |
| Digital-signature validation | Not assessed | **Not implemented**; presence reported only | Needs test documents and trust store |
| Explanation + remediation per flag | Unknown **[A]** | Yes | |

## 4. Evidence-supported limitations and candidate gaps

**Supported by official evidence**
1. Applicants submit incomplete document sets, causing delays and rejections (AICTE letter, 2021) **[V]**.
2. Compliance evidence is tracked through portal deficiencies and follow-up reports **[V]**.

**Candidate gaps (not confirmed; need stakeholder validation) [A]**
- Reviewers may have to compare names, identifiers and intake figures across documents by eye.
- Reuse of the same evidence across applications may be hard to notice at scale.
- Applicants may not receive plain-language, evidence-linked reasons for corrections.

Do not present these as established deficiencies of the AICTE system.

## 5. Proposed differentiation

Explainable rule engine with versioned rules; every finding names the rule version, the exact values compared, and the source line (page, line, and bounding box for scans). Three distinct states are never conflated: **passed / failed validation / review required**, and "verified" is reserved for a real trusted-source check. OCR-read values can only raise *review required*, because our own measurements showed misreads carrying confidence up to 0.88.

## 6. Regulatory and privacy considerations

- **Not official:** no AICTE logos or seals; visible disclaimer on every page; no real approvals.
- **DPDP Act 2023 and Rules 2025:** Rules were notified on 13 Nov 2025; most substantive obligations (notice and consent, security safeguards, breach notification, retention) commence on **12 May 2027** **[S]** (law-firm summary). The prototype uses synthetic data only, minimises personal data, and keeps files outside public directories.
- Real institutional documents must not be used without authorisation.
- A tool that influences regulatory outcomes should keep a human decision-maker and an audit trail, which the design enforces.

## 7. Integration constraints

| Integration | Needs | Status in prototype |
|---|---|---|
| AICTE portal data | Institutional agreement; no public API confirmed | Not attempted |
| DigiLocker verification | Authorised requester onboarding; relevance to institutional documents unconfirmed **[A]** | Interface only; simulation labelled |
| Digital-signature trust chain | Trust store, test certificates | Not implemented |
| Government registries | Authorisation | Never scraped |

## 8. Excluded from the MVP

Real integrations; signature cryptography; LLM-based extraction (core must work offline at ₹0); hardware kiosk (SIH26261 is a Software category; confirm eligibility with the SIH coordinator before any hardware spend); multi-language OCR.

## 9. Sources

| # | Source | Used for | Level |
|---|---|---|---|
| 1 | AICTE letter, ref. AICTE/Adv/AB/APH/2022-23, 06.12.2021: aicte.gov.in/sites/default/files/Lettr to Institutes regarding NOC - 14-06-2022 with ecnl.-2.pdf | Mandatory-document problem; indicative document list | V |
| 2 | AICTE letter on self-disclosure deficiencies (AY 2021-22 era; date garbled in scan): aicte.gov.in/sites/default/files/letter to Head of the Institutions - Insttt.pdf | Deficiencies and compliance reports | V |
| 3 | Kerala DTE circular L3/996/24/DTE, 12.01.2024: dtekerala.gov.in/static/DEPTCIRCULARS/240112AICTE.pdf | Documents requested with EoA applications in Kerala; online portal use | V |
| 4 | AICTE circular, 25.06.2021, linking academic awards to DigiLocker: cdn.digilocker.gov.in/nad/assets/circulars/4 Circular_AICTE_NAD_DigiLocker_06_2021.pdf | DigiLocker scope = student awards | V |
| 5 | AZB & Partners, DPDP rollout summary, 14.11.2025: azbpartners.com/bank/indias-digital-personal-data-protection-act-phased-rollout-and-key-compliance-milestones/ | DPDP dates | V (secondary source) |
| 6 | AICTE Approval Process Handbook 2020-21 (search excerpt): aicte.gov.in/sites/default/files/Approval Process Handbook - Revised.pdf | Online application; self-disclosure | S |
| 7 | Careers360, "AICTE Approval Process Handbook 2026-27 update" | 2026-27 handbook exists | S |
| 8 | sih.gov.in/sih2019ProblemStatementstudentInnovation | Earlier SIH problem on AI approval portal | S |
| 9 | DigiLocker Requester API spec v1.12 (cf-media.api-setu.in) and Authorized Partner spec v1.13 (img1.digitallocker.gov.in) | API existence | T |

## 10. Unanswered questions (ask the SIH coordinator or a domain expert)

1. What does the official SIH26261 text say exactly, and are other SIH 2026 statements on AICTE approval workflow overlapping with it? (A third-party aggregator hinted at siblings; **not verified**.)
2. Which documents are mandatory for each application type in the **current** APH, and which can be machine-checked?
3. Does AICTE's scrutiny process already run automated consistency checks? If so, where does V-Check add value?
4. Is any institution-level document verification service available to a student team?
5. Can SIH26261 be demonstrated with hardware, or is it Software-only?
6. Is the AICTE institution identifier format confirmed? (Our `1-<8–12 digits>` pattern is inferred from public sample letters and flagged illustrative.)
