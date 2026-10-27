import io
import unittest

from PIL import Image, ImageDraw

from tests.helpers import RB, RULESET, GF, dataset, doc_from, docs_for, make_app, rule_ids, specs, synth, validate
from vcheck import duplicates as dup
from vcheck.duplicates import corpus_entry_from
from vcheck.verification import (DigiLockerProvider, SimulatedProvider, UnavailableProvider, VerificationResult,
                                 verify_documents)


def corpus_from_rb():
    app = make_app(900, RB)
    return tuple(corpus_entry_from(doc_from(s, "pdf", app.id, f"P{i}"), app) for i, s in enumerate(specs(app, "RB").values()))


class ExactAndNearDuplicates(unittest.TestCase):
    def test_same_file_twice_in_one_application(self):
        app = make_app()
        docs = docs_for(app, specs(app))
        occ = next(d for d in docs if d.declared_type == "occupancy_certificate")
        again = doc_from(specs(app)["occupancy_certificate"], "pdf", app.id, "DUP")
        self.assertEqual(occ.sha256, again.sha256)                      # generator is deterministic
        rep = validate(app, docs=docs + [again])
        self.assertEqual(rule_ids(rep), ["DUP-001"])
        self.assertEqual(sorted(rep.findings[0].document_ids), sorted([occ.document_id, "DUP"]))

    def test_exact_reuse_from_another_institution_is_review_and_reviewer_only(self):
        app = make_app()
        s = specs(app)
        foreign = doc_from(specs(make_app(900, RB), "RB")["occupancy_certificate"], "pdf", app.id, "FX", declared="occupancy_certificate")
        docs = [d for d in docs_for(app, s) if d.declared_type != "occupancy_certificate"] + [foreign]
        rep = validate(app, docs=docs, corpus=corpus_from_rb())
        f = next(x for x in rep.findings if x.rule_id == "DUP-002")
        self.assertEqual(f.outcome, "review_required")
        self.assertTrue(f.reviewer_only)
        self.assertIn("not proof of misuse", f.explanation)
        self.assertTrue(f.limitations)

    def test_same_institution_reusing_its_own_document_is_not_flagged(self):
        app = make_app(2)
        docs = docs_for(app, specs(app))
        own_previous = tuple(corpus_entry_from(d, make_app(1)) for d in docs_for(make_app(1), specs(make_app(1))))
        self.assertEqual(rule_ids(validate(app, docs=docs, corpus=own_previous)), [])

    def test_template_sharing_between_genuine_institutions_is_not_flagged(self):
        self.assertEqual(rule_ids(validate(make_app(), corpus=corpus_from_rb())), [])

    def test_measured_similarity_separates_templates_from_reuse(self):
        """Pin the measured numbers behind the 0.80 threshold (see TESTING_AND_EVALUATION.md)."""
        gf, rb = specs(make_app()), specs(make_app(2, RB), "RB")
        for t in gf:
            self.assertLess(dup.jaccard(doc_from(gf[t]).shingles, doc_from(rb[t]).shingles), 0.75, t)
        occ = gf["occupancy_certificate"]
        one_token = dup.jaccard(doc_from(occ).shingles, doc_from(dict(occ, certificate_number="OCC/GF/2026/777")).shingles)
        self.assertGreater(one_token, 0.80)
        self.assertEqual(RULESET.rule("DUP-004").params["text_threshold"], 0.80)

    def test_near_duplicate_with_one_changed_number(self):
        app = make_app()
        s = specs(app)
        docs = docs_for(app, s) + [doc_from(dict(s["occupancy_certificate"], certificate_number="OCC/GF/2026/777"), "pdf", app.id, "D9")]
        self.assertIn("DUP-004", rule_ids(validate(app, docs=docs)))

    def test_certificate_number_reuse_across_institutions(self):
        app = make_app()
        s = specs(app, occupancy_certificate={"certificate_number": "OCC/RB/2026/201"})     # RB's number
        rep = validate(app, s, corpus=corpus_from_rb())
        f = next(x for x in rep.findings if x.rule_id == "DUP-003")
        self.assertTrue(f.reviewer_only)
        self.assertEqual(f.outcome, "review_required")

    def test_resaved_as_image_is_found_through_text(self):
        app = make_app()
        reused = doc_from(specs(make_app(900, RB), "RB")["occupancy_certificate"], "png", app.id, "FX", declared="occupancy_certificate")
        docs = [d for d in docs_for(app, specs(app)) if d.declared_type != "occupancy_certificate"] + [reused]
        ids = rule_ids(validate(app, docs=docs, corpus=corpus_from_rb()))
        self.assertIn("DUP-003", ids)
        self.assertIn("DUP-004", ids)


class PerceptualHash(unittest.TestCase):
    def img(self, seed=0, size=(200, 200)):
        im = Image.new("L", size, 255)
        d = ImageDraw.Draw(im)
        for i in range(8):
            top = 10 + (i * 37 + seed * 3) % 120
            d.rectangle([10 + i * 20 + seed, top, 30 + i * 20 + seed, top + 40 + (i * 11) % 30], fill=(i * 31 + seed * 17) % 200)
        return im

    def test_resized_and_recompressed_copy_is_close(self):
        a = self.img()
        buf = io.BytesIO(); a.resize((100, 100)).convert("RGB").save(buf, "JPEG", quality=40)
        b = Image.open(io.BytesIO(buf.getvalue()))
        self.assertLessEqual(dup.hamming(dup.dhash(a), dup.dhash(b)), 6)

    def test_different_image_is_far(self):
        self.assertGreater(dup.hamming(dup.dhash(self.img(0)), dup.dhash(self.img(9))), 6)

    def test_unreadable_bytes_give_none(self):
        self.assertIsNone(dup.dhash_bytes(b"not an image"))


class Verification(unittest.TestCase):
    def processed(self, over=None):
        app = make_app()
        return app, docs_for(app, specs(app, **(over or {})))

    def registry(self, docs, inst=GF["id"]):
        return {d.primary("certificate_number").effective(): inst for d in docs}

    def test_simulated_success_is_never_called_verified(self):
        app, docs = self.processed()
        results = verify_documents(SimulatedProvider(self.registry(docs)), docs)
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertEqual(r.status, "verified")
            self.assertTrue(r.simulated)
            self.assertFalse(r.is_trusted_verification)
            self.assertEqual(r.display_status, "simulated_match")
            self.assertIn("NOT a government verification", r.detail)
        self.assertEqual(rule_ids(validate(app, docs=docs, verifications=results)), [])

    def test_only_a_real_nonsimulated_success_counts_as_trusted(self):
        self.assertTrue(VerificationResult("D", "real", False, "verified", "x").is_trusted_verification)
        self.assertFalse(VerificationResult("D", "sim", True, "verified", "x").is_trusted_verification)
        self.assertFalse(VerificationResult("D", "real", False, "not_found", "x").is_trusted_verification)

    def test_unavailable_source_requires_review_and_is_not_a_failure(self):
        app, docs = self.processed()
        rep = validate(app, docs=docs, verifications=verify_documents(UnavailableProvider(), docs))
        self.assertEqual(rule_ids(rep), ["VER-001"])
        self.assertTrue(all(f.outcome == "review_required" for f in rep.findings))

    def test_registry_mismatch_and_not_found_never_say_forged(self):
        app, docs = self.processed()
        reg = self.registry(docs)
        aff = next(d for d in docs if d.declared_type == "affiliation_letter")
        reg[aff.primary("certificate_number").effective()] = "1-9000000999"
        gov = next(d for d in docs if d.declared_type == "government_approval")
        del reg[gov.primary("certificate_number").effective()]
        rep = validate(app, docs=docs, verifications=verify_documents(SimulatedProvider(reg), docs))
        self.assertEqual(sorted(f.observed for f in rep.findings), ["mismatch", "not_found"])
        for f in rep.findings:
            self.assertEqual(f.outcome, "review_required")
            text = (f.title + f.explanation).lower()
            self.assertNotIn("forg", text.replace("not a finding of forgery", ""))

    def test_unconfigured_real_connector_does_nothing_and_says_so(self):
        _, docs = self.processed()
        r = DigiLockerProvider().verify(docs[0])
        self.assertEqual((r.status, r.simulated), ("unavailable", False))
        self.assertIn("credentials", r.detail)

    def test_no_provider_means_no_attempts(self):
        _, docs = self.processed()
        self.assertEqual(verify_documents(None, docs), [])


if __name__ == "__main__":
    unittest.main()
