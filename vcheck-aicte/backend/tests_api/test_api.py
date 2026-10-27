import json
import os
import sqlite3
import unittest
from datetime import date

import jwt

from vcheck_api import security
from vcheck_api.app import create_app
from vcheck_api.config import Settings
from vcheck_api.seed import DEMO_PASSWORDS

from .helpers import NEW_APP, TODAY, Client, make_app, wait_until

A, A2, R, R2, ADM = ("applicant@demo.vcheck", "applicant2@demo.vcheck", "reviewer@demo.vcheck", "reviewer2@demo.vcheck", "admin@demo.vcheck")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = make_app()
        cls.c = Client(cls.app)
        cls.ctx = cls.app.ctx
        cls.tok = {e: cls.c.login(e) for e in (A, A2, R, R2, ADM)}


class TestAuth(Base):
    def test_unauthenticated_requests_are_rejected(self):
        for path in ("/applications", "/dashboard", "/audit", "/rules", "/documents"):
            s, r = self.c.call("GET", path)
            self.assertEqual(s, 401, path)
            self.assertEqual(r["error"]["code"], "unauthorized")

    def test_garbage_token_rejected(self):
        s, r = self.c.call("GET", "/applications", token="x" * 40)
        self.assertEqual((s, r["error"]["code"]), (401, "invalid_token"))

    def test_login_failure_is_generic_and_audited(self):
        s, r = self.c.call("POST", "/auth/login", {"email": "nobody@demo.vcheck", "password": "whatever123"})
        self.assertEqual((s, r["error"]["code"]), (401, "invalid_credentials"))
        s, r2 = self.c.call("POST", "/auth/login", {"email": R, "password": "wrong-password"})
        self.assertEqual(r["error"]["message"], r2["error"]["message"])      # no user enumeration
        s, a = self.c.call("GET", "/audit", token=self.tok[ADM], query="action=auth.login&result=failure")
        self.assertGreaterEqual(a["total"], 2)

    def test_password_is_hashed_in_db(self):
        row = self.ctx.db.one("SELECT password_hash FROM users WHERE email=?", (A,))
        self.assertTrue(row["password_hash"].startswith("scrypt$"))
        self.assertNotIn(DEMO_PASSWORDS[A], row["password_hash"])

    def test_expired_token_rejected(self):
        now = 1_000_000
        tok = jwt.encode({"sub": "1", "role": "admin", "jti": "abc", "iat": now, "exp": now + 1}, self.ctx.settings.jwt_secret, algorithm="HS256")
        s, r = self.c.call("GET", "/auth/me", token=tok)
        self.assertEqual((s, r["error"]["code"]), (401, "token_expired"))

    def test_token_signed_with_wrong_secret_rejected(self):
        tok = jwt.encode({"sub": "1", "role": "admin", "jti": "abc", "exp": 4_000_000_000}, "not-the-secret-not-the-secret-123456", algorithm="HS256")
        s, r = self.c.call("GET", "/auth/me", token=tok)
        self.assertEqual(s, 401)

    def test_logout_revokes_token(self):
        t = self.c.login(A2)
        self.assertEqual(self.c.call("GET", "/auth/me", token=t)[0], 200)
        self.assertEqual(self.c.call("POST", "/auth/logout", token=t)[0], 204)
        s, r = self.c.call("GET", "/auth/me", token=t)
        self.assertEqual((s, r["error"]["code"]), (401, "token_revoked"))

    def test_login_throttle(self):
        app = make_app(login_max_failures=3, seed_demo=False)
        c = Client(app)
        for _ in range(3):
            self.assertEqual(c.call("POST", "/auth/login", {"email": R, "password": "bad"})[0], 401)
        s, r = c.call("POST", "/auth/login", {"email": R, "password": DEMO_PASSWORDS[R]})
        self.assertEqual((s, r["error"]["code"]), (429, "too_many_attempts"))
        self.assertIn("Retry-After", c.last_headers)

    def test_change_password(self):
        app = make_app(seed_demo=False)
        c = Client(app)
        t = c.login(A)
        s, r = c.call("POST", "/auth/change-password", {"current_password": "wrong", "new_password": "Brand-New-Pass1"}, token=t)
        self.assertEqual(s, 422)
        s, r = c.call("POST", "/auth/change-password", {"current_password": DEMO_PASSWORDS[A], "new_password": "short"}, token=t)
        self.assertEqual(s, 422)
        s, r = c.call("POST", "/auth/change-password", {"current_password": DEMO_PASSWORDS[A], "new_password": "Brand-New-Pass1"}, token=t)
        self.assertEqual(s, 200)
        self.assertEqual(c.call("POST", "/auth/login", {"email": A, "password": DEMO_PASSWORDS[A]})[0], 401)
        self.assertEqual(c.call("POST", "/auth/login", {"email": A, "password": "Brand-New-Pass1"})[0], 200)

    def test_security_headers_and_cors(self):
        s, _ = self.c.call("GET", "/health")
        self.assertEqual(self.c.last_headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.c.last_headers["Cache-Control"], "no-store")
        self.c.call("OPTIONS", "/applications", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(self.c.last_headers.get("Access-Control-Allow-Origin"), "http://localhost:5173")
        self.c.call("OPTIONS", "/applications", headers={"Origin": "https://evil.example"})
        self.assertNotIn("Access-Control-Allow-Origin", self.c.last_headers)

    def test_unknown_route_and_method(self):
        self.assertEqual(self.c.call("GET", "/nope", token=self.tok[A])[0], 404)
        self.assertEqual(self.c.call("DELETE", "/dashboard", token=self.tok[A])[0], 405)

    def test_invalid_json_is_a_clean_400(self):
        s, r = self.c.call("POST", "/applications", token=self.tok[A], raw=b"{not json")
        self.assertEqual((s, r["error"]["code"]), (400, "invalid_json"))


class TestSeedScenarios(Base):
    """The six demo applications are real DB records whose findings come from the engine."""

    def rules(self, app_id, role=R):
        s, r = self.c.call("GET", f"/applications/{app_id}/findings", token=self.tok[role])
        self.assertEqual(s, 200)
        return sorted({f["rule_id"] for f in r["items"]}), r["items"]

    def test_six_demo_apps_exist(self):
        s, r = self.c.call("GET", "/applications", token=self.tok[R])
        self.assertEqual(sorted(i["id"] for i in r["items"]), [f"APP-00{n}" for n in range(1, 7)])
        self.assertTrue(all(i["is_demo"] for i in r["items"]))

    def test_app001_clean(self):
        ids, _ = self.rules("APP-001")
        self.assertEqual(ids, [])
        s, a = self.c.call("GET", "/applications/APP-001", token=self.tok[R])
        self.assertEqual((a["status"], a["validation"]), ("validation_complete", "passed"))

    def test_app002_missing_document(self):
        ids, items = self.rules("APP-002")
        self.assertEqual(ids, ["REQ-DOC-001"])
        self.assertEqual(items[0]["severity"], "high")
        self.assertEqual(items[0]["rule_kind"], "demonstration")
        self.assertTrue(items[0]["recommended_action"])

    def test_app003_inconsistent_institution_id(self):
        ids, items = self.rules("APP-003")
        self.assertEqual(ids, ["XD-002"])
        f = items[0]
        self.assertEqual(f["outcome"], "failed")
        self.assertIsNotNone(f["observed"])
        self.assertTrue(f["evidence"] and f["evidence"][0]["filename"])      # evidence resolves to a document name
        self.assertIn("affiliation", f["evidence"][0]["filename"])

    def test_app004_expired(self):
        ids, _ = self.rules("APP-004")
        self.assertEqual(ids, ["DATE-002"])

    def test_app005_duplicate_evidence_is_reviewer_only(self):
        ids, _ = self.rules("APP-005", R)
        self.assertIn("DUP-002", ids)
        ids_a, _ = self.rules("APP-005", A)
        self.assertNotIn("DUP-002", ids_a)                      # applicants never see other institutions' references

    def test_app006_verification_unavailable(self):
        ids, items = self.rules("APP-006")
        self.assertEqual(ids, ["VER-001"])
        self.assertTrue(all(f["outcome"] == "review_required" for f in items))     # unavailable source is never a failure

    def test_simulated_verification_is_never_called_verified(self):
        s, p = self.c.call("GET", "/applications/APP-001/pipeline", token=self.tok[R])
        self.assertTrue(p["verification"])
        for v in p["verification"]:
            self.assertTrue(v["simulated"])
            self.assertNotEqual(v["display_status"], "verified")
            self.assertEqual(v["display_status"], "simulated_match")
            self.assertIn("NOT a government verification", v["detail"])

    def test_pipeline_has_every_stage_with_real_state(self):
        s, p = self.c.call("GET", "/applications/APP-003/pipeline", token=self.tok[R])
        names = [x["stage"] for x in p["stages"]]
        self.assertEqual(names, ["Document Received", "File Integrity", "OCR", "Classification", "Field Extraction", "Cross-document Validation",
                                 "Duplicate Detection", "Compliance Rules", "Source Verification", "Human Review"])
        by = {x["stage"]: x for x in p["stages"]}
        self.assertEqual(by["Cross-document Validation"]["status"], "failed")
        self.assertTrue(by["Cross-document Validation"]["evidence"][0].startswith("VF-"))
        self.assertEqual(by["Source Verification"]["status"], "skipped")        # off by default: nothing claimed
        self.assertEqual(by["Human Review"]["status"], "pending")
        self.assertEqual(len(p["documents"]), 4)
        self.assertIsNotNone(p["latest_run"]["duration_ms"])

    def test_extracted_fields_have_page_references(self):
        s, docs = self.c.call("GET", "/applications/APP-003/documents", token=self.tok[R])
        d = next(x for x in docs["items"] if x["declared_type"] == "affiliation_letter")
        s, full = self.c.call("GET", f"/documents/{d['id']}", token=self.tok[R])
        self.assertEqual(s, 200)
        inst = next(f for f in full["fields"] if f["name"] == "institution_id")
        self.assertEqual(inst["value"], "1-9000000999")
        self.assertEqual(inst["page"], 1)
        self.assertTrue(inst["snippet"])
        self.assertEqual(full["text_source"], "text_layer")

    def test_dashboard_numbers_come_from_the_database(self):
        s, d = self.c.call("GET", "/dashboard", token=self.tok[R])
        db = self.ctx.db
        self.assertEqual(d["metrics"]["total_applications"], db.scalar("SELECT COUNT(*) FROM applications WHERE status<>'draft'"))
        self.assertEqual(d["metrics"]["validated_documents"], db.scalar("SELECT COUNT(*) FROM documents WHERE active=1 AND status='processed'"))
        self.assertEqual(d["metrics"]["critical_findings"], db.scalar("SELECT COUNT(*) FROM findings WHERE is_current=1 AND severity='high' AND outcome='failed' AND status IN ('open','under_review')"))
        self.assertEqual(sum(x["count"] for x in d["charts"]["validation_distribution"]), d["metrics"]["total_applications"])
        self.assertEqual(len(d["recent_applications"]), 6)


class TestAccessControl(Base):
    def test_applicant_sees_only_own_applications(self):
        s, r = self.c.call("GET", "/applications", token=self.tok[A2])
        self.assertEqual(r["total"], 0)
        s, r = self.c.call("GET", "/applications/APP-001", token=self.tok[A2])
        self.assertEqual(s, 404)                                      # no existence leak
        s, r = self.c.call("GET", "/applications/APP-001/pipeline", token=self.tok[A2])
        self.assertEqual(s, 404)

    def test_applicant_cannot_read_other_users_document_or_file(self):
        s, docs = self.c.call("GET", "/applications/APP-001/documents", token=self.tok[A])
        did = docs["items"][0]["id"]
        self.assertEqual(self.c.call("GET", f"/documents/{did}", token=self.tok[A2])[0], 404)
        self.assertEqual(self.c.call("GET", f"/documents/{did}/file", token=self.tok[A2])[0], 404)
        s, raw = self.c.call("GET", f"/documents/{did}/file", token=self.tok[A])
        self.assertEqual(s, 200)
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertIn("sandbox", self.c.last_headers["Content-Security-Policy"])

    def test_role_restrictions(self):
        t = self.tok
        self.assertEqual(self.c.call("GET", "/audit", token=t[A])[0], 403)
        self.assertEqual(self.c.call("GET", "/review/queue", token=t[A])[0], 403)
        self.assertEqual(self.c.call("GET", "/analytics", token=t[A])[0], 403)
        self.assertEqual(self.c.call("GET", "/rules", token=t[A])[0], 403)
        self.assertEqual(self.c.call("GET", "/settings/admin", token=t[R])[0], 403)
        self.assertEqual(self.c.call("POST", "/applications", NEW_APP, token=t[R])[0], 403)       # reviewers don't file applications
        self.assertEqual(self.c.call("POST", "/applications", NEW_APP, token=t[ADM])[0], 403)
        self.assertEqual(self.c.call("POST", "/demo/reset", {}, token=t[R])[0], 403)
        self.assertEqual(self.c.call("PATCH", "/rules/DATE-002", {"enabled": False}, token=t[R])[0], 403)
        self.assertEqual(self.c.call("POST", "/applications/APP-002/review/actions", {"action": "approve_demo", "remarks": "fine", "confirm": True}, token=t[A])[0], 403)    # owner, but not permitted
        self.assertEqual(self.c.call("PATCH", "/findings/VF-1001", {"status": "resolved", "note": "done now"}, token=t[A])[0], 403)
        self.assertEqual(self.c.call("GET", "/audit", token=t[R])[0], 200)
        self.assertEqual(self.c.call("GET", "/audit", token=t[ADM])[0], 200)

    def test_applicant_cannot_edit_submitted_application(self):
        s, r = self.c.call("PATCH", "/applications/APP-001", {"notes": "tamper"}, token=self.tok[A])
        self.assertEqual((s, r["error"]["code"]), (409, "not_editable"))
        s, docs = self.c.call("GET", "/applications/APP-001/documents", token=self.tok[A])
        self.assertEqual(self.c.call("DELETE", f"/documents/{docs['items'][0]['id']}", token=self.tok[A])[0], 409)

    def test_reviewer_cannot_see_drafts(self):
        t = self.c.login(A2)
        s, a = self.c.call("POST", "/applications", NEW_APP, token=t)
        self.assertEqual(s, 201)
        self.assertEqual(self.c.call("GET", f"/applications/{a['id']}", token=self.tok[R])[0], 404)
        s, q = self.c.call("GET", "/applications", token=self.tok[R])
        self.assertNotIn(a["id"], [i["id"] for i in q["items"]])


class TestUploadSecurity(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        s, a = cls.c.call("POST", "/applications", NEW_APP, token=cls.tok[A2])
        cls.app_id = a["id"]

    def test_executable_renamed_pdf_is_rejected_and_not_stored(self):
        before = set(os.listdir(self.ctx.settings.upload_dir))
        s, d = self.c.upload(self.tok[A2], self.app_id, "occupancy.pdf", b"MZ\x90\x00\x03" + b"\x00" * 300, "occupancy_certificate")
        self.assertEqual(s, 201)
        self.assertEqual(d["status"], "rejected")
        self.assertEqual(d["errors"][0]["code"], "UNSUPPORTED_TYPE")
        self.assertFalse(d["previewable"])
        self.assertEqual(set(os.listdir(self.ctx.settings.upload_dir)), before)             # bytes never kept

    def test_path_traversal_filename_is_sanitised_and_never_used_on_disk(self):
        from vcheck.files import storage_name
        from tests_api.helpers import wait_until
        import synth  # noqa
        pdf = __import__("vcheck_api.demo", fromlist=["synth"]).synth.digital_pdf({"type": "occupancy_certificate", "institution_name": "X Inst", "issue_date": "01-Jan-2026", "issuer": "Demo", "courses": [], "certificate_number": "OCC/1"})
        s, d = self.c.upload(self.tok[A2], self.app_id, "..\\..\\..\\windows\\evil/../name.pdf", pdf, "occupancy_certificate")
        self.assertEqual(s, 201, d)
        self.assertNotIn("..", d["filename"])
        self.assertNotIn("/", d["filename"])
        self.assertNotIn("\\", d["filename"])
        row = self.ctx.db.one("SELECT storage_name FROM documents WHERE id=?", (d["id"],))
        self.assertRegex(row["storage_name"], r"^[0-9a-f]{32}\.pdf$")

    def test_no_filesystem_paths_in_any_response(self):
        s, docs = self.c.call("GET", f"/applications/{self.app_id}/documents", token=self.tok[A2])
        text = json.dumps(docs)
        self.assertNotIn(str(self.ctx.settings.storage_dir), text)
        self.assertNotIn("storage_name", text)
        self.assertNotIn("uploads", text)

    def test_oversize_upload_rejected_with_413(self):
        s, r = self.c.upload(self.tok[A2], self.app_id, "big.pdf", b"%PDF-1.4\n" + b"0" * (11 * 1024 * 1024), "occupancy_certificate")
        self.assertEqual(s, 413)

    def test_unknown_document_type_and_empty_upload(self):
        s, r = self.c.upload(self.tok[A2], self.app_id, "a.pdf", b"%PDF-1.4", "passport")
        self.assertEqual(s, 422)
        s, r = self.c.call("POST", f"/applications/{self.app_id}/documents", token=self.tok[A2], query="filename=a.pdf", raw=b"", ctype="application/octet-stream")
        self.assertEqual(s, 201)
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(r["errors"][0]["code"], "EMPTY_FILE")

    def test_png_named_pdf_flagged(self):
        from vcheck_api.demo import synth
        png = synth.image_bytes(synth.page_image({"type": "occupancy_certificate", "institution_name": "X", "issue_date": "01-Jan-2026", "issuer": "D", "courses": [], "certificate_number": "O/1"}))
        s, d = self.c.upload(self.tok[A2], self.app_id, "scan.pdf", png, "occupancy_certificate")
        self.assertEqual(d["errors"][0]["code"], "EXTENSION_MISMATCH")


class TestStaticServingSafety(Base):
    """The API now serves the web UI from disk, so traversal must never leak source files or secrets."""

    def raw(self, path):
        import io
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_TYPE": "", "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""), "REMOTE_ADDR": "9.9.9.9"}
        out = {}
        body = b"".join(self.app(env, lambda s, h: out.update(status=int(s.split()[0]), headers=dict(h))))
        return out["status"], out["headers"], body

    def test_ui_shell_assets_and_csp(self):
        s, h, b = self.raw("/")
        self.assertEqual(s, 200)
        self.assertIn(b"<title>V-Check AICTE", b)
        csp = h["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertEqual(self.raw("/assets/js/main.js")[1]["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(self.raw("/dashboard")[0], 200)                    # client-side route falls back to the shell
        self.assertEqual(self.raw("/assets/js/missing.js")[0], 404)         # a missing asset is a 404, not the shell

    def test_traversal_attempts_never_leak_files(self):
        secret_markers = (b"class Settings", b"jwt_secret", b"root:x:", b"CREATE TABLE", b"def hash_password")
        attempts = ["/../backend/vcheck_api/config.py", "/assets/../../backend/vcheck_api/config.py", "/%2e%2e/backend/vcheck_api/security.py",
                    "/assets/%2e%2e/%2e%2e/storage/.jwt_secret", "/..%2f..%2fetc/passwd", "/....//....//etc/passwd", "/assets/js/../../../README.md",
                    "/%252e%252e/backend/vcheck_api/db.py", "/storage/vcheck.db", "/.env", "/backend/vcheck_api/config.py", "//etc/passwd"]
        for p in attempts:
            s, h, b = self.raw(p)
            self.assertIn(s, (200, 404), p)
            for m in secret_markers:
                self.assertNotIn(m, b, f"{p} leaked {m!r}")
            if s == 200:
                self.assertIn(b"<title>V-Check AICTE", b, p)                  # only ever the app shell

    def test_api_namespace_is_never_shadowed_by_static(self):
        s, h, b = self.raw("/api/v1/does-not-exist")
        self.assertEqual(s, 404)
        self.assertIn(b"unknown_endpoint", b)


class TestOcrThroughApi(unittest.TestCase):
    """A scanned (image-only) PDF needs real OCR; this proves the API path, not just the engine."""

    def test_scanned_pdf_is_ocr_read_and_checked(self):
        from vcheck_api import seed
        from vcheck_api.demo import synth
        app = make_app(seed_demo=False)
        c = Client(app)
        seed.ensure_users(app.ctx)
        ta = c.login(A)
        s, a = c.call("POST", "/applications", NEW_APP, token=ta)
        spec = {"type": "affiliation_letter", "institution_name": NEW_APP["institution"]["name"], "institution_id": "1-9000000555",
                "issue_date": "15-May-2026", "expiry_date": "31-May-2027", "issuer": "Demo University",
                "courses": [("B.E. Computer Science and Engineering", "120")], "certificate_number": "AFF/SCAN/1"}
        s, d = c.upload(ta, a["id"], "scan.pdf", synth.scanned_pdf(spec), "affiliation_letter")
        self.assertEqual((s, d["status"]), (201, "processed"))
        s, full = c.call("GET", f"/documents/{d['id']}", token=ta)
        self.assertEqual(full["text_source"], "ocr")
        self.assertGreater(full["ocr_mean_conf"], 0.8)
        inst = next(f for f in full["fields"] if f["name"] == "institution_id")
        self.assertEqual((inst["value"], inst["method"]), ("1-9000000555", "ocr"))
        self.assertIsNotNone(inst["bbox"])                                  # bounding box for the on-document highlight
        ocr_stage = next(x for x in full["stages"] if x["stage"] == "OCR")
        self.assertGreater(ocr_stage["duration_ms"], 0)                     # real measured OCR time
        s, f = c.call("POST", f"/applications/{a['id']}/validate", token=ta)
        s, fl = c.call("GET", f"/applications/{a['id']}/findings", token=ta)
        mm = [x for x in fl["items"] if x["rule_id"] == "XD-002"]
        self.assertEqual(len(mm), 1)                                        # OCR'd id differs from the application's id -> flagged
        self.assertEqual(mm[0]["observed"], "1-9000000555")


class TestEndToEndJourney(unittest.TestCase):
    """Login → create → upload → process → mismatch → finding → reviewer action → audit. Real background processing."""

    @classmethod
    def setUpClass(cls):
        cls.app = make_app(sync_processing=False, seed_demo=False)       # real thread-pool processing
        cls.c = Client(cls.app)
        cls.ctx = cls.app.ctx
        from vcheck_api import seed
        seed.ensure_users(cls.ctx)

    def test_full_journey(self):
        c, ctx = self.c, self.ctx
        ta, tr, tadm = c.login(A), c.login(R), c.login(ADM)

        # 1. create application (draft)
        s, app = c.call("POST", "/applications", NEW_APP, token=ta)
        self.assertEqual((s, app["status"]), (201, "draft"))
        app_id = app["id"]

        # 2. required-document checklist comes from the rules, not the UI
        s, a = c.call("GET", f"/applications/{app_id}", token=ta)
        self.assertEqual({r["doc_type"] for r in a["required_documents"]}, {"eoa_letter", "occupancy_certificate", "affiliation_letter", "government_approval"})
        self.assertFalse(any(r["uploaded"] for r in a["required_documents"]))

        # 3. cannot submit with no documents
        s, r = c.call("POST", f"/applications/{app_id}/submit", token=ta)
        self.assertEqual((s, r["error"]["code"]), (422, "no_documents"))

        # 4. upload synthetic documents with an institution-id mismatch (demo scenario goes through the real upload pipeline)
        s, r = c.call("POST", f"/applications/{app_id}/demo-documents", {"scenario": "institution_id_mismatch"}, token=ta)
        self.assertEqual(s, 201, r)
        self.assertEqual(len(r["items"]), 4)
        s, docs = c.call("GET", f"/applications/{app_id}/documents", token=ta)
        wait_until(lambda: all(d["status"] == "processed" for d in c.call("GET", f"/applications/{app_id}/documents", token=ta)[1]["items"]))
        s, docs = c.call("GET", f"/applications/{app_id}/documents", token=ta)
        for d in docs["items"]:
            self.assertEqual(d["status"], "processed")
            self.assertTrue(any(st["key"] == "fields" and st["state"] == "done" for st in d["steps"]))

        # 5. pre-check in draft shows the mismatch (applicant sees it) without changing status
        s, pre = c.call("POST", f"/applications/{app_id}/validate", token=ta)
        self.assertEqual(s, 200)
        self.assertEqual(pre["application"]["status"], "draft")

        # 6. submit → asynchronous processing → review_required
        s, sub = c.call("POST", f"/applications/{app_id}/submit", token=ta)
        self.assertEqual(s, 202)
        final = wait_until(lambda: (lambda x: x if x["status"] not in ("submitted", "processing") else None)(c.call("GET", f"/applications/{app_id}", token=ta)[1]))
        self.assertEqual(final["status"], "review_required")
        s, fl = c.call("GET", f"/applications/{app_id}/findings", token=ta)
        ids = {f["rule_id"] for f in fl["items"]}
        self.assertEqual(ids, {"XD-002"})
        finding = fl["items"][0]
        self.assertEqual(finding["observed"], "1-9000000999")
        self.assertEqual(finding["expected"], NEW_APP["institution"]["institution_id"])
        self.assertTrue(finding["evidence"][0]["snippet"])
        self.assertEqual(finding["evidence"][0]["page"], 1)
        self.assertEqual(finding["rule_kind"], "demonstration")
        self.assertEqual(finding["status"], "open")

        # 7. reviewer queue contains it; reviewer claims it
        s, q = c.call("GET", "/review/queue", token=tr)
        self.assertIn(app_id, [i["id"] for i in q["items"]])
        s, r = c.call("POST", f"/applications/{app_id}/review/actions", {"action": "assign", "reviewer_id": "self"}, token=tr)
        self.assertEqual(s, 200)
        self.assertEqual(r["reviewer"]["name"], "Meera Iyer")

        # 8. approving now fails: confirmation, remarks, then unreviewed high finding
        pay = {"action": "approve_demo", "remarks": "Looks fine to me", "confirm": False}
        s, r = c.call("POST", f"/applications/{app_id}/review/actions", pay, token=tr)
        self.assertEqual((s, r["error"]["code"]), (409, "confirmation_required"))
        s, r = c.call("POST", f"/applications/{app_id}/review/actions", {**pay, "confirm": True}, token=tr)
        self.assertEqual((s, r["error"]["code"]), (422, "workflow_error"))
        self.assertIn("high-severity", r["error"]["message"])

        # 9. reviewer corrects the extracted field (OCR/extraction misread case) → revalidation clears the finding
        s, docs = c.call("GET", f"/applications/{app_id}/documents", token=tr)
        aff = next(d for d in docs["items"] if d["declared_type"] == "affiliation_letter")
        s, full = c.call("GET", f"/documents/{aff['id']}", token=tr)
        fld = next(f for f in full["fields"] if f["name"] == "institution_id")
        s, res = c.call("PATCH", f"/documents/{aff['id']}/fields/{fld['id']}", {"value": NEW_APP["institution"]["institution_id"]}, token=tr)
        self.assertEqual(s, 200, res)
        self.assertEqual(res["field"]["value"], "1-9000000999")                  # original preserved
        self.assertEqual(res["field"]["corrected_value"], NEW_APP["institution"]["institution_id"])
        self.assertEqual(res["findings"]["total"], 0)
        s, fl = c.call("GET", f"/applications/{app_id}/findings", token=tr)
        self.assertEqual(fl["total"], 0)

        # 10. request correction (needs remarks), applicant is notified, edits & resubmits
        s, r = c.call("POST", f"/applications/{app_id}/review/actions", {"action": "request_correction", "remarks": ""}, token=tr)
        self.assertEqual(s, 422)
        s, r = c.call("POST", f"/applications/{app_id}/review/actions", {"action": "request_correction", "remarks": "Please upload a corrected affiliation letter."}, token=tr)
        self.assertEqual((s, r["status"]), (200, "corrections_requested"))
        s, n = c.call("GET", "/notifications", token=ta)
        self.assertTrue(any(app_id == x["application_id"] and "Corrections" in x["title"] for x in n["items"]))
        s, docs = c.call("GET", f"/applications/{app_id}/documents", token=ta)
        s, r = c.call("POST", f"/applications/{app_id}/demo-documents", {"scenario": "clean"}, token=ta)        # replaces documents
        self.assertEqual(s, 201)
        wait_until(lambda: all(d["status"] == "processed" for d in c.call("GET", f"/applications/{app_id}/documents", token=ta)[1]["items"]))
        s, docs = c.call("GET", f"/applications/{app_id}/documents", token=ta)
        self.assertEqual(len(docs["items"]), 4)                                   # replaced, not duplicated
        s, sub = c.call("POST", f"/applications/{app_id}/submit", token=ta)
        self.assertEqual(s, 202)
        final = wait_until(lambda: (lambda x: x if x["status"] not in ("resubmitted", "processing") else None)(c.call("GET", f"/applications/{app_id}", token=ta)[1]))
        self.assertEqual(final["status"], "validation_complete")
        self.assertEqual(final["correction_cycles"], 1)

        # 11. approve (demonstration only) with confirmation
        s, r = c.call("POST", f"/applications/{app_id}/review/actions", {"action": "approve_demo", "remarks": "Documents consistent now.", "confirm": True}, token=tr)
        self.assertEqual((s, r["status"]), (200, "approved_demo"))
        self.assertTrue(r["decision"]["demonstration_only"])
        self.assertIn("demonstration only", r["status_label"].lower())
        # final decisions are final
        s, r = c.call("POST", f"/applications/{app_id}/review/actions", {"action": "reject_demo", "remarks": "changed my mind", "confirm": True}, token=tr)
        self.assertEqual(s, 409)

        # 12. the audit trail tells the whole story
        s, aud = c.call("GET", "/audit", token=tadm, query=f"application_id={app_id}&page_size=100")
        actions = [x["action"] for x in aud["items"]]
        for expected in ("application.create", "document.upload", "application.submit", "pipeline.started", "pipeline.completed",
                         "review.assign", "extraction.correct", "review.request_correction", "application.resubmit", "review.approve_demo"):
            self.assertIn(expected, actions, expected)
        self.assertTrue(all(x["timestamp"] and x["user"] and x["role"] for x in aud["items"]))
        self.assertTrue(any(x["result"] == "failure" for x in aud["items"]))     # the blocked approvals are recorded too
        ts = [x["timestamp"] for x in aud["items"]]
        self.assertEqual(ts, sorted(ts, reverse=True))
        # audit never stores document contents or secrets
        blob = json.dumps(aud)
        self.assertNotIn("Reviewer@Demo2026", blob)

        # 13. review history is complete
        s, h = c.call("GET", f"/applications/{app_id}/review/history", token=tr)
        self.assertIn("approve_demo", [x["action"] for x in h["items"]])
        self.assertIn("field_correction", [x["action"] for x in h["items"]])
        self.assertEqual(c.call("GET", f"/applications/{app_id}/review/history", token=ta)[0], 403)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.executor.shutdown(wait=True)


class TestFindingsAndWorkflow(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.c = Client(self.app)
        self.t = {e: self.c.login(e) for e in (A, R, ADM)}

    def test_finding_triage_statuses_and_notes(self):
        c, t = self.c, self.t
        s, r = c.call("PATCH", "/findings/VF-1001", {"status": "resolved", "note": ""}, token=t[R])
        self.assertEqual(s, 422)                                            # note required to close
        s, r = c.call("PATCH", "/findings/VF-1001", {"status": "under_review"}, token=t[R])
        self.assertEqual((s, r["status"]), (200, "under_review"))
        s, r = c.call("PATCH", "/findings/VF-1001", {"status": "bogus"}, token=t[R])
        self.assertEqual(s, 422)
        s, r = c.call("PATCH", "/findings/VF-1001", {"status": "accepted_with_explanation", "note": "Certificate was reissued; verified by phone."}, token=t[R])
        self.assertEqual((s, r["status"], r["resolved_by"]), (200, "accepted_with_explanation", R))
        s, a = c.call("GET", "/audit", token=t[ADM], query="action=finding.status")
        self.assertEqual(a["total"], 2)

    def test_resolved_findings_unblock_approval_but_not_without_review(self):
        c, t = self.c, self.t
        pay = {"action": "approve_demo", "remarks": "All good after review", "confirm": True}
        s, r = c.call("POST", "/applications/APP-004/review/actions", pay, token=t[R])
        self.assertEqual(s, 422)
        fid = c.call("GET", "/applications/APP-004/findings", token=t[R])[1]["items"][0]["id"]
        c.call("PATCH", f"/findings/{fid}", {"status": "resolved", "note": "Renewed certificate supplied offline."}, token=t[R])
        s, r = c.call("POST", "/applications/APP-004/review/actions", pay, token=t[R])
        self.assertEqual((s, r["status"]), (200, "approved_demo"))
        s, r = c.call("PATCH", f"/findings/{fid}", {"status": "open"}, token=t[R])
        self.assertEqual(s, 409)                                            # read-only after a final decision

    def test_reject_and_escalate(self):
        c, t = self.c, self.t
        s, r = c.call("POST", "/applications/APP-002/review/actions", {"action": "escalate", "remarks": "x"}, token=t[R])
        self.assertEqual(s, 422)
        s, r = c.call("POST", "/applications/APP-002/review/actions", {"action": "escalate", "remarks": "Needs senior sign-off on missing certificate"}, token=t[R])
        self.assertEqual((s, r["escalated"]), (200, True))
        s, n = c.call("GET", "/notifications", token=t[ADM])
        self.assertTrue(any("escalated" in x["title"] for x in n["items"]))
        s, r = c.call("POST", "/applications/APP-002/review/actions", {"action": "reject_demo", "remarks": "Occupancy certificate not provided", "confirm": True}, token=t[R])
        self.assertEqual((s, r["status"]), (200, "rejected_demo"))
        self.assertEqual(r["status_label"], "Rejected (demonstration only)")

    def test_applicant_can_see_why_corrections_were_requested(self):
        c, t = self.c, self.t
        s, r = c.call("POST", "/applications/APP-002/review/actions", {"action": "request_correction", "remarks": "Upload the occupancy certificate for Block B."}, token=t[R])
        self.assertEqual(s, 200)
        ta = c.login(A)
        s, a = c.call("GET", "/applications/APP-002", token=ta)
        self.assertEqual(a["correction_request"]["remarks"], "Upload the occupancy certificate for Block B.")
        s, other = c.call("GET", "/applications/APP-001", token=ta)
        self.assertIsNone(other["correction_request"])                      # only present while corrections are outstanding

    def test_comment_and_mark_reviewed(self):
        c, t = self.c, self.t
        s, r = c.call("POST", "/applications/APP-003/review/actions", {"action": "comment", "remarks": "Checked the affiliation letter against the file."}, token=t[R])
        self.assertEqual(s, 200)
        s, r = c.call("POST", "/applications/APP-003/review/actions", {"action": "mark_reviewed"}, token=t[R])
        self.assertEqual(r["reviewed"]["by"], R)
        s, h = c.call("GET", "/applications/APP-003/review/history", token=t[R])
        self.assertEqual([x["action"] for x in h["items"]][:2], ["mark_reviewed", "comment"])
        self.assertEqual(c.call("POST", "/applications/APP-003/review/actions", {"action": "nonsense"}, token=t[R])[0], 422)

    def test_admin_can_assign_reviewer(self):
        c, t = self.c, self.t
        s, rv = c.call("GET", "/review/reviewers", token=t[ADM])
        self.assertEqual(len(rv["items"]), 2)
        rid = next(x["id"] for x in rv["items"] if x["email"] == "reviewer2@demo.vcheck")
        s, r = c.call("POST", "/applications/APP-005/review/actions", {"action": "assign", "reviewer_id": rid}, token=t[ADM])
        self.assertEqual((s, r["reviewer"]["name"]), (200, "Sanjay Kulkarni"))
        s, r = c.call("POST", "/applications/APP-005/review/actions", {"action": "assign", "reviewer_id": 99999}, token=t[ADM])
        self.assertEqual(s, 422)
        s, q = c.call("GET", "/review/queue", token=t[R], query="scope=unassigned")
        self.assertNotIn("APP-005", [i["id"] for i in q["items"]])

    def test_filters_search_and_pagination(self):
        c, t = self.c, self.t
        s, r = c.call("GET", "/applications", token=t[R], query="page_size=2&page=2&sort=oldest")
        self.assertEqual((r["total"], len(r["items"]), r["page"]), (6, 2, 2))
        s, r = c.call("GET", "/applications", token=t[R], query="status=validation_complete")
        self.assertEqual([i["id"] for i in r["items"]], ["APP-001"])
        s, r = c.call("GET", "/applications", token=t[R], query="q=Riverbend")
        self.assertEqual([i["id"] for i in r["items"]], ["APP-002"])
        s, r = c.call("GET", "/applications", token=t[R], query="institution=Hillcrest")
        self.assertEqual([i["id"] for i in r["items"]], ["APP-004"])
        s, r = c.call("GET", "/applications", token=t[R], query="severity=medium")
        self.assertEqual([i["id"] for i in r["items"]], ["APP-006"])
        s, r = c.call("GET", "/applications", token=t[R], query="date_from=2999-01-01")
        self.assertEqual(r["total"], 0)
        s, r = c.call("GET", "/applications", token=t[R], query="q=%25%27%3B+DROP+TABLE+users%3B--")       # SQL-injection-shaped input is just text
        self.assertEqual((s, r["total"]), (200, 0))
        s, r = c.call("GET", "/findings", token=t[R], query="severity=high&outcome=failed")
        self.assertEqual(r["total"], 4)
        s, r = c.call("GET", "/documents", token=t[R], query="type=occupancy_certificate")
        self.assertEqual(r["total"], 5)
        s, r = c.call("GET", "/audit", token=t[ADM], query="role=system&page_size=5")
        self.assertEqual(len(r["items"]), 5)

    def test_application_input_validation(self):
        c, t = self.c, self.t[A]
        bad = dict(NEW_APP, institution=dict(NEW_APP["institution"], name=""))
        self.assertEqual(c.call("POST", "/applications", bad, token=t)[0], 422)
        bad = dict(NEW_APP, application_type="made_up")
        self.assertEqual(c.call("POST", "/applications", bad, token=t)[0], 422)
        bad = dict(NEW_APP, institution=dict(NEW_APP["institution"], contact_email="not-an-email"))
        self.assertEqual(c.call("POST", "/applications", bad, token=t)[0], 422)
        bad = dict(NEW_APP, academic_year="twenty")
        self.assertEqual(c.call("POST", "/applications", bad, token=t)[0], 422)
        s, a = c.call("POST", "/applications", dict(NEW_APP, institution=dict(NEW_APP["institution"], name="<script>alert(1)</script> College")), token=t)
        self.assertEqual(s, 201)                                          # stored as inert text; the API is JSON-only
        s, a2 = c.call("PATCH", f"/applications/{a['id']}", {"courses": [{"name": "B.Sc. Physics", "intake": "40"}], "notes": "edit ok"}, token=t)
        self.assertEqual((s, a2["courses"][0]["name"]), (200, "B.Sc. Physics"))


class TestRules(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.c = Client(self.app)
        self.t = {e: self.c.login(e) for e in (R, ADM)}

    def test_rule_catalogue_distinguishes_official_from_demonstration(self):
        s, r = self.c.call("GET", "/rules", token=self.t[R])
        self.assertEqual(len(r["rules"]), 34)
        kinds = {x["kind"] for x in r["rules"]}
        self.assertEqual(kinds, {"demonstration"})                         # nothing is claimed as official without a confirmed source
        self.assertIn("NOT an official AICTE checklist", r["ruleset"]["notice"])
        row = r["rules"][0]
        for k in ("rule_id", "name", "category", "version", "enabled", "effective_date", "source_ref", "source_status", "last_updated"):
            self.assertIn(k, row)

    def test_admin_disable_rule_creates_new_version_and_changes_results(self):
        c, t = self.c, self.t
        s, r = c.call("PATCH", "/rules/DATE-002", {"enabled": False, "note": "Demonstrate rule toggle"}, token=t[ADM])
        self.assertEqual(s, 200)
        self.assertEqual(r["ruleset"]["version"], "1.0.1")
        rule = next(x for x in r["rules"] if x["rule_id"] == "DATE-002")
        self.assertFalse(rule["enabled"])
        self.assertEqual(rule["version"], "1.0.1")
        s, v = c.call("GET", "/rules/versions", token=t[R])
        self.assertEqual([x["version"] for x in v["items"]], ["1.0.1", "1.0.0"])
        self.assertEqual([x["active"] for x in v["items"]], [True, False])
        self.assertEqual(v["items"][0]["created_by"], ADM)
        s, d = c.call("GET", "/rules/DATE-002", token=t[R])
        self.assertEqual(d["history"][0]["version"], "1.0.1")
        # revalidation of the expired application now uses the new version; old findings keep their original rule version
        s, before = c.call("GET", "/applications/APP-004/findings", token=t[R])
        self.assertEqual(before["items"][0]["rule_version"], "1.0.0")
        s, rv = c.call("POST", "/applications/APP-004/validate", token=t[R])
        self.assertEqual(s, 200)
        s, after = c.call("GET", "/applications/APP-004/findings", token=t[R])
        self.assertEqual(after["total"], 0)
        s, pl = c.call("GET", "/applications/APP-004/pipeline", token=t[R])
        self.assertEqual(pl["latest_run"]["ruleset_version"], "1.0.1")
        s, a = c.call("GET", "/audit", token=t[ADM], query="action=rule.version")
        self.assertEqual(a["total"], 1)

    def test_rule_change_validation(self):
        c, t = self.c, self.t[ADM]
        s, r = c.call("POST", "/rules/versions", {"changes": {"DATE-002": {"severity": "catastrophic"}}, "note": "bad severity"}, token=t)
        self.assertEqual((s, r["error"]["code"]), (422, "invalid_rule_change"))
        s, r = c.call("POST", "/rules/versions", {"changes": {"DATE-002": {"source_status": "official_confirmed"}}, "note": "pretend official"}, token=t)
        self.assertEqual(s, 422)                                            # provenance cannot be edited
        s, r = c.call("POST", "/rules/versions", {"changes": {"NOPE": {"enabled": False}}, "note": "unknown"}, token=t)
        self.assertEqual(s, 422)
        s, r = c.call("POST", "/rules/versions", {"changes": {"DATE-002": {"enabled": False}}, "note": "", "new_version": "1.0.0"}, token=t)
        self.assertEqual(s, 422)
        s, r = c.call("POST", "/rules/versions", {"changes": {"DATE-002": {"severity": "medium"}}, "note": "Downgrade for demo", "new_version": "1.1.0"}, token=t)
        self.assertEqual((s, r["new_version"]), (201, "1.1.0"))
        s, v = c.call("GET", "/rules", token=t)
        self.assertEqual(next(x for x in v["rules"] if x["rule_id"] == "DATE-002")["severity"], "medium")
        self.assertEqual(next(x for x in v["rules"] if x["rule_id"] == "DATE-001")["version"], "1.0.0")        # untouched rules keep their version


class TestSettingsAndDemo(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.c = Client(self.app)
        self.t = {e: self.c.login(e) for e in (A, R, ADM)}

    def test_admin_settings_and_verification_mode(self):
        c, t = self.c, self.t
        s, r = c.call("GET", "/settings/admin", token=t[ADM])
        self.assertEqual(r["verification_mode"], "off")
        dl = next(p for p in r["providers"] if p["id"] == "digilocker")
        self.assertFalse(dl["available"])
        self.assertEqual(c.call("PUT", "/settings/admin", {"verification_mode": "digilocker"}, token=t[ADM])[0], 422)      # cannot enable what is not configured
        self.assertEqual(c.call("PUT", "/settings/admin", {"max_upload_mb": 999}, token=t[ADM])[0], 422)
        s, r = c.call("PUT", "/settings/admin", {"verification_mode": "simulation", "max_upload_mb": 5}, token=t[ADM])
        self.assertEqual((s, r["verification_mode"], r["max_upload_mb"]), (200, "simulation", 5))
        # with simulation on, an application whose certificates are not in the synthetic registry gets reviewable, non-forgery findings
        s, rv = c.call("POST", "/applications/APP-003/validate", token=t[R])
        s, f = c.call("GET", "/applications/APP-003/findings", token=t[R])
        ver = [x for x in f["items"] if x["rule_id"] == "VER-001"]
        # The synthetic registry maps the affiliation certificate to the TRUE institution id; the document carries a
        # different one, so the simulated source reports a mismatch -> a review item that explicitly is not a forgery claim.
        self.assertEqual(len(ver), 1)
        self.assertEqual((ver[0]["observed"], ver[0]["outcome"]), ("mismatch", "review_required"))
        self.assertIn("not a finding of forgery", ver[0]["explanation"])
        self.assertIn("SIMULATED", ver[0]["explanation"])
        s, p = c.call("GET", "/applications/APP-003/pipeline", token=t[R])
        self.assertEqual(next(x for x in p["stages"] if x["stage"] == "Source Verification")["status"], "review")
        self.assertTrue(p["verification"] and all(v["simulated"] for v in p["verification"]))

    def test_system_info_and_profile(self):
        c, t = self.c, self.t
        s, i = c.call("GET", "/settings/system", token=t[A])
        self.assertTrue(i["ocr_available"])
        self.assertIn("Not an official AICTE portal", i["affiliation"])
        self.assertNotIn(str(self.app.ctx.settings.storage_dir), json.dumps(i))          # no filesystem paths exposed
        s, p = c.call("PUT", "/settings/profile", {"name": "Arjun M. Menon", "organization": "Test Org"}, token=t[A])
        self.assertEqual((s, p["name"]), (200, "Arjun M. Menon"))
        s, p = c.call("PUT", "/settings/notifications", {"review": False}, token=t[A])
        self.assertFalse(p["notifications"]["review"])
        self.assertEqual(c.call("PUT", "/settings/profile", {"name": ""}, token=t[A])[0], 422)

    def test_meta_is_public_and_carries_disclaimer(self):
        s, m = self.c.call("GET", "/meta")
        self.assertEqual(s, 200)
        self.assertIn("not an official AICTE portal", m["disclaimer"])
        self.assertEqual(m["problem_statement"], "SIH26261")
        self.assertEqual(len(m["pipeline_stages"]), 10)

    def test_demo_documents_requires_demo_mode(self):
        c, t = self.c, self.t
        s, a = c.call("POST", "/applications", NEW_APP, token=t[A])
        c.call("PUT", "/settings/admin", {"demo_mode": False}, token=t[ADM])
        s, r = c.call("POST", f"/applications/{a['id']}/demo-documents", {"scenario": "clean"}, token=t[A])
        self.assertEqual(s, 403)
        c.call("PUT", "/settings/admin", {"demo_mode": True}, token=t[ADM])
        s, r = c.call("POST", f"/applications/{a['id']}/demo-documents", {"scenario": "nope"}, token=t[A])
        self.assertEqual(s, 422)

    def test_duplicate_reuse_scenario_for_new_application(self):
        c, t = self.c, self.t
        s, a = c.call("POST", "/applications", NEW_APP, token=t[A])
        s, r = c.call("POST", f"/applications/{a['id']}/demo-documents", {"scenario": "duplicate_reuse"}, token=t[A])
        self.assertEqual(s, 201)
        s, r = c.call("POST", f"/applications/{a['id']}/submit", token=t[A])
        s, f = c.call("GET", f"/applications/{a['id']}/findings", token=t[R])
        self.assertIn("DUP-002", {x["rule_id"] for x in f["items"]})

    def test_demo_reset_restores_scenarios_and_keeps_user_apps(self):
        c, t = self.c, self.t
        s, mine = c.call("POST", "/applications", NEW_APP, token=t[A])
        c.call("POST", "/applications/APP-004/review/actions", {"action": "comment", "remarks": "temp comment here"}, token=t[R])
        s, r = c.call("POST", "/demo/reset", {}, token=t[ADM])
        self.assertEqual(s, 200)
        s, h = c.call("GET", "/applications/APP-004/review/history", token=t[R])
        self.assertEqual(h["items"], [])
        s, apps = c.call("GET", "/applications", token=t[A])
        self.assertIn(mine["id"], [x["id"] for x in apps["items"]])
        self.assertEqual(apps["total"], 7)
        s, f = c.call("GET", "/applications/APP-003/findings", token=t[R])
        self.assertEqual({x["rule_id"] for x in f["items"]}, {"XD-002"})


class TestPersistence(unittest.TestCase):
    def test_data_survives_restart(self):
        app1 = make_app()
        c1 = Client(app1)
        tr = c1.login(R)
        c1.call("POST", "/applications/APP-002/review/actions", {"action": "comment", "remarks": "persisted comment"}, token=tr)
        c1.call("PATCH", "/findings/VF-1001", {"status": "under_review"}, token=tr)
        storage = app1.ctx.settings.storage_dir
        app1.ctx.executor.shutdown(wait=True)
        # brand-new process-equivalent: new Settings/Context/App pointing at the same storage; seeding must not duplicate
        app2 = create_app(Settings(storage_dir=storage, sync_processing=True, today=TODAY))
        c2 = Client(app2)
        tr2 = c2.login(R)                                                    # same password hashes + same JWT secret file
        s, apps = c2.call("GET", "/applications", token=tr2)
        self.assertEqual(apps["total"], 6)
        s, f = c2.call("GET", "/findings/VF-1001", token=tr2)
        self.assertEqual(f["status"], "under_review")
        s, h = c2.call("GET", "/applications/APP-002/review/history", token=tr2)
        self.assertIn("persisted comment", [x["remarks"] for x in h["items"]])
        self.assertEqual(c2.call("GET", "/auth/me", token=tr)[0], 200)       # tokens issued before restart remain valid
        s, a = c2.call("GET", "/audit", token=c2.login(ADM), query="page_size=200")
        self.assertGreater(a["total"], 40)
        s, docs = c2.call("GET", "/applications/APP-001/documents", token=tr2)
        s, raw = c2.call("GET", f"/documents/{docs['items'][0]['id']}/file", token=tr2)
        self.assertTrue(raw.startswith(b"%PDF"))                             # files persisted too

    def test_db_has_expected_tables_and_no_plaintext_passwords(self):
        app = make_app()
        con = sqlite3.connect(app.ctx.settings.db_path)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("users", "institutions", "applications", "documents", "extracted_fields", "validation_runs", "findings", "rule_sets",
                  "review_actions", "audit_logs", "stage_events", "verification_results"):
            self.assertIn(t, tables)
        dump = " ".join(str(r) for r in con.execute("SELECT * FROM users"))
        for pw in DEMO_PASSWORDS.values():
            self.assertNotIn(pw, dump)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM findings WHERE is_current=1").fetchone()[0], 9)   # 1+1+1+2+4 from the engine


class TestAnalytics(unittest.TestCase):
    def test_analytics_real_and_empty_states(self):
        app = make_app()
        c = Client(app)
        t = c.login(R)
        s, a = c.call("GET", "/analytics", token=t)
        self.assertEqual(s, 200)
        self.assertEqual(a["applications_processed"]["applications"], 6)
        self.assertEqual(a["issue_types"][0]["rule_id"], "VER-001")          # 4 findings: most common issue in the demo data
        self.assertEqual(a["issue_types"][0]["count"], 4)
        self.assertTrue(a["sufficient_data"])
        self.assertEqual([x["cycles"] for x in a["correction_cycles"]], [0])
        self.assertIsNotNone(a["processing_time"]["avg_document_read_ms"])
        empty = Client(make_app(seed_demo=False))
        te = empty.login(R)
        s, a = empty.call("GET", "/analytics", token=te)
        self.assertFalse(a["sufficient_data"])
        self.assertEqual(a["issue_types"], [])
        s, d = empty.call("GET", "/dashboard", token=te)
        self.assertEqual(d["metrics"]["total_applications"], 0)
        self.assertEqual(d["recent_applications"], [])


if __name__ == "__main__":
    unittest.main()
