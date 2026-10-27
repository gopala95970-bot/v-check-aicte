"""PDF metadata inspection.

Metadata is trivially editable and often legitimately absent, so every signal
produced here is informational / review-only, carries a plain statement of its
limits, and is never described as evidence of tampering.

Digital-signature *verification* is intentionally NOT implemented in this
build: we only report whether a signature field is present, and say so.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timezone
from typing import Any, Optional

from pypdf import PdfReader

# Producers that are image/graphics editors rather than document generators.
EDITOR_HINTS = ("photoshop", "gimp", "canva", "paint", "pixlr", "illustrator", "inkscape")
LIMIT = "Metadata can be edited or stripped and is often missing legitimately; this is a prompt to look, not proof of tampering."


def _pdf_date(raw: Optional[str]) -> Optional[datetime]:
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", raw or "")
    if not m:
        return None
    parts = [int(g) if g else d for g, d in zip(m.groups(), (0, 1, 1, 0, 0, 0))]
    try:
        return datetime(*parts, tzinfo=timezone.utc)
    except ValueError:
        return None


def inspect_pdf(raw: bytes, today: Optional[date] = None) -> tuple[dict[str, Any], list[dict[str, str]]]:
    today = today or date.today()
    meta: dict[str, Any] = {}
    signals: list[dict[str, str]] = []
    try:
        reader = PdfReader(io.BytesIO(raw), strict=False)
        info = reader.metadata or {}
        get = lambda k: str(info.get(k)) if info.get(k) is not None else None   # noqa: E731
        meta = {"producer": get("/Producer"), "creator": get("/Creator"), "author": get("/Author"),
                "title": get("/Title"), "created": get("/CreationDate"), "modified": get("/ModDate"),
                "pages": len(reader.pages), "revisions": raw.count(b"%%EOF")}
    except Exception:
        return {}, [{"code": "META_UNREADABLE", "message": "PDF metadata could not be read.", "limitation": LIMIT}]

    producer = " ".join(filter(None, [meta.get("producer"), meta.get("creator")])).lower()
    if any(h in producer for h in EDITOR_HINTS):
        signals.append({"code": "META_EDITOR_PRODUCER",
                        "message": f"The file was produced by software commonly used to edit images ({meta.get('producer') or meta.get('creator')}).",
                        "limitation": LIMIT})
    created, modified = _pdf_date(meta.get("created")), _pdf_date(meta.get("modified"))
    if created and modified and (modified - created).days >= 1:
        signals.append({"code": "META_MODIFIED_AFTER_CREATION",
                        "message": f"The modification date ({modified.date()}) is later than the creation date ({created.date()}).",
                        "limitation": LIMIT})
    for label, d in (("creation", created), ("modification", modified)):
        if d and d.date() > today:
            signals.append({"code": "META_FUTURE_DATE",
                            "message": f"The {label} date ({d.date()}) is in the future.", "limitation": LIMIT})
    if meta["revisions"] > 1:
        signals.append({"code": "META_INCREMENTAL_UPDATES",
                        "message": f"The file contains {meta['revisions']} saved revisions (incremental updates).",
                        "limitation": LIMIT})
    if b"/ByteRange" in raw and b"/Sig" in raw:
        signals.append({"code": "SIGNATURE_PRESENT_UNVERIFIED",
                        "message": "A digital-signature field is present, but its cryptographic validity and trust chain were NOT verified by this system.",
                        "limitation": "Signature verification is not implemented in this build."})
    return meta, signals
