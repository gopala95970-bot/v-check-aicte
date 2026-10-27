import io
import unittest

from PIL import Image

from tests.helpers import GF, RULESET, TODAY, make_app, specs, synth
from vcheck import files
from vcheck.pipeline import process_document


def pdf_bytes():
    return synth.digital_pdf(specs()["occupancy_certificate"])


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, "PNG")
    return buf.getvalue()


class UploadValidation(unittest.TestCase):
    def codes(self, raw, name):
        return [e.code for e in files.validate_upload(raw, name).errors]

    def test_valid_pdf_png_jpeg_accepted(self):
        self.assertTrue(files.validate_upload(pdf_bytes(), "a.pdf").ok)
        self.assertTrue(files.validate_upload(png_bytes(), "a.png").ok)
        buf = io.BytesIO(); Image.new("RGB", (50, 50)).save(buf, "JPEG")
        self.assertTrue(files.validate_upload(buf.getvalue(), "a.jpg").ok)
        self.assertTrue(files.validate_upload(buf.getvalue(), "a.JPEG").ok)

    def test_executable_with_pdf_extension_rejected_by_content(self):
        self.assertEqual(self.codes(b"MZ\x90\x00" + b"\x00" * 100, "evil.pdf"), ["UNSUPPORTED_TYPE"])

    def test_script_and_html_rejected(self):
        self.assertEqual(self.codes(b"<html><script>alert(1)</script></html>", "a.pdf"), ["UNSUPPORTED_TYPE"])
        self.assertEqual(self.codes(b"#!/bin/sh\nrm -rf /\n", "a.png"), ["UNSUPPORTED_TYPE"])

    def test_extension_must_match_content(self):
        self.assertEqual(self.codes(png_bytes(), "a.pdf"), ["EXTENSION_MISMATCH"])
        self.assertEqual(self.codes(pdf_bytes(), "a.png"), ["EXTENSION_MISMATCH"])
        self.assertEqual(self.codes(pdf_bytes(), "noextension"), ["EXTENSION_MISMATCH"])

    def test_empty_and_oversize(self):
        self.assertEqual(self.codes(b"", "a.pdf"), ["EMPTY_FILE"])
        big = b"%PDF-1.4\n" + b"0" * 2048
        self.assertEqual([e.code for e in files.validate_upload(big, "a.pdf", max_bytes=1024).errors], ["TOO_LARGE"])

    def test_corrupt_pdf(self):
        raw = pdf_bytes()
        self.assertEqual(self.codes(raw[: len(raw) // 3], "a.pdf"), ["CORRUPT_PDF"])
        self.assertEqual(self.codes(b"%PDF-1.4\nthis is not really a pdf", "a.pdf"), ["CORRUPT_PDF"])

    def test_corrupt_image(self):
        self.assertEqual(self.codes(png_bytes()[:40], "a.png"), ["CORRUPT_IMAGE"])

    def test_encrypted_pdf_rejected(self):
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes())))
        w.encrypt("secret")
        out = io.BytesIO(); w.write(out)
        self.assertEqual(self.codes(out.getvalue(), "a.pdf"), ["ENCRYPTED_PDF"])

    def test_pixel_limit(self):
        buf = io.BytesIO(); Image.new("L", (7000, 7000)).save(buf, "PNG")     # 49M px > 40M limit
        self.assertEqual(self.codes(buf.getvalue(), "big.png"), ["IMAGE_TOO_LARGE"])

    def test_pdf_javascript_flagged_not_executed(self):
        raw = synth.digital_pdf(specs()["occupancy_certificate"], javascript=True)
        chk = files.validate_upload(raw, "a.pdf")
        self.assertTrue(chk.ok)
        self.assertIn("PDF_ACTIVE_CONTENT", [w.code for w in chk.warnings])


class SafeNames(unittest.TestCase):
    def test_path_traversal_and_odd_characters_removed(self):
        for hostile in ["../../etc/passwd", "..\\..\\windows\\system32\\x.pdf", "a/b/c.pdf", "x;rm -rf.pdf", "<script>.pdf", "a\x00.pdf"]:
            with self.subTest(hostile=hostile):
                n = files.safe_display_name(hostile)
                self.assertNotIn("/", n); self.assertNotIn("\\", n); self.assertNotIn("..", n.split(".pdf")[0] or "x")
                self.assertRegex(n, r"^[A-Za-z0-9._ -]+$")

    def test_empty_name_gets_default_and_length_is_capped(self):
        self.assertEqual(files.safe_display_name(""), "file")
        self.assertLessEqual(len(files.safe_display_name("a" * 500 + ".pdf")), 80)

    def test_storage_name_is_random_and_ignores_user_input(self):
        a, b = files.storage_name("pdf"), files.storage_name("pdf")
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^[0-9a-f]{32}\.pdf$")


class PipelineNeverCrashes(unittest.TestCase):
    def test_bad_inputs_become_rejected_documents(self):
        for raw, name in [(b"", "a.pdf"), (b"garbage", "a.pdf"), (b"%PDF-1.4 junk", "a.pdf"), (png_bytes()[:30], "a.png")]:
            with self.subTest(name=name, raw=raw[:8]):
                d = process_document(raw, name, "D", "A", "occupancy_certificate", RULESET, TODAY)
                self.assertEqual(d.status, "rejected")
                self.assertTrue(d.errors)

    def test_hash_is_sha256_of_content(self):
        import hashlib
        raw = pdf_bytes()
        d = process_document(raw, "a.pdf", "D", "A", None, RULESET, TODAY)
        self.assertEqual(d.sha256, hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
