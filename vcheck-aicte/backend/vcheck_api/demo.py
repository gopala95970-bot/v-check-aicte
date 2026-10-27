"""Synthetic demo documents. Everything generated here is fictional and labelled as such.

Documents are rendered with the project's existing synthetic generator (data/synthetic/synth.py) so they
exercise the real OCR/extraction/validation pipeline; nothing is pre-baked into the database."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from typing import Optional

from .config import ROOT_DIR

sys.path.insert(0, str(ROOT_DIR / "data" / "synthetic"))
import synth  # noqa: E402

DOC_TYPES = ("eoa_letter", "occupancy_certificate", "affiliation_letter", "government_approval")
DEFAULT_COURSES = [("B.E. Computer Science and Engineering", "180"), ("B.Tech. Information Technology", "60")]

SCENARIOS = {
    "clean": "Clean set: four consistent documents, everything should pass.",
    "missing_occupancy": "Occupancy certificate is not included (required document missing).",
    "institution_id_mismatch": "The affiliation letter carries a different institution identifier.",
    "expired_affiliation": "The affiliation letter has already expired.",
    "intake_conflict": "The approval letter states a different approved intake than the application.",
    "duplicate_reuse": "The occupancy certificate is a copy of another institution's file.",
}


def _fmt(d: date) -> str:
    return d.strftime("%d-%b-%Y")


def build_specs(*, name: str, inst_id: str, reference: str, seq: int, courses: list[tuple[str, str]], today: date,
                scenario: str = "clean") -> dict:
    """Spec dicts per document type. Certificate numbers are unique per application so that unrelated
    demo applications never collide in the duplicate checks."""
    courses = courses or DEFAULT_COURSES
    issued = today - timedelta(days=150)
    valid_to = today + timedelta(days=220)
    code = f"{seq:03d}"
    common = dict(institution_name=name, institution_id=inst_id, issue_date=_fmt(issued), issuer="Demo Issuing Office")
    specs = {
        "eoa_letter": dict(common, type="eoa_letter", application_ref=reference, certificate_number=f"EOA/DEMO/2026/{code}1",
                           courses=list(courses)),
        "occupancy_certificate": dict(common, type="occupancy_certificate", certificate_number=f"OCC/DEMO/2026/{code}2",
                                      courses=[], institution_id=None),
        "affiliation_letter": dict(common, type="affiliation_letter", certificate_number=f"AFF/DEMO/2026/{code}3",
                                   expiry_date=_fmt(valid_to), courses=list(courses)),
        "government_approval": dict(common, type="government_approval", certificate_number=f"GOV/DEMO/2026/{code}4",
                                    expiry_date=_fmt(valid_to), courses=[(c, "") for c, _ in courses], institution_id=None),
    }
    if scenario == "institution_id_mismatch":
        specs["affiliation_letter"]["institution_id"] = "1-9000000999"
    elif scenario == "expired_affiliation":
        specs["affiliation_letter"].update(issue_date=_fmt(today - timedelta(days=600)), expiry_date=_fmt(today - timedelta(days=60)))
    elif scenario == "intake_conflict":
        first = list(courses)[0]
        specs["eoa_letter"]["courses"] = [(first[0], str(max(1, int(first[1] or 180) - 60)))] + list(courses)[1:]
    return specs


def build_documents(*, name: str, inst_id: str, reference: str, seq: int, courses: list[tuple[str, str]], today: date,
                    scenario: str = "clean", reuse_bytes: Optional[bytes] = None) -> list[tuple[str, bytes, str]]:
    if scenario not in SCENARIOS:
        raise ValueError("unknown scenario")
    specs = build_specs(name=name, inst_id=inst_id, reference=reference, seq=seq, courses=courses, today=today, scenario=scenario)
    out = []
    for t in DOC_TYPES:
        if t == "occupancy_certificate" and scenario == "missing_occupancy":
            continue
        if t == "occupancy_certificate" and scenario == "duplicate_reuse":
            if reuse_bytes is None:
                raise ValueError("no other institution's file is available to reuse")
            out.append(("occupancy_certificate.pdf", reuse_bytes, t))
            continue
        out.append((f"{t}.pdf", synth.digital_pdf(specs[t]), t))
    return out
