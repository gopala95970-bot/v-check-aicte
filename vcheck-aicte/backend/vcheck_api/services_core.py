"""Business operations: auth, applications, documents, findings, review workflow.

Every function takes the authenticated `user` dict ({id,email,role,name}) and enforces permissions itself;
the HTTP layer never decides who may do what.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from vcheck import workflow
from vcheck.models import utcnow_iso

from . import processing, repo, security
from .context import Context
from .errors import (ApiError, bad_request, conflict, forbidden, not_found, too_many, unauthorized, unprocessable)
from .permissions import has, require

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$|^[^@\s]+@demo\.vcheck$")
EDITABLE = (workflow.DRAFT, workflow.CORRECTIONS_REQUESTED)
TRIAGE_STATUSES = repo.FINDING_STATUSES


def public_user(u) -> dict:
    return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"], "organization": u["organization"],
            "permissions": sorted(__import__("vcheck_api.permissions", fromlist=["perms"]).perms(u["role"]))}


def _clean(v: Any, name: str, max_len: int, required: bool = False) -> str:
    s = (v or "")
    if not isinstance(s, str):
        raise unprocessable(f"{name} must be text.", fields={name: "must be text"})
    s = " ".join(s.split()) if "\n" not in s else s.strip()
    if required and not s:
        raise unprocessable(f"{name} is required.", fields={name: "required"})
    if len(s) > max_len:
        raise unprocessable(f"{name} is too long (max {max_len} characters).", fields={name: "too long"})
    return s


# ============================================================ auth
def login(ctx: Context, email: str, password: str, ip: str) -> dict:
    email = (email or "").strip().lower()
    key = f"{email}|{ip}"
    wait = ctx.throttle.blocked_for(key)
    if wait:
        raise too_many(f"Too many failed attempts. Try again in {wait} seconds.", wait)
    u = ctx.db.one("SELECT * FROM users WHERE email=?", (email,))
    ok = False
    if u is not None and u["active"]:
        ok = security.verify_password(password or "", u["password_hash"])
    else:
        security.burn_time(password or "")
    if not ok:
        ctx.throttle.fail(key)
        ctx.audit({"email": email or "unknown", "role": "anonymous"}, "auth.login", "user", email or "unknown",
                  "Sign-in failed.", result="failure", details={"ip": ip})
        raise unauthorized("Incorrect email or password.", code="invalid_credentials")
    ctx.throttle.clear(key)
    tok, jti, exp = security.issue_token(ctx.settings.jwt_secret, u["id"], u["role"], ctx.settings.token_ttl_minutes)
    with ctx.db.tx() as c:
        c.execute("UPDATE users SET last_login_at=? WHERE id=?", (utcnow_iso(), u["id"]))
    ctx.audit({"email": u["email"], "role": u["role"]}, "auth.login", "user", u["email"], "Signed in.")
    return {"token": tok, "token_type": "Bearer", "expires_at": exp, "user": public_user(u)}


def authenticate(ctx: Context, token: str) -> dict:
    import jwt as pyjwt
    try:
        claims = security.decode_token(ctx.settings.jwt_secret, token)
    except pyjwt.ExpiredSignatureError:
        raise unauthorized("Your session has expired. Sign in again.", code="token_expired")
    except pyjwt.PyJWTError:
        raise unauthorized("Invalid session.", code="invalid_token")
    if ctx.db.one("SELECT 1 FROM revoked_tokens WHERE jti=?", (claims["jti"],)):
        raise unauthorized("This session was signed out.", code="token_revoked")
    u = ctx.db.one("SELECT * FROM users WHERE id=? AND active=1", (int(claims["sub"]),))
    if u is None:
        raise unauthorized("Account not available.", code="invalid_token")
    user = {k: u[k] for k in ("id", "email", "name", "role", "organization")}
    user["jti"], user["exp"] = claims["jti"], claims["exp"]
    return user


def logout(ctx: Context, user: dict) -> None:
    with ctx.db.tx() as c:
        c.execute("INSERT OR IGNORE INTO revoked_tokens(jti,expires_at) VALUES(?,?)", (user["jti"], user["exp"]))
        c.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (int(time.time()),))
    ctx.audit(user, "auth.logout", "user", user["email"], "Signed out.")


def change_password(ctx: Context, user: dict, current: str, new: str) -> None:
    u = ctx.db.one("SELECT * FROM users WHERE id=?", (user["id"],))
    if not security.verify_password(current or "", u["password_hash"]):
        ctx.audit(user, "auth.password_change", "user", user["email"], "Password change rejected.", result="failure")
        raise unprocessable("The current password is incorrect.", code="invalid_credentials", fields={"current_password": "incorrect"})
    probs = security.password_problems(new or "")
    if probs:
        raise unprocessable("The new password needs " + ", ".join(probs) + ".", fields={"new_password": "too weak"})
    with ctx.db.tx() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (security.hash_password(new), user["id"]))
    ctx.audit(user, "auth.password_change", "user", user["email"], "Password changed.")


# ============================================================ access helpers
def app_for(ctx: Context, user: dict, app_id: str):
    """Fetch an application row the user may see. Hidden apps look like 404s (no existence leak)."""
    row = repo.get_app_row(ctx, app_id)
    if user["role"] == "applicant":
        if row["owner_id"] != user["id"]:
            raise not_found("Application not found.")
    elif row["status"] == workflow.DRAFT:
        raise not_found("Application not found.")
    return row


def _own_editable(ctx: Context, user: dict, app_id: str):
    require(user["role"], "application.edit_own")
    row = app_for(ctx, user, app_id)
    if row["status"] not in EDITABLE:
        raise conflict(f"This application is '{workflow.STATUS_LABELS[row['status']]}' and can no longer be edited.", code="not_editable")
    return row


# ============================================================ applications
def _validate_institution(i: dict) -> dict:
    i = i or {}
    out = {
        "name": _clean(i.get("name"), "institution.name", 200, True),
        "institution_id": _clean(i.get("institution_id"), "institution.institution_id", 40),
        "state": _clean(i.get("state"), "institution.state", 80, True),
        "district": _clean(i.get("district"), "institution.district", 80),
        "address": _clean(i.get("address"), "institution.address", 400),
        "contact_name": _clean(i.get("contact_name"), "institution.contact_name", 120),
        "contact_email": _clean(i.get("contact_email"), "institution.contact_email", 200),
        "contact_phone": _clean(i.get("contact_phone"), "institution.contact_phone", 30),
    }
    if out["contact_email"] and not EMAIL_RE.match(out["contact_email"]):
        raise unprocessable("Contact email is not a valid address.", fields={"institution.contact_email": "invalid"})
    if out["contact_phone"] and not re.fullmatch(r"[0-9+()\-\s]{6,30}", out["contact_phone"]):
        raise unprocessable("Contact phone may contain only digits, spaces, + ( ) and -.", fields={"institution.contact_phone": "invalid"})
    return out


def _validate_courses(courses) -> list[dict]:
    if courses is None:
        return []
    if not isinstance(courses, list) or len(courses) > 20:
        raise unprocessable("Courses must be a list of at most 20 entries.", fields={"courses": "invalid"})
    out = []
    for n, c in enumerate(courses):
        name = _clean((c or {}).get("name"), f"courses[{n}].name", 200)
        if not name:
            continue
        out.append({"name": name, "intake": _clean(str((c or {}).get("intake", "")), f"courses[{n}].intake", 20)})
    return out


def create_application(ctx: Context, user: dict, body: dict, *, _seq: Optional[int] = None) -> dict:
    require(user["role"], "application.create")
    inst = _validate_institution(body.get("institution"))
    types = ctx.active_ruleset().application_types
    atype = body.get("application_type") or ""
    if atype not in types:
        raise unprocessable("Choose a valid application category.", fields={"application_type": "invalid"})
    year = _clean(body.get("academic_year"), "academic_year", 20)
    if year and not re.fullmatch(r"\d{4}(-\d{2,4})?", year):
        raise unprocessable("Academic year should look like 2026-27.", fields={"academic_year": "invalid"})
    notes = _clean(body.get("notes"), "notes", 1000)
    courses = _validate_courses(body.get("courses"))
    now = utcnow_iso()
    with ctx.db.tx() as c:
        ipk = c.execute("""INSERT INTO institutions(owner_id,name,institution_id,address,state,district,contact_name,contact_email,
                           contact_phone,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (user["id"], inst["name"], inst["institution_id"], inst["address"], inst["state"], inst["district"],
                         inst["contact_name"], inst["contact_email"], inst["contact_phone"], now)).lastrowid
        seq = _seq or (c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM applications").fetchone()[0])
        app_id, ref = f"APP-{seq:03d}", f"VC-DEMO-{seq:04d}"
        c.execute("""INSERT INTO applications(id,seq,reference,institution_pk,owner_id,application_type,academic_year,notes,status,
                     is_demo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
                  (app_id, seq, ref, ipk, user["id"], atype, year, notes, workflow.DRAFT, now, now))
        for n, cr in enumerate(courses):
            c.execute("INSERT INTO application_courses(application_id,position,name,intake) VALUES(?,?,?,?)", (app_id, n, cr["name"], cr["intake"]))
        ctx.audit(user, "application.create", "application", app_id, f"Application {ref} created as a draft.", application_id=app_id, to_status=workflow.DRAFT, conn=c)
    return repo.app_dict(ctx, repo.get_app_row(ctx, app_id), detail=True, role=user["role"])


def update_application(ctx: Context, user: dict, app_id: str, body: dict) -> dict:
    row = _own_editable(ctx, user, app_id)
    with ctx.db.tx() as c:
        if "institution" in body:
            inst = _validate_institution({**{"name": row["inst_name"], "state": row["inst_state"]}, **body["institution"]})
            c.execute("""UPDATE institutions SET name=?,institution_id=?,address=?,state=?,district=?,contact_name=?,contact_email=?,
                         contact_phone=? WHERE id=?""", (inst["name"], inst["institution_id"], inst["address"], inst["state"],
                                                          inst["district"], inst["contact_name"], inst["contact_email"], inst["contact_phone"], row["institution_pk"]))
        if "application_type" in body:
            if body["application_type"] not in ctx.active_ruleset().application_types:
                raise unprocessable("Choose a valid application category.", fields={"application_type": "invalid"})
            c.execute("UPDATE applications SET application_type=? WHERE id=?", (body["application_type"], app_id))
        if "academic_year" in body:
            y = _clean(body["academic_year"], "academic_year", 20)
            if y and not re.fullmatch(r"\d{4}(-\d{2,4})?", y):
                raise unprocessable("Academic year should look like 2026-27.", fields={"academic_year": "invalid"})
            c.execute("UPDATE applications SET academic_year=? WHERE id=?", (y, app_id))
        if "notes" in body:
            c.execute("UPDATE applications SET notes=? WHERE id=?", (_clean(body["notes"], "notes", 1000), app_id))
        if "courses" in body:
            c.execute("DELETE FROM application_courses WHERE application_id=?", (app_id,))
            for n, cr in enumerate(_validate_courses(body["courses"])):
                c.execute("INSERT INTO application_courses(application_id,position,name,intake) VALUES(?,?,?,?)", (app_id, n, cr["name"], cr["intake"]))
        c.execute("UPDATE applications SET updated_at=? WHERE id=?", (utcnow_iso(), app_id))
        ctx.audit(user, "application.update", "application", app_id, "Application details updated.", application_id=app_id, conn=c)
    return repo.app_dict(ctx, repo.get_app_row(ctx, app_id), detail=True, role=user["role"])


def get_application(ctx: Context, user: dict, app_id: str) -> dict:
    row = app_for(ctx, user, app_id)
    d = repo.app_dict(ctx, row, detail=True, role=user["role"])
    last = ctx.db.one("SELECT actor_email, created_at FROM review_actions WHERE application_id=? AND action='mark_reviewed' ORDER BY id DESC LIMIT 1", (app_id,))
    d["reviewed"] = {"by": last["actor_email"], "at": last["created_at"]} if last else None
    d["required_documents"] = required_documents(ctx, row)
    d["correction_request"] = None
    if row["status"] == workflow.CORRECTIONS_REQUESTED:      # the applicant must be able to see what to fix
        cr = ctx.db.one("SELECT remarks, actor_email, created_at FROM review_actions WHERE application_id=? AND action='request_correction' ORDER BY id DESC LIMIT 1", (app_id,))
        if cr:
            d["correction_request"] = {"remarks": cr["remarks"], "requested_at": cr["created_at"]}
    return d


def required_documents(ctx: Context, row) -> list[dict]:
    """Checklist derived from the active ruleset's REQ-DOC rules (never hard-coded in the UI)."""
    rs = ctx.active_ruleset()
    have = {r["declared_type"]: r["id"] for r in ctx.db.all(
        "SELECT id, declared_type FROM documents WHERE application_id=? AND active=1 AND status<>'rejected'", (row["id"],))}
    out = []
    for r in rs.enabled_rules(row["application_type"]):
        if r.check == "required_document":
            t = r.params["doc_type"]
            out.append({"doc_type": t, "label": rs.document_types.get(t, {}).get("label", t), "rule_id": r.rule_id,
                        "uploaded": t in have, "document_id": have.get(t)})
    return out


def list_applications(ctx: Context, user: dict, q: dict) -> dict:
    where, args = [], []
    if user["role"] == "applicant":
        where.append("a.owner_id=?"); args.append(user["id"])
    else:
        where.append("a.status<>'draft'")
    if q.get("status"):
        sts = [s for s in q["status"].split(",") if s in workflow.STATUSES]
        if sts:
            where.append("a.status IN (%s)" % ",".join("?" * len(sts))); args += sts
    if q.get("q"):
        like = f"%{q['q'].strip()[:80]}%"
        where.append("(a.id LIKE ? OR a.reference LIKE ? OR i.name LIKE ? OR i.institution_id LIKE ?)"); args += [like] * 4
    if q.get("institution"):
        where.append("i.name LIKE ?"); args.append(f"%{q['institution'].strip()[:80]}%")
    if q.get("application_type"):
        where.append("a.application_type=?"); args.append(q["application_type"])
    if q.get("date_from"):
        where.append("substr(COALESCE(a.submitted_at,a.created_at),1,10) >= ?"); args.append(q["date_from"][:10])
    if q.get("date_to"):
        where.append("substr(COALESCE(a.submitted_at,a.created_at),1,10) <= ?"); args.append(q["date_to"][:10])
    if q.get("severity") in repo.SEV_RANK:
        where.append("EXISTS (SELECT 1 FROM findings f WHERE f.application_id=a.id AND f.is_current=1 AND f.severity=?"
                     + (" AND f.reviewer_only=0" if user["role"] == "applicant" else "") + ")"); args.append(q["severity"])
    if str(q.get("reviewer_id") or "").isdigit():
        where.append("a.reviewer_id=?"); args.append(int(q["reviewer_id"]))
    page, size = max(1, int(q.get("page") or 1)), min(100, max(1, int(q.get("page_size") or 10)))
    sort = {"submitted": "COALESCE(a.submitted_at,a.created_at) DESC", "oldest": "COALESCE(a.submitted_at,a.created_at) ASC",
            "institution": "i.name COLLATE NOCASE ASC", "status": "a.status ASC"}.get(q.get("sort"), "a.seq DESC")
    base = " FROM applications a JOIN institutions i ON i.id=a.institution_pk WHERE " + " AND ".join(where)
    total = ctx.db.scalar("SELECT COUNT(*)" + base, tuple(args))
    ids = [r["id"] for r in ctx.db.all(f"SELECT a.id{base} ORDER BY {sort} LIMIT ? OFFSET ?", tuple(args) + (size, (page - 1) * size))]
    items = [repo.app_dict(ctx, repo.get_app_row(ctx, i), role=user["role"]) for i in ids]
    return {"items": items, "page": page, "page_size": size, "total": total}


def submit_application(ctx: Context, user: dict, app_id: str) -> dict:
    require(user["role"], "application.submit")
    row = app_for(ctx, user, app_id)
    resubmit = row["status"] == workflow.CORRECTIONS_REQUESTED
    target = workflow.RESUBMITTED if resubmit else workflow.SUBMITTED
    new = workflow.transition(row["status"], target, "applicant")
    n_docs = ctx.db.scalar("SELECT COUNT(*) FROM documents WHERE application_id=? AND active=1", (app_id,))
    if not n_docs:
        raise unprocessable("Upload at least one document before submitting.", code="no_documents")
    if not row["inst_name"].strip():
        raise unprocessable("Institution name is required.", code="incomplete")
    with ctx.db.tx() as c:
        c.execute("UPDATE applications SET status=?, submitted_at=COALESCE(submitted_at,?), updated_at=? WHERE id=?", (new, utcnow_iso(), utcnow_iso(), app_id))
        ctx.audit(user, "application.resubmit" if resubmit else "application.submit", "application", app_id,
                  f"Application {row['reference']} {'resubmitted' if resubmit else 'submitted'} with {n_docs} document(s).",
                  application_id=app_id, from_status=row["status"], to_status=new, conn=c)
    processing.start_pipeline(ctx, app_id, user, "resubmit" if resubmit else "submit")
    return repo.app_dict(ctx, repo.get_app_row(ctx, app_id), detail=True, role=user["role"])


def revalidate(ctx: Context, user: dict, app_id: str) -> dict:
    """Re-run the rules (e.g. after a field correction or a rule-version change). Status is not changed."""
    if user["role"] == "applicant":
        row = app_for(ctx, user, app_id)
        if row["status"] not in EDITABLE:
            raise forbidden("Applicants can run a pre-check only while the application is editable.")
    else:
        require(user["role"], "application.revalidate")
        row = app_for(ctx, user, app_id)
    if row["status"] == workflow.PROCESSING or ctx.is_pending(f"app:{app_id}"):
        raise conflict("Processing is already in progress.", code="busy")
    processing.wait_for_documents(ctx, app_id)
    run_id = processing.run_validation(ctx, app_id, user, "precheck" if row["status"] in EDITABLE else "revalidate",
                                       carry_status=row["status"] not in EDITABLE)
    ctx.audit(user, "validation.run", "application", app_id, "Validation re-run.", application_id=app_id, details={"run_id": run_id})
    return {"run_id": run_id, "application": repo.app_dict(ctx, repo.get_app_row(ctx, app_id), detail=True, role=user["role"])}


# ============================================================ documents
def _check_declared(ctx: Context, declared: Optional[str]) -> Optional[str]:
    if not declared:
        return None
    if declared not in ctx.active_ruleset().document_types:
        raise unprocessable("Unknown document type.", fields={"document_type": "invalid"})
    return declared


def upload_document(ctx: Context, user: dict, app_id: str, raw: bytes, filename: str, declared_type: Optional[str],
                    replaces: Optional[str] = None) -> dict:
    require(user["role"], "document.upload")
    row = _own_editable(ctx, user, app_id)
    declared = _check_declared(ctx, declared_type)
    if len(raw) > ctx.max_upload_bytes:
        raise ApiError(413, "payload_too_large", f"The file is larger than the {ctx.max_upload_bytes // (1024 * 1024)} MB limit.")
    if replaces:
        old = repo.get_doc_row(ctx, replaces)
        if old["application_id"] != app_id or not old["active"]:
            raise not_found("The document to replace was not found.")
        declared = declared or old["declared_type"]
    elif ctx.db.scalar("SELECT COUNT(*) FROM documents WHERE application_id=? AND active=1", (app_id,)) >= 20:
        raise conflict("An application can hold at most 20 documents.", code="too_many_documents")
    doc_id = processing.create_document(ctx, app_id, raw, filename, declared, user, replaces)
    if replaces:
        _drop_file(ctx, replaces)
    ctx.audit(user, "document.replace" if replaces else "document.upload", "document", doc_id,
              f"Document '{repo.get_doc_row(ctx, doc_id)['original_filename']}' {'replaced' if replaces else 'uploaded'}.",
              application_id=app_id, details={"declared_type": declared, "size": len(raw)})
    return repo.doc_dict(ctx, repo.get_doc_row(ctx, doc_id))


def _drop_file(ctx: Context, doc_id: str) -> None:
    row = ctx.db.one("SELECT storage_name FROM documents WHERE id=?", (doc_id,))
    if row and row["storage_name"]:
        try:
            repo.doc_path(ctx, row["storage_name"]).unlink(missing_ok=True)
        except OSError:
            pass
        with ctx.db.tx() as c:
            c.execute("UPDATE documents SET storage_name=NULL WHERE id=?", (doc_id,))


def remove_document(ctx: Context, user: dict, doc_id: str) -> None:
    d = repo.get_doc_row(ctx, doc_id)
    _own_editable(ctx, user, d["application_id"])
    with ctx.db.tx() as c:
        c.execute("UPDATE documents SET active=0 WHERE id=?", (doc_id,))
    _drop_file(ctx, doc_id)
    ctx.audit(user, "document.remove", "document", doc_id, f"Document '{d['original_filename']}' removed.", application_id=d["application_id"])


def doc_for(ctx: Context, user: dict, doc_id: str):
    d = repo.get_doc_row(ctx, doc_id)
    app_for(ctx, user, d["application_id"])       # same visibility as the parent application
    return d


def get_document(ctx: Context, user: dict, doc_id: str) -> dict:
    d = doc_for(ctx, user, doc_id)
    out = repo.doc_dict(ctx, d, fields=True)
    if user["role"] != "applicant":
        pj = ctx.db.scalar("SELECT processed_json FROM documents WHERE id=?", (doc_id,))
        if pj:
            data = json.loads(pj)
            out["pages"] = [{"page": p["page"], "source": p["source"], "mean_conf": p.get("mean_conf"),
                             "text": "\n".join(l["text"] for l in p["lines"])[:20000]} for p in data.get("pages", [])]
            out["courses"] = [{"course": r["course"]["value"], "intake": (r.get("intake") or {}).get("value")} for r in data.get("course_rows", [])]
            out["metadata_signals"] = data.get("metadata_signals", [])
    else:
        out["courses"] = []
    out["findings"] = [repo.finding_dict(ctx, r) for r in ctx.db.all(
        "SELECT * FROM findings WHERE application_id=? AND is_current=1 AND document_ids_json LIKE ?" +
        (" AND reviewer_only=0" if user["role"] == "applicant" else ""), (d["application_id"], f'%"{doc_id}"%'))]
    out["stages"] = [{"stage": s["stage"], "status": s["status"], "duration_ms": s["duration_ms"], "result": s["result"],
                      "errors": repo.j(s["errors_json"], []), "evidence": repo.j(s["evidence_json"], [])}
                     for s in ctx.db.all("SELECT * FROM stage_events WHERE document_id=? ORDER BY id", (doc_id,))]
    return out


def list_documents(ctx: Context, user: dict, app_id: Optional[str] = None, q: Optional[dict] = None) -> dict:
    q = q or {}
    where, args = ["d.active=1"], []
    if app_id:
        app_for(ctx, user, app_id)
        where.append("d.application_id=?"); args.append(app_id)
    if user["role"] == "applicant":
        where.append("a.owner_id=?"); args.append(user["id"])
    else:
        where.append("a.status<>'draft'")
    if q.get("status"):
        where.append("d.status=?"); args.append(q["status"])
    if q.get("type"):
        where.append("d.declared_type=?"); args.append(q["type"])
    if q.get("q"):
        where.append("(d.original_filename LIKE ? OR a.id LIKE ? OR i.name LIKE ?)"); args += [f"%{q['q'][:80]}%"] * 3
    page, size = max(1, int(q.get("page") or 1)), min(100, max(1, int(q.get("page_size") or 20)))
    base = " FROM documents d JOIN applications a ON a.id=d.application_id JOIN institutions i ON i.id=a.institution_pk WHERE " + " AND ".join(where)
    total = ctx.db.scalar("SELECT COUNT(*)" + base, tuple(args))
    rows = ctx.db.all("SELECT d.*, (SELECT COUNT(*) FROM extracted_fields f WHERE f.document_id=d.id) AS field_count, a.reference AS app_ref, i.name AS inst_name"
                      + base + " ORDER BY d.created_at DESC, d.id LIMIT ? OFFSET ?", tuple(args) + (size, (page - 1) * size))
    items = []
    for r in rows:
        d = repo.doc_dict(ctx, r)
        d["application_reference"], d["institution_name"] = r["app_ref"], r["inst_name"]
        d["finding_count"] = ctx.db.scalar("SELECT COUNT(*) FROM findings WHERE application_id=? AND is_current=1 AND document_ids_json LIKE ?" +
                                           (" AND reviewer_only=0" if user["role"] == "applicant" else ""), (r["application_id"], f'%"{r["id"]}"%'))
        items.append(d)
    return {"items": items, "page": page, "page_size": size, "total": total}


def document_file(ctx: Context, user: dict, doc_id: str) -> tuple[bytes, str, str]:
    d = doc_for(ctx, user, doc_id)
    path = repo.doc_path(ctx, d["storage_name"])
    if not path.is_file():
        raise not_found("The file is no longer available.")
    ctx.audit(user, "document.view", "document", doc_id, f"Document '{d['original_filename']}' opened.", application_id=d["application_id"])
    mime = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg"}[d["kind"]]
    return path.read_bytes(), mime, d["original_filename"]


def correct_field(ctx: Context, user: dict, doc_id: str, field_id: int, value: Optional[str], revalidate_after: bool = True) -> dict:
    require(user["role"], "document.correct_fields")
    d = doc_for(ctx, user, doc_id)
    app = repo.get_app_row(ctx, d["application_id"])
    if app["status"] in workflow.TERMINAL:
        raise conflict("This application has a final demonstration decision and cannot be changed.", code="final")
    f = ctx.db.one("SELECT * FROM extracted_fields WHERE id=? AND document_id=?", (field_id, doc_id))
    if f is None:
        raise not_found("Field not found.")
    new = None if value is None else _clean(value, "value", 300, True)
    with ctx.db.tx() as c:
        c.execute("UPDATE extracted_fields SET corrected_value=?, corrected_by=?, corrected_at=? WHERE id=?",
                  (new, user["email"] if new is not None else None, utcnow_iso() if new is not None else None, field_id))
        c.execute("INSERT INTO review_actions(application_id,actor_id,actor_email,actor_role,action,remarks,created_at) VALUES(?,?,?,?,?,?,?)",
                  (app["id"], user["id"], user["email"], user["role"], "field_correction",
                   f"{f['name']}: '{f['value']}' -> '{new}'" if new is not None else f"{f['name']}: correction cleared", utcnow_iso()))
        ctx.audit(user, "extraction.correct" if new is not None else "extraction.reset", "field", f"{doc_id}#{field_id}",
                  f"Extracted field '{f['name']}' {'corrected' if new is not None else 'reset to the extracted value'}; original value kept.",
                  application_id=app["id"], details={"original": f["value"], "corrected": new}, conn=c)
    result = {"field": next(x for x in repo.field_rows(ctx, doc_id) if x["id"] == field_id)}
    if revalidate_after and not ctx.is_pending(f"app:{app['id']}"):
        result["run_id"] = processing.run_validation(ctx, app["id"], user, "correction", carry_status=True)
        result["findings"] = repo.finding_counts(ctx, app["id"])
    return result


# ============================================================ findings
def list_findings(ctx: Context, user: dict, q: dict, app_id: Optional[str] = None) -> dict:
    where, args = ["f.is_current=1"], []
    if app_id:
        app_for(ctx, user, app_id)
        where.append("f.application_id=?"); args.append(app_id)
    if user["role"] == "applicant":
        where += ["a.owner_id=?", "f.reviewer_only=0"]; args.append(user["id"])
    else:
        where.append("a.status<>'draft'")
    for key, col in (("severity", "f.severity"), ("status", "f.status"), ("outcome", "f.outcome"), ("rule_id", "f.rule_id")):
        if q.get(key):
            where.append(f"{col}=?"); args.append(q[key])
    if q.get("q"):
        where.append("(f.title LIKE ? OR f.explanation LIKE ? OR f.rule_id LIKE ? OR f.public_id LIKE ?)"); args += [f"%{q['q'][:80]}%"] * 4
    page, size = max(1, int(q.get("page") or 1)), min(100, max(1, int(q.get("page_size") or 20)))
    base = " FROM findings f JOIN applications a ON a.id=f.application_id JOIN institutions i ON i.id=a.institution_pk WHERE " + " AND ".join(where)
    total = ctx.db.scalar("SELECT COUNT(*)" + base, tuple(args))
    rows = ctx.db.all("SELECT f.*, a.reference AS app_ref, i.name AS inst_name" + base +
                      " ORDER BY CASE f.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, f.id DESC LIMIT ? OFFSET ?",
                      tuple(args) + (size, (page - 1) * size))
    items = []
    for r in rows:
        d = repo.finding_dict(ctx, r)
        d["application_reference"], d["institution_name"] = r["app_ref"], r["inst_name"]
        items.append(d)
    return {"items": items, "page": page, "page_size": size, "total": total}


def get_finding(ctx: Context, user: dict, public_id: str) -> dict:
    r = ctx.db.one("SELECT * FROM findings WHERE public_id=?", (public_id,))
    if r is None:
        raise not_found("Finding not found.")
    app_for(ctx, user, r["application_id"])
    if user["role"] == "applicant" and r["reviewer_only"]:
        raise not_found("Finding not found.")
    return repo.finding_dict(ctx, r)


def update_finding(ctx: Context, user: dict, public_id: str, status: str, note: str) -> dict:
    require(user["role"], "finding.resolve")
    r = ctx.db.one("SELECT * FROM findings WHERE public_id=?", (public_id,))
    if r is None:
        raise not_found("Finding not found.")
    app = app_for(ctx, user, r["application_id"])
    if status not in TRIAGE_STATUSES:
        raise unprocessable("Unknown finding status.", fields={"status": "invalid"})
    if app["status"] in workflow.TERMINAL:
        raise conflict("This application has a final demonstration decision; findings are read-only.", code="final")
    if not r["is_current"]:
        raise conflict("This finding belongs to an earlier validation run and is read-only.", code="superseded")
    note = _clean(note, "note", 1000)
    if status in ("resolved", "accepted_with_explanation") and len(note) < 5:
        raise unprocessable("Add a short note (at least 5 characters) explaining the resolution.", fields={"note": "required"})
    closing = status in ("resolved", "accepted_with_explanation")
    with ctx.db.tx() as c:
        c.execute("UPDATE findings SET status=?, resolution_note=?, resolved_by=?, resolved_at=? WHERE id=?",
                  (status, note or None, user["email"] if closing else None, utcnow_iso() if closing else None, r["id"]))
        c.execute("INSERT INTO review_actions(application_id,finding_id,actor_id,actor_email,actor_role,action,remarks,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (r["application_id"], public_id, user["id"], user["email"], user["role"], f"finding.{status}", note, utcnow_iso()))
        if app["reviewer_id"] is None and user["role"] == "reviewer":
            c.execute("UPDATE applications SET reviewer_id=? WHERE id=?", (user["id"], app["id"]))
        ctx.audit(user, "finding.status", "finding", public_id, f"Finding {public_id} ({r['rule_id']}) set to '{status}'.",
                  application_id=r["application_id"], from_status=r["status"], to_status=status, conn=c)
    return repo.finding_dict(ctx, ctx.db.one("SELECT * FROM findings WHERE id=?", (r["id"],)))


# ============================================================ review workflow
def _map_workflow(exc: workflow.WorkflowError) -> ApiError:
    if isinstance(exc, workflow.PermissionDenied):
        return forbidden(str(exc))
    if isinstance(exc, workflow.InvalidTransition):
        return conflict(str(exc), code="invalid_transition")
    if isinstance(exc, workflow.ConfirmationRequired):
        return conflict(str(exc), code="confirmation_required")
    return unprocessable(str(exc), code="workflow_error")


def list_reviewers(ctx: Context, user: dict) -> list[dict]:
    require(user["role"], "review.assign")
    return [{"id": r["id"], "name": r["name"], "email": r["email"]} for r in
            ctx.db.all("SELECT id,name,email FROM users WHERE role='reviewer' AND active=1 ORDER BY name")]


def review_queue(ctx: Context, user: dict, q: dict) -> dict:
    require(user["role"], "application.view_all")
    where, args = ["a.status<>'draft'"], []
    scope = q.get("scope", "open")
    if scope == "open":
        where.append("a.status IN ('review_required','validation_complete','resubmitted','processing','submitted')")
    elif scope == "mine":
        where.append("a.reviewer_id=?"); args.append(user["id"])
    elif scope == "unassigned":
        where.append("a.reviewer_id IS NULL AND a.status NOT IN ('approved_demo','rejected_demo')")
    elif scope == "corrections":
        where.append("a.status='corrections_requested'")
    elif scope == "decided":
        where.append("a.status IN ('approved_demo','rejected_demo')")
    if q.get("q"):
        where.append("(a.id LIKE ? OR a.reference LIKE ? OR i.name LIKE ?)"); args += [f"%{q['q'][:80]}%"] * 3
    rows = ctx.db.all("""SELECT a.id FROM applications a JOIN institutions i ON i.id=a.institution_pk WHERE """ + " AND ".join(where) +
                      """ ORDER BY a.escalated DESC,
                          (SELECT COUNT(*) FROM findings f WHERE f.application_id=a.id AND f.is_current=1 AND f.severity='high' AND f.status IN ('open','under_review')) DESC,
                          COALESCE(a.submitted_at,a.created_at) ASC LIMIT 200""", tuple(args))
    items = []
    for r in rows:
        d = repo.app_dict(ctx, repo.get_app_row(ctx, r["id"]), role=user["role"])
        top = ctx.db.all("SELECT public_id,title,severity,status FROM findings WHERE application_id=? AND is_current=1 ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id LIMIT 3", (r["id"],))
        d["top_findings"] = [dict(x) for x in top]
        items.append(d)
    return {"items": items, "total": len(items)}


def review_history(ctx: Context, user: dict, app_id: str) -> list[dict]:
    if user["role"] == "applicant":
        raise forbidden("Review history is visible to reviewers and administrators.")
    app_for(ctx, user, app_id)
    return [dict(r) for r in ctx.db.all("""SELECT id, finding_id, actor_email, actor_role, action, remarks, from_status, to_status, created_at
                                           FROM review_actions WHERE application_id=? ORDER BY id DESC""", (app_id,))]


def review_action(ctx: Context, user: dict, app_id: str, body: dict) -> dict:
    action = body.get("action")
    remarks = _clean(body.get("remarks"), "remarks", 2000)
    row = app_for(ctx, user, app_id)
    status = row["status"]
    to_status = None
    if action == "assign":
        require(user["role"], "review.assign")
        rid = body.get("reviewer_id")
        if rid in (None, "self"):
            if user["role"] != "reviewer":
                raise unprocessable("Choose a reviewer to assign.", fields={"reviewer_id": "required"})
            rid = user["id"]
        tgt = ctx.db.one("SELECT id,name,email FROM users WHERE id=? AND role='reviewer' AND active=1", (rid,))
        if tgt is None:
            raise unprocessable("That user is not an active reviewer.", fields={"reviewer_id": "invalid"})
        if status in workflow.TERMINAL:
            raise conflict("A final decision has been recorded; the case cannot be reassigned.", code="final")
        with ctx.db.tx() as c:
            c.execute("UPDATE applications SET reviewer_id=?, updated_at=? WHERE id=?", (tgt["id"], utcnow_iso(), app_id))
            c.execute("INSERT INTO review_actions(application_id,actor_id,actor_email,actor_role,action,remarks,created_at) VALUES(?,?,?,?,?,?,?)",
                      (app_id, user["id"], user["email"], user["role"], "assign", f"Assigned to {tgt['name']}", utcnow_iso()))
            ctx.audit(user, "review.assign", "application", app_id, f"Assigned to {tgt['name']}.", application_id=app_id, conn=c)
        if tgt["id"] != user["id"]:
            ctx.notify(tgt["id"], "review", f"{row['reference']} assigned to you", "", app_id)
    elif action == "comment":
        require(user["role"], "comment.add")
        if len(remarks) < 2:
            raise unprocessable("Write a comment first.", fields={"remarks": "required"})
        _record(ctx, user, app_id, "comment", remarks, None, None, "review.comment", "Comment added.")
    elif action == "mark_reviewed":
        require(user["role"], "finding.mark_reviewed")
        if status in workflow.TERMINAL:
            raise conflict("A final decision has been recorded.", code="final")
        _record(ctx, user, app_id, "mark_reviewed", remarks or "Marked as reviewed.", None, None, "review.mark_reviewed", "Application marked as reviewed.")
        if row["reviewer_id"] is None and user["role"] == "reviewer":
            with ctx.db.tx() as c:
                c.execute("UPDATE applications SET reviewer_id=? WHERE id=?", (user["id"], app_id))
    elif action == "escalate":
        require(user["role"], "review.escalate")
        if len(remarks) < 5:
            raise unprocessable("Explain why this is being escalated (at least 5 characters).", fields={"remarks": "required"})
        if status in workflow.TERMINAL:
            raise conflict("A final decision has been recorded.", code="final")
        with ctx.db.tx() as c:
            c.execute("UPDATE applications SET escalated=1, updated_at=? WHERE id=?", (utcnow_iso(), app_id))
        _record(ctx, user, app_id, "escalate", remarks, None, None, "review.escalate", "Escalated to a senior reviewer / administrator.")
        ctx.notify_role("admin", "review", f"{row['reference']} escalated", remarks, app_id)
    elif action in ("request_correction", "approve_demo", "reject_demo"):
        target = {"request_correction": workflow.CORRECTIONS_REQUESTED, "approve_demo": workflow.APPROVED_DEMO,
                  "reject_demo": workflow.REJECTED_DEMO}[action]
        require(user["role"], "review.request_corrections" if action == "request_correction" else "review.decide")
        unreviewed = ctx.db.scalar("SELECT COUNT(*) FROM findings WHERE application_id=? AND is_current=1 AND severity='high' AND status IN ('open','under_review')", (app_id,))
        try:
            to_status = workflow.transition(status, target, user["role"], confirm=bool(body.get("confirm")), remarks=remarks, unreviewed_high_findings=unreviewed)
        except workflow.WorkflowError as exc:
            ctx.audit(user, f"review.{action}", "application", app_id, f"Rejected: {exc}", application_id=app_id, result="failure", from_status=status)
            raise _map_workflow(exc)
        with ctx.db.tx() as c:
            if target == workflow.CORRECTIONS_REQUESTED:
                c.execute("UPDATE applications SET status=?, correction_cycles=correction_cycles+1, updated_at=? WHERE id=?", (to_status, utcnow_iso(), app_id))
            else:
                c.execute("UPDATE applications SET status=?, decision_remarks=?, decided_by=?, decided_at=?, updated_at=? WHERE id=?",
                          (to_status, remarks, user["email"], utcnow_iso(), utcnow_iso(), app_id))
            if row["reviewer_id"] is None and user["role"] == "reviewer":
                c.execute("UPDATE applications SET reviewer_id=? WHERE id=?", (user["id"], app_id))
            c.execute("INSERT INTO review_actions(application_id,actor_id,actor_email,actor_role,action,remarks,from_status,to_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (app_id, user["id"], user["email"], user["role"], action, remarks, status, to_status, utcnow_iso()))
            label = {"request_correction": "Corrections requested", "approve_demo": "DEMONSTRATION approval recorded (not an official decision)",
                     "reject_demo": "DEMONSTRATION rejection recorded (not an official decision)"}[action]
            ctx.audit(user, f"review.{action}", "application", app_id, f"{label}.", application_id=app_id, from_status=status, to_status=to_status, conn=c)
        ctx.notify(row["owner_id"], "review", f"{row['reference']}: {workflow.STATUS_LABELS[to_status]}", remarks, app_id)
    else:
        raise unprocessable("Unknown review action.", fields={"action": "invalid"})
    return get_application(ctx, user, app_id)


def _record(ctx: Context, user: dict, app_id: str, action: str, remarks: str, f, t, audit_action: str, desc: str) -> None:
    with ctx.db.tx() as c:
        c.execute("INSERT INTO review_actions(application_id,actor_id,actor_email,actor_role,action,remarks,from_status,to_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (app_id, user["id"], user["email"], user["role"], action, remarks, f, t, utcnow_iso()))
        ctx.audit(user, audit_action, "application", app_id, desc, application_id=app_id, conn=c)
