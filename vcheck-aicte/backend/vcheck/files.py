"""Upload validation.

We never trust the extension or the client-supplied MIME type. The content is
sniffed from magic bytes, parsed defensively, and measured against limits.
Uploaded bytes are never executed. The user's filename is sanitised for display
only; on disk a file is stored under a generated name (see storage_name).
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import uuid
import warnings
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from .models import UploadIssue

logging.getLogger("pypdf").setLevel(logging.ERROR)
MAX_BYTES_DEFAULT = 10 * 1024 * 1024       # 10 MB: sensible for a demo
MAX_PAGES_DEFAULT = 50
MAX_IMAGE_PIXELS = 40_000_000              # blocks decompression bombs
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

ALLOWED_EXTENSIONS = {"pdf": {".pdf"}, "png": {".png"}, "jpeg": {".jpg", ".jpeg"}}

# Names that indicate active or embedded content inside a PDF. We only *flag*
# them for review; the PDF is never rendered or executed by this system.
ACTIVE_CONTENT_TOKENS = {
    b"/JavaScript": "PDF_ACTIVE_CONTENT", b"/JS": "PDF_ACTIVE_CONTENT",
    b"/Launch": "PDF_ACTIVE_CONTENT", b"/OpenAction": "PDF_ACTIVE_CONTENT",
    b"/EmbeddedFile": "PDF_EMBEDDED_FILE",
}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sniff_kind(raw: bytes) -> Optional[str]:
    head = raw[:1024]
    if b"%PDF-" in head[:8] or raw[:5] == b"%PDF-":
        return "pdf"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:3] == b"\xff\xd8\xff":
        return "jpeg"
    return None


def safe_display_name(name: str, max_len: int = 80) -> str:
    """Strip any path, keep a conservative character set. Display only."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    base = re.sub(r"_{2,}", "_", base)
    return (base or "file")[:max_len]


def storage_name(kind: str) -> str:
    """Name used on disk: random, extension derived from sniffed kind."""
    ext = {"pdf": "pdf", "png": "png", "jpeg": "jpg"}[kind]
    return f"{uuid.uuid4().hex}.{ext}"


@dataclass
class UploadCheck:
    ok: bool
    kind: Optional[str] = None
    sha256: Optional[str] = None
    size: int = 0
    display_name: str = "file"
    errors: list[UploadIssue] = field(default_factory=list)
    warnings: list[UploadIssue] = field(default_factory=list)


def validate_upload(raw: bytes, filename: str, max_bytes: int = MAX_BYTES_DEFAULT,
                    max_pages: int = MAX_PAGES_DEFAULT) -> UploadCheck:
    res = UploadCheck(ok=False, size=len(raw or b""), display_name=safe_display_name(filename))
    err = lambda c, m: res.errors.append(UploadIssue(c, m))   # noqa: E731
    if not raw:
        err("EMPTY_FILE", "The file is empty.")
        return res
    if len(raw) > max_bytes:
        err("TOO_LARGE", f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit.")
        return res
    res.sha256 = sha256_bytes(raw)
    kind = sniff_kind(raw)
    if kind is None:
        err("UNSUPPORTED_TYPE", "Only PDF, PNG and JPEG files are accepted. The file content is not one of these.")
        return res
    ext = "." + res.display_name.rsplit(".", 1)[-1].lower() if "." in res.display_name else ""
    if ext not in ALLOWED_EXTENSIONS[kind]:
        err("EXTENSION_MISMATCH",
            f"The file name ends in '{ext or 'nothing'}' but the content is {kind.upper()}. Rename or re-export the file.")
        return res
    res.kind = kind
    if kind == "pdf":
        _check_pdf(raw, res, max_pages)
    else:
        _check_image(raw, res)
    res.ok = not res.errors
    return res


def _check_pdf(raw: bytes, res: UploadCheck, max_pages: int) -> None:
    try:
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            res.errors.append(UploadIssue("ENCRYPTED_PDF",
                              "The PDF is password-protected. Upload an unprotected copy."))
            return
        n = len(reader.pages)
        if n == 0:
            raise ValueError("no pages")
        if n > max_pages:
            res.errors.append(UploadIssue("TOO_MANY_PAGES", f"The PDF has {n} pages; the limit is {max_pages}."))
            return
        reader.pages[0].mediabox          # touches the first page object
        reader.pages[0].extract_text()    # forces content-stream parsing
    except Exception:
        res.errors.append(UploadIssue("CORRUPT_PDF", "The PDF could not be read. It may be damaged or incomplete."))
        return
    seen = set()
    for token, code in ACTIVE_CONTENT_TOKENS.items():
        if token in raw and code not in seen:
            seen.add(code)
            msg = ("The PDF contains an embedded file." if code == "PDF_EMBEDDED_FILE"
                   else "The PDF contains script or auto-run actions. They are never executed here; flagged for review.")
            res.warnings.append(UploadIssue(code, msg))


def _check_image(raw: bytes, res: UploadCheck) -> None:
    try:
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)   # we enforce our own explicit limit below
        with Image.open(io.BytesIO(raw)) as im:
            w, h = im.size
            if w * h > MAX_IMAGE_PIXELS:
                res.errors.append(UploadIssue("IMAGE_TOO_LARGE",
                                  "The image has too many pixels to process safely."))
                return
            im.verify()
        with Image.open(io.BytesIO(raw)) as im:   # verify() invalidates the handle
            im.load()
    except Image.DecompressionBombError:
        res.errors.append(UploadIssue("IMAGE_TOO_LARGE", "The image has too many pixels to process safely."))
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        res.errors.append(UploadIssue("CORRUPT_IMAGE", "The image could not be read. It may be damaged."))
