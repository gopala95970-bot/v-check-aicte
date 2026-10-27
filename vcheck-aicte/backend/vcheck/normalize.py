"""Normalisation helpers. Pure functions.

Policy: normalise only for *comparison*. The original text is always kept, and
a normalised match is reported as such (never as an exact match) so a reviewer
can see that formatting differences were smoothed over.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Optional

# Explicit, documented abbreviation table. Deliberately small: every entry is a
# judgement call, so we keep the list auditable rather than clever.
ABBREVIATIONS = {
    "inst": "institute", "instt": "institute", "tech": "technology",
    "technol": "technology", "engg": "engineering", "eng": "engineering",
    "coll": "college", "univ": "university", "mgmt": "management",
    "govt": "government", "dept": "department", "sci": "science",
    "pvt": "private", "ltd": "limited",
}
# Words dropped when comparing names (they carry no identifying information).
STOPWORDS = {"the", "of", "and"}

# Characters OCR commonly confuses; used ONLY to flag a "possible OCR
# confusion" for human review, never to declare a match.
OCR_CONFUSABLE = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.casefold().replace("&", " and ")
    return s


def normalize_text(s: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    s = re.sub(r"[\W_]+", " ", _fold(s))
    return " ".join(s.split())


def normalize_name(s: str) -> str:
    tokens = normalize_text(s).split()
    tokens = [ABBREVIATIONS.get(t, t) for t in tokens]
    return " ".join(t for t in tokens if t not in STOPWORDS)


def normalize_id(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").upper()
    return re.sub(r"[^A-Z0-9]", "", s)


def ocr_canonical_id(s: str) -> str:
    return normalize_id(s).translate(OCR_CONFUSABLE)


# ---------------------------------------------------------------- dates
_MONTHS = {}
for _i, _name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1):
    _MONTHS[_name] = _i
    _MONTHS[_name[:3]] = _i
_MONTHS["sept"] = 9


@dataclass(frozen=True)
class ParsedDate:
    ok: bool
    value: Optional[date] = None
    reason: Optional[str] = None   # unrecognised_format | calendar_invalid | empty


def _mk(y: int, m: int, d: int) -> ParsedDate:
    try:
        return ParsedDate(True, date(y, m, d))
    except ValueError:
        return ParsedDate(False, None, "calendar_invalid")


def parse_date(raw: Optional[str]) -> ParsedDate:
    """Parse the date formats seen on Indian official documents.

    Numeric day/month/year is read DAY-FIRST (DD/MM/YYYY), the Indian
    convention. Two-digit years are rejected as ambiguous.
    """
    s = (raw or "").strip()
    if not s:
        return ParsedDate(False, None, "empty")
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{4})", s)
    if m:
        return _mk(int(m[3]), int(m[2]), int(m[1]))
    m = re.fullmatch(r"(\d{1,2})[-/. ]+([A-Za-z]{3,9})\.?[-/ ,.]*(\d{4})", s)
    if m and m[2].lower() in _MONTHS:
        return _mk(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m[1].lower() in _MONTHS:
        return _mk(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))
    return ParsedDate(False, None, "unrecognised_format")


# -------------------------------------------------------------- numbers
@dataclass(frozen=True)
class ParsedInt:
    ok: bool
    value: Optional[int] = None
    reason: Optional[str] = None   # empty | not_a_number | not_positive | too_large


def parse_intake(raw: Optional[str], max_value: int = 5000) -> ParsedInt:
    s = (raw or "").strip()
    if not s:
        return ParsedInt(False, None, "empty")
    # plain digits, western grouping (1,200) or Indian grouping (1,20,000);
    # anything else such as "1,20" is rejected rather than guessed at.
    m = re.match(r"^(\d+|\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3})(?:\s*\(.*\))?$", s)
    if not m:
        return ParsedInt(False, None, "not_a_number")
    v = int(m[1].replace(",", ""))
    if v <= 0:
        return ParsedInt(False, v, "not_positive")
    if v > max_value:
        return ParsedInt(False, v, "too_large")
    return ParsedInt(True, v)


def parse_academic_year(raw: Optional[str]) -> Optional[tuple[int, int]]:
    m = re.fullmatch(r"\s*(\d{4})\s*[-/]\s*(\d{2}|\d{4})\s*", raw or "")
    if not m:
        return None
    start = int(m[1])
    end = int(m[2]) if len(m[2]) == 4 else (start // 100) * 100 + int(m[2])
    return (start, end) if end == start + 1 else None
