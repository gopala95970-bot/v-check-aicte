"""Field comparison.

Every comparison returns one of four outcomes:

  match        equal, or equal after documented normalisation
  probable     similar but not equal -> a human must look (never auto-accepted)
  mismatch     clearly different
  unavailable  one side is blank, so nothing can be concluded
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from .normalize import (normalize_id, normalize_name, ocr_canonical_id,
                        parse_date)

MATCH, PROBABLE, MISMATCH, UNAVAILABLE = "match", "probable", "mismatch", "unavailable"

# Words that name *what kind* of institution it is. If both names have a
# different one of these, they are treated as different institutions rather
# than as a spelling variation ("... College of Engineering" vs "... College of Pharmacy").
DISCRIMINATORS = {
    "engineering", "pharmacy", "management", "technology", "polytechnic",
    "medical", "law", "arts", "science", "architecture", "nursing",
    "education", "commerce", "agriculture", "dental", "hotel",
}


@dataclass(frozen=True)
class MatchResult:
    outcome: str
    score: float
    method: str
    left_norm: str = ""
    right_norm: str = ""
    note: str = ""


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def compare_names(a: Optional[str], b: Optional[str], probable_threshold: float = 0.80) -> MatchResult:
    if not (a or "").strip() or not (b or "").strip():
        return MatchResult(UNAVAILABLE, 0.0, "blank", note="one side is blank")
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return MatchResult(UNAVAILABLE, 0.0, "blank", na, nb, "nothing left after normalisation")
    if a.strip() == b.strip():
        return MatchResult(MATCH, 1.0, "exact", na, nb)
    if na == nb:
        return MatchResult(MATCH, 1.0, "normalized_equal", na, nb,
                           "equal after normalising case, punctuation or abbreviations")
    ta, tb = set(na.split()), set(nb.split())
    only_a, only_b = ta - tb, tb - ta
    if only_a & DISCRIMINATORS and only_b & DISCRIMINATORS:
        return MatchResult(MISMATCH, 0.0, "discriminator_conflict", na, nb,
                           "the names carry different institution-type words")
    score = max(SequenceMatcher(None, na, nb).ratio(),
                SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio())
    if ta <= tb or tb <= ta:
        score = max(score, probable_threshold)
    if score >= probable_threshold:
        return MatchResult(PROBABLE, round(score, 3), "similar", na, nb,
                           "similar but not identical; may be a spelling variation or a different entity")
    return MatchResult(MISMATCH, round(score, 3), "different", na, nb)


def compare_ids(a: Optional[str], b: Optional[str]) -> MatchResult:
    if not (a or "").strip() or not (b or "").strip():
        return MatchResult(UNAVAILABLE, 0.0, "blank", note="one side is blank")
    na, nb = normalize_id(a), normalize_id(b)
    if not na or not nb:
        return MatchResult(UNAVAILABLE, 0.0, "blank", na, nb)
    if a.strip() == b.strip():
        return MatchResult(MATCH, 1.0, "exact", na, nb)
    if na == nb:
        return MatchResult(MATCH, 1.0, "format_variation", na, nb,
                           "same characters, different separators or case")
    if ocr_canonical_id(a) == ocr_canonical_id(b):
        return MatchResult(PROBABLE, 0.9, "ocr_confusable", na, nb,
                           "differs only in characters OCR often confuses (e.g. O/0, I/1)")
    if len(na) == len(nb) and levenshtein(na, nb) == 1:
        return MatchResult(PROBABLE, 0.85, "one_char_difference", na, nb,
                           "differs by a single character; could be a misread or a different identifier")
    return MatchResult(MISMATCH, 0.0, "different", na, nb)


def compare_ints(a: Optional[int], b: Optional[int]) -> MatchResult:
    if a is None or b is None:
        return MatchResult(UNAVAILABLE, 0.0, "blank", note="one side is missing or invalid")
    return MatchResult(MATCH if a == b else MISMATCH, 1.0 if a == b else 0.0, "numeric", str(a), str(b))


def compare_dates(a: Optional[str], b: Optional[str]) -> MatchResult:
    pa, pb = parse_date(a), parse_date(b)
    if not (pa.ok and pb.ok):
        return MatchResult(UNAVAILABLE, 0.0, "unparseable", note="a date could not be parsed")
    same = pa.value == pb.value
    return MatchResult(MATCH if same else MISMATCH, 1.0 if same else 0.0, "date",
                       pa.value.isoformat(), pb.value.isoformat())
