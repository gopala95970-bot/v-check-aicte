"""Row <-> object helpers shared by the services. No business rules here."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from vcheck import workflow
from vcheck.duplicates import CorpusEntry
from vcheck.models import Application, CourseRow, ProcessedDocument

from .context import Context
from .errors import not_found
from .serialize import doc_from_json

OPEN_STATUSES = ("open", "under_review")
FINDING_STATUSES = ("open", "under_review", "resolved", "accepted_with_explanation")
STORAGE_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|png|jpg)$")


def j(s: Optional[str], default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default


# ------------------------------------------------------------------ applications
APP_SELECT = """
SELECT a.*, i.name AS inst_name, i.institution_id AS inst_code, i.address AS inst_address, i.state AS inst_state,
       i.district AS inst_district, i.contact_name, i.contact_email, i.contact_phone,
       o.name AS owner_name, o.email AS owner_email, r.name AS reviewer_name, r.email AS reviewer_email
FROM applications a
JOIN institutions i ON i.id = a.institution_pk
JOIN users o ON o.id = a.owner_id
LEFT JOIN users r ON r.id = a.reviewer_id
"""


def get_app_row(ctx: Context, app_id: str):
    row = ctx.db.one(APP_SELECT + " WHERE a.id=?", (app_id,))
    if row is None:
        raise not_found("Application not found.")
    return row


def app_courses(ctx: Context, app_id: str) -> list[dict]:
    return [{"name": r["name"], "intake": r["intake"]} for r in
            ctx.db.all("SELECT name, intake FROM application_courses WHERE application_id=? ORDER BY position", (app_id,))]


def app_model(ctx: Context, row) -> Application:
    courses = [CourseRow(c["name"], c["intake"]) for c in app_courses(ctx, row["id"])]
    return Application(id=row["id"], reference=row["reference"], institution_name=row["inst_name"],
                       institution_id=row["inst_code"], state=row["inst_state"], address=row["inst_address"],
                       application_type=row["application_type"], courses=courses, is_demo=bool(row["is_demo"]))


def finding_counts(ctx: Context, app_id: str) -> dict:
    rows = ctx.db.all("SELECT severity, outcome, status, COUNT(*) n FROM findings WHERE application_id=? AND is_current=1 "
                      "GROUP BY severity, outcome, status", (app_id,))
    out = {"total": 0, "open": 0, "failed": 0, "review_required": 0, "high": 0, "critical_open": 0}
    for r in rows:
        n = r["n"]
        out["total"] += n
        if r["status"] in OPEN_STATUSES:
            out["open"] += n
            if r["severity"] == "high" and r["outcome"] == "failed":
                out["critical_open"] += n
        out[r["outcome"]] = out.get(r["outcome"], 0) + n
        if r["severity"] == "high":
            out["high"] += n
    return out


def validation_state(ctx: Context, app_id: str, counts: dict) -> str:
    ran = ctx.db.scalar("SELECT COUNT(*) FROM validation_runs WHERE application_id=? AND status='complete'", (app_id,))
    if not ran:
        return "not_run"
    if counts["total"] == 0:
        return "passed"
    return "failed" if counts["failed"] else "review_required"


def app_dict(ctx: Context, row, *, detail: bool = False, role: str = "reviewer") -> dict[str, Any]:
    app_id = row["id"]
    counts = finding_counts(ctx, app_id)
    if role == "applicant":      # applicants never count reviewer-only findings
        hidden = ctx.db.scalar("SELECT COUNT(*) FROM findings WHERE application_id=? AND is_current=1 AND reviewer_only=1", (app_id,)) or 0
        counts["total"] = max(0, counts["total"] - hidden)
    docs = ctx.db.scalar("SELECT COUNT(*) FROM documents WHERE application_id=? AND active=1", (app_id,))
    d = {
        "id": app_id, "reference": row["reference"], "application_type": row["application_type"],
        "application_type_label": (ctx.active_ruleset().application_types.get(row["application_type"]) or {}).get("label", row["application_type"]),
        "academic_year": row["academic_year"], "status": row["status"],
        "status_label": workflow.STATUS_LABELS.get(row["status"], row["status"]),
        "institution": {"name": row["inst_name"], "institution_id": row["inst_code"], "state": row["inst_state"],
                        "district": row["inst_district"], "address": row["inst_address"]},
        "created_at": row["created_at"], "submitted_at": row["submitted_at"], "updated_at": row["updated_at"],
        "document_count": docs, "findings": counts, "validation": validation_state(ctx, app_id, counts),
        "reviewer": ({"id": row["reviewer_id"], "name": row["reviewer_name"]} if row["reviewer_id"] else None),
        "owner": {"id": row["owner_id"], "name": row["owner_name"]},
        "escalated": bool(row["escalated"]), "is_demo": bool(row["is_demo"]), "demo_scenario": row["demo_scenario"],
        "correction_cycles": row["correction_cycles"],
        "processing": ctx.is_pending(f"app:{app_id}") or row["status"] in (workflow.PROCESSING,),
    }
    if detail:
        d["institution"].update({"contact_name": row["contact_name"], "contact_email": row["contact_email"],
                                 "contact_phone": row["contact_phone"]})
        d["courses"] = app_courses(ctx, app_id)
        d["notes"] = row["notes"]
        d["verification_mode"] = row["verification_mode"]
        d["decision"] = ({"remarks": row["decision_remarks"], "by": row["decided_by"], "at": row["decided_at"],
                          "demonstration_only": True} if row["decided_at"] else None)
        d["allowed_transitions"] = workflow.allowed_targets(row["status"], role)
    return d


# ------------------------------------------------------------------ documents
def doc_label(ctx: Context, declared: Optional[str]) -> str:
    return (ctx.active_ruleset().document_types.get(declared or "") or {}).get("label", declared or "Unclassified document")


def doc_dict(ctx: Context, row, *, fields: bool = False) -> dict[str, Any]:
    issues = j(row["issues_json"], {"errors": [], "warnings": []})
    d = {
        "id": row["id"], "application_id": row["application_id"], "declared_type": row["declared_type"],
        "type_label": doc_label(ctx, row["declared_type"]), "filename": row["original_filename"],
        "kind": row["kind"], "size": row["size"], "sha256": row["sha256"], "status": row["status"],
        "detected_type": row["detected_type"], "detected_type_label": doc_label(ctx, row["detected_type"]) if row["detected_type"] else None,
        "detected_confidence": row["detected_confidence"], "text_source": row["text_source"],
        "ocr_mean_conf": row["ocr_mean_conf"], "page_count": row["page_count"], "errors": issues.get("errors", []),
        "warnings": issues.get("warnings", []), "uploaded_at": row["created_at"], "processed_at": row["processed_at"],
        "previewable": bool(row["storage_name"]), "active": bool(row["active"]),
    }
    d["steps"] = doc_steps(row, issues)
    if fields:
        d["fields"] = field_rows(ctx, row["id"])
    return d


def doc_steps(row, issues: dict) -> list[dict]:
    """Per-file checklist shown in the upload UI (Uploaded -> OCR -> Fields -> Verification)."""
    st = row["status"]
    done = st in ("processed", "unreadable", "rejected")
    steps = [{"key": "uploaded", "label": "Uploaded", "state": "done"}]
    if st == "rejected":
        steps.append({"key": "integrity", "label": "File check", "state": "failed"})
        return steps
    steps.append({"key": "integrity", "label": "File check", "state": "done"})
    if not done:
        steps.append({"key": "ocr", "label": "OCR / text read", "state": "running" if st == "processing" else "pending"})
        steps.append({"key": "fields", "label": "Fields extracted", "state": "pending"})
        return steps
    steps.append({"key": "ocr", "label": "OCR / text read" if row["text_source"] != "text_layer" else "Text layer read",
                  "state": "review" if st == "unreadable" else "done"})
    nf = row["field_count"] if "field_count" in row.keys() else None
    steps.append({"key": "fields", "label": "Fields extracted",
                  "state": "skipped" if st == "unreadable" else ("done" if (nf is None or nf > 0) else "review")})
    if row["declared_type"] and row["detected_type"] and row["declared_type"] != row["detected_type"]:
        steps.append({"key": "classification", "label": "Type check", "state": "review"})
    return steps


def field_rows(ctx: Context, doc_id: str) -> list[dict]:
    return [{"id": r["id"], "name": r["name"], "index": r["idx"], "value": r["value"], "corrected_value": r["corrected_value"],
             "effective_value": r["corrected_value"] if r["corrected_value"] is not None else r["value"],
             "page": r["page"], "line_no": r["line_no"], "snippet": r["snippet"], "confidence": r["confidence"],
             "method": r["method"], "bbox": j(r["bbox"]), "corrected_by": r["corrected_by"], "corrected_at": r["corrected_at"]}
            for r in ctx.db.all("SELECT * FROM extracted_fields WHERE document_id=? ORDER BY id", (doc_id,))]


DOC_SELECT = "SELECT d.*, (SELECT COUNT(*) FROM extracted_fields f WHERE f.document_id=d.id) AS field_count FROM documents d"


def get_doc_row(ctx: Context, doc_id: str):
    row = ctx.db.one(DOC_SELECT + " WHERE d.id=?", (doc_id,))
    if row is None:
        raise not_found("Document not found.")
    return row


def load_processed_docs(ctx: Context, app_id: str) -> list[ProcessedDocument]:
    """Rehydrate the application's active documents, overlaying reviewer corrections."""
    out = []
    for row in ctx.db.all("SELECT id, processed_json FROM documents WHERE application_id=? AND active=1 "
                          "AND processed_json IS NOT NULL ORDER BY created_at, id", (app_id,)):
        doc = doc_from_json(json.loads(row["processed_json"]))
        doc.document_id = row["id"]
        corr = ctx.db.all("SELECT name, idx, corrected_value FROM extracted_fields WHERE document_id=? AND corrected_value IS NOT NULL", (row["id"],))
        for c in corr:
            lst = doc.fields.get(c["name"], [])
            if c["idx"] < len(lst):
                lst[c["idx"]].corrected_value = c["corrected_value"]
        out.append(doc)
    return out


def build_corpus(ctx: Context, app_id: str) -> tuple:
    entries = []
    rows = ctx.db.all("""SELECT d.id, d.application_id, d.sha256, d.text_fingerprint, d.phash, d.certificate_numbers,
                                json_extract(d.processed_json,'$.shingles') AS sh, i.institution_id AS inst
                         FROM documents d JOIN applications a ON a.id=d.application_id
                         JOIN institutions i ON i.id=a.institution_pk
                         WHERE d.application_id<>? AND d.active=1 AND d.status IN ('processed','unreadable')
                           AND a.status<>'draft'""", (app_id,))
    for r in rows:
        entries.append(CorpusEntry(r["application_id"], r["id"], r["inst"], r["sha256"], r["text_fingerprint"],
                                   frozenset(j(r["sh"], [])), tuple(j(r["certificate_numbers"], [])),
                                   int(r["phash"]) if r["phash"] else None))
    return tuple(entries)


def doc_path(ctx: Context, storage_name: str) -> Path:
    if not storage_name or not STORAGE_RE.match(storage_name):
        raise not_found("File not available.")
    base = ctx.settings.upload_dir.resolve()
    p = (base / storage_name).resolve()
    if base not in p.parents:           # path-traversal guard (belt and braces; names are generated)
        raise not_found("File not available.")
    return p


# ------------------------------------------------------------------ findings
SEV_RANK = {"high": 3, "medium": 2, "low": 1, "info": 0}


def finding_dict(ctx: Context, row, doc_names: Optional[dict] = None) -> dict[str, Any]:
    rs = ctx.active_ruleset()
    rule = rs.rule(row["rule_id"])
    doc_ids = j(row["document_ids_json"], [])
    names = doc_names if doc_names is not None else {
        r["id"]: (r["original_filename"], r["declared_type"]) for r in
        ctx.db.all("SELECT id, original_filename, declared_type FROM documents WHERE application_id=?", (row["application_id"],))}
    ev = j(row["evidence_json"], [])
    for e in ev:
        n = names.get(e.get("document_id"))
        e["filename"] = n[0] if n else None
    return {
        "id": row["public_id"], "application_id": row["application_id"], "run_id": row["run_id"],
        "rule_id": row["rule_id"], "rule_version": row["rule_version"], "rule_name": rule.name if rule else row["rule_id"],
        "rule_source_status": rule.source_status if rule else None, "rule_source_ref": rule.source_ref if rule else None,
        "rule_kind": rule_kind(rule.source_status) if rule else "demonstration",
        "title": row["title"], "outcome": row["outcome"], "severity": row["severity"],
        "critical": row["severity"] == "high" and row["outcome"] == "failed",
        "explanation": row["explanation"], "recommended_action": row["recommended_action"],
        "observed": row["observed"], "expected": row["expected"], "confidence": row["confidence"],
        "limitations": row["limitations"], "reviewer_only": bool(row["reviewer_only"]),
        "documents": [{"id": d, "filename": (names.get(d) or (None,))[0], "declared_type": (names.get(d) or (None, None))[1]} for d in doc_ids],
        "fields": j(row["fields_json"], []), "evidence": ev,
        "status": row["status"], "resolution_note": row["resolution_note"], "resolved_by": row["resolved_by"],
        "resolved_at": row["resolved_at"], "is_current": bool(row["is_current"]), "created_at": row["created_at"],
    }


def rule_kind(source_status: str) -> str:
    """Officially sourced vs demonstration rules are always distinguished in the API."""
    return "official" if source_status == "official_confirmed" else "demonstration"
