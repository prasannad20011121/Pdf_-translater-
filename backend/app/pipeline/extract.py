"""Get paragraphs of text out of a page: natively from the PDF, or by OCR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image

from .normalize import normalize_text

DISPLAY_DPI = 110   # page images shown in the review screen
OCR_DPI = 300       # page images given to OCR


@dataclass
class Block:
    text: str
    bbox: tuple[float, float, float, float] | None = None


def native_blocks(page: pymupdf.Page) -> list[Block]:
    blocks: list[Block] = []
    for x0, y0, x1, y1, text, _no, block_type in page.get_text("blocks", sort=True):
        if block_type != 0:  # 1 = image block
            continue
        # Lines inside a block are wrapped lines of one paragraph.
        joined = " ".join(normalize_text(text).splitlines())
        if joined.strip():
            blocks.append(Block(joined, (x0, y0, x1, y1)))
    return blocks


def render_png(page: pymupdf.Page, path: Path, dpi: int = DISPLAY_DPI) -> None:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(path))


def page_image(page: pymupdf.Page, dpi: int = OCR_DPI) -> Image.Image:
    """Greyscale page image for OCR, kept in memory only."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    return Image.frombytes("L", (pix.width, pix.height), pix.samples)
