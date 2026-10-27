import unittest

from tests.helpers import make_app, rule_ids, specs, validate
from vcheck import workflow as wf
from vcheck.audit import AuditLog, redact
from vcheck.models import Finding

ROLES = ("applicant", "reviewer", "admin", "system")


def finding(reviewer_only=False, severity="high"):
    return Finding("R", "1.0.0", "t", "failed", severity, "A", "e", "r", reviewer_only=reviewer_only)


class Transitions(unittest.TestCase):
    def test_happy_path(self):
        s = wf.transition("draft", "submitted", "applicant")
        s = wf.transition(s, "processing", "system")
        s = wf.transition(s, "review_required", "system")
        s = wf.transition(s, "corrections_requested", "reviewer", remarks="Please fix the ID")
        s = wf.transition(s, "resubmitted", "applicant")
        s = wf.transition(s, "processing", "system")
        s = wf.transition(s, "validation_complete", "system")
        self.assertEqual(wf.transition(s, "approved_demo", "reviewer", confirm=True, remarks="All checks reviewed"), "approved_demo")

    def test_every_status_in_the_spec_exists(self):
        self.assertEqual(set(wf.STATUSES), {"draft", "submitted", "processing", "validation_complete", "review_required",
                                            "corrections_requested", "resubmitted", "approved_demo", "rejected_demo"})

    def test_illegal_jumps_rejected(self):
        for cur, tgt in [("draft", "approved_demo"), ("draft", "processing"), ("submitted", "approved_demo"),
                         ("review_required", "draft"), ("corrections_requested", "approved_demo")]:
            with self.subTest(cur=cur, tgt=tgt):
                for role in ROLES:
                    with self.assertRaises(wf.WorkflowError):
                        wf.transition(cur, tgt, role, confirm=True, remarks="long enough remarks")

    def test_final_states_are_final(self):
        for end in ("approved_demo", "rejected_demo"):
            for tgt in wf.STATUSES:
                with self.assertRaises(wf.InvalidTransition):
                    wf.transition(end, tgt, "reviewer", confirm=True, remarks="long enough remarks")

    def test_decisions_need_confirmation_and_remarks(self):
        with self.assertRaises(wf.ConfirmationRequired):
            wf.transition("review_required", "rejected_demo", "reviewer", remarks="Not acceptable")
        with self.assertRaises(wf.WorkflowError):
            wf.transition("review_required", "rejected_demo", "reviewer", confirm=True, remarks="")
        with self.assertRaises(wf.WorkflowError):
            wf.transition("review_required", "corrections_requested", "reviewer", remarks="  ")

    def test_cannot_approve_with_unreviewed_high_findings(self):
        with self.assertRaises(wf.WorkflowError):
            wf.transition("review_required", "approved_demo", "reviewer", confirm=True, remarks="Looks fine", unreviewed_high_findings=2)
        self.assertEqual(wf.transition("review_required", "rejected_demo", "reviewer", confirm=True, remarks="Documents expired", unreviewed_high_findings=2), "rejected_demo")

    def test_allowed_targets_by_role(self):
        self.assertEqual(wf.allowed_targets("draft", "applicant"), ["submitted"])
        self.assertEqual(wf.allowed_targets("draft", "reviewer"), [])
        self.assertEqual(set(wf.allowed_targets("review_required", "reviewer")), {"corrections_requested", "approved_demo", "rejected_demo"})
        self.assertEqual(wf.allowed_targets("review_required", "applicant"), [])


class AccessControl(unittest.TestCase):
    def test_only_reviewers_decide(self):
        for role in ("applicant", "admin", "system"):
            with self.subTest(role=role):
                with self.assertRaises(wf.PermissionDenied):
                    wf.transition("review_required", "approved_demo", role, confirm=True, remarks="trying anyway")
                self.assertFalse(wf.can(role, "review.decide"))
        self.assertTrue(wf.can("reviewer", "review.decide"))

    def test_applicants_cannot_submit_on_behalf_of_system_or_reviewers(self):
        with self.assertRaises(wf.PermissionDenied):
            wf.transition("submitted", "processing", "applicant")
        with self.assertRaises(wf.PermissionDenied):
            wf.transition("corrections_requested", "resubmitted", "reviewer")

    def test_only_admin_manages_rules_and_users(self):
        for action in ("rules.manage", "users.manage"):
            self.assertTrue(wf.can("admin", action))
            for role in ("applicant", "reviewer", "system"):
                self.assertFalse(wf.can(role, action), (role, action))
        with self.assertRaises(wf.PermissionDenied):
            wf.require("reviewer", "rules.manage")

    def test_unknown_role_has_no_permissions(self):
        self.assertFalse(wf.can("hacker", "application.view_all"))
        with self.assertRaises(wf.PermissionDenied):
            wf.require("", "application.create")

    def test_applicants_never_see_findings_about_other_institutions(self):
        fs = [finding(False), finding(True), finding(False)]
        self.assertEqual(len(wf.visible_findings("applicant", fs)), 2)
        self.assertTrue(all(not f.reviewer_only for f in wf.visible_findings("applicant", fs)))
        self.assertEqual(len(wf.visible_findings("reviewer", fs)), 3)
        self.assertEqual(wf.visible_findings("nobody", fs), [])


class Audit(unittest.TestCase):
    def test_records_actor_action_object_timestamp_and_transition(self):
        log = AuditLog()
        ev = log.record("rev1", "reviewer", "status_change", "application", "APP-1", "Requested corrections",
                        from_status="review_required", to_status="corrections_requested")
        self.assertEqual((ev.actor, ev.action, ev.object_type, ev.object_id), ("rev1", "status_change", "application", "APP-1"))
        self.assertEqual((ev.from_status, ev.to_status), ("review_required", "corrections_requested"))
        self.assertTrue(ev.timestamp and ev.event_id)

    def test_sensitive_details_are_redacted(self):
        d = redact({"password": "hunter2", "access_token": "abc", "Authorization": "Bearer x", "api_key": "k",
                    "document_text": "full text of a certificate", "file_bytes": b"...", "accessToken": "t", "apiKey": "k2",
                    "filename": "a.pdf", "status": "ok"})
        self.assertEqual([k for k, v in d.items() if v != "[redacted]"], ["filename", "status"])
        log = AuditLog()
        ev = log.record("u", "applicant", "login", "user", "u1", "login", details={"password": "hunter2"})
        self.assertNotIn("hunter2", str(ev))

    def test_description_length_is_bounded(self):
        ev = AuditLog().record("u", "applicant", "x", "y", "z", "A" * 5000)
        self.assertLessEqual(len(ev.description), 300)

    def test_access_restricted_to_authorised_roles(self):
        log = AuditLog(); log.record("u", "applicant", "upload", "document", "D1", "Uploaded a document")
        for role in ("applicant", "system", "nobody"):
            with self.assertRaises(wf.PermissionDenied):
                log.search(role)
        self.assertEqual(len(log.search("reviewer")), 1)
        self.assertEqual(len(log.search("admin")), 1)

    def test_search_filters_and_newest_first(self):
        log = AuditLog()
        log.record("a1", "applicant", "application_created", "application", "APP-1", "Created application")
        log.record("a1", "applicant", "document_uploaded", "document", "D1", "Uploaded occupancy certificate")
        log.record("r1", "reviewer", "finding_reviewed", "finding", "F1", "Marked finding reviewed")
        self.assertEqual([e.object_id for e in log.search("admin")], ["F1", "D1", "APP-1"])
        self.assertEqual(len(log.search("admin", actor="a1")), 2)
        self.assertEqual(len(log.search("admin", action="finding_reviewed")), 1)
        self.assertEqual(len(log.search("admin", object_type="document")), 1)
        self.assertEqual(len(log.search("admin", text="OCCUPANCY")), 1)


if __name__ == "__main__":
    unittest.main()
