"""Page classification, legacy fonts, invisible text and render size limits."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from conftest import LETTER, make_clean_pdf, make_scanned_pdf

from app.pipeline import extract
from app.pipeline.classify import classify_page
from app.pipeline.extract import native_blocks, page_image, render_png
from app.pipeline.legacy import english_like, legacy_font_names, looks_like_legacy

KRUTI_LINES = [
    "fcgkj ljdkj] lwpuk izkoS/kfdh foHkkx",            # बिहार सरकार, सूचना प्रावैधिकी विभाग
    "Kkikad&1234@2026] fnukad 12-03-2026",              # ज्ञापांक-1234/2026, दिनांक 12.03.2026
    "mi;qZDr fo\"k; ds laca/k esa lwfpr djuk gS fd fufonk dh vafre frfFk c<+kbZ xbZ gSA",
]


def rename_font(doc: pymupdf.Document, page: pymupdf.Page, contains: str, new_name: str) -> None:
    """Give a font on the page another BaseFont name, as legacy-font PDFs have."""
    for xref, _ext, _type, base, *_ in page.get_fonts():
        if contains.lower() in base.lower():
            doc.xref_set_key(xref, "BaseFont", f"/{new_name}")


def reopen(doc: pymupdf.Document, path: Path) -> pymupdf.Page:
    doc.save(str(path))
    return pymupdf.open(str(path))[0]


@pytest.fixture()
def scan(tmp_path) -> Path:
    return make_scanned_pdf(tmp_path / "scan.pdf", LETTER)


@pytest.fixture()
def clean(tmp_path) -> Path:
    return make_clean_pdf(tmp_path / "clean.pdf", LETTER)


# ---- scans that carry some text of their own (finding 6) ------------------------------------

def test_scan_with_eoffice_footer_is_still_a_scan(scan, tmp_path):
    doc = pymupdf.open(str(scan))
    doc[0].insert_text((40, 830), "Generated from eOffice by RAKESH KUMAR, on 12/03/2026 05:30 PM", fontsize=7)
    info = classify_page(reopen(doc, tmp_path / "footer.pdf"))
    assert info.kind == "scan" and info.needs_ocr


def test_scan_with_invisible_english_ocr_layer_is_a_scan(scan, tmp_path):
    doc = pymupdf.open(str(scan))
    for i in range(30):
        doc[0].insert_text((60, 80 + i * 20), "Notice regarding the tender extension 1234/2026", fontsize=11,
                           render_mode=3)
    page = reopen(doc, tmp_path / "hidden.pdf")
    info = classify_page(page)
    assert info.kind == "scan" and info.needs_ocr
    assert native_blocks(page) == []   # invisible text never becomes a segment


def test_scan_with_visible_garbage_text_layer_is_a_scan(scan, tmp_path):
    # An English-only OCR of a Hindi scan reads as nonsense, even when visible.
    doc = pymupdf.open(str(scan))
    for i in range(30):
        doc[0].insert_text((60, 80 + i * 20), "fae te saeciiaa sacate aieakerd fees Wath-1234/2026 feAiH",
                           fontsize=11)
    assert classify_page(reopen(doc, tmp_path / "garbage.pdf")).kind == "scan"


def test_typed_page_with_large_pasted_scan_is_ocred(clean, scan, tmp_path):
    picture = pymupdf.open(str(scan))[0].get_pixmap(dpi=40).tobytes("png")
    doc = pymupdf.open(str(clean))
    doc[0].insert_image(pymupdf.Rect(0, 280, 595, 842), stream=picture, keep_proportion=False)
    assert classify_page(reopen(doc, tmp_path / "pasted.pdf")).kind == "scan"


def test_typed_page_with_medium_pasted_image_gets_a_note(clean, scan, tmp_path):
    picture = pymupdf.open(str(scan))[0].get_pixmap(dpi=40).tobytes("png")
    doc = pymupdf.open(str(clean))
    doc[0].insert_image(pymupdf.Rect(60, 420, 540, 700), stream=picture, keep_proportion=False)
    info = classify_page(reopen(doc, tmp_path / "pasted.pdf"))
    assert info.kind == "unicode" and not info.needs_ocr
    assert "image" in info.note


def test_text_over_a_full_page_background_stays_native(scan, tmp_path):
    background = pymupdf.open(str(scan))[0].get_pixmap(dpi=30).tobytes("png")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=background, keep_proportion=False)
    for i in range(40):
        page.insert_text((60, 60 + i * 18), "The bidder shall submit the proposal on the GeM portal before the due date.",
                         fontsize=10)
    info = classify_page(reopen(doc, tmp_path / "bg.pdf"))
    assert info.kind == "english" and not info.needs_ocr and info.note == ""


# ---- legacy fonts (finding 21 and the span-level rule) --------------------------------------

def test_kruti_dev_letterhead_on_a_unicode_letter_sends_the_page_to_ocr(clean, tmp_path):
    doc = pymupdf.open(str(clean))
    doc[0].insert_text((60, 40), KRUTI_LINES[0], fontname="tiro", fontsize=14)
    rename_font(doc, doc[0], "Times", "KrutiDev010")
    page = reopen(doc, tmp_path / "letterhead.pdf")
    info = classify_page(page)
    assert info.kind == "legacy" and info.needs_ocr
    assert info.legacy_fonts == ["KrutiDev010"]
    # Native text never carries the gibberish, while the Unicode text stays.
    texts = [b.text for b in native_blocks(page)]
    assert not any("fcgkj" in t for t in texts)
    assert any("ज्ञापांक" in t for t in texts)
    assert any("fcgkj" in b.text for b in native_blocks(page, exclude_legacy=False))


@pytest.mark.parametrize("font_name", ["F1", "T3Font_0", "SHREE-DEV-0714"])
def test_kruti_text_in_an_unknown_font_is_legacy(tmp_path, font_name):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(KRUTI_LINES):
        page.insert_text((60, 80 + 20 * i), line, fontname="cour", fontsize=11)
    rename_font(doc, page, "Courier", font_name)
    page = reopen(doc, tmp_path / "kruti.pdf")
    info = classify_page(page)
    assert info.kind == "legacy" and info.needs_ocr and info.legacy_fonts == [font_name]
    assert native_blocks(page) == []


def test_kruti_letterhead_in_an_unknown_font_on_a_unicode_letter(clean, tmp_path):
    doc = pymupdf.open(str(clean))
    doc[0].insert_text((60, 40), KRUTI_LINES[0], fontname="cour", fontsize=14)
    rename_font(doc, doc[0], "Courier", "F7")
    page = reopen(doc, tmp_path / "letterhead.pdf")
    assert classify_page(page).kind == "legacy"
    assert not any("fcgkj" in b.text for b in native_blocks(page))


def test_english_in_its_own_font_is_not_legacy(clean, tmp_path):
    doc = pymupdf.open(str(clean))
    doc[0].insert_text((60, 40), "GeM", fontname="cour", fontsize=14)
    doc[0].insert_text((60, 780), "Managing Director, BELTRON", fontname="cour", fontsize=11)
    page = reopen(doc, tmp_path / "english_bits.pdf")
    info = classify_page(page)
    assert info.kind == "unicode" and not info.needs_ocr
    texts = " ".join(b.text for b in native_blocks(page))
    assert "GeM" in texts and "Managing Director" in texts


@pytest.mark.parametrize("text", KRUTI_LINES + ["fcgkj ljdkj", "Hkkjr ljdkj", "dk;kZy; vkns'k"])
def test_kruti_dev_text_is_recognised(text):
    assert looks_like_legacy(text)


@pytest.mark.parametrize("text", [
    "Annexure A: Technical Specifications",
    "The bidder shall submit the proposal on the GeM portal before the due date.",
    "Generated from eOffice by RAKESH KUMAR, on 12/03/2026 05:30 PM",
    "Sl. No. Name of Item Qty Unit Rate Amount",
    "Dt. 12/03/2026 Govt. of Bihar Sd/-",
    "M/s ABC Pvt. Ltd., Patna",
    "Email: md@beltron.in",
    "Shri Brajesh Kumar Jha, Bhagalpur, Muzaffarpur, Darbhanga, Chhapra, Purnia",
    "Bidder's turnover shouldn't be less than Rs. 10 Cr.",
    "GeM",
    "BELTRON",
])
def test_english_is_not_mistaken_for_kruti(text):
    assert not looks_like_legacy(text)


def test_font_names_and_english_likeness():
    assert legacy_font_names([("KrutiDev010", "dqN Hkh"), ("Helvetica", "Tender notice")]) == {"KrutiDev010"}
    assert legacy_font_names([("Kruti Dev 010", "1234")]) == set()   # digits only: nothing to misread
    assert english_like("Copy forwarded to the Secretary for information")
    assert not english_like("fae te saeciiaa sacate aieakerd fees Wath feAiH")


# ---- short and outlined pages (finding 47) ----------------------------------------------------

def test_short_annexure_divider_is_not_empty(tmp_path):
    page = pymupdf.open(str(make_clean_pdf(tmp_path / "ann.pdf", ["अनुलग्नक-1"])))[0]
    info = classify_page(page)
    assert info.kind == "unicode" and not info.needs_ocr
    assert [b.text for b in native_blocks(page)] == ["अनुलग्नक-1"]


def test_text_drawn_as_outlines_goes_to_ocr():
    page = pymupdf.open().new_page()
    for i in range(60):   # glyph outlines are filled curves
        page.draw_circle((60 + (i % 20) * 20, 100 + (i // 20) * 30), 6, fill=(0, 0, 0))
    assert classify_page(page).kind == "scan"


def test_blank_page_and_table_grid_are_empty():
    assert classify_page(pymupdf.open().new_page()).kind == "empty"
    page = pymupdf.open().new_page()
    for i in range(20):
        page.draw_line((50, 100 + i * 20), (500, 100 + i * 20))
    assert classify_page(page).kind == "empty"


# ---- page images have a pixel cap (findings 31 and 49) -----------------------------------------

def test_huge_pages_render_within_the_pixel_caps(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=14000, height=14000)
    page.insert_text((100, 200), "huge page", fontsize=40)
    out = tmp_path / "huge.png"
    render_png(page, out)
    shown = pymupdf.Pixmap(str(out))
    assert shown.width * shown.height <= extract.DISPLAY_MAX_PIXELS
    image = page_image(page)
    assert image.width * image.height <= extract.OCR_MAX_PIXELS
    assert max(image.size) <= extract.OCR_MAX_SIDE


def test_long_thin_page_stays_under_tesseract_side_limit():
    page = pymupdf.open().new_page(width=100, height=14000)
    image = page_image(page)
    assert max(image.size) <= extract.OCR_MAX_SIDE


def test_scan_stored_with_wrong_dpi_is_read_at_its_own_resolution(tmp_path):
    # A 300 dpi A4 scan stored as a 2480x3508 pt page: 300 DPI of that is 151 MP.
    src = pymupdf.open().new_page()
    src.insert_text((72, 100), "Memo No. 1234/2026", fontsize=12)
    pix = src.get_pixmap(dpi=300)
    doc = pymupdf.open()
    page = doc.new_page(width=pix.width, height=pix.height)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    image = page_image(page)
    assert image.size == (pix.width, pix.height)


def test_normal_pages_keep_their_dpi(scan):
    page = pymupdf.open(str(scan))[0]
    image = page_image(page)
    assert abs(image.width - page.rect.width * extract.OCR_DPI / 72) <= 1
