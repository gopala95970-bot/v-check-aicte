"""Validation engine.

validate_application() runs every enabled, applicable rule of a RuleSet and
returns evidence-linked findings. It is deterministic: no network, no LLM, no
randomness. `today` is injectable so date rules are testable.

Outcome vocabulary (see models.py):
  failed           a defined check did not pass
  review_required  uncertain or incomplete; a human must look
Policy applied throughout: a value read by OCR with low confidence can raise a
review item but never a hard failure, because the "mismatch" may be a misread.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import time
from itertools import combinations
from typing import Callable, Optional

from .duplicates import CorpusEntry, hamming, jaccard
from .matching import (MATCH, MISMATCH, PROBABLE, UNAVAILABLE, compare_dates,
                       compare_ids, compare_ints, compare_names)
from .models import (OUTCOME_FAILED, OUTCOME_REVIEW, Application, EvidenceRef,
                     ExtractedField, Finding, ProcessedDocument, utcnow_iso)
from .normalize import normalize_id, parse_date, parse_intake
from .rules import Rule, RuleSet, RuleSetError
from .verification import VerificationResult

import re

HUMAN = {
    "institution_name": "institution name", "institution_id": "institution identifier",
    "application_ref": "application reference", "certificate_number": "certificate number",
    "issue_date": "issue date", "expiry_date": "validity date", "approved_intake": "approved intake",
    "course_name": "course name", "issuer": "issuing authority",
}
DATE_REASON = {"unrecognised_format": "is not in a recognised date format",
               "calendar_invalid": "is not a real calendar date", "empty": "is blank"}
INTAKE_REASON = {"not_a_number": "is not a valid whole number", "not_positive": "must be greater than zero",
                 "too_large": "is unrealistically large", "empty": "is blank"}


@dataclass
class Ctx:
    app: Application
    docs: list[ProcessedDocument]
    ruleset: RuleSet
    today: date
    corpus: tuple
    verifications: tuple

    @property
    def readable(self) -> list[ProcessedDocument]:
        return [d for d in self.docs if d.status == "processed"]

    @property
    def present(self) -> list[ProcessedDocument]:
        return [d for d in self.docs if d.status in ("processed", "unreadable")]

    def label(self, d: ProcessedDocument) -> str:
        t = d.effective_type
        base = self.ruleset.document_types.get(t, {}).get("label", "document") if t else "document"
        return f"{base} '{d.original_filename}'"


def _ev(d: ProcessedDocument, ef: ExtractedField) -> EvidenceRef:
    return EvidenceRef(d.document_id, ef.page, ef.line_no, ef.snippet, ef.name, ef.bbox)


def _mk(ctx: Ctx, rule: Rule, outcome: str, explanation: str, **kw) -> Finding:
    severity = kw.pop("severity", rule.severity)
    title = kw.pop("title", rule.name)
    kw.setdefault("recommended_action", rule.remediation)
    return Finding(rule_id=rule.rule_id, rule_version=rule.version, title=title, outcome=outcome,
                   severity=severity, application_id=ctx.app.id, explanation=explanation, **kw)


def _ocr_unsure(ef: Optional[ExtractedField], low: float = 0.0) -> bool:
    """Any OCR-read value is treated as uncertain, whatever its confidence.

    Measured on our synthetic scans: misread values carried confidences up to
    0.88, so a confidence cut-off cannot separate right from wrong. (`low` is
    kept for rule-parameter compatibility and is intentionally unused.)
    """
    return bool(ef and ef.method == "ocr")


def _outcome_for_mismatch(efs: list[Optional[ExtractedField]], low: float) -> tuple[str, str]:
    if any(_ocr_unsure(e, low) for e in efs):
        return OUTCOME_REVIEW, " The value was read by OCR, which can misread characters, so a reviewer should compare it with the original."
    return OUTCOME_FAILED, ""


# ------------------------------------------------------------------ checks
def c_required_document(ctx: Ctx, rule: Rule) -> list[Finding]:
    want = rule.params["doc_type"]
    if any(d.effective_type == want for d in ctx.present):
        return []
    label = ctx.ruleset.document_types.get(want, {}).get("label", want)
    rejected = [d for d in ctx.docs if d.status == "rejected" and d.declared_type == want]
    extra = ""
    if rejected:
        extra = f" An upload for this category was rejected ({rejected[0].errors[0].message})"
    return [_mk(ctx, rule, OUTCOME_FAILED, f"No {label.lower()} has been uploaded.{extra}",
                expected=f"at least one '{label}'", observed="none uploaded",
                document_ids=[d.document_id for d in rejected])]


def c_required_field(ctx: Ctx, rule: Rule) -> list[Finding]:
    fname, types = rule.params["field"], rule.params["doc_types"]
    out = []
    for d in ctx.readable:
        if types != "*" and d.effective_type not in types:
            continue
        if fname == "approved_intake":
            if d.course_rows:
                missing = [r.course.effective() for r in d.course_rows if r.intake is None]
                found = not missing
                detail = f" for course(s): {', '.join(missing)}" if missing else ""
            else:
                found, detail = False, " (no course lines were found)"
        else:
            found, detail = bool(d.fields.get(fname)), ""
        if found:
            continue
        ocr = d.text_source in ("ocr", "mixed")
        note = " The text of this document came from OCR, so the value may be present but unreadable." if ocr else ""
        out.append(_mk(ctx, rule, OUTCOME_REVIEW if ocr else OUTCOME_FAILED,
                       f"The {HUMAN[fname]} was not found on {ctx.label(d)}{detail}.{note}",
                       document_ids=[d.document_id], fields=[fname], observed="not found",
                       expected=f"a {HUMAN[fname]} on the document"))
    return out


def c_date_valid(ctx: Ctx, rule: Rule) -> list[Finding]:
    out = []
    for d in ctx.readable:
        for fname in rule.params["fields"]:
            for ef in d.fields.get(fname, []):
                pd = parse_date(ef.effective())
                if pd.ok:
                    continue
                oc, note = (OUTCOME_REVIEW, " It was read by OCR and may be a misread.") if ef.method == "ocr" else (OUTCOME_FAILED, "")
                out.append(_mk(ctx, rule, oc, f"The {HUMAN[fname]} '{ef.effective()}' on {ctx.label(d)} {DATE_REASON[pd.reason]}.{note}",
                               document_ids=[d.document_id], fields=[fname], observed=ef.effective(),
                               evidence=[_ev(d, ef)], confidence=ef.confidence))
    return out


def c_not_expired(ctx: Ctx, rule: Rule) -> list[Finding]:
    out = []
    for d in ctx.readable:
        ef = d.primary(rule.params["field"])
        pd = parse_date(ef.effective()) if ef else None
        if pd and pd.ok and pd.value < ctx.today:
            oc, note = _outcome_for_mismatch([ef], 0.6)
            out.append(_mk(ctx, rule, oc, f"{ctx.label(d).capitalize()} expired on {pd.value.isoformat()} (checked against {ctx.today.isoformat()}).{note}",
                           document_ids=[d.document_id], fields=[ef.name], observed=pd.value.isoformat(),
                           expected=f"a validity date on or after {ctx.today.isoformat()}", evidence=[_ev(d, ef)],
                           confidence=ef.confidence))
    return out


def c_date_order(ctx: Ctx, rule: Rule) -> list[Finding]:
    out = []
    for d in ctx.readable:
        a, b = d.primary(rule.params["first"]), d.primary(rule.params["second"])
        if not (a and b):
            continue
        pa, pb = parse_date(a.effective()), parse_date(b.effective())
        if pa.ok and pb.ok and pa.value > pb.value:
            oc, note = _outcome_for_mismatch([a, b], 0.6)
            out.append(_mk(ctx, rule, oc, f"On {ctx.label(d)} the {HUMAN[a.name]} ({pa.value}) is later than the {HUMAN[b.name]} ({pb.value}).{note}",
                           document_ids=[d.document_id], fields=[a.name, b.name],
                           observed=f"{pa.value} > {pb.value}", expected=f"{HUMAN[a.name]} on or before {HUMAN[b.name]}",
                           evidence=[_ev(d, a), _ev(d, b)]))
    return out


def c_date_not_future(ctx: Ctx, rule: Rule) -> list[Finding]:
    out = []
    for d in ctx.readable:
        ef = d.primary(rule.params["field"])
        pd = parse_date(ef.effective()) if ef else None
        if pd and pd.ok and pd.value > ctx.today:
            out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                           f"The {HUMAN[ef.name]} on {ctx.label(d)} ({pd.value}) is later than today ({ctx.today}).",
                           document_ids=[d.document_id], fields=[ef.name], observed=pd.value.isoformat(),
                           expected=f"a date on or before {ctx.today.isoformat()}", evidence=[_ev(d, ef)]))
    return out


def c_app_fields_present(ctx: Ctx, rule: Rule) -> list[Finding]:
    missing = [f for f in rule.params["fields"] if not (getattr(ctx.app, f, "") or "").strip()]
    if not [c for c in ctx.app.courses if (c.name or "").strip()]:
        missing.append("courses")
    if not missing:
        return []
    names = [HUMAN.get(m, m) for m in missing]
    return [_mk(ctx, rule, OUTCOME_FAILED, f"The application is missing: {', '.join(names)}.",
                fields=missing, observed="blank", expected="a value for each required application field")]


def c_app_id_format(ctx: Ctx, rule: Rule) -> list[Finding]:
    v = (ctx.app.institution_id or "").strip()
    if v and not re.fullmatch(rule.params["pattern"], v):
        return [_mk(ctx, rule, OUTCOME_FAILED, f"The institution identifier '{v}' does not have the expected format.",
                    fields=["institution_id"], observed=v, expected=f"pattern {rule.params['pattern']}")]
    return []


def c_intake_valid(ctx: Ctx, rule: Rule) -> list[Finding]:
    mx, out = rule.params.get("max_value", 5000), []
    for c in ctx.app.courses:
        p = parse_intake(c.intake, mx)
        if not p.ok:
            out.append(_mk(ctx, rule, OUTCOME_FAILED, f"The intake '{c.intake}' entered for course '{c.name}' {INTAKE_REASON[p.reason]}.",
                           fields=["approved_intake"], observed=c.intake, expected="a positive whole number"))
    for d in ctx.readable:
        for row in d.course_rows:
            if row.intake is None:
                continue
            p = parse_intake(row.intake.effective(), mx)
            if not p.ok:
                oc, note = (OUTCOME_REVIEW, " It was read by OCR and may be a misread.") if row.intake.method == "ocr" else (OUTCOME_FAILED, "")
                out.append(_mk(ctx, rule, oc, f"The intake '{row.intake.effective()}' on {ctx.label(d)} {INTAKE_REASON[p.reason]}.{note}",
                               document_ids=[d.document_id], fields=["approved_intake"], observed=row.intake.effective(),
                               expected="a positive whole number", evidence=[_ev(d, row.intake)], confidence=row.intake.confidence))
    return out


def _compare_field(ctx, rule, fname, app_value, comparer, subject, cert_word) -> list[Finding]:
    low, out = rule.params.get("low_conf", 0.6), []
    for d in ctx.readable:
        ef = d.primary(fname)
        if ef is None:
            continue
        res = comparer(app_value, ef.effective())
        if res.outcome in (MATCH, UNAVAILABLE):
            continue
        if res.outcome == PROBABLE:
            out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                           f"The {subject} on {ctx.label(d)} ('{ef.effective()}') is similar to, but not the same as, the application ('{app_value}'): {res.note}. It is treated as uncertain, not as a confirmed mismatch.",
                           severity="medium", document_ids=[d.document_id], fields=[fname], observed=ef.effective(),
                           expected=app_value, evidence=[_ev(d, ef)], confidence=res.score))
        else:
            oc, note = _outcome_for_mismatch([ef], low)
            out.append(_mk(ctx, rule, oc, f"The {subject} on {ctx.label(d)} ('{ef.effective()}') does not match the application ('{app_value}').{note}",
                           document_ids=[d.document_id], fields=[fname], observed=ef.effective(), expected=app_value,
                           evidence=[_ev(d, ef)], confidence=ef.confidence))
    return out


def c_xd_institution_name(ctx, rule):
    return _compare_field(ctx, rule, "institution_name", ctx.app.institution_name, compare_names, "institution name", "")


def c_xd_institution_id(ctx, rule):
    return _compare_field(ctx, rule, "institution_id", ctx.app.institution_id, compare_ids, "institution identifier", "")


def c_xd_application_ref(ctx: Ctx, rule: Rule) -> list[Finding]:
    low, out = rule.params.get("low_conf", 0.6), []
    for d in ctx.readable:
        ef = d.primary("application_ref")
        if ef is None:
            continue
        res = compare_ids(ctx.app.reference, ef.effective())
        if res.outcome in (MATCH, UNAVAILABLE):
            continue
        if res.outcome == PROBABLE:
            out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                           f"The application reference on {ctx.label(d)} ('{ef.effective()}') is close to this application's reference ('{ctx.app.reference}') but not identical.",
                           severity="medium", document_ids=[d.document_id], fields=["application_ref"], observed=ef.effective(),
                           expected=ctx.app.reference, evidence=[_ev(d, ef)], confidence=res.score))
        else:
            oc, note = _outcome_for_mismatch([ef], low)
            out.append(_mk(ctx, rule, oc, f"{ctx.label(d).capitalize()} refers to application '{ef.effective()}', not this application ('{ctx.app.reference}'). It may have been issued for a different application.{note}",
                           document_ids=[d.document_id], fields=["application_ref"], observed=ef.effective(),
                           expected=ctx.app.reference, evidence=[_ev(d, ef)], confidence=ef.confidence))
    return out


def _pair_courses(ctx: Ctx, d: ProcessedDocument):
    """For each course row on a document, find the closest application course."""
    rank = {MATCH: 2, PROBABLE: 1, MISMATCH: 0, UNAVAILABLE: -1}
    pairs = []
    for row in d.course_rows:
        best = None
        for c in ctx.app.courses:
            res = compare_names(c.name, row.course.effective())
            if best is None or (rank[res.outcome], res.score) > (rank[best[1].outcome], best[1].score):
                best = (c, res)
        pairs.append((row, best))
    return pairs


def c_xd_course(ctx: Ctx, rule: Rule) -> list[Finding]:
    low, out = rule.params.get("low_conf", 0.6), []
    for d in ctx.readable:
        for row, best in _pair_courses(ctx, d):
            if best is None or best[1].outcome in (MATCH, UNAVAILABLE):
                continue
            c, res = best
            ef = row.course
            if res.outcome == PROBABLE:
                out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                               f"The course '{ef.effective()}' on {ctx.label(d)} is similar to the application course '{c.name}' but not identical.",
                               severity="low", document_ids=[d.document_id], fields=["course_name"], observed=ef.effective(),
                               expected=c.name, evidence=[_ev(d, ef)], confidence=res.score))
            else:
                oc, note = _outcome_for_mismatch([ef], low)
                out.append(_mk(ctx, rule, oc, f"The course '{ef.effective()}' on {ctx.label(d)} does not correspond to any course in the application.{note}",
                               document_ids=[d.document_id], fields=["course_name"], observed=ef.effective(),
                               expected="; ".join(x.name for x in ctx.app.courses) or "a course in the application",
                               evidence=[_ev(d, ef)], confidence=ef.confidence))
    return out


def c_xd_intake(ctx: Ctx, rule: Rule) -> list[Finding]:
    low, out = rule.params.get("low_conf", 0.6), []
    for d in ctx.readable:
        for row, best in _pair_courses(ctx, d):
            if best is None or best[1].outcome not in (MATCH, PROBABLE) or row.intake is None:
                continue
            c, res = best
            pd, pa = parse_intake(row.intake.effective()), parse_intake(c.intake)
            if not (pd.ok and pa.ok) or compare_ints(pd.value, pa.value).outcome != MISMATCH:
                continue
            oc, note = _outcome_for_mismatch([row.intake, row.course], low)
            if res.outcome == PROBABLE:
                oc, note = OUTCOME_REVIEW, " The course name was only a probable match."
            out.append(_mk(ctx, rule, oc,
                           f"For course '{c.name}', {ctx.label(d)} shows an intake of {pd.value} but the application states {pa.value}.{note}",
                           document_ids=[d.document_id], fields=["approved_intake", "course_name"],
                           observed=str(pd.value), expected=str(pa.value),
                           evidence=[_ev(d, row.course), _ev(d, row.intake)], confidence=row.intake.confidence))
    return out


def c_xd_certificate_conflict(ctx: Ctx, rule: Rule) -> list[Finding]:
    out = []
    by_type: dict[str, list[tuple[ProcessedDocument, ExtractedField]]] = {}
    for d in ctx.readable:
        ef = d.primary("certificate_number")
        if ef and d.effective_type:
            by_type.setdefault(d.effective_type, []).append((d, ef))
    for _t, items in by_type.items():
        for (d1, e1), (d2, e2) in combinations(items, 2):
            if compare_ids(e1.effective(), e2.effective()).outcome == MISMATCH:
                out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                               f"{ctx.label(d1).capitalize()} shows certificate number '{e1.effective()}' but {ctx.label(d2)} shows '{e2.effective()}'. Two documents of the same type should normally carry the same number.",
                               document_ids=[d1.document_id, d2.document_id], fields=["certificate_number"],
                               observed=f"{e1.effective()} vs {e2.effective()}", evidence=[_ev(d1, e1), _ev(d2, e2)]))
    for d in ctx.readable:
        vals = {normalize_id(e.effective()) for e in d.fields.get("certificate_number", [])}
        if len(vals) > 1:
            out.append(_mk(ctx, rule, OUTCOME_REVIEW, f"{ctx.label(d).capitalize()} contains more than one different certificate number.",
                           document_ids=[d.document_id], fields=["certificate_number"],
                           observed=", ".join(sorted(vals)), evidence=[_ev(d, e) for e in d.fields["certificate_number"]]))
    return out


def _other_institution(ctx: Ctx, ce: CorpusEntry) -> bool:
    return (ce.application_id != ctx.app.id and
            normalize_id(ce.app_institution_id or "") != normalize_id(ctx.app.institution_id or ""))


def c_dup_exact_within(ctx: Ctx, rule: Rule) -> list[Finding]:
    groups: dict[str, list[ProcessedDocument]] = {}
    for d in ctx.present:
        if d.sha256:
            groups.setdefault(d.sha256, []).append(d)
    return [_mk(ctx, rule, OUTCOME_FAILED,
                f"{len(g)} uploads are byte-for-byte identical ({', '.join(x.original_filename for x in g)}).",
                document_ids=[x.document_id for x in g], observed=f"SHA-256 {sha[:16]}…", expected="each upload to be a distinct file")
            for sha, g in groups.items() if len(g) > 1]


def c_dup_exact_across(ctx: Ctx, rule: Rule) -> list[Finding]:
    out = []
    for d in ctx.present:
        for ce in ctx.corpus:
            if d.sha256 and ce.sha256 == d.sha256 and _other_institution(ctx, ce):
                out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                               f"{ctx.label(d).capitalize()} is byte-for-byte identical to a document in application {ce.application_id}, which belongs to a different institution. A shared file is not proof of misuse (for example a joint letter), but the reviewer should confirm it belongs here.",
                               document_ids=[d.document_id], observed=f"SHA-256 {d.sha256[:16]}…",
                               expected="evidence specific to this institution", reviewer_only=True,
                               limitations="Identical files can be legitimate when one document covers several institutions."))
    return out


def c_dup_cert_reuse(ctx: Ctx, rule: Rule) -> list[Finding]:
    out = []
    for d in ctx.readable:
        for ef in d.fields.get("certificate_number", []):
            key = normalize_id(ef.effective())
            for ce in ctx.corpus:
                if not _other_institution(ctx, ce) or d.sha256 == ce.sha256:
                    continue            # exact reuse is already reported by DUP-002
                if key and key in {normalize_id(c) for c in ce.certificate_numbers}:
                    out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                                   f"Certificate number '{ef.effective()}' on {ctx.label(d)} also appears on a document in application {ce.application_id} for a different institution.",
                                   document_ids=[d.document_id], fields=["certificate_number"], observed=ef.effective(),
                                   evidence=[_ev(d, ef)], reviewer_only=True,
                                   limitations="Numbering schemes can collide by chance; a human must check the issuing records."))
    return out


def c_dup_near(ctx: Ctx, rule: Rule) -> list[Finding]:
    thr, img_max, out = rule.params["text_threshold"], rule.params["image_max_distance"], []
    limit = "Documents from one issuer often share template wording, so similarity alone does not show reuse."
    docs = [d for d in ctx.readable if d.shingles]
    for d1, d2 in combinations(docs, 2):
        if d1.sha256 != d2.sha256 and jaccard(d1.shingles, d2.shingles) >= thr:
            out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                           f"{ctx.label(d1).capitalize()} and {ctx.label(d2)} have almost identical text (similarity {jaccard(d1.shingles, d2.shingles):.2f}) but are different files.",
                           document_ids=[d1.document_id, d2.document_id], observed=f"{jaccard(d1.shingles, d2.shingles):.2f}",
                           expected=f"below {thr}", limitations=limit))
    for d in ctx.readable:
        for ce in ctx.corpus:
            if not _other_institution(ctx, ce) or d.sha256 == ce.sha256:
                continue
            sim = jaccard(d.shingles, ce.shingles)
            if sim >= thr:
                out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                               f"{ctx.label(d).capitalize()} has almost identical text (similarity {sim:.2f}) to a different file in application {ce.application_id} for another institution.",
                               document_ids=[d.document_id], observed=f"{sim:.2f}", expected=f"below {thr}",
                               reviewer_only=True, limitations=limit))
            elif d.phash is not None and ce.phash is not None and hamming(d.phash, ce.phash) <= img_max:
                out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                               f"{ctx.label(d).capitalize()} looks visually near-identical (image hash distance {hamming(d.phash, ce.phash)}) to a different file in application {ce.application_id} for another institution.",
                               document_ids=[d.document_id], observed=f"distance {hamming(d.phash, ce.phash)}",
                               expected=f"more than {img_max}", reviewer_only=True,
                               limitations="Perceptual hashes also match plain pages with similar layout."))
    return out


def c_meta_signals(ctx: Ctx, rule: Rule) -> list[Finding]:
    return [_mk(ctx, rule, OUTCOME_REVIEW, f"{ctx.label(d).capitalize()}: {s['message']}",
                title=f"{rule.name} ({s['code']})", document_ids=[d.document_id], observed=s["code"],
                limitations=s["limitation"])
            for d in ctx.present for s in d.metadata_signals]


def c_pdf_active_content(ctx: Ctx, rule: Rule) -> list[Finding]:
    return [_mk(ctx, rule, OUTCOME_REVIEW, f"{ctx.label(d).capitalize()}: {w.message}",
                document_ids=[d.document_id], observed=w.code)
            for d in ctx.present for w in d.warnings if w.code in ("PDF_ACTIVE_CONTENT", "PDF_EMBEDDED_FILE")]


def c_verification_status(ctx: Ctx, rule: Rule) -> list[Finding]:
    out = []
    docs = {d.document_id: d for d in ctx.docs}
    for vr in ctx.verifications:
        d = docs.get(vr.document_id)
        label = ctx.label(d) if d else vr.document_id
        if vr.status in ("unavailable", "error"):
            out.append(_mk(ctx, rule, OUTCOME_REVIEW, f"Official verification of {label} could not be completed: {vr.detail}",
                           title="Official verification unavailable", severity="medium", document_ids=[vr.document_id], observed=vr.status))
        elif vr.status in ("not_found", "mismatch"):
            out.append(_mk(ctx, rule, OUTCOME_REVIEW, f"The verification source did not confirm {label} ({vr.status.replace('_', ' ')}): {vr.detail} This is not a finding of forgery.",
                           title="Not confirmed by verification source", severity="high", document_ids=[vr.document_id], observed=vr.status))
    return out


def c_system_upload_rejected(ctx: Ctx, rule: Rule) -> list[Finding]:
    return [_mk(ctx, rule, OUTCOME_FAILED, f"The file '{d.original_filename}' was rejected: {' '.join(e.message for e in d.errors)}",
                document_ids=[d.document_id], observed=", ".join(e.code for e in d.errors))
            for d in ctx.docs if d.status == "rejected"]


def c_system_unreadable(ctx: Ctx, rule: Rule) -> list[Finding]:
    return [_mk(ctx, rule, OUTCOME_REVIEW,
                f"No usable text could be read from {ctx.label(d)}, so field checks were skipped for it. A reviewer should inspect the original.",
                document_ids=[d.document_id], observed="no text extracted")
            for d in ctx.docs if d.status == "unreadable"]


def c_system_low_confidence(ctx: Ctx, rule: Rule) -> list[Finding]:
    thr, out = rule.params["threshold"], []
    for d in ctx.readable:
        if d.ocr_mean_conf is not None and d.ocr_mean_conf < thr:
            flags = (d.image_quality or {}).get("flags") or []
            more = f" Image-quality signals: {', '.join(flags)}." if flags else ""
            out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                           f"Text on {ctx.label(d)} was read with low average confidence ({d.ocr_mean_conf:.2f}); extracted values may be wrong.{more}",
                           document_ids=[d.document_id], observed=f"{d.ocr_mean_conf:.2f}", expected=f"at least {thr}"))
    return out


def c_system_type_mismatch(ctx: Ctx, rule: Rule) -> list[Finding]:
    out = []
    for d in ctx.readable:
        if d.declared_type and d.detected_type and d.declared_type != d.detected_type and d.detected_confidence >= rule.params["min_confidence"]:
            dt = ctx.ruleset.document_types
            out.append(_mk(ctx, rule, OUTCOME_REVIEW,
                           f"'{d.original_filename}' was uploaded as {dt.get(d.declared_type, {}).get('label', d.declared_type)} but its text looks like {dt.get(d.detected_type, {}).get('label', d.detected_type)}.",
                           document_ids=[d.document_id], observed=d.detected_type, expected=d.declared_type,
                           confidence=d.detected_confidence))
    return out


CHECKS: dict[str, Callable[[Ctx, Rule], list[Finding]]] = {
    "required_document": c_required_document, "required_field": c_required_field,
    "date_valid": c_date_valid, "not_expired": c_not_expired, "date_order": c_date_order,
    "date_not_future": c_date_not_future, "app_fields_present": c_app_fields_present,
    "app_id_format": c_app_id_format, "intake_valid": c_intake_valid,
    "xd_institution_name": c_xd_institution_name, "xd_institution_id": c_xd_institution_id,
    "xd_application_ref": c_xd_application_ref, "xd_course": c_xd_course, "xd_intake": c_xd_intake,
    "xd_certificate_conflict": c_xd_certificate_conflict, "dup_exact_within": c_dup_exact_within,
    "dup_exact_across": c_dup_exact_across, "dup_cert_reuse": c_dup_cert_reuse, "dup_near": c_dup_near,
    "meta_signals": c_meta_signals, "pdf_active_content": c_pdf_active_content,
    "verification_status": c_verification_status, "system_upload_rejected": c_system_upload_rejected,
    "system_unreadable": c_system_unreadable, "system_low_confidence": c_system_low_confidence,
    "system_type_mismatch": c_system_type_mismatch,
}


@dataclass
class ValidationReport:
    application_id: str
    ruleset_id: str
    ruleset_version: str
    generated_at: str
    findings: list[Finding] = field(default_factory=list)
    rules_run: list[dict] = field(default_factory=list)
    rules_skipped: list[dict] = field(default_factory=list)

    @property
    def suggested_status(self) -> str:
        return "review_required" if self.findings else "validation_complete"

    def counts(self) -> dict:
        c = {"failed": 0, "review_required": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for f in self.findings:
            c[f.outcome] += 1
            c[f.severity] += 1
        return c


def validate_application(app: Application, docs: list[ProcessedDocument], ruleset: RuleSet,
                         corpus: tuple | list = (), verifications: tuple | list = (),
                         today: Optional[date] = None) -> ValidationReport:
    ctx = Ctx(app, docs, ruleset, today or date.today(), tuple(corpus), tuple(verifications))
    report = ValidationReport(app.id, ruleset.ruleset_id, ruleset.version, utcnow_iso())
    for rule in ruleset.rules:
        if not rule.enabled:
            report.rules_skipped.append({"rule_id": rule.rule_id, "reason": "disabled"})
            continue
        if not rule.applies(app.application_type):
            report.rules_skipped.append({"rule_id": rule.rule_id, "reason": "not applicable to this application type"})
            continue
        fn = CHECKS.get(rule.check)
        if fn is None:
            raise RuleSetError(f"{rule.rule_id}: unknown check '{rule.check}'")
        t0 = time.perf_counter()
        found = fn(ctx, rule)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        report.findings.extend(found)
        report.rules_run.append({"rule_id": rule.rule_id, "version": rule.version, "findings": len(found), "ms": ms})
    return report
