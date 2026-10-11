"""Tesseract OCR (hin+eng) on a page image.

Tesseract runs as a separate program per call, so it holds no memory between pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import pytesseract
from PIL import Image

from ..extract import Block
from ..normalize import normalize_text

LANGS = "hin+eng"


@lru_cache(maxsize=4)
def available(cmd: str | None) -> bool:
    if not cmd:
        return False
    pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        return False
    return "hin" in langs


@dataclass
class OcrResult:
    blocks: list[Block]
    mean_confidence: float


def ocr_image(image: Image.Image, cmd: str, psm: int = 3) -> OcrResult:
    pytesseract.pytesseract.tesseract_cmd = cmd
    data = pytesseract.image_to_data(
        image, lang=LANGS, config=f"--psm {psm}", output_type=pytesseract.Output.DICT
    )
    paragraphs: dict[tuple[int, int], dict[int, list[str]]] = {}
    boxes: dict[tuple[int, int], list[int]] = {}
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue
        conf = float(data["conf"][i])
        if conf >= 0:
            confidences.append(conf)
        key = (data["block_num"][i], data["par_num"][i])
        paragraphs.setdefault(key, {}).setdefault(data["line_num"][i], []).append(word)
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        box = boxes.setdefault(key, [x, y, x + w, y + h])
        box[0], box[1] = min(box[0], x), min(box[1], y)
        box[2], box[3] = max(box[2], x + w), max(box[3], y + h)

    blocks: list[Block] = []
    for key in sorted(paragraphs):
        lines = paragraphs[key]
        text = normalize_text(" ".join(" ".join(lines[n]) for n in sorted(lines)))
        if text:
            x0, y0, x1, y1 = boxes[key]
            blocks.append(Block(text, (x0, y0, x1, y1)))
    mean = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrResult(blocks, mean)
