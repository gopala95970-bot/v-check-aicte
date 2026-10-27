"""Pipeline view, dashboard, analytics, audit trail, rules, settings, notifications, demo helpers."""
from __future__ import annotations

import json
import platform
import re
from collections import Counter
from datetime import timedelta
from typing import Optional

from vcheck import workflow
from vcheck.models import utcnow_iso
from vcheck.rules import RuleSetError

from . import demo, processing, repo, services_core as core
from .context import Context, ruleset_to_dict
from .errors import ApiError, bad_request, conflict, forbidden, not_found, unprocessable
from .permissions import has, require

CATEGORY = {"REQ": "Required documents", "APP": "Application data", "FLD": "Field extraction", "DATE": "Dates & validity",
            "NUM": "Numeric values", "XD": "Cross-document consistency", "DUP": "Duplicates & reuse", "META": "File metadata",
            "VER": "Source verification", "SYS": "Processing & file quality"}
SEV_ORDER = {"failed": 4, "review": 3, "running": 2, "pending": 1, "passed": 0, "skipped": -1}


def category_of(rule_id: str) -> str:
    return CATEGORY.get(rule_id.split("-")[0], "Other")


# ============================================================ meta
def meta(ctx: Context) -> dict:
    rs = ctx.active_ruleset()
    return {
        "product": "V-Check AICTE", "version": "0.2.0", "problem_statement": "SIH26261",
        "disclaimer": "V-Check AICTE is an independent demonstration prototype developed for Smart India Hackathon. It is not an official AICTE portal and does not issue government approvals or official verification.",
        "demo_mode": ctx.get_setting("demo_mode") == "true",
        "application_types": [{"id": k, "label": v["label"]} for k, v in rs.application_types.items()],
        "document_types": [{"id": k, "label": v["label"]} for k, v in rs.document_types.items()],
        "statuses": [{"id": s, "label": workflow.STATUS_LABELS[s]} for s in workflow.STATUSES],
        "finding_statuses": list(repo.FINDING_STATUSES),
        "pipeline_stages": processing.ALL_STAGES,
        "ruleset": {"id": rs.ruleset_id, "version": rs.version, "effective_date": rs.effective_date, "notice": rs.notice},
        "limits": {"max_upload_mb": ctx.max_upload_bytes // (1024 * 1024), "accepted_types": ["PDF", "PNG", "JPEG"]},
        "verification_mode": ctx.get_setting("verification_mode"),
    }


# ============================================================ pipeline (Verification Center)
def _worst(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: SEV_ORDER.get(s, 0)) if statuses else "pending"


def pipeline(ctx: Context, user: dict, app_id: str) -> dict:
    row = core.app_for(ctx, user, app_id)
    docs = ctx.db.all("SELECT id, original_filename, declared_type, status FROM documents WHERE application_id=? AND active=1 ORDER BY created_at, id", (app_id,))
    run = ctx.db.one("SELECT * FROM validation_runs WHERE application_id=? AND status='complete' ORDER BY id DESC LIMIT 1", (app_id,))
    busy = ctx.is_pending(f"app:{app_id}") or row["status"] == workflow.PROCESSING
    per_doc = []
    doc_events: dict[str, dict[str, dict]] = {}
    for d in docs:
        evs = {e["stage"]: e for e in ctx.db.all("SELECT * FROM stage_events WHERE document_id=? ORDER BY id", (d["id"],))}
        doc_events[d["id"]] = evs
        live = d["status"] in ("queued", "processing")
        stages = []
        for st in processing.DOC_STAGES:
            e = evs.get(st)
            if e:
                stages.append({"stage": st, "status": e["status"], "duration_ms": e["duration_ms"], "result": e["result"], "errors": repo.j(e["errors_json"], [])})
            else:
                stages.append({"stage": st, "status": "running" if live and st != "Document Received" else ("passed" if st == "Document Received" else "pending"),
                               "duration_ms": None, "result": "In progress…" if live else "Waiting.", "errors": []})
        per_doc.append({"id": d["id"], "filename": d["original_filename"], "declared_type": d["declared_type"],
                        "type_label": repo.doc_label(ctx, d["declared_type"]), "status": d["status"], "stages": stages})
    stages_out = []
    for st in processing.ALL_STAGES:
        if st in processing.DOC_STAGES:
            items = [(d, next(s for s in d["stages"] if s["stage"] == st)) for d in per_doc]
            if not items:
                stages_out.append({"stage": st, "status": "pending", "duration_ms": None, "result": "No documents uploaded yet.", "evidence": [], "errors": [], "scope": "document"})
                continue
            status = _worst([s["status"] for _, s in items])
            ms = sum(s["duration_ms"] or 0 for _, s in items)
            ok = sum(1 for _, s in items if s["status"] == "passed")
            stages_out.append({"stage": st, "status": status, "duration_ms": ms,
                               "result": f"{ok} of {len(items)} document(s) passed this stage.",
                               "evidence": [f"{d['filename']}: {s['result']}" for d, s in items if s["status"] not in ("passed", "pending")][:8],
                               "errors": sorted({e for _, s in items for e in s["errors"]}), "scope": "document"})
        elif st in processing.APP_STAGES:
            e = ctx.db.one("SELECT * FROM stage_events WHERE application_id=? AND scope='application' AND stage=? AND run_id=?", (app_id, st, run["id"])) if run else None
            if e:
                stages_out.append({"stage": st, "status": e["status"], "duration_ms": e["duration_ms"], "result": e["result"],
                                   "evidence": repo.j(e["evidence_json"], []), "errors": repo.j(e["errors_json"], []), "scope": "application"})
            else:
                stages_out.append({"stage": st, "status": "running" if busy else "pending", "duration_ms": None,
                                   "result": "Running…" if busy else "Runs after the application is submitted.", "evidence": [], "errors": [], "scope": "application"})
        else:  # Human Review
            s = row["status"]
            if s in workflow.TERMINAL:
                status, result = "passed", f"Demonstration decision recorded: {workflow.STATUS_LABELS[s]}."
            elif s == workflow.CORRECTIONS_REQUESTED:
                status, result = "review", "Corrections requested from the applicant."
            elif s in (workflow.REVIEW_REQUIRED, workflow.VALIDATION_COMPLETE, workflow.RESUBMITTED):
                status, result = "pending", "Waiting for a reviewer decision."
            else:
                status, result = "pending", "Starts after automated validation."
            stages_out.append({"stage": st, "status": status, "duration_ms": None, "result": result, "evidence": [], "errors": [], "scope": "human"})
    ver = [dict(r) for r in ctx.db.all("SELECT document_id,provider,simulated,status,display_status,detail,checked_at FROM verification_results WHERE run_id=?", (run["id"],))] if run else []
    names = {d["id"]: d["original_filename"] for d in docs}
    for v in ver:
        v["filename"], v["simulated"] = names.get(v["document_id"]), bool(v["simulated"])
    return {
        "application_id": app_id, "application_status": row["status"], "processing": busy, "stages": stages_out, "documents": per_doc,
        "latest_run": ({"id": run["id"], "started_at": run["started_at"], "finished_at": run["finished_at"], "duration_ms": run["duration_ms"],
                        "ruleset_id": run["ruleset_id"], "ruleset_version": run["ruleset_version"], "trigger": run["trigger"],
                        "counts": repo.j(run["counts_json"], {}), "rules_run": len(repo.j(run["rules_run_json"], [])),
                        "rules_skipped": len(repo.j(run["rules_skipped_json"], []))} if run else None),
        "verification": ver,
        "verification_mode": row["verification_mode"] or ctx.get_setting("verification_mode"),
    }


def verification_overview(ctx: Context, user: dict) -> dict:
    require(user["role"], "application.view_all")
    rows = ctx.db.all("SELECT id FROM applications WHERE status<>'draft' ORDER BY seq DESC LIMIT 50")
    apps = []
    for r in rows:
        a = repo.app_dict(ctx, repo.get_app_row(ctx, r["id"]), role=user["role"])
        a["run"] = None
        run = ctx.db.one("SELECT id, duration_ms, ruleset_version, finished_at FROM validation_runs WHERE application_id=? AND status='complete' ORDER BY id DESC LIMIT 1", (r["id"],))
        if run:
            a["run"] = dict(run)
        apps.append(a)
    ver = ctx.db.all("SELECT status, display_status, simulated, COUNT(*) n FROM verification_results WHERE run_id IN (SELECT MAX(id) FROM validation_runs WHERE status='complete' GROUP BY application_id) GROUP BY status, display_status, simulated")
    return {"applications": apps, "verification_summary": [dict(v) | {"simulated": bool(v["simulated"])} for v in ver],
            "verification_mode": ctx.get_setting("verification_mode")}


# ============================================================ dashboard + analytics
def _scope(ctx: Context, user: dict) -> tuple[str, tuple]:
    if user["role"] == "applicant":
        return "a.owner_id=?", (user["id"],)
    return "a.status<>'draft'", ()


def dashboard(ctx: Context, user: dict) -> dict:
    sc, sa = _scope(ctx, user)
    fscope = sc + (" AND f.reviewer_only=0" if user["role"] == "applicant" else "")
    one = lambda sql, a=(): ctx.db.scalar(sql, a)  # noqa: E731
    total = one(f"SELECT COUNT(*) FROM applications a WHERE {sc}", sa)
    metrics = {
        "total_applications": total,
        "pending_review": one(f"SELECT COUNT(*) FROM applications a WHERE {sc} AND a.status IN ('review_required','validation_complete','resubmitted')", sa),
        "verification_required": one(f"SELECT COUNT(DISTINCT f.application_id) FROM findings f JOIN applications a ON a.id=f.application_id WHERE {fscope} AND f.is_current=1 AND f.outcome='review_required' AND f.status IN ('open','under_review') AND a.status NOT IN ('approved_demo','rejected_demo')", sa),
        "corrections_requested": one(f"SELECT COUNT(*) FROM applications a WHERE {sc} AND a.status='corrections_requested'", sa),
        "validated_documents": one(f"SELECT COUNT(*) FROM documents d JOIN applications a ON a.id=d.application_id WHERE {sc} AND d.active=1 AND d.status='processed'", sa),
        "critical_findings": one(f"SELECT COUNT(*) FROM findings f JOIN applications a ON a.id=f.application_id WHERE {fscope} AND f.is_current=1 AND f.severity='high' AND f.outcome='failed' AND f.status IN ('open','under_review')", sa),
    }
    over_time = [{"date": r["d"], "count": r["n"]} for r in ctx.db.all(
        f"SELECT substr(COALESCE(a.submitted_at,a.created_at),1,10) d, COUNT(*) n FROM applications a WHERE {sc} AND substr(COALESCE(a.submitted_at,a.created_at),1,10) >= ? GROUP BY d ORDER BY d",
        sa + ((ctx.today() - timedelta(days=60)).isoformat(),))]
    states = Counter()
    for r in ctx.db.all(f"SELECT a.id FROM applications a WHERE {sc} AND a.status<>'draft'", sa):
        c = repo.finding_counts(ctx, r["id"])
        states[repo.validation_state(ctx, r["id"], c)] += 1
    cats = Counter()
    for r in ctx.db.all(f"SELECT f.rule_id, COUNT(*) n FROM findings f JOIN applications a ON a.id=f.application_id WHERE {fscope} AND f.is_current=1 GROUP BY f.rule_id", sa):
        cats[category_of(r["rule_id"])] += r["n"]
    app_status = {r["status"]: r["n"] for r in ctx.db.all(f"SELECT a.status, COUNT(*) n FROM applications a WHERE {sc} GROUP BY a.status", sa)}
    doc_status = {r["status"]: r["n"] for r in ctx.db.all(f"SELECT d.status, COUNT(*) n FROM documents d JOIN applications a ON a.id=d.application_id WHERE {sc} AND d.active=1 GROUP BY d.status", sa)}
    out = {
        "metrics": metrics,
        "charts": {
            "applications_over_time": over_time,
            "validation_distribution": [{"key": k, "count": states.get(k, 0)} for k in ("passed", "review_required", "failed", "not_run")],
            "finding_categories": [{"category": k, "count": v} for k, v in cats.most_common()],
            "processing_status": {"applications": [{"status": k, "label": workflow.STATUS_LABELS[k], "count": v} for k, v in app_status.items()],
                                  "documents": [{"status": k, "count": v} for k, v in doc_status.items()]},
        },
        "recent_applications": [repo.app_dict(ctx, repo.get_app_row(ctx, r["id"]), role=user["role"]) for r in
                                ctx.db.all(f"SELECT a.id FROM applications a WHERE {sc} ORDER BY a.updated_at DESC LIMIT 8", sa)],
    }
    if user["role"] != "applicant":
        out["charts"]["review_workload"] = review_workload(ctx)
    return out


def review_workload(ctx: Context) -> list[dict]:
    rows = ctx.db.all("""SELECT COALESCE(u.name,'Unassigned') AS reviewer, COUNT(*) n FROM applications a LEFT JOIN users u ON u.id=a.reviewer_id
                         WHERE a.status IN ('review_required','validation_complete','resubmitted','corrections_requested') GROUP BY reviewer ORDER BY n DESC""")
    return [{"reviewer": r["reviewer"], "open": r["n"]} for r in rows]


def analytics(ctx: Context, user: dict) -> dict:
    require(user["role"], "stats.view")
    d = dashboard(ctx, user)["charts"]
    top = [{"rule_id": r["rule_id"], "title": r["title"], "count": r["n"], "category": category_of(r["rule_id"])} for r in ctx.db.all(
        "SELECT f.rule_id, MIN(f.title) title, COUNT(*) n FROM findings f JOIN applications a ON a.id=f.application_id WHERE a.status<>'draft' AND f.is_current=1 GROUP BY f.rule_id ORDER BY n DESC LIMIT 10")]
    runs = ctx.db.all("SELECT substr(finished_at,1,10) d, AVG(duration_ms) avg_ms, COUNT(*) n FROM validation_runs WHERE status='complete' GROUP BY d ORDER BY d")
    doc_ms = ctx.db.scalar("SELECT AVG(duration_ms) FROM stage_events WHERE scope='document' AND stage='OCR' AND duration_ms IS NOT NULL")
    cycles = Counter(r["correction_cycles"] for r in ctx.db.all("SELECT correction_cycles FROM applications WHERE status<>'draft'"))
    doc_by_status = d["processing_status"]["documents"]
    total_apps = sum(x["count"] for x in d["processing_status"]["applications"])
    return {
        "applications_processed": {"total": ctx.db.scalar("SELECT COUNT(*) FROM validation_runs WHERE status='complete'"),
                                   "applications": total_apps, "by_day": d["applications_over_time"]},
        "validation_findings": {"distribution": d["validation_distribution"], "by_category": d["finding_categories"]},
        "issue_types": top,
        "documents_by_status": doc_by_status,
        "review_workload": d["review_workload"],
        "processing_time": {"validation_by_day": [{"date": r["d"], "avg_ms": round(r["avg_ms"] or 0), "runs": r["n"]} for r in runs],
                            "avg_document_read_ms": round(doc_ms) if doc_ms is not None else None},
        "correction_cycles": [{"cycles": k, "applications": v} for k, v in sorted(cycles.items())],
        "sufficient_data": total_apps >= 1,
        "note": "All figures are computed from the application database. Demonstration data is synthetic.",
    }


# ============================================================ audit
def audit_list(ctx: Context, user: dict, q: dict) -> dict:
    require(user["role"], "audit.view")
    where, args = [], []
    for key, col in (("role", "a.actor_role"), ("action", "a.action"), ("object_type", "a.object_type"),
                     ("application_id", "a.application_id"), ("result", "a.result")):
        if q.get(key):
            where.append(f"{col}=?"); args.append(q[key])
    if q.get("user"):
        where.append("a.actor_email LIKE ?"); args.append(f"%{q['user'][:80]}%")
    if q.get("q"):
        where.append("(a.description LIKE ? OR a.object_id LIKE ? OR a.action LIKE ?)"); args += [f"%{q['q'][:80]}%"] * 3
    if q.get("date_from"):
        where.append("substr(a.ts,1,10) >= ?"); args.append(q["date_from"][:10])
    if q.get("date_to"):
        where.append("substr(a.ts,1,10) <= ?"); args.append(q["date_to"][:10])
    w = (" WHERE " + " AND ".join(where)) if where else ""
    page, size = max(1, int(q.get("page") or 1)), min(200, max(1, int(q.get("page_size") or 25)))
    total = ctx.db.scalar("SELECT COUNT(*) FROM audit_logs a" + w, tuple(args))
    rows = ctx.db.all("SELECT a.*, u.name AS actor_name FROM audit_logs a LEFT JOIN users u ON u.email=a.actor_email" + w +
                      " ORDER BY a.id DESC LIMIT ? OFFSET ?", tuple(args) + (size, (page - 1) * size))
    items = [{"id": r["event_id"], "timestamp": r["ts"], "user": r["actor_email"], "user_name": r["actor_name"] or r["actor_email"],
              "role": r["actor_role"], "action": r["action"], "object_type": r["object_type"], "object_id": r["object_id"],
              "application_id": r["application_id"], "description": r["description"], "from_status": r["from_status"],
              "to_status": r["to_status"], "result": r["result"], "details": repo.j(r["details_json"], {})} for r in rows]
    return {"items": items, "page": page, "page_size": size, "total": total}


def audit_facets(ctx: Context, user: dict) -> dict:
    require(user["role"], "audit.view")
    return {"actions": [r[0] for r in ctx.db.all("SELECT DISTINCT action FROM audit_logs ORDER BY action")],
            "roles": [r[0] for r in ctx.db.all("SELECT DISTINCT actor_role FROM audit_logs ORDER BY actor_role")]}


# ============================================================ rules
def _rule_row(ctx: Context, r, history: dict) -> dict:
    h = history.get(r.rule_id, [])
    return {"rule_id": r.rule_id, "name": r.name, "description": r.description, "category": category_of(r.rule_id), "check": r.check,
            "version": r.version, "enabled": r.enabled, "severity": r.severity, "effective_date": r.effective_date,
            "source_ref": r.source_ref, "source_status": r.source_status, "kind": repo.rule_kind(r.source_status),
            "applies_to": list(r.applies_to), "last_updated": h[0]["created_at"] if h else None}


def _rule_history(ctx: Context) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in ctx.db.all("SELECT version, created_at, created_by, change_note, changed_rules_json FROM rule_sets ORDER BY id DESC"):
        for rid in repo.j(row["changed_rules_json"], []):
            out.setdefault(rid, []).append({"version": row["version"], "created_at": row["created_at"], "created_by": row["created_by"], "change_note": row["change_note"]})
    return out


def list_rules(ctx: Context, user: dict) -> dict:
    require(user["role"], "rules.view")
    rs, hist = ctx.active_ruleset(), _rule_history(ctx)
    return {"ruleset": {"id": rs.ruleset_id, "version": rs.version, "effective_date": rs.effective_date, "notice": rs.notice},
            "rules": [_rule_row(ctx, r, hist) for r in rs.rules],
            "legend": {"official": "Officially sourced: cites an AICTE/government source URL that the team has confirmed.",
                       "demonstration": "Demonstration rule: illustrative or derived from a state circular; NOT an official AICTE checklist."}}


def get_rule(ctx: Context, user: dict, rule_id: str) -> dict:
    require(user["role"], "rules.view")
    r = ctx.active_ruleset().rule(rule_id)
    if r is None:
        raise not_found("Rule not found.")
    d = _rule_row(ctx, r, _rule_history(ctx))
    d.update({"params": r.params, "remediation": r.remediation, "history": _rule_history(ctx).get(rule_id, []),
              "open_findings": ctx.db.scalar("SELECT COUNT(*) FROM findings WHERE rule_id=? AND is_current=1 AND status IN ('open','under_review')", (rule_id,))})
    return d


def rule_versions(ctx: Context, user: dict) -> list[dict]:
    require(user["role"], "rules.view")
    return [{"ruleset_id": r["ruleset_id"], "version": r["version"], "effective_date": r["effective_date"], "active": bool(r["is_active"]),
             "created_by": r["created_by"], "created_at": r["created_at"], "change_note": r["change_note"],
             "changed_rules": repo.j(r["changed_rules_json"], [])} for r in ctx.db.all("SELECT * FROM rule_sets ORDER BY id DESC")]


def _ver_tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def create_rule_version(ctx: Context, user: dict, changes: dict, new_version: Optional[str], note: str) -> dict:
    """Deterministic, version-controlled rule change. Only whitelisted fields can change; never done by an LLM."""
    require(user["role"], "rules.manage")
    if not isinstance(changes, dict) or not changes:
        raise unprocessable("Specify at least one rule change.", fields={"changes": "required"})
    note = core._clean(note, "note", 500, True)
    rs = ctx.active_ruleset()
    if not new_version:
        a, b, c = _ver_tuple(rs.version)
        new_version = f"{a}.{b}.{c + 1}"
    if not re.fullmatch(r"\d+\.\d+\.\d+", new_version) or _ver_tuple(new_version) <= _ver_tuple(rs.version):
        raise unprocessable(f"The new version must look like x.y.z and be greater than {rs.version}.", fields={"new_version": "invalid"})
    for rid, ch in changes.items():
        if not isinstance(ch, dict):
            raise unprocessable("Each change must be an object of fields.", fields={"changes": "invalid"})
        if "params" in ch and not isinstance(ch["params"], dict):
            raise unprocessable("params must be an object.", fields={"params": "invalid"})
    try:
        new = rs.derive(changes, new_version)
    except RuleSetError as exc:
        raise unprocessable(str(exc), code="invalid_rule_change")
    body = ruleset_to_dict(new)
    with ctx.db.tx() as c:
        c.execute("UPDATE rule_sets SET is_active=0 WHERE is_active=1")
        c.execute("""INSERT INTO rule_sets(ruleset_id,version,effective_date,body_json,is_active,created_by,change_note,changed_rules_json,created_at)
                     VALUES(?,?,?,?,1,?,?,?,?)""", (new.ruleset_id, new.version, new.effective_date, json.dumps(body), user["email"], note, json.dumps(sorted(changes)), utcnow_iso()))
        ctx.audit(user, "rule.version", "ruleset", f"{new.ruleset_id}@{new.version}", f"Ruleset {rs.version} -> {new.version}: {', '.join(sorted(changes))}.",
                  details={"changes": sorted(changes), "note": note}, conn=c)
    return list_rules(ctx, user) | {"new_version": new.version}


def set_rule_enabled(ctx: Context, user: dict, rule_id: str, enabled: bool, note: str) -> dict:
    require(user["role"], "rules.manage")
    if ctx.active_ruleset().rule(rule_id) is None:
        raise not_found("Rule not found.")
    return create_rule_version(ctx, user, {rule_id: {"enabled": bool(enabled)}}, None, note or f"{'Enabled' if enabled else 'Disabled'} {rule_id}.")


# ============================================================ settings
def get_profile(ctx: Context, user: dict) -> dict:
    u = ctx.db.one("SELECT * FROM users WHERE id=?", (user["id"],))
    return {**core.public_user(u), "notifications": {"processing": True, "review": True, **repo.j(u["notify_prefs"], {})}, "last_login_at": u["last_login_at"]}


def update_profile(ctx: Context, user: dict, body: dict) -> dict:
    name = core._clean(body.get("name", user["name"]), "name", 100, True)
    org = core._clean(body.get("organization", user["organization"]), "organization", 150)
    with ctx.db.tx() as c:
        c.execute("UPDATE users SET name=?, organization=? WHERE id=?", (name, org, user["id"]))
    ctx.audit(user, "settings.profile", "user", user["email"], "Profile updated.")
    return get_profile(ctx, user)


def update_notifications(ctx: Context, user: dict, body: dict) -> dict:
    prefs = {k: bool(body[k]) for k in ("processing", "review") if k in body}
    u = ctx.db.one("SELECT notify_prefs FROM users WHERE id=?", (user["id"],))
    merged = {**repo.j(u["notify_prefs"], {}), **prefs}
    with ctx.db.tx() as c:
        c.execute("UPDATE users SET notify_prefs=? WHERE id=?", (json.dumps(merged), user["id"]))
    ctx.audit(user, "settings.notifications", "user", user["email"], "Notification preferences updated.")
    return get_profile(ctx, user)


def system_info(ctx: Context, user: dict) -> dict:
    from vcheck import ocr
    try:
        ocr._tesseract()
        tess = True
    except Exception:
        tess = False
    rs = ctx.active_ruleset()
    return {"product": "V-Check AICTE", "version": "0.2.0", "python": platform.python_version(), "database": "SQLite (local file)",
            "ocr_engine": "Tesseract" if tess else "Unavailable", "ocr_available": tess, "ruleset_version": rs.version,
            "demo_mode": ctx.get_setting("demo_mode") == "true", "verification_mode": ctx.get_setting("verification_mode"),
            "max_upload_mb": ctx.max_upload_bytes // (1024 * 1024), "token_ttl_minutes": ctx.settings.token_ttl_minutes,
            "problem_statement": "SIH26261", "affiliation": "Independent demonstration prototype. Not an official AICTE portal."}


def get_admin_settings(ctx: Context, user: dict) -> dict:
    require(user["role"], "settings.admin")
    return {
        "verification_mode": ctx.get_setting("verification_mode"), "demo_mode": ctx.get_setting("demo_mode") == "true",
        "max_upload_mb": ctx.max_upload_bytes // (1024 * 1024), "max_pdf_pages": ctx.max_pdf_pages,
        "providers": [
            {"id": "off", "name": "No verification source", "simulated": False, "available": True, "description": "Source verification is skipped; nothing is claimed as verified."},
            {"id": "simulation", "name": "Simulation (synthetic registry)", "simulated": True, "available": True, "description": "Looks certificate numbers up in a local synthetic registry. NOT a government verification."},
            {"id": "unavailable", "name": "Simulated outage", "simulated": True, "available": True, "description": "Models an unreachable verification source to demonstrate the review path."},
            {"id": "digilocker", "name": "DigiLocker (not configured)", "simulated": False, "available": False, "description": "Requires authorised requester credentials that this prototype does not have."},
        ],
    }


def update_admin_settings(ctx: Context, user: dict, body: dict) -> dict:
    require(user["role"], "settings.admin")
    changed = {}
    if "verification_mode" in body:
        if body["verification_mode"] not in processing.VERIFICATION_MODES:
            raise unprocessable("Choose a supported verification provider.", fields={"verification_mode": "invalid"})
        ctx.set_setting("verification_mode", body["verification_mode"]); changed["verification_mode"] = body["verification_mode"]
    if "max_upload_mb" in body:
        v = body["max_upload_mb"]
        if not isinstance(v, int) or not 1 <= v <= 25:
            raise unprocessable("Upload limit must be between 1 and 25 MB.", fields={"max_upload_mb": "invalid"})
        ctx.set_setting("max_upload_mb", str(v)); changed["max_upload_mb"] = v
    if "max_pdf_pages" in body:
        v = body["max_pdf_pages"]
        if not isinstance(v, int) or not 1 <= v <= 100:
            raise unprocessable("Page limit must be between 1 and 100.", fields={"max_pdf_pages": "invalid"})
        ctx.set_setting("max_pdf_pages", str(v)); changed["max_pdf_pages"] = v
    if "demo_mode" in body:
        ctx.set_setting("demo_mode", "true" if body["demo_mode"] else "false"); changed["demo_mode"] = bool(body["demo_mode"])
    ctx.audit(user, "settings.admin", "settings", "system", "Administrator settings updated: " + ", ".join(changed) + ".", details=changed)
    return get_admin_settings(ctx, user)


# ============================================================ notifications
def list_notifications(ctx: Context, user: dict) -> dict:
    rows = ctx.db.all("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 30", (user["id"],))
    return {"items": [{"id": r["id"], "kind": r["kind"], "title": r["title"], "body": r["body"], "application_id": r["application_id"],
                       "read": bool(r["read"]), "created_at": r["created_at"]} for r in rows],
            "unread": ctx.db.scalar("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (user["id"],))}


def mark_notifications(ctx: Context, user: dict, nid: Optional[int]) -> dict:
    with ctx.db.tx() as c:
        if nid is None:
            c.execute("UPDATE notifications SET read=1 WHERE user_id=?", (user["id"],))
        else:
            c.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (nid, user["id"]))
    return list_notifications(ctx, user)


# ============================================================ demo helpers
def demo_scenarios(ctx: Context, user: dict) -> dict:
    return {"demo_mode": ctx.get_setting("demo_mode") == "true", "synthetic": True,
            "scenarios": [{"id": k, "description": v} for k, v in demo.SCENARIOS.items()],
            "notice": "Sample documents are synthetic and fictional. They exist only to demonstrate the pipeline."}


def generate_demo_documents(ctx: Context, user: dict, app_id: str, scenario: str) -> list[dict]:
    """Create synthetic documents for an editable application and push them through the REAL upload pipeline."""
    require(user["role"], "document.upload")
    if ctx.get_setting("demo_mode") != "true":
        raise forbidden("Demo mode is switched off by the administrator.")
    row = core._own_editable(ctx, user, app_id)
    if scenario not in demo.SCENARIOS:
        raise unprocessable("Unknown demo scenario.", fields={"scenario": "invalid"})
    reuse = None
    if scenario == "duplicate_reuse":
        other = ctx.db.one("""SELECT d.storage_name FROM documents d JOIN applications a ON a.id=d.application_id
                              WHERE d.declared_type='occupancy_certificate' AND d.active=1 AND d.storage_name IS NOT NULL AND a.id<>? ORDER BY d.created_at LIMIT 1""", (app_id,))
        if other is None:
            raise conflict("No other application has an occupancy certificate to reuse in this scenario.", code="no_source")
        reuse = repo.doc_path(ctx, other["storage_name"]).read_bytes()
    courses = [(c["name"], c["intake"]) for c in repo.app_courses(ctx, app_id)]
    built = demo.build_documents(name=row["inst_name"], inst_id=row["inst_code"] or "1-9000000000", reference=row["reference"], seq=row["seq"],
                                 courses=courses, today=ctx.today(), scenario=scenario, reuse_bytes=reuse)
    existing = {r["declared_type"]: r["id"] for r in ctx.db.all("SELECT id, declared_type FROM documents WHERE application_id=? AND active=1", (app_id,))}
    out = []
    for fname, raw, dtype in built:
        out.append(core.upload_document(ctx, user, app_id, raw, fname, dtype, replaces=existing.get(dtype)))
    ctx.audit(user, "demo.documents", "application", app_id, f"Synthetic demo documents loaded (scenario: {scenario}).", application_id=app_id, details={"scenario": scenario})
    return out
