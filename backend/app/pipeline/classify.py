"""Decide how to read each PDF page (PLAN.md §3, §6.2).

Page kinds:
- unicode : real Hindi text in the PDF; use it if it passes the quality check
- legacy  : text in a legacy font (Kruti Dev, DevLys, Chanakya...) that copies out as
            Latin gibberish; converted in Phase 2, sent to OCR for now
- scan    : no usable text layer, only an image; needs OCR
- english : text with no Devanagari; copied through unchanged
- empty   : nothing on the page
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from .quality import QUALITY_THRESHOLD, assess

LEGACY_FONT = re.compile(
    r"kruti|devlys|dev[\s_-]?lys|chanakya|walkman|shusha|aps[\s_-]?dv|akruti|dv[\s_-]?tt|agra|shivaji",
    re.IGNORECASE,
)

MIN_TEXT_CHARS = 15


@dataclass
class PageInfo:
    kind: str
    chars: int
    quality: float | None = None
    deva_ratio: float = 0.0
    legacy_fonts: list[str] = field(default_factory=list)
    image_coverage: float = 0.0

    @property
    def needs_ocr(self) -> bool:
        if self.kind in ("scan", "legacy"):
            return True
        return self.kind == "unicode" and (self.quality or 0) < QUALITY_THRESHOLD


def _image_coverage(page: pymupdf.Page) -> float:
    area = abs(page.rect)
    if not area:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        bbox = pymupdf.Rect(info["bbox"]) & page.rect
        covered += abs(bbox)
    return min(1.0, covered / area)


def classify_page(page: pymupdf.Page) -> PageInfo:
    text = page.get_text("text", sort=True)
    chars = len(re.sub(r"\s", "", text))
    coverage = _image_coverage(page)

    if chars < MIN_TEXT_CHARS:
        kind = "scan" if coverage > 0.2 else "empty"
        return PageInfo(kind=kind, chars=chars, image_coverage=coverage)

    legacy_chars = 0
    legacy_fonts: set[str] = set()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if LEGACY_FONT.search(span["font"]):
                    legacy_chars += len(span["text"].strip())
                    legacy_fonts.add(span["font"])
    if legacy_chars / max(chars, 1) > 0.3:
        return PageInfo(kind="legacy", chars=chars, legacy_fonts=sorted(legacy_fonts), image_coverage=coverage)

    q = assess(text)
    if q.deva_words == 0 and q.garbage_tokens == 0:
        return PageInfo(kind="english", chars=chars, quality=1.0, deva_ratio=0.0, image_coverage=coverage)
    return PageInfo(kind="unicode", chars=chars, quality=q.score, deva_ratio=q.deva_ratio, image_coverage=coverage)
