"""Plain data models for the V-Check engine.

Nothing here touches a database, the network or the file system, so the same
objects are used by the tests, the evaluation harness and the (later) API layer.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

# Finding outcomes. "verified" is deliberately NOT a finding outcome: it is
# reserved for verification through a documented trusted source.
OUTCOME_FAILED = "failed"                  # a defined check did not pass
OUTCOME_REVIEW = "review_required"         # uncertain / incomplete -> human looks
OUTCOMES = (OUTCOME_FAILED, OUTCOME_REVIEW)

SEVERITIES = ("high", "medium", "low", "info")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Line:
    text: str
    conf: Optional[float] = None                       # 0..1, OCR only
    bbox: Optional[tuple[int, int, int, int]] = None   # x0, y0, x1, y1 in image px


@dataclass
class PageContent:
    page: int                                          # 1-based
    source: str                                        # text_layer | ocr | none
    lines: list[Line] = field(default_factory=list)
    mean_conf: Optional[float] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class ExtractedField:
    name: str
    value: str
    page: int
    line_no: int
    snippet: str
    confidence: float          # heuristic 0..1, NOT a calibrated probability
    method: str                # text_layer | ocr
    bbox: Optional[tuple[int, int, int, int]] = None
    corrected_value: Optional[str] = None   # reviewer correction; original kept

    def effective(self) -> str:
        return self.corrected_value if self.corrected_value is not None else self.value


@dataclass
class CourseRowExtract:
    course: ExtractedField
    intake: Optional[ExtractedField] = None


@dataclass
class CourseRow:
    """A course line as entered by the applicant."""
    name: str
    intake: str   # raw text as entered; validated by rules, never trusted


@dataclass
class Application:
    id: str
    reference: str
    institution_name: str
    institution_id: str
    state: str
    address: str
    application_type: str
    courses: list[CourseRow] = field(default_factory=list)
    is_demo: bool = True


@dataclass
class EvidenceRef:
    document_id: str
    page: Optional[int] = None
    line_no: Optional[int] = None
    snippet: Optional[str] = None
    field: Optional[str] = None
    bbox: Optional[tuple[int, int, int, int]] = None


@dataclass
class Finding:
    rule_id: str
    rule_version: str
    title: str
    outcome: str
    severity: str
    application_id: str
    explanation: str
    recommended_action: str
    document_ids: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    observed: Optional[str] = None
    expected: Optional[str] = None
    confidence: Optional[float] = None
    evidence: list[EvidenceRef] = field(default_factory=list)
    limitations: Optional[str] = None
    reviewer_only: bool = False     # mentions other applications: never show to applicants
    finding_id: str = field(default_factory=lambda: new_id("FND"))
    processed_at: str = field(default_factory=utcnow_iso)

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"invalid outcome {self.outcome!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity {self.severity!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UploadIssue:
    code: str
    message: str


@dataclass
class ProcessedDocument:
    document_id: str
    application_id: str
    original_filename: str            # display only, never used as a path
    declared_type: Optional[str]
    status: str                       # processed | unreadable | rejected
    kind: Optional[str] = None        # pdf | png | jpeg
    size: int = 0
    sha256: Optional[str] = None
    detected_type: Optional[str] = None
    detected_confidence: float = 0.0
    errors: list[UploadIssue] = field(default_factory=list)
    warnings: list[UploadIssue] = field(default_factory=list)
    pages: list[PageContent] = field(default_factory=list)
    text_source: str = "none"         # text_layer | ocr | mixed | none
    ocr_mean_conf: Optional[float] = None
    fields: dict[str, list[ExtractedField]] = field(default_factory=dict)
    course_rows: list[CourseRowExtract] = field(default_factory=list)
    metadata: Optional[dict[str, Any]] = None
    metadata_signals: list[dict[str, str]] = field(default_factory=list)
    image_quality: Optional[dict[str, Any]] = None
    phash: Optional[int] = None
    text_fingerprint: Optional[str] = None
    shingles: frozenset = frozenset()

    @property
    def effective_type(self) -> Optional[str]:
        return self.declared_type or self.detected_type

    @property
    def full_text(self) -> str:
        return "\n".join(l.text for p in self.pages for l in p.lines)

    def primary(self, name: str) -> Optional[ExtractedField]:
        vals = self.fields.get(name) or []
        return vals[0] if vals else None
