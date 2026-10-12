"""Get paragraphs of text out of a page: natively from the PDF, or by OCR."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image

from .legacy import legacy_spans
from .normalize import normalize_text

DISPLAY_DPI = 110   # page images shown in the review screen
OCR_DPI = 300       # page images given to OCR

# Pixel caps (PLAN.md §12, "limits on memory"). A PDF can declare a page of any size,
# and some scanners store a 300 dpi scan as a 72 dpi page (A4 becomes 2480x3508 pt).
# Rendering such a page at a fixed DPI would need gigabytes, so the DPI is lowered
# until the image fits. 40 MP is A2 at 300 DPI.
DISPLAY_MAX_PIXELS = 8_000_000
DISPLAY_MAX_SIDE = 8_000
OCR_MAX_PIXELS = 40_000_000
OCR_MAX_SIDE = 12_000        # Tesseract refuses images with a side over 32767 px
MIN_ZOOM = 0.05              # never below ~4 DPI, even for absurd page sizes
# A page larger than this (in points, A3 is 842x1191) holding one big image is most
# likely a scan with a wrong DPI in the file: read it at the image's own resolution.
LARGE_PAGE_PT = 1400

# MuPDF character flags (fz_stext): how a glyph was drawn.
_FILLED, _STROKED, _CLIPPED = 16, 32, 64


@dataclass
class Block:
    text: str
    bbox: tuple[float, float, float, float] | None = None
    # Numbers in this block that two OCR readings disagreed on (OCR blocks only).
    uncertain_numbers: list[str] = field(default_factory=list)


# ---- the text layer ----------------------------------------------------------------------

def span_visible(span: dict) -> bool:
    """False for text a reader can't see: render mode 3 (the invisible text layer of a
    searchable scan), fully transparent text, and text clipped away."""
    if span.get("alpha", 255) == 0:
        return False
    flags = span.get("char_flags")
    if flags is None:          # older PyMuPDF: no per-glyph flags
        return True
    if flags & _CLIPPED:
        return False
    return bool(flags & (_FILLED | _STROKED))


@dataclass
class TextLine:
    block_no: int
    bbox: tuple[float, float, float, float]
    spans: list[dict]          # visible spans only


def text_lines(page: pymupdf.Page, *, include_invisible: bool = False) -> list[TextLine]:
    """The page's text lines in reading order, keeping only visible spans."""
    lines: list[TextLine] = []
    for block_no, block in enumerate(page.get_text("dict", sort=True)["blocks"]):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if include_invisible or span_visible(s)]
            if spans:
                lines.append(TextLine(block_no, tuple(line["bbox"]), spans))
    return lines


def legacy_span_keys(lines: list[TextLine]) -> tuple[set[tuple[int, int]], set[str]]:
    """(line index, span index) of spans in a legacy font, and those fonts' names."""
    return legacy_spans([[(s["font"], s["text"]) for s in line.spans] for line in lines])


def native_blocks(
    page: pymupdf.Page,
    *,
    exclude_legacy: bool = True,
    include_invisible: bool = False,
) -> list[Block]:
    """Paragraphs of the page's own text layer.

    Spans in a legacy font (Kruti Dev and similar) are left out by default: their text
    is Latin gibberish ("fcgkj ljdkj") that must never reach a translation. Invisible
    text (a scanner's hidden OCR layer) is left out too.
    """
    lines = text_lines(page, include_invisible=include_invisible)
    skip = legacy_span_keys(lines)[0] if exclude_legacy else set()
    grouped: dict[int, list[tuple[str, list[float]]]] = {}
    for li, line in enumerate(lines):
        kept = [s for si, s in enumerate(line.spans) if (li, si) not in skip]
        if not kept:
            continue
        text = "".join(s["text"] for s in kept)
        x0 = min(s["bbox"][0] for s in kept)
        y0 = min(s["bbox"][1] for s in kept)
        x1 = max(s["bbox"][2] for s in kept)
        y1 = max(s["bbox"][3] for s in kept)
        grouped.setdefault(line.block_no, []).append((text, [x0, y0, x1, y1]))

    blocks: list[Block] = []
    for block_no in sorted(grouped):
        parts = grouped[block_no]
        # Lines inside a block are wrapped lines of one paragraph.
        joined = " ".join(normalize_text("\n".join(text for text, _ in parts)).splitlines())
        if not joined.strip():
            continue
        boxes = [box for _, box in parts]
        bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))
        blocks.append(Block(joined, bbox))
    return blocks


# ---- page images -------------------------------------------------------------------------

def capped_zoom(width_pt: float, height_pt: float, dpi: float, max_pixels: int, max_side: int) -> float:
    """Zoom (pixels per point) for a page, lowered so the image stays within the caps."""
    zoom = dpi / 72.0
    if not (width_pt > 0 and height_pt > 0) or math.isinf(width_pt) or math.isinf(height_pt):
        return MIN_ZOOM
    zoom = min(zoom, math.sqrt(max_pixels / (width_pt * height_pt)))
    zoom = min(zoom, max_side / max(width_pt, height_pt))
    # MuPDF rounds the image size up to whole pixels; stay within the caps after that.
    while zoom > MIN_ZOOM and (
        math.ceil(width_pt * zoom) * math.ceil(height_pt * zoom) > max_pixels
        or math.ceil(max(width_pt, height_pt) * zoom) > max_side
    ):
        zoom *= 0.999
    return max(MIN_ZOOM, zoom)


def _native_scan_zoom(page: pymupdf.Page) -> float | None:
    """For an oversized page that is one big image, the image's own pixels per point."""
    rect = page.rect
    if max(rect.width, rect.height) <= LARGE_PAGE_PT:
        return None
    area = abs(rect)
    for info in page.get_image_info():
        bbox = pymupdf.Rect(info["bbox"]) & rect
        if area and abs(bbox) / area >= 0.9 and bbox.width > 0 and info.get("width"):
            return info["width"] / bbox.width
    return None


def render_png(page: pymupdf.Page, path: Path, dpi: int = DISPLAY_DPI) -> None:
    zoom = capped_zoom(page.rect.width, page.rect.height, dpi, DISPLAY_MAX_PIXELS, DISPLAY_MAX_SIDE)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(path))


def ocr_zoom(page: pymupdf.Page, dpi: int = OCR_DPI) -> float:
    """Zoom used for the OCR image of a page (see the pixel caps above)."""
    zoom = capped_zoom(page.rect.width, page.rect.height, dpi, OCR_MAX_PIXELS, OCR_MAX_SIDE)
    native = _native_scan_zoom(page)
    if native is not None:
        # The scan's own pixels carry all there is to read; upsampling a
        # wrongly-declared page to 300 DPI only multiplies memory.
        zoom = max(MIN_ZOOM, min(zoom, max(native, 1.0)))
    return zoom


def page_image(page: pymupdf.Page, dpi: int = OCR_DPI) -> Image.Image:
    """Greyscale page image for OCR, kept in memory only."""
    zoom = ocr_zoom(page, dpi)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples_mv)
    del pix
    return image
