"""ProcessedDocument <-> JSON, so documents survive restarts and can be re-validated."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from vcheck.models import (CourseRowExtract, ExtractedField, Line, PageContent,
                           ProcessedDocument, UploadIssue)


def _bbox(v):
    return tuple(v) if v else None


def doc_to_json(d: ProcessedDocument) -> dict[str, Any]:
    data = asdict(d)
    data["shingles"] = sorted(d.shingles)
    return data


def _field(x: dict) -> ExtractedField:
    return ExtractedField(x["name"], x["value"], x["page"], x["line_no"], x["snippet"], x["confidence"],
                          x["method"], _bbox(x.get("bbox")), x.get("corrected_value"))


def doc_from_json(data: dict[str, Any]) -> ProcessedDocument:
    pages = [PageContent(p["page"], p["source"], [Line(l["text"], l.get("conf"), _bbox(l.get("bbox"))) for l in p["lines"]],
                         p.get("mean_conf"), list(p.get("notes", []))) for p in data.get("pages", [])]
    fields = {k: [_field(f) for f in v] for k, v in data.get("fields", {}).items()}
    rows = [CourseRowExtract(_field(r["course"]), _field(r["intake"]) if r.get("intake") else None)
            for r in data.get("course_rows", [])]
    return ProcessedDocument(
        document_id=data["document_id"], application_id=data["application_id"],
        original_filename=data["original_filename"], declared_type=data.get("declared_type"),
        status=data["status"], kind=data.get("kind"), size=data.get("size", 0), sha256=data.get("sha256"),
        detected_type=data.get("detected_type"), detected_confidence=data.get("detected_confidence", 0.0),
        errors=[UploadIssue(**e) for e in data.get("errors", [])],
        warnings=[UploadIssue(**e) for e in data.get("warnings", [])],
        pages=pages, text_source=data.get("text_source", "none"), ocr_mean_conf=data.get("ocr_mean_conf"),
        fields=fields, course_rows=rows, metadata=data.get("metadata"),
        metadata_signals=list(data.get("metadata_signals", [])), image_quality=data.get("image_quality"),
        phash=data.get("phash"), text_fingerprint=data.get("text_fingerprint"),
        shingles=frozenset(data.get("shingles", [])))
