"""Processing runner: connects the engine modules to the database.

upload -> (File Integrity) -> OCR/text read -> classification -> field extraction -> normalise/match ->
duplicate check -> rule engine -> verification -> findings -> human review.
Every stage is persisted with its real duration so the Verification Center shows measured data only.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from vcheck import files, workflow
from vcheck.engine import validate_application
from vcheck.models import ProcessedDocument, new_id, utcnow_iso
from vcheck.pipeline import process_document
from vcheck.verification import SimulatedProvider, UnavailableProvider, verify_documents

from . import repo
from .context import SYSTEM, Context
from .serialize import doc_to_json

log = logging.getLogger("vcheck.processing")

DOC_STAGES = ["Document Received", "File Integrity", "OCR", "Classification", "Field Extraction"]
APP_STAGES = ["Cross-document Validation", "Duplicate Detection", "Compliance Rules", "Source Verification"]
ALL_STAGES = DOC_STAGES + APP_STAGES + ["Human Review"]
VERIFICATION_MODES = ("off", "simulation", "unavailable")


def stage_for_rule(rule_id: str) -> str:
    if rule_id.startswith("XD-"):
        return "Cross-document Validation"
    if rule_id.startswith(("DUP-", "META-")):
        return "Duplicate Detection"
    if rule_id.startswith("VER-"):
        return "Source Verification"
    return "Compliance Rules"


# ============================================================ document upload + processing
def add_stage(ctx: Context, app_id: str, scope: str, stage: str, status: str, ms: Optional[int], result: str,
              *, doc_id: Optional[str] = None, run_id: Optional[int] = None, evidence=None, errors=None, conn=None) -> None:
    sql = """INSERT INTO stage_events(application_id,run_id,document_id,scope,stage,status,duration_ms,result,
             evidence_json,errors_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)"""
    args = (app_id, run_id, doc_id, scope, stage, status, ms, result, json.dumps(evidence or []),
            json.dumps(errors or []), utcnow_iso())
    if conn is not None:
        conn.execute(sql, args)
    else:
        with ctx.db.tx() as c:
            c.execute(sql, args)


def create_document(ctx: Context, app_id: str, raw: bytes, filename: str, declared_type: Optional[str],
                    user: dict, replaces: Optional[str] = None) -> str:
    """Validate and store an upload, then queue processing. Returns the document id.

    Files that fail the sniff/size/structure check are recorded (so the reviewer sees a finding) but their
    bytes are NOT kept on disk."""
    chk = files.validate_upload(raw, filename, max_bytes=ctx.max_upload_bytes, max_pages=ctx.max_pdf_pages)
    doc_id = new_id("DOC")
    storage = None
    if chk.ok:
        storage = files.storage_name(chk.kind)
        ctx.settings.ensure_dirs()
        (ctx.settings.upload_dir / storage).write_bytes(raw)
    now = utcnow_iso()
    status = "queued" if chk.ok else "rejected"
    with ctx.db.tx() as c:
        if replaces:
            c.execute("UPDATE documents SET active=0 WHERE id=?", (replaces,))
        c.execute("""INSERT INTO documents(id,application_id,declared_type,original_filename,storage_name,kind,size,sha256,status,
                     issues_json,active,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                  (doc_id, app_id, declared_type, chk.display_name, storage, chk.kind, chk.size, chk.sha256, status,
                   json.dumps({"errors": [e.__dict__ for e in chk.errors], "warnings": [w.__dict__ for w in chk.warnings]}),
                   user.get("id"), now))
    if not chk.ok:
        # Run the pipeline in-line: it is cheap for rejected files and yields the ProcessedDocument the engine needs.
        _process_document_job(ctx, doc_id, raw=raw)
    else:
        ctx.mark_pending(f"doc:{doc_id}")
        if ctx.settings.sync_processing:
            _process_document_job(ctx, doc_id)
        else:
            ctx.executor.submit(_process_document_job, ctx, doc_id)
    return doc_id


def _process_document_job(ctx: Context, doc_id: str, raw: Optional[bytes] = None) -> None:
    key = f"doc:{doc_id}"
    try:
        row = ctx.db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
        if row is None or not row["active"] and row["status"] != "queued":
            return
        app_id = row["application_id"]
        with ctx.db.tx() as c:
            c.execute("UPDATE documents SET status='processing' WHERE id=? AND status='queued'", (doc_id,))
            c.execute("DELETE FROM stage_events WHERE document_id=?", (doc_id,))
        if raw is None:
            raw = repo.doc_path(ctx, row["storage_name"]).read_bytes()
        t = {}
        t0 = time.perf_counter()
        doc: ProcessedDocument = process_document(raw, row["original_filename"], doc_id, app_id, row["declared_type"],
                                                  ctx.active_ruleset(), ctx.today(), ctx.max_upload_bytes, timings=t)
        total = round((time.perf_counter() - t0) * 1000)
        _persist_document(ctx, row, doc, t, total)
    except Exception:                     # a bad file must never leave a document stuck in "processing"
        log.exception("document processing failed for %s", doc_id)
        with ctx.db.tx() as c:
            c.execute("UPDATE documents SET status='unreadable', processed_at=?, issues_json=? WHERE id=?",
                      (utcnow_iso(), json.dumps({"errors": [], "warnings": [{"code": "READ_FAILED", "message": "The document could not be processed and was routed to manual review."}]}), doc_id))
    finally:
        ctx.clear_pending(key)


def _persist_document(ctx: Context, row, doc: ProcessedDocument, t: dict, total_ms: int) -> None:
    app_id, doc_id = row["application_id"], row["id"]
    certs = [f.effective() for f in doc.fields.get("certificate_number", [])]
    n_fields = sum(len(v) for v in doc.fields.values())
    with ctx.db.tx() as c:
        c.execute("""UPDATE documents SET status=?, kind=?, sha256=?, detected_type=?, detected_confidence=?, text_source=?,
                     ocr_mean_conf=?, page_count=?, text_fingerprint=?, phash=?, certificate_numbers=?, processed_json=?,
                     issues_json=?, processed_at=? WHERE id=?""",
                  (doc.status, doc.kind, doc.sha256, doc.detected_type, doc.detected_confidence, doc.text_source,
                   doc.ocr_mean_conf, len(doc.pages), doc.text_fingerprint, str(doc.phash) if doc.phash is not None else None,
                   json.dumps(certs), json.dumps(doc_to_json(doc)),
                   json.dumps({"errors": [e.__dict__ for e in doc.errors], "warnings": [w.__dict__ for w in doc.warnings]}),
                   utcnow_iso(), doc_id))
        c.execute("DELETE FROM extracted_fields WHERE document_id=?", (doc_id,))
        for name, vals in doc.fields.items():
            for idx, f in enumerate(vals):
                c.execute("""INSERT INTO extracted_fields(document_id,name,idx,value,page,line_no,snippet,confidence,method,bbox)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (doc_id, name, idx, f.value, f.page, f.line_no, f.snippet, f.confidence, f.method,
                           json.dumps(list(f.bbox)) if f.bbox else None))
        _write_doc_stages(ctx, c, row, doc, t, n_fields)


def _write_doc_stages(ctx: Context, c, row, doc: ProcessedDocument, t: dict, n_fields: int) -> None:
    app_id, doc_id = row["application_id"], row["id"]
    S = lambda stage, status, ms, result, **kw: add_stage(ctx, app_id, "document", stage, status, ms, result, doc_id=doc_id, conn=c, **kw)  # noqa: E731
    S("Document Received", "passed", 0, f"{doc.original_filename} ({doc.size:,} bytes) received.",
      evidence=[f"SHA-256 {doc.sha256[:16]}…"] if doc.sha256 else [])
    if doc.status == "rejected":
        S("File Integrity", "failed", t.get("integrity_ms"), "File rejected: " + " ".join(e.message for e in doc.errors),
          errors=[e.code for e in doc.errors])
        for st in ("OCR", "Classification", "Field Extraction"):
            S(st, "skipped", None, "Skipped: the file did not pass the integrity check.")
        return
    warn = [w.code for w in doc.warnings if w.code in ("PDF_ACTIVE_CONTENT", "PDF_EMBEDDED_FILE")]
    S("File Integrity", "review" if warn else "passed", t.get("integrity_ms"),
      "Content type, size and structure verified" + ("; active content flagged for review." if warn else "."),
      evidence=[f"Detected format: {(doc.kind or '').upper()}"], errors=warn)
    if doc.status == "unreadable":
        S("OCR", "review", t.get("read_ms"), "Little or no usable text could be read; routed to manual review.",
          errors=[w.code for w in doc.warnings])
        for st in ("Classification", "Field Extraction"):
            S(st, "skipped", None, "Skipped: no readable text.")
        return
    if doc.text_source == "text_layer":
        S("OCR", "passed", t.get("read_ms"), f"Embedded text layer read directly ({len(doc.pages)} page(s)); OCR not needed.")
    else:
        conf = doc.ocr_mean_conf
        S("OCR", "review" if (conf is not None and conf < 0.6) else "passed", t.get("read_ms"),
          f"OCR on {len(doc.pages)} page(s), mean confidence {conf:.2f}." if conf is not None else "OCR completed.",
          evidence=[f"Text source: {doc.text_source}"])
    declared, detected = doc.declared_type, doc.detected_type
    if declared and detected and declared != detected:
        S("Classification", "review", None, f"Declared as '{declared}' but content looks like '{detected}'.")
    elif detected:
        S("Classification", "passed", None, f"Classified as '{detected}' (score {doc.detected_confidence:.2f}).")
    else:
        S("Classification", "review", None, "Could not classify the document from its content.")
    S("Field Extraction", "passed" if n_fields else "review", t.get("extract_ms"),
      f"{n_fields} field(s) extracted with page and line references." if n_fields else "No fields could be extracted.")


# ============================================================ application validation
def provider_for(ctx: Context, app_row):
    mode = app_row["verification_mode"] or ctx.get_setting("verification_mode") or "off"
    if mode == "unavailable":
        return UnavailableProvider(), mode
    if mode == "simulation":
        reg = {r["certificate_number"]: r["institution_id"] for r in ctx.db.all("SELECT * FROM verification_registry")}
        return SimulatedProvider(reg), mode
    return None, "off"


def wait_for_documents(ctx: Context, app_id: str, timeout: float = 180.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        n = ctx.db.scalar("SELECT COUNT(*) FROM documents WHERE application_id=? AND active=1 AND status IN ('queued','processing')", (app_id,))
        if not n:
            return
        time.sleep(0.1)


def _signature(f) -> str:
    return "|".join([f.rule_id, f.title, f.observed or "", f.expected or ""])


def run_validation(ctx: Context, app_id: str, actor: dict, trigger: str, *, carry_status: bool = False) -> int:
    """Run the full rule engine over the application's current documents and persist everything."""
    row = repo.get_app_row(ctx, app_id)
    app = repo.app_model(ctx, row)
    rs = ctx.active_ruleset()
    started = time.perf_counter()
    with ctx.db.tx() as c:
        run_id = c.execute("""INSERT INTO validation_runs(application_id,ruleset_id,ruleset_version,triggered_by,trigger,started_at,status)
                              VALUES(?,?,?,?,?,?, 'running')""", (app_id, rs.ruleset_id, rs.version, actor["email"], trigger, utcnow_iso())).lastrowid
    try:
        docs = repo.load_processed_docs(ctx, app_id)
        corpus = repo.build_corpus(ctx, app_id)
        provider, mode = provider_for(ctx, row)
        tv = time.perf_counter()
        vers = verify_documents(provider, docs)
        ver_ms = round((time.perf_counter() - tv) * 1000)
        report = validate_application(app, docs, rs, corpus, vers, ctx.today())
        duration = round((time.perf_counter() - started) * 1000)
        _persist_run(ctx, run_id, app_id, report, vers, mode, ver_ms, duration, carry_status, docs)
    except Exception as exc:
        log.exception("validation failed for %s", app_id)
        with ctx.db.tx() as c:
            c.execute("UPDATE validation_runs SET status='error', finished_at=?, error=? WHERE id=?",
                      (utcnow_iso(), type(exc).__name__ + ": " + str(exc)[:200], run_id))
        raise
    return run_id


def _persist_run(ctx: Context, run_id: int, app_id: str, report, vers, mode: str, ver_ms: int, duration: int,
                 carry: bool, docs) -> None:
    with ctx.db.tx() as c:
        prior = {}
        if carry:
            for r in c.execute("SELECT signature,status,resolution_note,resolved_by,resolved_at FROM findings WHERE application_id=? AND is_current=1", (app_id,)):
                prior[r["signature"]] = r
        c.execute("UPDATE findings SET is_current=0 WHERE application_id=?", (app_id,))
        by_stage: dict[str, list] = {s: [] for s in APP_STAGES}
        for f in report.findings:
            sig = _signature(f)
            p = prior.get(sig)
            cur = c.execute("""INSERT INTO findings(public_id,run_id,application_id,signature,rule_id,rule_version,title,outcome,severity,
                    explanation,recommended_action,observed,expected,confidence,limitations,reviewer_only,document_ids_json,
                    fields_json,evidence_json,status,resolution_note,resolved_by,resolved_at,is_current,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                            ("TMP-" + uuid.uuid4().hex, run_id, app_id, sig, f.rule_id, f.rule_version, f.title, f.outcome, f.severity,
                             f.explanation, f.recommended_action, f.observed, f.expected, f.confidence, f.limitations,
                             int(f.reviewer_only), json.dumps(f.document_ids), json.dumps(f.fields),
                             json.dumps([e.__dict__ if not hasattr(e, "__dataclass_fields__") else _ev(e) for e in f.evidence]),
                             p["status"] if p else "open", p["resolution_note"] if p else None,
                             p["resolved_by"] if p else None, p["resolved_at"] if p else None, f.processed_at))
            pid = f"VF-{1000 + cur.lastrowid}"
            c.execute("UPDATE findings SET public_id=? WHERE id=?", (pid, cur.lastrowid))
            by_stage[stage_for_rule(f.rule_id)].append((pid, f))
        for v in vers:
            c.execute("""INSERT INTO verification_results(run_id,application_id,document_id,provider,simulated,status,display_status,detail,checked_at)
                         VALUES(?,?,?,?,?,?,?,?,?)""", (run_id, app_id, v.document_id, v.provider, int(v.simulated), v.status, v.display_status, v.detail, v.checked_at))
        # ---- stage rows (application scope) with measured time per rule group
        ms_by_stage = {s: 0.0 for s in APP_STAGES}
        runs_by_stage = {s: 0 for s in APP_STAGES}
        for r in report.rules_run:
            s = stage_for_rule(r["rule_id"])
            ms_by_stage[s] += r.get("ms", 0.0)
            runs_by_stage[s] += 1
        for s in APP_STAGES:
            items = by_stage[s]
            if s == "Source Verification":
                ms_by_stage[s] += ver_ms
            if s == "Source Verification" and mode == "off":
                add_stage(ctx, app_id, "application", s, "skipped", 0,
                          "No verification source is enabled (simulation is off). Nothing was verified.", run_id=run_id, conn=c)
                continue
            if not runs_by_stage[s] and s != "Source Verification":
                add_stage(ctx, app_id, "application", s, "skipped", 0, "No enabled rules in this group.", run_id=run_id, conn=c)
                continue
            if items:
                failed = any(f.outcome == "failed" for _, f in items)
                result = f"{len(items)} finding(s) from {runs_by_stage[s]} rule(s)."
                status = "failed" if failed else "review"
            else:
                status = "passed"
                result = f"{runs_by_stage[s]} rule(s) passed with no findings."
                if s == "Source Verification":
                    result = (f"{len(vers)} document(s) checked against a SIMULATED synthetic registry; not a government verification."
                              if mode == "simulation" else "Source unavailable.")
            add_stage(ctx, app_id, "application", s, status, round(ms_by_stage[s]), result, run_id=run_id,
                      evidence=[pid for pid, _ in items][:12], errors=[], conn=c)
        c.execute("""UPDATE validation_runs SET status='complete', finished_at=?, duration_ms=?, counts_json=?, suggested_status=?,
                     rules_run_json=?, rules_skipped_json=? WHERE id=?""",
                  (utcnow_iso(), duration, json.dumps(report.counts()), report.suggested_status,
                   json.dumps(report.rules_run), json.dumps(report.rules_skipped), run_id))


def _ev(e) -> dict:
    d = {"document_id": e.document_id, "page": e.page, "line_no": e.line_no, "snippet": e.snippet, "field": e.field,
         "bbox": list(e.bbox) if e.bbox else None}
    return d


# ============================================================ application pipeline (submit / resubmit / revalidate)
def start_pipeline(ctx: Context, app_id: str, actor: dict, trigger: str) -> None:
    """Move the application to 'processing' (system transition) and run validation in the background."""
    row = repo.get_app_row(ctx, app_id)
    new = workflow.transition(row["status"], workflow.PROCESSING, "system")
    with ctx.db.tx() as c:
        c.execute("UPDATE applications SET status=?, updated_at=? WHERE id=?", (new, utcnow_iso(), app_id))
        ctx.audit(SYSTEM, "pipeline.started", "application", app_id, f"Validation pipeline started ({trigger}).",
                  application_id=app_id, from_status=row["status"], to_status=new, conn=c)
    ctx.mark_pending(f"app:{app_id}")
    if ctx.settings.sync_processing:
        _application_job(ctx, app_id, actor, trigger)
    else:
        ctx.executor.submit(_application_job, ctx, app_id, actor, trigger)


def _application_job(ctx: Context, app_id: str, actor: dict, trigger: str) -> None:
    try:
        wait_for_documents(ctx, app_id)
        started_from = repo.get_app_row(ctx, app_id)["status"]
        try:
            run_id = run_validation(ctx, app_id, actor, trigger)
        except Exception:
            _finish_app(ctx, app_id, started_from, workflow.REVIEW_REQUIRED, "pipeline.error",
                        "Validation could not be completed; routed to manual review.", result="error")
            return
        n = ctx.db.scalar("SELECT COUNT(*) FROM findings WHERE run_id=?", (run_id,))
        target = workflow.REVIEW_REQUIRED if n else workflow.VALIDATION_COMPLETE
        _finish_app(ctx, app_id, started_from, target, "pipeline.completed",
                    f"Validation complete: {n} finding(s). Suggested status: {target}.")
    finally:
        ctx.clear_pending(f"app:{app_id}")


def _finish_app(ctx: Context, app_id: str, from_status: str, target: str, action: str, desc: str, result: str = "success") -> None:
    row = repo.get_app_row(ctx, app_id)
    if row["status"] != workflow.PROCESSING:
        return
    new = workflow.transition(row["status"], target, "system")
    with ctx.db.tx() as c:
        c.execute("UPDATE applications SET status=?, updated_at=? WHERE id=?", (new, utcnow_iso(), app_id))
        ctx.audit(SYSTEM, action, "application", app_id, desc, application_id=app_id, from_status=row["status"],
                  to_status=new, result=result, conn=c)
    ctx.notify(row["owner_id"], "processing", f"{row['reference']}: validation finished",
               "Open the application to see the result.", app_id)
    if new == workflow.REVIEW_REQUIRED and row["reviewer_id"]:
        ctx.notify(row["reviewer_id"], "review", f"{row['reference']} needs review", desc, app_id)
    elif new == workflow.REVIEW_REQUIRED:
        ctx.notify_role("reviewer", "review", f"{row['reference']} needs review", desc, app_id)
