"""Duplicate and reuse analysis.

Three independent signals, none of which proves forgery:

* exact      identical SHA-256 -> byte-identical file
* text       Jaccard similarity of word 4-gram shingles of normalised text
* image      64-bit difference hash (dHash) Hamming distance

Limitation worth stating: documents from the same issuer often share template
wording, so text similarity alone is expected to be high between *different*
genuine documents. Callers combine it with identifier overlap before flagging.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
from PIL import Image, ImageOps

from .normalize import normalize_text

SHINGLE_SIZE = 4


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def shingles(text: str, size: int = SHINGLE_SIZE) -> frozenset:
    toks = normalize_text(text).split()
    if len(toks) < size:
        return frozenset([" ".join(toks)]) if toks else frozenset()
    return frozenset(" ".join(toks[i:i + size]) for i in range(len(toks) - size + 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dhash(img: Image.Image, hash_size: int = 8) -> int:
    g = ImageOps.exif_transpose(img).convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    px = np.asarray(g, dtype=int).flatten().tolist()   # numpy: stable across Pillow versions
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            bits = (bits << 1) | (px[row * (hash_size + 1) + col] > px[row * (hash_size + 1) + col + 1])
    return bits


def dhash_bytes(raw: bytes) -> Optional[int]:
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            return dhash(im)
    except Exception:
        return None


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


@dataclass(frozen=True)
class CorpusEntry:
    """What we remember about a document from another application."""
    application_id: str
    document_id: str
    app_institution_id: Optional[str]   # the applying institution's id
    sha256: Optional[str]
    text_fingerprint: Optional[str]
    shingles: frozenset
    certificate_numbers: tuple
    phash: Optional[int] = None


def corpus_entry_from(doc, application) -> CorpusEntry:
    certs = tuple(f.effective() for f in doc.fields.get("certificate_number", []))
    return CorpusEntry(doc.application_id, doc.document_id, application.institution_id,
                       doc.sha256, doc.text_fingerprint, doc.shingles, certs, doc.phash)
