"""Shared fixtures: an isolated data folder and generated Hindi test PDFs."""

from __future__ import annotations

import os
from pathlib import Path

import pymupdf
import pytest

LETTER = [
    "बिहार स्टेट इलेक्ट्रॉनिक्स डेवलपमेंट कॉरपोरेशन लिमिटेड",
    "ज्ञापांक-1234/2026, दिनांक 12.03.2026",
    "सेवा में, सभी पैनलबद्ध एजेंसियाँ।",
    "विषय: निविदा की अंतिम तिथि में विस्तार के संबंध में।",
    "उपर्युक्त विषय के संबंध में सूचित करना है कि निविदा की अंतिम तिथि 25.03.2026 तक बढ़ाई गई है। "
    "अग्रधन राशि Rs. 5,00,000/- पूर्ववत रहेगी।",
    "आदेश से, प्रबंध निदेशक",
]

ENGLISH = [
    "Annexure A: Technical Specifications",
    "The bidder shall submit the proposal on the GeM portal before the due date.",
]


def _deva_font_file(tmp: Path) -> Path:
    """MuPDF ships Noto Serif Devanagari; save it so we can embed it with insert_text."""
    path = tmp / "NotoSerifDevanagari.ttf"
    if not path.exists():
        path.write_bytes(pymupdf.Font(script=9).buffer)  # 9 = Devanagari
    return path


def make_clean_pdf(path: Path, paragraphs: list[str]) -> Path:
    """Text that extracts correctly (logical order). Glyphs aren't shaped, which is fine for tests."""
    font = _deva_font_file(path.parent)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="deva", fontfile=str(font))
    y = 72
    for para in paragraphs:
        # One paragraph per text block; wrap long ones manually.
        words, line = para.split(), ""
        for w in words:
            if len(line) + len(w) > 70:
                page.insert_text((60, y), line, fontname="deva", fontsize=11)
                y += 16
                line = ""
            line = f"{line} {w}".strip()
        page.insert_text((60, y), line, fontname="deva", fontsize=11)
        y += 34
    doc.save(str(path))
    return path


def make_broken_pdf(path: Path, paragraphs: list[str]) -> Path:
    """Properly shaped Hindi whose text layer extracts with garbled vowel signs."""
    doc = pymupdf.open()
    page = doc.new_page()
    html = "".join(f"<p style='margin-bottom:14px'>{p}</p>" for p in paragraphs)
    page.insert_htmlbox(pymupdf.Rect(60, 60, 540, 780), html, css="* {font-size: 13px;}")
    doc.save(str(path))
    return path


def make_scanned_pdf(path: Path, paragraphs: list[str]) -> Path:
    """A page that is only an image of (correctly shaped) Hindi text."""
    shaped = make_broken_pdf(path.with_suffix(".src.pdf"), paragraphs)
    src = pymupdf.open(str(shaped))
    pix = src[0].get_pixmap(dpi=200)
    doc = pymupdf.open()
    page = doc.new_page(width=src[0].rect.width, height=src[0].rect.height)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    doc.save(str(path))
    return path


def make_english_pdf(path: Path, paragraphs: list[str]) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for para in paragraphs:
        page.insert_text((60, y), para, fontsize=11)
        y += 30
    doc.save(str(path))
    return path


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Point the app at a temporary data folder and the dev profile."""
    monkeypatch.setenv("PDFT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PDFT_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("PDFT_PROFILE", os.environ.get("PDFT_TEST_PROFILE", "dev"))
    monkeypatch.setenv("PDFT_DEV_DELAY", "0")
    from app import config, db

    config.reset_settings_cache()
    db.reset_engine()
    yield config.get_settings()
    db.reset_engine()
    config.reset_settings_cache()


@pytest.fixture()
def pdfs(tmp_path) -> dict[str, Path]:
    d = tmp_path / "pdfs"
    d.mkdir()
    return {
        "clean": make_clean_pdf(d / "clean.pdf", LETTER),
        "broken": make_broken_pdf(d / "broken.pdf", LETTER),
        "scan": make_scanned_pdf(d / "scan.pdf", LETTER),
        "english": make_english_pdf(d / "english.pdf", ENGLISH),
    }
