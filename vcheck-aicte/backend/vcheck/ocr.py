"""Text extraction.

* Digital PDFs: text layer via pypdf (pure Python, no build tools needed on
  Windows). PyMuPDF can be added later for vector-page rendering.
* Scanned PDFs: the embedded page images are extracted with pypdf and OCR'd.
* PNG/JPEG: OCR directly.

OCR = Tesseract (pytesseract) with OpenCV preprocessing. Tesseract is an
external program; if it is missing we raise OCRUnavailable and the caller
degrades to "unreadable -> manual review" instead of crashing.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageOps
from pypdf import PdfReader

from .models import Line, PageContent

MIN_TEXT_CHARS = 20          # below this a PDF page is treated as image-only
TEXT_LAYER_CONF = 0.95       # heuristic confidence for embedded text
OCR_TIMEOUT_S = 30           # per Tesseract call; slow machines degrade to "unreadable", never hang
GOOD_ENOUGH_CONF = 0.90      # skip the second preprocessing variant when the first is already this good

# Image-quality thresholds are heuristics calibrated only on our synthetic data.
LOW_RES_MIN_SIDE = 700
BLUR_LAPLACIAN_VAR = 60.0
DARK_MEAN = 70
LOW_CONTRAST_STD = 25


logging.getLogger("pypdf").setLevel(logging.ERROR)


class OCRUnavailable(RuntimeError):
    pass


class OCRTimeout(RuntimeError):
    pass


def _tesseract():
    try:
        import pytesseract
        if os.environ.get("TESSERACT_CMD"):      # e.g. C:\\Program Files\\Tesseract-OCR\\tesseract.exe
            pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
        pytesseract.get_tesseract_version()
        return pytesseract
    except Exception as exc:   # missing binary or package
        raise OCRUnavailable("Tesseract OCR is not installed or not on PATH") from exc


def _to_gray(img: Image.Image) -> np.ndarray:
    img = ImageOps.exif_transpose(img).convert("L")
    return np.array(img)


def image_quality(gray: np.ndarray) -> dict:
    h, w = gray.shape[:2]
    # median filter first so salt-and-pepper noise does not masquerade as sharpness
    lap = float(cv2.Laplacian(cv2.medianBlur(gray, 3), cv2.CV_64F).var())
    mean, std = float(gray.mean()), float(gray.std())
    flags = []
    if min(h, w) < LOW_RES_MIN_SIDE:
        flags.append("low_resolution")
    if lap < BLUR_LAPLACIAN_VAR:
        flags.append("blurry")
    if mean < DARK_MEAN:
        flags.append("dark")
    if std < LOW_CONTRAST_STD:
        flags.append("low_contrast")
    return {"width": w, "height": h, "sharpness": round(lap, 1),
            "brightness": round(mean, 1), "contrast": round(std, 1), "flags": flags}


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Straighten small rotations (<= 10 degrees). Leaves the image alone if unsure."""
    inv = cv2.threshold(cv2.GaussianBlur(gray, (3, 3), 0), 0, 255,
                        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(inv > 0))
    if len(coords) < 200:
        return gray
    angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))[-1]
    angle = angle - 90 if angle > 45 else angle
    if angle < -45:
        angle += 90
    if abs(angle) < 0.3 or abs(angle) > 10:
        return gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _candidates(gray: np.ndarray) -> list[tuple[str, np.ndarray, float]]:
    scale = 1.0
    if min(gray.shape) < 1400:
        scale = 1400 / min(gray.shape)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = _deskew(gray)
    otsu = cv2.threshold(cv2.GaussianBlur(gray, (3, 3), 0), 0, 255,
                         cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return [("gray", gray, scale), ("otsu", otsu, scale)]


def _run_tesseract(pt, arr: np.ndarray, scale: float) -> tuple[list[Line], float]:
    try:
        data = pt.image_to_data(Image.fromarray(arr), config="--psm 6",
                                output_type=pt.Output.DICT, timeout=OCR_TIMEOUT_S)
    except RuntimeError as exc:
        if "timeout" in str(exc).lower():
            raise OCRTimeout(f"OCR did not finish within {OCR_TIMEOUT_S} seconds") from exc
        raise
    groups: dict[tuple, list[int]] = {}
    for i, txt in enumerate(data["text"]):
        if not (txt or "").strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        groups.setdefault(key, []).append(i)
    lines, confs = [], []
    for key in sorted(groups, key=lambda k: (min(data["top"][i] for i in groups[k]),
                                             min(data["left"][i] for i in groups[k]))):
        idx = groups[key]
        words = [data["text"][i] for i in sorted(idx, key=lambda i: data["left"][i])]
        wc = [float(data["conf"][i]) for i in idx if float(data["conf"][i]) >= 0]
        conf = (sum(wc) / len(wc) / 100.0) if wc else 0.0
        x0 = min(data["left"][i] for i in idx)
        y0 = min(data["top"][i] for i in idx)
        x1 = max(data["left"][i] + data["width"][i] for i in idx)
        y1 = max(data["top"][i] + data["height"][i] for i in idx)
        bbox = tuple(int(v / scale) for v in (x0, y0, x1, y1))
        lines.append(Line(" ".join(words), round(conf, 3), bbox))
        confs.append(conf)
    mean = sum(confs) / len(confs) if confs else 0.0
    return lines, mean


def ocr_image(img: Image.Image) -> tuple[list[Line], float, dict]:
    """OCR one image. Returns (lines, mean_confidence 0..1, quality)."""
    pt = _tesseract()
    gray = _to_gray(img)
    quality = image_quality(gray)
    best: Optional[tuple[list[Line], float]] = None
    for _name, arr, scale in _candidates(gray):
        lines, mean = _run_tesseract(pt, arr, scale)
        if best is None or mean > best[1]:
            best = (lines, mean)
        if best[1] >= GOOD_ENOUGH_CONF:
            break
    assert best is not None
    return best[0], best[1], quality


def _lines_from_text(text: str) -> list[Line]:
    return [Line(t.strip(), TEXT_LAYER_CONF) for t in text.splitlines() if t.strip()]


def read_pdf(raw: bytes, max_pages: int = 50) -> tuple[list[PageContent], list[dict]]:
    """Return per-page content and per-page image quality (for scanned pages)."""
    reader = PdfReader(io.BytesIO(raw), strict=False)
    pages, qualities = [], []
    for i, page in enumerate(reader.pages[:max_pages], start=1):
        text = ""
        try:
            text = page.extract_text() or ""
        except Exception:
            pass
        if len(text.strip()) >= MIN_TEXT_CHARS:
            pages.append(PageContent(i, "text_layer", _lines_from_text(text), TEXT_LAYER_CONF))
            continue
        lines: list[Line] = []
        confs: list[float] = []
        notes: list[str] = []
        try:
            images = list(page.images)
        except Exception:
            images = []
            notes.append("page images could not be extracted")
        if not images:
            notes.append("no text layer and no embedded image")
        for im in images:
            try:
                lns, mean, q = ocr_image(im.image)
            except (OCRUnavailable, OCRTimeout):
                raise
            except Exception:
                notes.append("an embedded image could not be OCR'd")
                continue
            lines.extend(lns)
            confs.append(mean)
            qualities.append({"page": i, **q})
        src = "ocr" if lines else "none"
        pages.append(PageContent(i, src, lines, sum(confs) / len(confs) if confs else None, notes))
    return pages, qualities


def read_image(raw: bytes) -> tuple[list[PageContent], list[dict]]:
    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        lines, mean, q = ocr_image(im)
    src = "ocr" if lines else "none"
    return [PageContent(1, src, lines, mean)], [{"page": 1, **q}]
