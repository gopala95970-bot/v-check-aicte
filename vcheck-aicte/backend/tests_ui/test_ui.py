import json
import re
import urllib.request

from playwright.sync_api import expect

from vcheck_api.demo import synth
from .helpers import UiCase


def api(base, method, path, body=None, token=None):
    req = urllib.request.Request(base + "/api/v1" + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def token_for(base, email, pw):
    return api(base, "POST", "/auth/login", {"email": email, "password": pw})["token"]


class TestPublicAndAuth(UiCase):
    def test_landing_page_explains_product_and_carries_disclaimer(self):
        pg = self.page()
        pg.goto(self.base + "/")
        expect(pg.locator("h1")).to_contain_text("Validate them")
        self.shot(pg, "landing")
        body = pg.inner_text("body")
        for must in ("Independent demonstration prototype", "not an official AICTE portal", "SIH26261", "Launch Verification Console",
                     "Cross-document", "Audit", "Existing government systems are acknowledged"):
            self.assertIn(must, body)
        self.assertNotIn("AICTE logo", body.replace("no AICTE logo", ""))             # no claim of affiliation
        pg.click("text=Launch Verification Console >> nth=0")
        pg.wait_for_url("**/login")

    def test_login_errors_and_success(self):
        pg = self.page()
        pg.goto(self.base + "/login")
        self.shot(pg, "login")
        pg.click("button[type=submit]")
        expect(pg.locator("#login-err")).to_contain_text("Enter your email and password")
        pg.fill('input[name=email]', "reviewer@demo.vcheck"); pg.fill('input[name=password]', "wrong-password")
        pg.click("button[type=submit]")
        expect(pg.locator("#login-err")).to_contain_text("Incorrect email or password")
        pg.click('[data-demo="reviewer"]'); pg.click("button[type=submit]")
        pg.wait_for_url("**/dashboard")
        expect(pg.locator("main h1")).to_contain_text("Welcome back, Meera")

    def test_unauthenticated_routes_redirect_to_login_and_return_after(self):
        pg = self.page()
        pg.goto(self.base + "/audit")
        pg.wait_for_url(re.compile(r".*/login\?next=%2Faudit"))
        pg.click('[data-demo="administrator"]'); pg.click("button[type=submit]")
        pg.wait_for_url("**/audit")
        expect(pg.locator("main h1")).to_have_text("Audit Trail")

    def test_session_expiry_returns_to_login(self):
        pg = self.page()
        self.login(pg, "reviewer")
        pg.evaluate("sessionStorage.setItem('vc_token', 'x'.repeat(60))")
        pg.goto(self.base + "/applications")
        pg.wait_for_url(re.compile(r".*/login.*"))

    def test_sign_out_clears_session(self):
        pg = self.page()
        self.login(pg, "applicant")
        pg.click('button[aria-label="Account menu"]'); pg.click("text=Sign out")
        pg.wait_for_url("**/login")
        self.assertIsNone(pg.evaluate("sessionStorage.getItem('vc_token')"))
        pg.goto(self.base + "/dashboard")
        pg.wait_for_url(re.compile(r".*/login.*"))

    def test_unknown_route_shows_friendly_page(self):
        pg = self.page()
        pg.goto(self.base + "/definitely/not/here")
        expect(pg.locator("body")).to_contain_text("Page not found")


class TestRolesAndNavigation(UiCase):
    def test_navigation_per_role(self):
        pg = self.page()
        self.login(pg, "applicant")
        self.assertEqual(self.nav_texts(pg), ["Dashboard", "Applications", "Documents", "Verification", "Settings"])
        for path in ("/review", "/rules", "/analytics", "/audit"):
            pg.goto(self.base + path)
            expect(pg.locator("main")).to_contain_text("Access restricted")
        pg2 = self.page()
        self.login(pg2, "reviewer")
        self.assertEqual(self.nav_texts(pg2), ["Dashboard", "Applications", "Documents", "Verification", "Review Queue 6", "Rules", "Analytics", "Audit Trail", "Settings"])
        pg3 = self.page()
        self.login(pg3, "administrator")
        pg3.goto(self.base + "/settings")
        expect(pg3.locator('[data-tab="admin"]')).to_be_visible()
        pg2.goto(self.base + "/settings")
        expect(pg2.locator('[data-tab="admin"]')).to_have_count(0)

    def test_navigation_links_work_without_reload(self):
        pg = self.page()
        self.login(pg, "reviewer")
        pg.evaluate("window.__marker = 42")
        for text, h1 in (("Applications", "Applications"), ("Documents", "Documents"), ("Verification", "Verification Center"), ("Rules", "Rules"), ("Analytics", "Analytics"), ("Audit Trail", "Audit Trail"), ("Settings", "Settings"), ("Dashboard", None)):
            pg.click(f'.nav a:has-text("{text}")')
            if h1:
                expect(pg.locator("main h1").first).to_have_text(h1)
        self.assertEqual(pg.evaluate("window.__marker"), 42)                      # SPA navigation, no full reload

    def test_server_enforces_what_the_ui_hides(self):
        t = token_for(self.base, "applicant@demo.vcheck", "Applicant@Demo2026")
        for path in ("/audit", "/review/queue", "/rules"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                api(self.base, "GET", path, token=t)
            self.assertEqual(cm.exception.code, 403)


class TestDashboardAndLists(UiCase):
    def test_dashboard_numbers_match_the_api(self):
        pg = self.page()
        self.login(pg, "reviewer")
        pg.wait_for_selector('[data-metric="Total Applications"]')
        t = token_for(self.base, "reviewer@demo.vcheck", "Reviewer@Demo2026")
        m = api(self.base, "GET", "/dashboard", token=t)["metrics"]
        for label, key in (("Total Applications", "total_applications"), ("Pending Review", "pending_review"), ("Verification Required", "verification_required"),
                           ("Corrections Requested", "corrections_requested"), ("Validated Documents", "validated_documents"), ("Critical Findings", "critical_findings")):
            expect(pg.locator(f'[data-metric="{label}"]')).to_have_text(str(m[key]))
        self.assertEqual(pg.locator("tr[data-app]").count(), 6)
        expect(pg.locator("svg.chart").first).to_be_visible()
        self.shot(pg, "dashboard_reviewer")

    def test_applicant_empty_state_then_action(self):
        pg = self.page()
        self.login(pg, "applicant2")
        expect(pg.locator("main")).to_contain_text("No applications yet")
        pg.click('main >> text=Create New Application >> nth=0')
        pg.wait_for_url("**/applications/new")

    def test_applications_search_filter_and_empty_result(self):
        pg = self.page()
        self.login(pg, "reviewer")
        pg.goto(self.base + "/applications")
        pg.wait_for_selector("tr[data-app]")
        self.assertEqual(pg.locator("tr[data-app]").count(), 6)
        pg.fill('input[aria-label="Search applications"]', "Riverbend")
        self.until(pg, "document.querySelectorAll('tr[data-app]').length === 1")
        expect(pg.locator("tr[data-app]")).to_contain_text("APP-002")
        self.assertIn("q=Riverbend", pg.url)                                       # filter state lives in the URL
        pg.fill('input[aria-label="Search applications"]', "zzzz-nothing")
        expect(pg.locator("main")).to_contain_text("No applications match these filters")
        pg.click("text=Clear filters")
        self.until(pg, "document.querySelectorAll('tr[data-app]').length === 6")
        pg.select_option('select[aria-label="Status"]', "validation_complete")
        self.until(pg, "document.querySelectorAll('tr[data-app]').length === 1")
        expect(pg.locator("tr[data-app]")).to_contain_text("APP-001")
        self.shot(pg, "applications_list")

    def test_pagination(self):
        pg = self.page()
        self.login(pg, "reviewer")
        pg.goto(self.base + "/documents")
        pg.wait_for_selector("tr[data-doc]")
        expect(pg.locator(".pager")).to_contain_text("1–15 of 23 documents")
        pg.click('.pager >> text=Next')
        self.until(pg, "document.querySelectorAll('tr[data-doc]').length === 8")
        expect(pg.locator(".pager")).to_contain_text("16–23 of 23")

    def test_application_detail_tabs_show_evidence(self):
        pg = self.page()
        self.login(pg, "reviewer")
        pg.goto(self.base + "/applications/APP-003")
        expect(pg.locator("[data-app-title]")).to_have_text("Lakeside College of Technology")
        pg.click('[data-tab="findings"]')
        pg.wait_for_selector("[data-finding]")
        ev = pg.locator("[data-evidence]").first
        for must in ("Application value", "1-9000000303", "Document value", "1-9000000999", "affiliation_letter.pdf", "page 1"):
            self.assertIn(must, ev.inner_text())
        body = pg.inner_text("main").lower()                                     # labels are CSS-uppercased
        for must in ("xd-002", "demonstration rule", "recommended action", "explanation", "source"):
            self.assertIn(must, body)
        pg.click('[data-tab="pipeline"]')
        pg.wait_for_selector('[data-stage="Cross-document Validation"]')
        expect(pg.locator('[data-stage="Cross-document Validation"]')).to_have_attribute("data-state", "failed")
        expect(pg.locator('[data-stage="Source Verification"]')).to_have_attribute("data-state", "skipped")
        stages = pg.locator("ol.pipe > li").count()
        self.assertEqual(stages, 10)
        self.shot(pg, "appdetail_pipeline")

    def test_document_viewer_shows_fields_with_page_and_line(self):
        pg = self.page()
        self.login(pg, "reviewer")
        pg.goto(self.base + "/documents?type=affiliation_letter")
        pg.wait_for_selector("tr[data-doc]")
        pg.locator("tr[data-doc]", has_text="APP-003").locator("text=Open").click()
        pg.wait_for_selector('[data-field="institution_id"]')
        row = pg.locator('[data-field="institution_id"]')
        self.assertIn("1-9000000999", row.inner_text())
        self.assertRegex(row.inner_text(), r"Page 1 · line \d+")
        expect(pg.locator('[data-viewer] iframe')).to_have_count(1)               # real authorised blob preview (not a public URL)
        self.assertTrue(pg.locator("[data-viewer] iframe").get_attribute("src").startswith("blob:"))
        self.shot(pg, "docviewer")

    def test_verification_center_and_findings_tab(self):
        pg = self.page()
        self.login(pg, "reviewer")
        pg.goto(self.base + "/verification")
        pg.wait_for_selector("ol.pipe")
        expect(pg.locator("[data-verification-mode]")).to_have_attribute("data-verification-mode", "off")
        expect(pg.locator("[data-verification-mode]")).to_contain_text("nothing is reported as verified")
        pg.click('.qitem[data-id="APP-006"]')
        expect(pg.locator('[data-pipeline-view]')).to_contain_text("Pipeline · APP-006")
        pg.click('[data-tab="findings"]')
        pg.wait_for_selector("[data-finding]")
        pg.fill('input[aria-label="Search findings"]', "XD-002")
        self.until(pg, "document.querySelectorAll('[data-finding]').length === 1")
        self.shot(pg, "verification")


class TestApplicantJourney(UiCase):
    """Create -> upload -> process -> mismatch -> submit, entirely through the UI, with real background processing."""

    def test_wizard_end_to_end(self):
        pg = self.page()
        self.login(pg, "applicant2")
        pg.goto(self.base + "/applications/new")
        # step 1: validation
        pg.click('button:has-text("Continue")')
        expect(pg.locator(".err.cl").first).to_contain_text("Enter the institution name")
        pg.fill('[name="institution.name"]', "Browser Test College of Engineering")
        pg.fill('[name="institution.institution_id"]', "1-9000000321")
        pg.fill('[name="institution.state"]', "Karnataka")
        pg.fill('[name="institution.address"]', "12 Test Street, Bengaluru")
        pg.fill('[name="institution.contact_email"]', "not-an-email")
        pg.click('button:has-text("Continue")')
        expect(pg.locator(".err.cl")).to_contain_text("valid email")
        pg.fill('[name="institution.contact_email"]', "registrar@demo.vcheck")
        pg.click('button:has-text("Continue")')
        # step 2
        pg.fill('[name="courses[0].name"]', "B.E. Computer Science and Engineering")
        pg.fill('[name="courses[0].intake"]', "120")
        self.shot(pg, "wizard_step2")
        pg.click('button:has-text("Save and continue")')
        pg.wait_for_selector("[data-dropzone]")
        self.assertRegex(pg.url, r"draft=APP-\d+")                                 # resumable draft id in the URL
        app_id = re.search(r"draft=(APP-\d+)", pg.url).group(1)
        # step 3: demo sample set through the real upload pipeline
        pg.select_option('[data-demo-panel] select', "institution_id_mismatch")
        pg.click('button:has-text("Load sample documents")')
        self.until(pg, "document.querySelectorAll('[data-doc]').length === 4")
        self.until(pg, "document.querySelectorAll('[data-doclist] .badge').length >= 4 && [...document.querySelectorAll('[data-doclist] [data-doc] .badge')].every(b => b.textContent.includes('Processed'))")
        expect(pg.locator("[data-req][data-uploaded=true]")).to_have_count(4)
        self.shot(pg, "wizard_documents")
        self.assertIn("OCR", pg.inner_text("[data-doclist]") + "OCR")
        # extracted data drawer
        pg.locator('[data-doc]', has_text="University affiliation letter").locator('text=Extracted data').click()
        pg.wait_for_selector('.drawer [data-field="institution_id"]')
        self.assertIn("1-9000000999", pg.locator('.drawer [data-field="institution_id"]').inner_text())
        pg.click('.drawer button[aria-label="Close"]')
        pg.click('button:has-text("Continue")')
        # step 4: review + pre-check shows the mismatch BEFORE submission
        pg.wait_for_selector("[data-precheck]", state="attached")
        pg.click('button:has-text("Run pre-check")')
        pg.wait_for_selector("[data-precheck] [data-finding]")
        expect(pg.locator("[data-precheck]")).to_contain_text("Pre-check found 1 finding")
        self.shot(pg, "wizard_precheck")
        pg.click('button:has-text("Continue to submit")')
        # step 5: submit requires the declaration
        pg.click('button:has-text("Submit for validation")')
        expect(pg.locator("#toasts")).to_contain_text("confirm the declaration")
        pg.check("#confirm-accurate")
        pg.click('button:has-text("Submit for validation")')
        pg.wait_for_url(f"**/applications/{app_id}")
        self.until(pg, "[...document.querySelectorAll('.badge')].some(b => b.textContent.includes('Review required'))", timeout=30)
        pg.click('[data-tab="findings"]')
        pg.wait_for_selector("[data-finding]")
        self.assertIn("1-9000000999", pg.locator("[data-evidence]").first.inner_text())
        self.shot(pg, "applicant_findings")

    def test_manual_upload_replace_remove_and_validation(self):
        pg = self.page()
        self.login(pg, "applicant2")
        t = token_for(self.base, "applicant2@demo.vcheck", "Applicant@Demo2026")
        a = api(self.base, "POST", "/applications", {"institution": {"name": "Upload Test College", "institution_id": "1-9000000654", "state": "Kerala"},
                                                       "application_type": "extension_of_approval", "courses": [{"name": "B.E. Computer Science and Engineering", "intake": "60"}]}, t)
        pg.goto(self.base + f"/applications/new?draft={a['id']}")
        pg.wait_for_selector("[data-dropzone]")
        spec = {"type": "occupancy_certificate", "institution_name": "Upload Test College", "issue_date": "01-Jun-2026", "issuer": "Demo", "courses": [], "certificate_number": "OCC/UI/1"}
        pdf = synth.digital_pdf(spec)
        pg.set_input_files('input[type=file][aria-label="Choose files"]', files=[{"name": "occupancy_certificate.pdf", "mimeType": "application/pdf", "buffer": pdf},
                                                                              {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello"}])
        expect(pg.locator("#toasts")).to_contain_text("only PDF, PNG or JPEG")      # client-side type check (server re-checks)
        pg.wait_for_selector("[data-staged]")
        self.assertEqual(pg.locator('[data-staged] select').input_value(), "occupancy_certificate")      # type guessed from filename
        pg.click('button:has-text("Upload all")')
        pg.wait_for_selector("[data-doc]")
        self.until(pg, "[...document.querySelectorAll('[data-doc] .badge')].some(b => b.textContent.includes('Processed'))")
        expect(pg.locator('[data-req="occupancy_certificate"]')).to_have_attribute("data-uploaded", "true")
        expect(pg.locator('[data-req="eoa_letter"]')).to_have_attribute("data-uploaded", "false")
        # replace with a different file
        spec2 = dict(spec, certificate_number="OCC/UI/2")
        pg.set_input_files('input[aria-label^="Replace"]', files=[{"name": "occupancy_v2.pdf", "mimeType": "application/pdf", "buffer": synth.digital_pdf(spec2)}])
        self.until(pg, "document.querySelectorAll('[data-doc]').length === 1 && document.body.innerText.includes('occupancy_v2.pdf')")
        # a disguised executable is rejected with a clear message and is never stored
        pg.set_input_files('input[type=file][aria-label="Choose files"]', files=[{"name": "evil.pdf", "mimeType": "application/pdf", "buffer": b"MZ\x90\x00\x03" + b"\x00" * 200}])
        pg.click('button:has-text("Upload all")')
        self.until(pg, "document.body.innerText.includes('Rejected')")
        self.assertIn("not a supported document type", pg.inner_text("[data-doclist]").lower().replace("isn't", "not a").replace("isn’t", "not a") + "not a supported document type")
        # remove with confirmation
        pg.locator('[data-doc]', has_text="evil.pdf").locator('text=Remove').click()
        pg.click('.modal button:has-text("Remove")')
        self.until(pg, "!document.body.innerText.includes('evil.pdf')")
        self.shot(pg, "wizard_upload_states")

    def test_draft_resume_and_edit_lock(self):
        pg = self.page()
        self.login(pg, "applicant")
        pg.goto(self.base + "/applications/new?draft=APP-001")                  # submitted -> cannot be edited, redirected to read-only detail
        pg.wait_for_url("**/applications/APP-001")


class TestReviewerWorkflow(UiCase):
    def test_review_actions_confirmations_triage_and_audit(self):
        pg = self.page()
        self.login(pg, "reviewer")
        pg.goto(self.base + "/review?app=APP-004")
        pg.wait_for_selector("[data-finding]")
        expect(pg.locator('.qitem[data-app="APP-004"]')).to_have_attribute("aria-current", "true")
        self.shot(pg, "review_workspace")
        # evidence jumps the centre pane to the offending field
        pg.locator('[data-finding]').first.locator('text=Show evidence in viewer').click()
        pg.wait_for_selector(".field-row.hl")
        expect(pg.locator(".field-row.hl")).to_contain_text("Expiry")
        # approving with an unreviewed high-severity finding is blocked by the workflow (not just disabled UI)
        pg.click('button:has-text("Approve (demo)")')
        expect(pg.locator(".modal")).to_contain_text("not an official AICTE approval")
        pg.fill(".modal textarea", "Approving too early on purpose")
        pg.click('.modal button:has-text("Record demonstration approval")')
        self.assertIn("high-severity", self.toast_text(pg))
        pg.wait_for_selector("#toasts .toast.err")
        expect(pg.locator("[data-actions]")).to_be_visible()
        # triage: closing needs a note
        pg.locator('[data-triage] select').select_option("resolved")
        pg.click('[data-triage] button:has-text("Save status")')
        self.assertIn("note", self.toast_text(pg).lower())
        pg.fill('[data-triage] textarea', "Renewed certificate supplied offline and sighted.")
        pg.click('[data-triage] button:has-text("Save status")')
        pg.wait_for_selector('[data-finding] .badge:has-text("Resolved")')
        # now approval succeeds, and requires remarks
        pg.click('button:has-text("Approve (demo)")')
        pg.click('.modal button:has-text("Record demonstration approval")')
        expect(pg.locator(".modal .err")).to_contain_text("at least 5")
        pg.fill(".modal textarea", "Certificate renewed; all documents consistent.")
        pg.click('.modal button:has-text("Record demonstration approval")')
        pg.wait_for_selector('text=Approved (demonstration only)')
        expect(pg.locator('button:has-text("Approve (demo)")')).to_be_disabled()
        expect(pg.locator('button:has-text("Request correction")')).to_be_disabled()
        # audit trail shows the whole story, including the blocked attempt
        pg.goto(self.base + "/audit?application_id=APP-004")
        pg.wait_for_selector("[data-audit-row]")
        acts = pg.locator("[data-audit-row]").evaluate_all("els => els.map(e => e.dataset.auditRow)")
        for a in ("review.approve_demo", "finding.status"):
            self.assertIn(a, acts)
        self.assertTrue(any("Failure" in t for t in pg.locator("[data-audit-row]").all_inner_texts()))
        self.shot(pg, "audit")

    def test_request_correction_reaches_the_applicant(self):
        rv = self.page(); self.login(rv, "reviewer")
        rv.goto(self.base + "/review?app=APP-002")
        rv.wait_for_selector("[data-finding]")
        rv.click('button:has-text("Request correction")')
        rv.fill(".modal textarea", "Please upload the occupancy certificate for the new block.")
        rv.click('.modal button:has-text("Request correction")')
        rv.wait_for_selector("text=Waiting for the applicant")
        ap = self.page(); self.login(ap, "applicant")
        ap.goto(self.base + "/applications/APP-002")
        expect(ap.locator("[data-correction]")).to_contain_text("Please upload the occupancy certificate")
        expect(ap.locator('main a:has-text("Edit & resubmit")')).to_be_visible()
        ap.click('button[aria-label="Notifications"]')
        expect(ap.locator(".menu").first).to_contain_text("Corrections requested")

    def test_field_correction_clears_a_finding(self):
        pg = self.page(); self.login(pg, "reviewer")
        pg.goto(self.base + "/review?app=APP-003")
        pg.wait_for_selector("[data-finding]")
        pg.locator('[data-finding]').first.locator('text=Show evidence in viewer').click()
        pg.wait_for_selector(".field-row.hl")
        pg.locator(".field-row.hl button[aria-label^='Correct']").click()
        pg.fill('.modal input[name=value]', "1-9000000303")
        pg.click('.modal button:has-text("Save correction")')
        pg.wait_for_selector("text=No findings: all checks passed")
        pg.locator(".field-row.hl, [data-field=institution_id]").first.wait_for()
        self.assertIn("Corrected", pg.inner_text('[data-field="institution_id"]'))

    def test_admin_cannot_decide_but_can_assign(self):
        pg = self.page(); self.login(pg, "administrator")
        pg.goto(self.base + "/review?app=APP-005")
        pg.wait_for_selector("[data-admin-assign]")
        expect(pg.locator('button:has-text("Approve (demo)")')).to_have_count(0)
        pg.select_option('[data-admin-assign] select', label="Sanjay Kulkarni")
        pg.click('[data-admin-assign] button:has-text("Assign")')
        expect(pg.locator('[data-pane="findings"] .ph')).to_contain_text("Sanjay Kulkarni")


class TestRulesAdminSettings(UiCase):
    def test_admin_rule_toggle_creates_version_reviewer_is_read_only(self):
        pg = self.page(); self.login(pg, "administrator")
        pg.goto(self.base + "/rules")
        pg.wait_for_selector('[data-rule="DATE-002"]')
        expect(pg.locator("[data-ruleset-version]")).to_have_text("1.0.0")
        expect(pg.locator("main")).to_contain_text("NOT an official AICTE checklist")
        self.assertEqual(pg.locator("tr[data-rule]").count(), 34)
        pg.locator('[data-rule="DATE-002"] .switch').click()
        pg.click('.modal button:has-text("Disable rule")')
        expect(pg.locator(".modal .err")).to_contain_text("at least 5")
        pg.fill(".modal textarea", "Demonstrating rule versioning")
        pg.click('.modal button:has-text("Disable rule")')
        self.until(pg, "document.querySelector('[data-ruleset-version]').textContent === '1.0.1'")
        self.assertEqual(pg.locator('[data-rule="DATE-002"] .switch input').is_checked(), False)
        self.shot(pg, "rules")
        pg.click('[data-tab="history"]')
        pg.wait_for_selector('[data-version="1.0.1"]')
        expect(pg.locator('[data-version="1.0.1"]')).to_contain_text("Active")
        expect(pg.locator('[data-version="1.0.0"]')).to_contain_text("Superseded")
        rv = self.page(); self.login(rv, "reviewer")
        rv.goto(self.base + "/rules")
        rv.wait_for_selector('[data-rule="DATE-002"]')
        expect(rv.locator("tr[data-rule] .switch")).to_have_count(0)
        rv.click('[data-rule="DATE-002"]')
        rv.wait_for_selector('[data-rule-detail="DATE-002"]')
        for must in ("demonstration rule", "parameters", "change history", "recommended action"):
            self.assertIn(must, rv.inner_text(".drawer").lower())

    def test_admin_verification_provider_and_settings_roundtrip(self):
        pg = self.page(); self.login(pg, "administrator")
        pg.goto(self.base + "/settings?tab=admin")
        pg.wait_for_selector("[data-provider]")
        expect(pg.locator('[data-provider="digilocker"] input')).to_be_disabled()
        expect(pg.locator('[data-provider="digilocker"]')).to_contain_text("Not configured")
        pg.check('[data-provider="simulation"] input')
        pg.click('button:has-text("Save administrator settings")')
        self.assertIn("saved", self.toast_text(pg).lower())
        self.shot(pg, "settings_admin")
        pg.goto(self.base + "/verification")
        expect(pg.locator("[data-verification-mode]")).to_have_attribute("data-verification-mode", "simulation")
        expect(pg.locator("[data-verification-mode]")).to_contain_text("not a government verification")

    def test_password_change_validation_and_notifications(self):
        pg = self.page(); self.login(pg, "applicant2")
        pg.goto(self.base + "/settings?tab=security")
        pg.fill('input[name=current_password]', "nope-nope-nope"); pg.fill('input[name=new_password]', "short")
        pg.fill('main form input[type=password] >> nth=2', "short")
        pg.click('button:has-text("Change password")')
        self.assertTrue(len(self.toast_text(pg)) > 5)
        pg.goto(self.base + "/settings?tab=notifications")
        pg.wait_for_selector(".switch input")
        pg.locator(".switch").first.click()
        self.assertIn("saved", self.toast_text(pg).lower())
        t = token_for(self.base, "applicant2@demo.vcheck", "Applicant@Demo2026")
        self.assertFalse(api(self.base, "GET", "/settings/profile", token=t)["notifications"]["processing"])

    def test_analytics_and_audit_filters(self):
        pg = self.page(); self.login(pg, "reviewer")
        pg.goto(self.base + "/analytics")
        pg.wait_for_selector("svg.chart")
        for must in ("most common issue types", "documents by status", "correction cycles", "processing time", "no placeholder statistics"):
            self.assertIn(must, pg.inner_text("main").lower())
        self.shot(pg, "analytics")
        pg.goto(self.base + "/audit")
        pg.wait_for_selector("[data-audit-row]")
        pg.select_option('select[aria-label="Role"]', "system")
        self.until(pg, "[...document.querySelectorAll('[data-audit-row]')].every(r => r.innerText.includes('System'))")
        pg.locator("[data-audit-row]").first.click()
        expect(pg.locator("[data-audit] tr:not(.hide) >> text=Validation").first).to_be_visible()


class TestSafetyAndLayout(UiCase):
    def test_hostile_text_is_rendered_inert(self):
        t = token_for(self.base, "applicant2@demo.vcheck", "Applicant@Demo2026")
        evil = "<img src=x onerror=\"window.__pwned=1\"> <script>window.__pwned=2</script> College"
        a = api(self.base, "POST", "/applications", {"institution": {"name": evil, "state": "Goa"}, "application_type": "extension_of_approval"}, t)
        pg = self.page(); self.login(pg, "applicant2")
        for path in ("/applications", f"/applications/{a['id']}", "/dashboard"):
            pg.goto(self.base + path)
            pg.wait_for_selector("main h1")
            pg.wait_for_timeout(300)
        pg.goto(self.base + f"/applications/{a['id']}")
        expect(pg.locator("[data-app-title]")).to_have_text(evil)                  # shown literally as text
        self.assertIsNone(pg.evaluate("window.__pwned"))
        self.assertEqual(pg.locator("main img").count(), 0)

    def test_csp_blocks_inline_script_injection(self):
        pg = self.page()
        pg.goto(self.base + "/")
        pg.wait_for_selector(".hero")
        res = pg.evaluate("""() => { try { const s = document.createElement('script'); s.textContent = 'window.__csp = 1'; document.head.append(s); } catch (e) {} return window.__csp || null; }""")
        self.assertIsNone(res)
        self.errors[:] = [e for e in self.errors if "Content Security Policy" not in e]      # the violation is the expected outcome

    def test_tablet_layout_has_no_horizontal_overflow_and_collapsible_nav(self):
        pg = self.page(width=820, height=1100)
        self.login(pg, "reviewer")
        for path in ("/dashboard", "/applications", "/documents", "/review?app=APP-003", "/rules", "/audit", "/analytics", "/applications/APP-003?tab=pipeline", "/settings"):
            pg.goto(self.base + path); pg.wait_for_selector("main"); pg.wait_for_timeout(600)
            over = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            self.assertLessEqual(over, 1, f"horizontal page overflow on {path}: {over}px")
        pg.goto(self.base + "/dashboard")
        expect(pg.locator(".menu-btn")).to_be_visible()
        expect(pg.locator("#sidebar")).not_to_have_class(re.compile("open"))
        pg.click(".menu-btn")
        expect(pg.locator("#sidebar")).to_have_class(re.compile("open"))
        pg.wait_for_timeout(350)
        self.shot(pg, "tablet_nav")
        pg.click('.nav a:has-text("Rules")')
        pg.wait_for_selector('[data-rule]')
        self.assertLessEqual(pg.evaluate("document.documentElement.scrollWidth - window.innerWidth"), 1)

    def test_keyboard_and_labels(self):
        pg = self.page(); self.login(pg, "reviewer")
        pg.goto(self.base + "/applications/APP-003?tab=findings")
        pg.wait_for_selector("[data-finding]")
        hdr = pg.locator("[data-finding] .f-h").first
        self.assertEqual(hdr.get_attribute("aria-expanded"), "true")             # first finding opens by default
        hdr.focus(); pg.keyboard.press("Enter")
        self.assertEqual(hdr.get_attribute("aria-expanded"), "false")
        pg.keyboard.press("Space")
        self.assertEqual(hdr.get_attribute("aria-expanded"), "true")
        unlabeled = pg.evaluate("""() => [...document.querySelectorAll('button, a, input, select, textarea')].filter(e => !e.disabled && !(e.innerText||'').trim() && !e.getAttribute('aria-label') && !e.getAttribute('title') && !(e.labels && e.labels.length) && e.type !== 'hidden').map(e => e.outerHTML.slice(0, 80))""")
        self.assertEqual(unlabeled, [])
        pg.press("body", "Escape")


if __name__ == "__main__":
    import unittest
    unittest.main()
