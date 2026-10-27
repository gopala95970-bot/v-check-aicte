"""Demo data. Users, a synthetic verification registry and six scenario applications.

The scenario applications are NOT canned database rows: synthetic PDFs are generated and pushed through the
same upload -> OCR -> extraction -> validation pipeline as any user upload. Their findings are whatever the
engine actually produces."""
from __future__ import annotations

import logging

from vcheck.models import utcnow_iso

from . import demo, repo, security, services_core as core
from .context import SYSTEM, Context

log = logging.getLogger("vcheck.seed")

DEMO_PASSWORDS = {
    "applicant@demo.vcheck": "Applicant@Demo2026",
    "applicant2@demo.vcheck": "Applicant@Demo2026",
    "reviewer@demo.vcheck": "Reviewer@Demo2026",
    "reviewer2@demo.vcheck": "Reviewer@Demo2026",
    "admin@demo.vcheck": "Admin@Demo2026",
}
USERS = [
    ("applicant@demo.vcheck", "Arjun Menon", "applicant", "Demo Institutions Consortium"),
    ("applicant2@demo.vcheck", "Divya Nair", "applicant", "Demo Institutions Consortium"),
    ("reviewer@demo.vcheck", "Meera Iyer", "reviewer", "Demo Review Office (fictional)"),
    ("reviewer2@demo.vcheck", "Sanjay Kulkarni", "reviewer", "Demo Review Office (fictional)"),
    ("admin@demo.vcheck", "Karthik Raman", "admin", "V-Check Demo Administration"),
]

# (seq, institution name, institution id, state, district, scenario, courses)
COURSES = [{"name": "B.E. Computer Science and Engineering", "intake": "180"}, {"name": "B.Tech. Information Technology", "intake": "60"}]
SCENARIO_APPS = [
    (1, "Greenfield Institute of Technology", "1-9000000101", "Tamil Nadu", "Demo District A", "clean", COURSES),
    (2, "Riverbend College of Engineering", "1-9000000202", "Karnataka", "Demo District B", "missing_occupancy", COURSES),
    (3, "Lakeside College of Technology", "1-9000000303", "Maharashtra", "Demo District C", "institution_id_mismatch", COURSES),
    (4, "Hillcrest Engineering Academy", "1-9000000404", "Kerala", "Demo District D", "expired_affiliation", COURSES),
    (5, "Maplewood Institute of Science", "1-9000000505", "Telangana", "Demo District E", "duplicate_reuse", COURSES),
    (6, "Sunrise School of Engineering", "1-9000000606", "Gujarat", "Demo District F", "clean", COURSES),
]
CAPTIONS = {1: "APP-001 · Clean application", 2: "APP-002 · Missing document", 3: "APP-003 · Inconsistent application",
            4: "APP-004 · Expired document", 5: "APP-005 · Duplicate evidence", 6: "APP-006 · Review required (source unavailable)"}


def ensure_users(ctx: Context) -> None:
    for email, name, role, org in USERS:
        if ctx.db.one("SELECT 1 FROM users WHERE email=?", (email,)) is None:
            with ctx.db.tx() as c:
                c.execute("INSERT INTO users(email,name,role,organization,password_hash,created_at) VALUES(?,?,?,?,?,?)",
                          (email, name, role, org, security.hash_password(DEMO_PASSWORDS[email]), utcnow_iso()))


def user_dict(ctx: Context, email: str) -> dict:
    u = ctx.db.one("SELECT * FROM users WHERE email=?", (email,))
    return {k: u[k] for k in ("id", "email", "name", "role", "organization")}


def seed_demo(ctx: Context) -> None:
    ensure_users(ctx)
    if ctx.db.scalar("SELECT COUNT(*) FROM applications WHERE demo_scenario IS NOT NULL"):
        return
    log.info("Seeding demo applications (this runs the real pipeline)…")
    prev_sync = ctx.settings.sync_processing
    ctx.settings.sync_processing = True           # deterministic: finish each stage before the next application
    try:
        owner = user_dict(ctx, "applicant@demo.vcheck")
        reviewer, reviewer2 = user_dict(ctx, "reviewer@demo.vcheck"), user_dict(ctx, "reviewer2@demo.vcheck")
        first_occupancy: bytes | None = None
        for seq, name, inst_id, state, district, scenario, courses in SCENARIO_APPS:
            created = core.create_application(ctx, owner, {
                "institution": {"name": name, "institution_id": inst_id, "state": state, "district": district,
                                "address": f"{seq * 12} Demo Road, Demo City (fictional)", "contact_name": "Demo Registrar",
                                "contact_email": f"registrar{seq}@demo.vcheck", "contact_phone": "+91 00000 0000" + str(seq)},
                "application_type": "extension_of_approval", "academic_year": "2026-27", "courses": courses,
                "notes": CAPTIONS[seq] + ". Synthetic demonstration record."}, _seq=seq)
            app_id = created["id"]
            reuse = first_occupancy if scenario == "duplicate_reuse" else None
            built = demo.build_documents(name=name, inst_id=inst_id, reference=created["reference"], seq=seq,
                                         courses=[(c["name"], c["intake"]) for c in courses], today=ctx.today(),
                                         scenario=scenario, reuse_bytes=reuse)
            for fname, raw, dtype in built:
                if seq == 1 and dtype == "occupancy_certificate":
                    first_occupancy = raw
                core.upload_document(ctx, owner, app_id, raw, fname, dtype)
            with ctx.db.tx() as c:
                c.execute("UPDATE applications SET demo_scenario=?, verification_mode=? WHERE id=?",
                          (scenario, "simulation" if seq == 1 else ("unavailable" if seq == 6 else None), app_id))
                # synthetic registry entries: certificate number -> the institution it belongs to
                for t, num in _certs(seq).items():
                    c.execute("INSERT OR REPLACE INTO verification_registry(certificate_number,institution_id,note) VALUES(?,?,?)",
                              (num, inst_id, "synthetic demo registry"))
            core.submit_application(ctx, owner, app_id)
            if seq in (2, 3):
                _assign(ctx, app_id, reviewer["id"])
            if seq in (4,):
                _assign(ctx, app_id, reviewer2["id"])
    finally:
        ctx.settings.sync_processing = prev_sync
    log.info("Demo data ready.")


def _certs(seq: int) -> dict:
    code = f"{seq:03d}"
    return {"eoa_letter": f"EOA/DEMO/2026/{code}1", "occupancy_certificate": f"OCC/DEMO/2026/{code}2",
            "affiliation_letter": f"AFF/DEMO/2026/{code}3", "government_approval": f"GOV/DEMO/2026/{code}4"}


def _assign(ctx: Context, app_id: str, reviewer_id: int) -> None:
    with ctx.db.tx() as c:
        c.execute("UPDATE applications SET reviewer_id=? WHERE id=?", (reviewer_id, app_id))


def reset_demo(ctx: Context, actor: dict) -> None:
    """Remove ONLY the six seeded scenario applications and rebuild them. User-created applications are kept."""
    rows = ctx.db.all("SELECT id, institution_pk FROM applications WHERE demo_scenario IS NOT NULL")
    for r in rows:
        for d in ctx.db.all("SELECT id, storage_name FROM documents WHERE application_id=?", (r["id"],)):
            if d["storage_name"]:
                try:
                    repo.doc_path(ctx, d["storage_name"]).unlink(missing_ok=True)
                except OSError:
                    pass
    with ctx.db.tx() as c:
        for r in rows:
            c.execute("DELETE FROM stage_events WHERE application_id=?", (r["id"],))
            c.execute("DELETE FROM verification_results WHERE application_id=?", (r["id"],))
            c.execute("DELETE FROM review_actions WHERE application_id=?", (r["id"],))
            c.execute("DELETE FROM notifications WHERE application_id=?", (r["id"],))
            c.execute("DELETE FROM applications WHERE id=?", (r["id"],))
            c.execute("DELETE FROM institutions WHERE id=?", (r["institution_pk"],))
        c.execute("DELETE FROM verification_registry")
    ctx.audit(actor, "demo.reset", "system", "demo", "Demo applications were reset to their initial synthetic state.")
    seed_demo(ctx)
