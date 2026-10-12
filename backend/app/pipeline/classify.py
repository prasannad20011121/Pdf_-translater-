"""Decide how to read each PDF page (PLAN.md §3, §6.2).

Page kinds:
- unicode : real Hindi text in the PDF; use it if it passes the quality check
- legacy  : text in a legacy font (Kruti Dev, DevLys, Chanakya...) that copies out as
            Latin gibberish; converted in Phase 2, sent to OCR for now
- scan    : no usable text layer, only an image; needs OCR
- english : text with no Devanagari; copied through unchanged
- empty   : nothing on the page

Only visible text counts. A scanned page often carries a little text of its own (an
eOffice footer, a "Digitally signed by" stamp) or a hidden English OCR layer; such a
page is still a scan, and its Hindi must be read by OCR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from .extract import legacy_span_keys, text_lines
from .legacy import LEGACY_FONT, english_like
from .quality import QUALITY_THRESHOLD, assess

__all__ = ["LEGACY_FONT", "MIN_TEXT_CHARS", "PageInfo", "classify_page"]

MIN_TEXT_CHARS = 15
# This many letters in a legacy font make the whole page go to OCR (a Kruti Dev
# letterhead on a Unicode letter is enough). Fewer are dropped from native text.
LEGACY_MIN_LETTERS = 4
LEGACY_SHARE = 0.3
# A page counts as a scan when images cover at least this share of it and the
# visible text is sparse (fewer than SCAN_CHARS_PER_SQIN characters per square
# inch: ~290 on A4, where a typed page has 1500+).
SCAN_COVERAGE = 0.5
SCAN_CHARS_PER_SQIN = 3.0
# Images with no native text on them (pasted scans, photos of notices), as a share
# of the page. From UNREAD_IMAGE_OCR the whole page is read by OCR so nothing is
# missed; from UNREAD_IMAGE_NOTE the page gets a note.
UNREAD_IMAGE_OCR = 0.4
UNREAD_IMAGE_NOTE = 0.2
# An image with at least this share of its area under native text is a background.
BACKGROUND_TEXT_SHARE = 0.05
# Pages without text but with this many curved vector paths are most likely text
# converted to outlines (e.g. a notice made in CorelDRAW): read them by OCR.
OUTLINE_TEXT_PATHS = 30


@dataclass
class PageInfo:
    kind: str
    chars: int
    quality: float | None = None
    deva_ratio: float = 0.0
    legacy_fonts: list[str] = field(default_factory=list)
    image_coverage: float = 0.0
    legacy_chars: int = 0
    # Something the reader of the result should know about this page, e.g. that a
    # large image on a native-text page was not read.
    note: str = ""

    @property
    def needs_ocr(self) -> bool:
        if self.kind in ("scan", "legacy"):
            return True
        return self.kind == "unicode" and (self.quality or 0) < QUALITY_THRESHOLD


def _image_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    rects = []
    for info in page.get_image_info():
        bbox = pymupdf.Rect(info["bbox"]) & page.rect
        if not bbox.is_empty:
            rects.append(bbox)
    return rects


def _image_coverage(page: pymupdf.Page, rects: list[pymupdf.Rect] | None = None) -> float:
    area = abs(page.rect)
    if not area:
        return 0.0
    covered = sum(abs(r) for r in (rects if rects is not None else _image_rects(page)))
    return min(1.0, covered / area)


def _unread_image_share(page: pymupdf.Page, images: list[pymupdf.Rect], text_rects: list[pymupdf.Rect]) -> float:
    """Share of the page covered by images that have (almost) no native text on them.

    An image with text drawn over it is a background (a letterhead template, a faint
    emblem); an image without is a picture of its own, often a pasted scan.
    """
    area = abs(page.rect)
    if not area or not images:
        return 0.0
    unread = 0.0
    for img in images:
        size = abs(img)
        if not size:
            continue
        on_top = sum(abs(img & t) for t in text_rects)
        if on_top / size < BACKGROUND_TEXT_SHARE:
            unread += size
    return min(1.0, unread / area)


def _has_outlined_text(page: pymupdf.Page) -> bool:
    """Many filled curves and no text: glyphs drawn as vector outlines."""
    try:
        # get_cdrawings is the fast, C-level variant (same item tuples).
        paths = page.get_cdrawings() if hasattr(page, "get_cdrawings") else page.get_drawings()
    except Exception:
        return False
    curved = 0
    for path in paths:
        if any(item[0] in ("c", "qu") for item in path.get("items", [])):
            curved += 1
            if curved >= OUTLINE_TEXT_PATHS:
                return True
    return False


def classify_page(page: pymupdf.Page) -> PageInfo:
    lines = text_lines(page)                       # visible text only
    text = "\n".join("".join(s["text"] for s in line.spans) for line in lines)
    chars = len(re.sub(r"\s", "", text))
    images = _image_rects(page)
    coverage = _image_coverage(page, images)

    if chars == 0:
        if coverage > 0.2 or _has_outlined_text(page):
            return PageInfo(kind="scan", chars=0, image_coverage=coverage)
        return PageInfo(kind="empty", chars=0, image_coverage=coverage)

    # Legacy fonts, by name or by what their text looks like, span by span.
    legacy_keys, fonts = legacy_span_keys(lines)
    legacy_text = "".join(lines[li].spans[si]["text"] for li, si in legacy_keys)
    legacy_letters = sum(c.isascii() and c.isalpha() for c in legacy_text)
    legacy_chars = len(re.sub(r"\s", "", legacy_text))
    if legacy_letters >= LEGACY_MIN_LETTERS or legacy_chars / chars > LEGACY_SHARE:
        return PageInfo(kind="legacy", chars=chars, legacy_fonts=sorted(fonts), image_coverage=coverage,
                        legacy_chars=legacy_chars)

    q = assess(text)
    area_sqin = abs(page.rect) / (72 * 72)
    text_rects = [pymupdf.Rect(line.bbox) for line in lines]
    unread = _unread_image_share(page, images, text_rects)
    sparse = chars < SCAN_CHARS_PER_SQIN * area_sqin
    if coverage > 0.2 and chars < MIN_TEXT_CHARS:
        return PageInfo(kind="scan", chars=chars, image_coverage=coverage)
    if (coverage >= SCAN_COVERAGE and sparse) or unread >= UNREAD_IMAGE_OCR:
        # A scan with a footer, a stamp or a few typed lines of its own, or a typed
        # page with a large pasted scan: OCR reads both the text and the image.
        return PageInfo(kind="scan", chars=chars, image_coverage=coverage)
    if coverage >= SCAN_COVERAGE and q.deva_words == 0 and not english_like(text):
        # A visible but unreadable text layer (an English-only OCR of a Hindi scan).
        return PageInfo(kind="scan", chars=chars, image_coverage=coverage)

    note = ""
    if unread >= UNREAD_IMAGE_NOTE:
        note = "Part of this page is an image; text inside it was not read"
    if q.deva_words == 0 and q.garbage_tokens == 0:
        return PageInfo(kind="english", chars=chars, quality=1.0, deva_ratio=0.0, image_coverage=coverage,
                        note=note)
    return PageInfo(kind="unicode", chars=chars, quality=q.score, deva_ratio=q.deva_ratio,
                    image_coverage=coverage, note=note)
