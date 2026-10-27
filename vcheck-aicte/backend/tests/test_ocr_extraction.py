import unittest

from tests.helpers import RULESET, doc_from, make_app, specs
from vcheck import fields as fieldlib

AFF = lambda: specs()["affiliation_letter"]   # noqa: E731


def values(doc, name):
    return [f.effective() for f in doc.fields.get(name, [])]


class DigitalPdfExtraction(unittest.TestCase):
    def test_all_fields_and_course_rows(self):
        d = doc_from(AFF())
        self.assertEqual(d.status, "processed")
        self.assertEqual(d.text_source, "text_layer")
        self.assertEqual(values(d, "institution_name"), ["Greenfield Institute of Technology"])
        self.assertEqual(values(d, "institution_id"), ["1-9000000101"])
        self.assertEqual(values(d, "certificate_number"), ["AFF/GF/2026/102"])
        self.assertEqual(values(d, "issue_date"), ["15-May-2026"])
        self.assertEqual(values(d, "expiry_date"), ["31-May-2027"])
        rows = [(r.course.effective(), r.intake.effective()) for r in d.course_rows]
        self.assertEqual(rows, [("B.E. Computer Science and Engineering", "180"), ("B.Tech. Information Technology", "60")])

    def test_every_field_records_where_it_came_from(self):
        d = doc_from(AFF())
        f = d.primary("certificate_number")
        self.assertEqual((f.page, f.method), (1, "text_layer"))
        self.assertGreater(f.line_no, 0)
        self.assertIn("AFF/GF/2026/102", f.snippet)

    def test_classification(self):
        for t in ["eoa_letter", "occupancy_certificate", "affiliation_letter", "government_approval"]:
            with self.subTest(t=t):
                d = doc_from(specs()[t])
                self.assertEqual(d.detected_type, t)
                self.assertGreaterEqual(d.detected_confidence, 0.5)

    def test_classification_returns_none_for_unrelated_text(self):
        self.assertEqual(fieldlib.classify_document("grocery list: milk eggs bread", RULESET.document_types)[0], None)

    def test_corrections_preserve_original_value(self):
        d = doc_from(AFF())
        f = d.primary("certificate_number")
        f.corrected_value = "AFF/GF/2026/999"
        self.assertEqual(f.effective(), "AFF/GF/2026/999")
        self.assertEqual(f.value, "AFF/GF/2026/102")


class OcrExtraction(unittest.TestCase):
    """These run real Tesseract on synthetic renders."""

    def check_clean(self, mode):
        d = doc_from(AFF(), mode)
        self.assertEqual(d.status, "processed")
        self.assertEqual(d.text_source, "ocr")
        self.assertEqual(values(d, "institution_id"), ["1-9000000101"])
        self.assertEqual(values(d, "certificate_number"), ["AFF/GF/2026/102"])
        self.assertEqual(values(d, "expiry_date"), ["31-May-2027"])
        self.assertEqual(len(d.course_rows), 2)
        f = d.primary("certificate_number")
        self.assertEqual(f.method, "ocr")
        self.assertIsNotNone(f.bbox)                     # source location for the evidence viewer
        self.assertGreater(f.confidence, 0.5)

    def test_scanned_pdf(self):
        self.check_clean("scan")

    def test_png(self):
        self.check_clean("png")

    def test_jpeg(self):
        self.check_clean("jpg")

    def test_unreadable_scan_is_flagged_not_trusted(self):
        """Holds whether OCR returns junk (low confidence) or runs out of time on a slow machine."""
        d = doc_from(AFF(), "scan", blur=7.0, noise=0.03)
        self.assertEqual(d.status, "unreadable")
        self.assertEqual(d.fields, {})
        self.assertTrue({w.code for w in d.warnings} & {"OCR_NOISE", "OCR_TIMEOUT", "PAGE_NOTE"}, "the reason must be recorded")

    def test_blur_detector_ignores_noise_inflation(self):
        import numpy as np
        from tests.helpers import synth
        from vcheck.ocr import image_quality
        flags = image_quality(np.array(synth.page_image(AFF(), blur=7.0, noise=0.03)))["flags"]
        self.assertIn("blurry", flags)
        self.assertEqual(image_quality(np.array(synth.page_image(AFF())))["flags"], [])

    def test_ocr_timeout_is_explicit_not_silent(self):
        from vcheck import ocr
        old, ocr.OCR_TIMEOUT_S = ocr.OCR_TIMEOUT_S, 1
        try:
            d = doc_from(AFF(), "scan", blur=7.0, noise=0.03)
        finally:
            ocr.OCR_TIMEOUT_S = old
        self.assertEqual(d.status, "unreadable")
        self.assertIn("OCR_TIMEOUT", [w.code for w in d.warnings])

    def test_missing_tesseract_degrades_to_unreadable(self):
        from unittest import mock
        from vcheck import ocr
        with mock.patch.object(ocr, "_tesseract", side_effect=ocr.OCRUnavailable("Tesseract OCR is not installed or not on PATH")):
            d = doc_from(AFF(), "png")
        self.assertEqual(d.status, "unreadable")
        self.assertIn("OCR_UNAVAILABLE", [w.code for w in d.warnings])

    def test_degraded_scan_never_yields_a_confident_wrong_value_silently(self):
        d = doc_from(AFF(), "png", rotate=2.0, noise=0.002)
        for f in d.fields.get("institution_id", []):
            if f.effective() != "1-9000000101":
                self.assertLess(f.confidence, 0.95)    # a misread must carry visibly lower confidence than clean text


if __name__ == "__main__":
    unittest.main()
