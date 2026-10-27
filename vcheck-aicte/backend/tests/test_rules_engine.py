import unittest

from tests.helpers import RULESET, GF, RB, dataset, doc_from, docs_for, make_app, rule_ids, specs, validate
from vcheck.engine import CHECKS
from vcheck.models import CourseRow
from vcheck.rules import RuleSetError, load_ruleset, ruleset_from_dict

ALL = ("eoa_letter", "occupancy_certificate", "affiliation_letter", "government_approval")


class RulesetStructure(unittest.TestCase):
    def test_every_rule_has_a_known_check_and_required_metadata(self):
        for r in RULESET.rules:
            self.assertIn(r.check, CHECKS, r.rule_id)
            for attr in ("rule_id", "name", "description", "severity", "version", "effective_date", "source_ref", "remediation"):
                self.assertTrue(getattr(r, attr), f"{r.rule_id}.{attr}")

    def test_no_demo_rule_claims_to_be_official(self):
        self.assertEqual([r.rule_id for r in RULESET.rules if r.source_status == "official_confirmed"], [])
        self.assertIn("NOT an official AICTE checklist", RULESET.notice)

    def test_unique_ids(self):
        ids = [r.rule_id for r in RULESET.rules]
        self.assertEqual(len(ids), len(set(ids)))

    def test_malformed_ruleset_rejected(self):
        import json, pathlib
        from vcheck.rules import DEFAULT_RULESET_PATH
        d = json.loads(pathlib.Path(DEFAULT_RULESET_PATH).read_text())
        bad = json.loads(json.dumps(d)); del bad["rules"][0]["remediation"]
        with self.assertRaises(RuleSetError): ruleset_from_dict(bad)
        bad = json.loads(json.dumps(d)); bad["rules"][0]["severity"] = "catastrophic"
        with self.assertRaises(RuleSetError): ruleset_from_dict(bad)
        bad = json.loads(json.dumps(d)); bad["rules"].append(dict(bad["rules"][0]))
        with self.assertRaises(RuleSetError): ruleset_from_dict(bad)
        bad = json.loads(json.dumps(d)); bad["rules"][0]["source_status"] = "official_confirmed"; bad["rules"][0]["source_ref"] = "trust me"
        with self.assertRaises(RuleSetError): ruleset_from_dict(bad)


class RuleVersioning(unittest.TestCase):
    def test_derive_creates_new_version_and_leaves_original_untouched(self):
        new = RULESET.derive({"DATE-002": {"enabled": False}}, "1.1.0")
        self.assertEqual(new.version, "1.1.0")
        self.assertFalse(new.rule("DATE-002").enabled)
        self.assertEqual(new.rule("DATE-002").version, "1.1.0")
        self.assertTrue(RULESET.rule("DATE-002").enabled)          # original unchanged
        self.assertEqual(RULESET.rule("DATE-002").version, "1.0.0")
        self.assertEqual(new.rule("REQ-DOC-001").version, "1.0.0")  # untouched rules keep their version

    def test_cannot_edit_identity_or_source_fields_or_reuse_version(self):
        with self.assertRaises(RuleSetError): RULESET.derive({"DATE-002": {"rule_id": "X"}}, "1.1.0")
        with self.assertRaises(RuleSetError): RULESET.derive({"DATE-002": {"source_status": "official_confirmed"}}, "1.1.0")
        with self.assertRaises(RuleSetError): RULESET.derive({"DATE-002": {"enabled": False}}, "1.0.0")
        with self.assertRaises(RuleSetError): RULESET.derive({"NOPE-1": {"enabled": False}}, "1.1.0")

    def test_findings_record_the_rule_version_that_produced_them(self):
        new = RULESET.derive({"DATE-002": {"severity": "low"}}, "2.0.0")
        app = make_app()
        s = specs(app, affiliation_letter={"issue_date": "01-Apr-2025", "expiry_date": "31-Mar-2026"})
        f_old = validate(app, s).findings[0]
        f_new = validate(app, s, ruleset=new).findings[0]
        self.assertEqual((f_old.rule_id, f_old.rule_version, f_old.severity), ("DATE-002", "1.0.0", "high"))
        self.assertEqual((f_new.rule_id, f_new.rule_version, f_new.severity), ("DATE-002", "2.0.0", "low"))

    def test_disabled_rule_does_not_run_and_is_reported_as_skipped(self):
        new = RULESET.derive({"DATE-002": {"enabled": False}}, "1.1.0")
        app = make_app()
        rep = validate(app, specs(app, affiliation_letter={"issue_date": "01-Apr-2025", "expiry_date": "31-Mar-2026"}), ruleset=new)
        self.assertEqual(rule_ids(rep), [])
        self.assertIn({"rule_id": "DATE-002", "reason": "disabled"}, rep.rules_skipped)


class Checklists(unittest.TestCase):
    def test_clean_application_has_no_findings(self):
        self.assertEqual(rule_ids(validate(make_app())), [])

    def test_each_missing_required_document_is_reported(self):
        for skipped, rid in [("occupancy_certificate", "REQ-DOC-001"), ("eoa_letter", "REQ-DOC-002"),
                             ("affiliation_letter", "REQ-DOC-003"), ("government_approval", "REQ-DOC-004")]:
            with self.subTest(skipped=skipped):
                self.assertEqual(rule_ids(validate(make_app(), skip=(skipped,))), [rid])

    def test_checklist_depends_on_application_type(self):
        app = make_app(app_type="new_institution")
        rep = validate(app, skip=("eoa_letter", "affiliation_letter"))
        self.assertEqual(rule_ids(rep), [])
        skipped = {s["rule_id"] for s in rep.rules_skipped}
        self.assertTrue({"REQ-DOC-002", "REQ-DOC-003"} <= skipped)
        self.assertEqual(rule_ids(validate(app, skip=("occupancy_certificate", "eoa_letter", "affiliation_letter"))), ["REQ-DOC-001"])

    def test_missing_field_on_text_layer_is_a_failure(self):
        s = specs(); s["occupancy_certificate"].pop("certificate_number")
        f = validate(make_app(), s).findings
        self.assertEqual([(x.rule_id, x.outcome) for x in f], [("FLD-003", "failed")])

    def test_missing_field_on_ocr_text_is_only_review(self):
        s = specs(); s["occupancy_certificate"].pop("certificate_number")
        app = make_app()
        docs = [doc_from(sp, "png" if t == "occupancy_certificate" else "pdf", app.id, f"D{i}") for i, (t, sp) in enumerate(s.items())]
        f = [x for x in validate(app, docs=docs).findings if x.rule_id == "FLD-003"]
        self.assertEqual([x.outcome for x in f], ["review_required"])

    def test_rejected_upload_does_not_satisfy_requirement_and_explains_why(self):
        from vcheck.pipeline import process_document
        from tests.helpers import RULESET as RS, TODAY
        app = make_app()
        docs = docs_for(app, specs(app), skip=("occupancy_certificate",))
        docs.append(process_document(b"MZ\x00\x00" * 20, "occ.pdf", "DX", app.id, "occupancy_certificate", RS, TODAY))
        rep = validate(app, docs=docs)
        self.assertEqual(rule_ids(rep), ["REQ-DOC-001", "SYS-001"])
        req = next(f for f in rep.findings if f.rule_id == "REQ-DOC-001")
        self.assertIn("rejected", req.explanation)


class DateRules(unittest.TestCase):
    def test_boundaries(self):
        app = make_app()
        for expiry, expect in [("21-Oct-2026", ["DATE-002"]), ("22-Oct-2026", []), ("23-Oct-2026", [])]:
            with self.subTest(expiry=expiry):
                s = specs(app, affiliation_letter={"issue_date": "01-Apr-2026", "expiry_date": expiry})
                self.assertEqual(rule_ids(validate(app, s)), expect)

    def test_issue_after_expiry(self):
        app = make_app()
        s = specs(app, affiliation_letter={"issue_date": "15-May-2027", "expiry_date": "10-Jan-2027"})
        self.assertIn("DATE-003", rule_ids(validate(app, s)))

    def test_future_issue_date_needs_review_not_failure(self):
        f = [x for x in validate(make_app(), specs(occupancy_certificate={"issue_date": "15-Dec-2026"})).findings]
        self.assertEqual([(x.rule_id, x.outcome) for x in f], [("DATE-004", "review_required")])


class CrossDocument(unittest.TestCase):
    def one(self, over, app=None):
        app = app or make_app()
        return validate(app, specs(app, **over)).findings

    def test_name_mismatch_is_failure_with_evidence(self):
        (f,) = self.one({"occupancy_certificate": {"institution_name": "Lakeside College of Pharmacy"}})
        self.assertEqual((f.rule_id, f.outcome, f.severity), ("XD-001", "failed", "high"))
        self.assertEqual(f.observed, "Lakeside College of Pharmacy")
        self.assertEqual(f.expected, GF["name"])
        self.assertEqual(len(f.document_ids), 1)
        ev = f.evidence[0]
        self.assertEqual((ev.page, ev.field), (1, "institution_name"))
        self.assertIn("Lakeside", ev.snippet)
        self.assertTrue(f.recommended_action)

    def test_spelling_variant_is_review_with_confidence_not_failure(self):
        (f,) = self.one({"affiliation_letter": {"institution_name": "Greenfeld Institute of Technology"}})
        self.assertEqual((f.rule_id, f.outcome), ("XD-001", "review_required"))
        self.assertIn("not as a confirmed mismatch", f.explanation)
        self.assertTrue(0 < f.confidence < 1)

    def test_abbreviation_and_case_variants_raise_nothing(self):
        for variant in ["Greenfield Inst. of Tech.", "GREENFIELD INSTITUTE OF TECHNOLOGY", "greenfield institute of technology"]:
            with self.subTest(variant=variant):
                self.assertEqual(self.one({"affiliation_letter": {"institution_name": variant}}), [])

    def test_id_mismatch_vs_confusable(self):
        (a,) = self.one({"affiliation_letter": {"institution_id": "1-9000000999"}})
        (b,) = self.one({"eoa_letter": {"institution_id": "1-9OO0000101"}})
        self.assertEqual((a.rule_id, a.outcome), ("XD-002", "failed"))
        self.assertEqual((b.rule_id, b.outcome), ("XD-002", "review_required"))

    def test_intake_conflict_reports_both_values(self):
        (f,) = self.one({"eoa_letter": {"courses": [(dataset.COURSES[0][0], "120"), dataset.COURSES[1]]}})
        self.assertEqual((f.rule_id, f.observed, f.expected, f.outcome), ("XD-005", "120", "180", "failed"))
        self.assertEqual(len(f.evidence), 2)           # course line and intake line

    def test_course_not_in_application(self):
        (f,) = self.one({"affiliation_letter": {"courses": [dataset.COURSES[0], ("B.Sc. Nursing", "40")]}})
        self.assertEqual((f.rule_id, f.outcome), ("XD-004", "failed"))

    def test_document_for_another_application(self):
        (f,) = self.one({"eoa_letter": {"application_ref": "VC-DEMO-9999"}})
        self.assertEqual((f.rule_id, f.outcome), ("XD-003", "failed"))

    def test_conflicting_certificate_numbers_same_type(self):
        app = make_app()
        s = specs(app)
        docs = docs_for(app, s) + [doc_from(dict(s["occupancy_certificate"], certificate_number="OCC/GF/2026/777"), "pdf", app.id, "D9")]
        rep = validate(app, docs=docs)
        self.assertIn("XD-006", rule_ids(rep))

    def test_low_confidence_ocr_mismatch_downgrades_to_review(self):
        app = make_app()
        s = specs(app, affiliation_letter={"institution_id": "1-9000000999"})
        docs = docs_for(app, s)
        aff = next(d for d in docs if d.declared_type == "affiliation_letter")
        aff.fields["institution_id"][0].method = "ocr"
        aff.fields["institution_id"][0].confidence = 0.3
        (f,) = [x for x in validate(app, docs=docs).findings if x.rule_id == "XD-002"]
        self.assertEqual(f.outcome, "review_required")
        self.assertIn("misread", f.explanation)

    def test_ocr_mismatch_is_never_a_hard_failure_even_at_high_confidence(self):
        """Measured: wrong OCR values reached confidence 0.88, so confidence cannot gate this."""
        app = make_app()
        docs = docs_for(app, specs(app, affiliation_letter={"institution_id": "1-9000000999"}))
        aff = next(d for d in docs if d.declared_type == "affiliation_letter")
        aff.fields["institution_id"][0].method = "ocr"
        aff.fields["institution_id"][0].confidence = 0.88
        (f,) = [x for x in validate(app, docs=docs).findings if x.rule_id == "XD-002"]
        self.assertEqual(f.outcome, "review_required")

    def test_unavailable_comparisons_are_silent_not_mismatches(self):
        app = make_app(institution_id="")
        self.assertEqual(rule_ids(validate(app, specs(make_app()))), ["APP-001"])      # blank app id must not cause XD-002


class ApplicationRules(unittest.TestCase):
    def test_invalid_intake_in_application(self):
        app = make_app(); app.courses[0] = CourseRow(dataset.COURSES[0][0], "-5")
        self.assertEqual(rule_ids(validate(app, specs(make_app()))), ["NUM-001"])

    def test_identifier_format(self):
        app = make_app(institution_id="GF-101")
        s = specs(app)
        self.assertEqual(rule_ids(validate(app, s)), ["APP-002"])

    def test_report_summary_and_status(self):
        rep = validate(make_app(), skip=("occupancy_certificate",))
        self.assertEqual(rep.suggested_status, "review_required")
        self.assertEqual(rep.counts()["failed"], 1)
        self.assertEqual(validate(make_app()).suggested_status, "validation_complete")
        self.assertEqual(len(rep.rules_run) + len(rep.rules_skipped), len(RULESET.rules))


class FindingContract(unittest.TestCase):
    def test_every_finding_has_the_required_fields(self):
        app = make_app(institution_id="1-9000000999")
        s = specs(make_app(), occupancy_certificate={"institution_name": "Lakeside College of Pharmacy"},
                  affiliation_letter={"issue_date": "01-Apr-2025", "expiry_date": "31-Mar-2026"})
        rep = validate(app, s, skip=("government_approval",))
        self.assertGreater(len(rep.findings), 3)
        for f in rep.findings:
            self.assertTrue(f.finding_id and f.rule_id and f.rule_version and f.application_id == app.id)
            self.assertIn(f.outcome, ("failed", "review_required"))
            self.assertIn(f.severity, ("high", "medium", "low", "info"))
            self.assertTrue(f.explanation and f.recommended_action and f.processed_at)
            self.assertNotIn("verified", f.outcome)
        self.assertEqual(len({f.finding_id for f in rep.findings}), len(rep.findings))   # unique ids


if __name__ == "__main__":
    unittest.main()
