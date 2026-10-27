"""Document processing pipeline.

process_document() never raises for bad input: every failure becomes a
ProcessedDocument with status "rejected" or "unreadable" plus a clear message,
so one corrupt upload cannot crash an application's validation run.
"""
from __future__ import annotations

import io
import time
from datetime import date
from typing import Optional

from PIL import Image

from . import duplicates, fields as fieldlib, files, metadata, ocr
from .models import ProcessedDocument, UploadIssue
from .rules import RuleSet

MIN_USABLE_CHARS = 15
# Below this mean OCR confidence the "text" is effectively noise. Chosen AFTER
# observing one synthetic failure (garbage text at 0.26); it has not been
# validated on real scans. See KNOWN_LIMITATIONS.md.
UNREADABLE_CONF = 0.40


def process_document(raw: bytes, filename: str, document_id: str, application_id: str,
                     declared_type: Optional[str], ruleset: RuleSet,
                     today: Optional[date] = None,
                     max_bytes: int = files.MAX_BYTES_DEFAULT,
                     timings: Optional[dict] = None) -> ProcessedDocument:
    """`timings`, if given, is filled with wall-clock milliseconds per stage
    (integrity_ms, read_ms, extract_ms, metadata_ms). It never changes results."""
    t = timings if timings is not None else {}
    t0 = time.perf_counter()
    chk = files.validate_upload(raw, filename, max_bytes=max_bytes)
    t["integrity_ms"] = round((time.perf_counter() - t0) * 1000)
    doc = ProcessedDocument(document_id=document_id, application_id=application_id,
                            original_filename=chk.display_name, declared_type=declared_type,
                            status="rejected", kind=chk.kind, size=chk.size, sha256=chk.sha256,
                            errors=list(chk.errors), warnings=list(chk.warnings))
    if not chk.ok:
        return doc

    t0 = time.perf_counter()
    try:
        pages, qualities = ocr.read_pdf(raw) if chk.kind == "pdf" else ocr.read_image(raw)
    except ocr.OCRTimeout as exc:
        doc.status = "unreadable"
        doc.warnings.append(UploadIssue("OCR_TIMEOUT", f"{exc}. The document is routed to manual review."))
        pages, qualities = [], []
    except ocr.OCRUnavailable as exc:
        doc.status = "unreadable"
        doc.warnings.append(UploadIssue("OCR_UNAVAILABLE", str(exc)))
        pages, qualities = [], []
    except Exception:
        doc.status = "unreadable"
        doc.warnings.append(UploadIssue("READ_FAILED", "The document content could not be processed."))
        pages, qualities = [], []

    t["read_ms"] = round((time.perf_counter() - t0) * 1000)
    doc.pages = pages
    for p in pages:                      # never hide why a page produced no text
        for note in p.notes:
            doc.warnings.append(UploadIssue("PAGE_NOTE", f"Page {p.page}: {note}"))
    sources = {p.source for p in pages if p.source != "none"}
    doc.text_source = ("mixed" if len(sources) > 1 else next(iter(sources))) if sources else "none"
    ocr_confs = [p.mean_conf for p in pages if p.source == "ocr" and p.mean_conf is not None]
    doc.ocr_mean_conf = round(sum(ocr_confs) / len(ocr_confs), 3) if ocr_confs else None
    if qualities:
        worst = min(qualities, key=lambda q: q["sharpness"])
        doc.image_quality = {**worst, "flags": sorted({f for q in qualities for f in q["flags"]})}

    text = doc.full_text
    if doc.status != "unreadable" and len("".join(text.split())) < MIN_USABLE_CHARS:
        doc.status = "unreadable"
    if (doc.status != "unreadable" and doc.text_source == "ocr"
            and doc.ocr_mean_conf is not None and doc.ocr_mean_conf < UNREADABLE_CONF):
        doc.status = "unreadable"
        doc.warnings.append(UploadIssue("OCR_NOISE", "OCR produced text with very low confidence; treated as unreadable."))
    if doc.status == "unreadable":
        _fingerprints(doc, raw)
        return doc

    doc.status = "processed"
    t0 = time.perf_counter()
    doc.fields, doc.course_rows = fieldlib.extract_fields(pages)
    doc.detected_type, doc.detected_confidence, _ = fieldlib.classify_document(text, ruleset.document_types)
    t["extract_ms"] = round((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    if chk.kind == "pdf":
        doc.metadata, doc.metadata_signals = metadata.inspect_pdf(raw, today)
    t["metadata_ms"] = round((time.perf_counter() - t0) * 1000)
    _fingerprints(doc, raw)
    return doc


def _fingerprints(doc: ProcessedDocument, raw: bytes) -> None:
    text = doc.full_text
    if text.strip():
        doc.text_fingerprint = duplicates.text_fingerprint(text)
        doc.shingles = duplicates.shingles(text)
    if doc.kind in ("png", "jpeg"):
        doc.phash = duplicates.dhash_bytes(raw)
