"""Render synthetic demonstration documents.

Every document carries a visible SYNTHETIC banner. Formats are invented for
this prototype; they are NOT copies of any official AICTE, university or
government template. Institution names and identifiers are fictional.
"""
from __future__ import annotations

import io
import os
import random
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

BANNER = "SYNTHETIC DEMONSTRATION DOCUMENT - NOT AN OFFICIAL RECORD"
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    os.path.join(os.path.dirname(__import__("reportlab").__file__), "fonts", "Vera.ttf"),
]

TITLES = {
    "eoa_letter": "EXTENSION OF APPROVAL (DEMO)",
    "occupancy_certificate": "OCCUPANCY CERTIFICATE (DEMO)",
    "affiliation_letter": "UNIVERSITY AFFILIATION LETTER (DEMO)",
    "government_approval": "STATE GOVERNMENT APPROVAL AND NO OBJECTION (DEMO)",
}
BODY = {
    "eoa_letter": "This letter records the extension of approval for the academic year stated below, subject to the conditions of the demonstration process handbook.",
    "occupancy_certificate": "This is to certify that the building described below is complete and fit for occupation as an educational institution.",
    "affiliation_letter": "The university grants affiliation to the institution for the courses and intake stated below for the academic year.",
    "government_approval": "The state government has no objection to the continued operation of the courses listed below.",
}


def doc_lines(spec: dict) -> list[str]:
    """spec keys: type, institution_name, institution_id, application_ref,
    certificate_number, issue_date, expiry_date, courses=[(name, intake)], issuer"""
    t = spec["type"]
    lines = [BANNER, "", TITLES[t], "", BODY[t], ""]
    add = lambda label, key: lines.append(f"{label}: {spec[key]}") if spec.get(key) not in (None, "") else None  # noqa: E731
    add("Name of the Institution", "institution_name")
    add("AICTE Permanent Id", "institution_id")
    add("Application Id", "application_ref")
    add("Certificate No", "certificate_number")
    add("Date of Issue", "issue_date")
    add("Valid Until", "expiry_date")
    for name, intake in spec.get("courses", []):
        lines.append(f"Course: {name}")
        if intake not in (None, ""):
            lines.append(f"Approved Intake: {intake}")
    add("Issued by", "issuer")
    return lines


def digital_pdf(spec: dict, producer: Optional[str] = None, javascript: bool = False) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)   # invariant -> reproducible bytes
    c.setTitle(TITLES[spec["type"]])
    if producer:
        c.setProducer(producer)
        c.setCreator(producer)
    y = 800
    for line in doc_lines(spec):
        c.setFont("Helvetica-Bold" if line == TITLES[spec["type"]] else "Helvetica", 11)
        c.drawString(50, y, line)
        y -= 20
    c.save()
    raw = buf.getvalue()
    if javascript:   # inert test payload; the system never executes PDFs
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter(clone_from=PdfReader(io.BytesIO(raw)))
        w.add_js("app.alert('demo');")
        out = io.BytesIO()
        w.write(out)
        raw = out.getvalue()
    return raw


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def page_image(spec: dict, dpi: int = 150, blur: float = 0.0, noise: float = 0.0,
               rotate: float = 0.0, seed: int = 7) -> Image.Image:
    w, h = int(8.27 * dpi), int(11.69 * dpi)
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    font = _font(int(dpi * 0.15))
    y = int(dpi * 0.6)
    for line in doc_lines(spec):
        d.text((int(dpi * 0.6), y), line, fill=0, font=font)
        y += int(dpi * 0.3)
    if rotate:
        img = img.rotate(rotate, expand=False, fillcolor=255, resample=Image.BICUBIC)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        rnd = random.Random(seed)
        px = img.load()
        for _ in range(int(w * h * noise)):
            x, yy = rnd.randrange(w), rnd.randrange(h)
            px[x, yy] = rnd.choice((0, 255))
    return img


def image_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=70)
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def scanned_pdf(spec: dict, **degrade) -> bytes:
    img = page_image(spec, **degrade)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.drawImage(ImageReader(img.convert("RGB")), 0, 0, width=A4[0], height=A4[1])
    c.save()
    return buf.getvalue()
