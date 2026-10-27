"""Field extraction and document classification.

Extraction is label-driven ("Certificate No: ...") and records exactly where
each value came from (page, line, bounding box for OCR text). Confidence is a
heuristic: the line's OCR confidence, or a fixed value for embedded text. It is
not a calibrated probability and is never shown as one.

The label table is configuration, not scattered logic: add a synonym here and
every rule benefits.
"""
from __future__ import annotations

import re
from typing import Iterable

from .models import CourseRowExtract, ExtractedField, PageContent
from .normalize import normalize_text

# Order matters: a line is assigned to the first field whose label matches.
FIELD_LABELS: dict[str, list[str]] = {
    "institution_name": [r"name\s+of\s+(?:the\s+)?institut(?:ion|e)", r"institut(?:ion|e)\s+name",
                         r"name\s+of\s+(?:the\s+)?college", r"college\s+name"],
    "institution_id": [r"(?:aicte\s+)?permanent\s+id", r"institut(?:ion|e)\s+id", r"aicte\s+id"],
    "application_ref": [r"application\s+(?:id|no\.?|number|ref(?:erence)?(?:\s+no\.?)?)"],
    "certificate_number": [r"certificate\s+(?:no\.?|number)", r"(?:letter|order|file|approval)\s+(?:no\.?|number)"],
    "issue_date": [r"date\s+of\s+(?:issue|approval)", r"issue\s+date", r"issued\s+on"],
    "expiry_date": [r"valid\s+(?:up\s*to|until|till|through)", r"expiry\s+date", r"date\s+of\s+expiry", r"expires\s+on"],
    "approved_intake": [r"(?:approved|sanctioned)\s+intake", r"intake\s+approved"],
    "course_name": [r"course(?:\s+name)?", r"programme?(?:\s+name)?"],
    "issuer": [r"issued\s+by", r"issuing\s+authority"],
}
_COMPILED = {
    name: [re.compile(rf"^\s*(?:{p})\s*[:\-\u2013]\s*(?P<value>\S.*?)\s*$", re.I) for p in pats]
    for name, pats in FIELD_LABELS.items()
}


def extract_fields(pages: Iterable[PageContent]) -> tuple[dict[str, list[ExtractedField]], list[CourseRowExtract]]:
    """Return (fields by name, course rows).

    A course row pairs each course line with the next intake line before the
    following course line, so documents listing several courses stay aligned.
    """
    fields: dict[str, list[ExtractedField]] = {}
    rows: list[CourseRowExtract] = []
    current: CourseRowExtract | None = None
    for page in pages:
        for ln_no, line in enumerate(page.lines, start=1):
            for name, patterns in _COMPILED.items():
                m = next((m for m in (p.match(line.text) for p in patterns) if m), None)
                if not m:
                    continue
                conf = line.conf if line.conf is not None else 0.0
                ef = ExtractedField(name=name, value=m.group("value").strip(), page=page.page,
                                    line_no=ln_no, snippet=line.text[:200], confidence=round(conf, 3),
                                    method="ocr" if page.source == "ocr" else "text_layer", bbox=line.bbox)
                fields.setdefault(name, []).append(ef)
                if name == "course_name":
                    current = CourseRowExtract(course=ef)
                    rows.append(current)
                elif name == "approved_intake" and current is not None and current.intake is None:
                    current.intake = ef
                break   # one field per line
    return fields, rows


def classify_document(text: str, doc_types: dict[str, dict]) -> tuple[str | None, float, list[str]]:
    """Keyword scoring against configured document types.

    Returns (type or None, confidence 0..1, matched keywords). Confidence is the
    share of that type's keywords found, halved when two types tie. A heuristic,
    shown to reviewers as "detected type", never used to override the applicant.
    """
    norm = normalize_text(text)
    scored = []
    for key, cfg in doc_types.items():
        kws = [normalize_text(k) for k in cfg.get("keywords", [])]
        hits = [k for k in kws if k and k in norm]
        if hits:
            scored.append((len(hits) / len(kws), key, hits))
    if not scored:
        return None, 0.0, []
    scored.sort(reverse=True)
    best = scored[0]
    conf = best[0]
    if len(scored) > 1 and abs(scored[1][0] - best[0]) < 1e-9:
        conf /= 2
    return best[1], round(conf, 3), best[2]
