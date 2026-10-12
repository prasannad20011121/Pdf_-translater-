"""OCR numbers: Tesseract must not drop the digit 1, and the cross-check must be safe."""

from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf
import pytest
from conftest import LETTER, make_broken_pdf, make_scanned_pdf
from PIL import Image

from app.pipeline.extract import page_image
from app.pipeline.ocr import tesseract
from app.pipeline.ocr.tesseract import _cross_check, _Word
from app.pipeline.protect import numbers_in

TESSERACT = shutil.which("tesseract")
needs_tesseract = pytest.mark.skipif(not tesseract.available(TESSERACT), reason="tesseract with hin+eng not installed")

NUMBERS_PAGE = LETTER + [
    "शुल्क Rs. 11,800/- तथा कुल राशि 1,23,45,678 है। दिनांक 07.01.2026 से लागू।",
    "पत्रांक 1/2026, क्रमांक 11 एवं 101 तथा 1.1.2026 को जारी।",
    "निविदा संख्या BSEDC/2026/111, कार्यादेश 2118/2025 दिनांक 31.12.2025।",
    "कुल 15 प्रतियाँ, 21 दिन के अंदर 1,10,000/- जमा करें। राशि 19,41,100/- है।",
]
EXPECTED = [
    "1234/2026", "12.03.2026", "25.03.2026", "5,00,000/-", "11,800/-", "1,23,45,678", "07.01.2026",
    "1/2026", "11", "101", "1.1.2026", "BSEDC/2026/111", "2118/2025", "31.12.2025", "15", "21",
    "1,10,000/-", "19,41,100/-",
]


def make_rotated_scan(path: Path, paragraphs: list[str], angle: float) -> Path:
    """A slightly skewed scan, as from a sheet fed at an angle."""
    src = pymupdf.open(str(make_broken_pdf(path.with_suffix(".src.pdf"), paragraphs)))[0]
    pix = src.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples).rotate(angle, expand=True, fillcolor=255)
    png = path.with_suffix(".png")
    image.save(png)
    doc = pymupdf.open()
    page = doc.new_page(width=src.rect.width, height=src.rect.width * image.height / image.width)
    page.insert_image(page.rect, filename=str(png))
    doc.save(str(path))
    return path


def ocr_text(pdf: Path) -> tuple[str, tesseract.OcrResult]:
    result = tesseract.ocr_image(page_image(pymupdf.open(str(pdf))[0]), TESSERACT)
    return " ".join(b.text for b in result.blocks), result


def test_english_leads_the_language_order():
    # "hin+eng" makes Tesseract drop the digit 1 (see the module docstring).
    assert tesseract.LANGS.split("+")[0] == "eng"
    assert "hin" in tesseract.LANGS.split("+")


@needs_tesseract
@pytest.mark.parametrize("angle", [0, 1.2])
def test_scanned_numbers_come_through_exactly(tmp_path, angle):
    pdf = (make_scanned_pdf(tmp_path / "scan.pdf", NUMBERS_PAGE) if angle == 0
           else make_rotated_scan(tmp_path / "scan.pdf", NUMBERS_PAGE, angle))
    text, result = ocr_text(pdf)
    missing = [n for n in EXPECTED if n not in text]
    assert not missing, (missing, text)
    # A number that isn't in the document (on the skewed scan "Rs." is read as "47.")
    # must at least be flagged as uncertain.
    extra = numbers_in(text) - numbers_in(" ".join(NUMBERS_PAGE))
    unflagged = extra - numbers_in(" ".join(result.uncertain_numbers))
    assert not unflagged, (dict(unflagged), text)
    assert result.checked


# ---- the cross-check, without Tesseract ------------------------------------------------------

def w(text: str, x0: int, x1: int, conf: float = 95.0, line: int = 1, y: int = 100) -> _Word:
    return _Word(text, conf, (1, 1, line), (x0, y, x1, y + 30))


def joined(words: list[_Word]) -> str:
    return " ".join(x.text for x in words if x.text)


def test_cross_check_restores_a_dropped_leading_one():
    primary = [w("ज्ञापांक-234/2026,", 100, 400), w("दिनांक", 420, 520), w("2.03.2026", 540, 700)]
    check = [w("Wuih-1234/2026,", 100, 400, conf=90), w("fetes", 420, 520), w("12.03.2026", 535, 700, conf=93)]
    repaired, uncertain = _cross_check(primary, check)
    assert repaired == 2 and not uncertain
    assert joined(primary) == "ज्ञापांक-1234/2026, दिनांक 12.03.2026"


def test_cross_check_joins_a_number_split_by_a_space():
    primary = [w("ज्ञापांक-1", 100, 260), w("234/2026,", 270, 400)]
    check = [w("Wuih-1234/2026,", 100, 400, conf=40)]
    repaired, _ = _cross_check(primary, check)
    assert repaired == 1
    assert joined(primary) == "ज्ञापांक-1234/2026,"


def test_cross_check_reads_bracket_as_one():
    primary = [w("क्रमांक", 100, 200), w("]", 220, 240), w("एवं", 260, 300), w("0]", 320, 360)]
    check = [w("HAIH", 100, 200), w("11", 218, 242, conf=90), w("V4", 260, 300), w("101", 318, 362, conf=90)]
    _cross_check(primary, check)
    assert joined(primary) == "क्रमांक 11 एवं 101"


def test_cross_check_never_turns_a_danda_into_a_one():
    # The English pass reads "800001।" as "8000011".
    primary = [w("पिन", 100, 150), w("800001।", 160, 300)]
    check = [w("fea", 100, 150), w("8000011", 160, 305, conf=95)]
    repaired, uncertain = _cross_check(primary, check)
    assert repaired == 0 and not uncertain
    assert joined(primary) == "पिन 800001।"
    # Same when the primary pass lost the danda altogether: the trailing "1" reaches
    # past the number, so it is flagged, not added.
    primary = [w("पिन", 100, 150), w("800001", 160, 280)]
    check = [w("fea", 100, 150), w("8000011", 160, 305, conf=95)]
    repaired, uncertain = _cross_check(primary, check)
    assert repaired == 0 and joined(primary) == "पिन 800001"
    assert uncertain == {(1, 1, 1): ["800001"]}


def test_cross_check_ignores_digits_read_into_hindi_letters():
    # "है।" read by the English pass as "81": there is no number there.
    primary = [w("राशि", 100, 160), w("है।", 170, 220)]
    check = [w("UTR", 100, 160), w("81", 170, 220, conf=96)]
    assert _cross_check(primary, check) == (0, {})
    assert joined(primary) == "राशि है।"


def test_cross_check_leaves_numbers_the_check_pass_broke_up():
    # Noisy scans: the English pass splits "12.03.2026" into pieces.
    primary = [w("12.03.2026", 100, 300)]
    check = [w("12.", 100, 150, conf=95), w("03.2026", 160, 300, conf=95)]
    assert _cross_check(primary, check) == (0, {})
    assert joined(primary) == "12.03.2026"


def test_cross_check_flags_but_does_not_change_other_disagreements():
    primary = [w("25.03.2026", 100, 300)]
    check = [w("26.03.2026", 100, 300, conf=92)]
    repaired, uncertain = _cross_check(primary, check)
    assert repaired == 0 and uncertain == {(1, 1, 1): ["25.03.2026"]}
    assert joined(primary) == "25.03.2026"
    # A doubtful check reading is not even worth a flag.
    assert _cross_check([w("25.03.2026", 100, 300)], [w("26.03.2026", 100, 300, conf=40)]) == (0, {})


def test_cross_check_flags_a_word_read_as_a_number():
    primary = [w("शुल्क", 100, 180), w("47.", 190, 240), w("11,800/-", 250, 380)]
    check = [w("Yeh", 100, 180, conf=60), w("Rs.", 190, 240, conf=93), w("11,800/-", 250, 380, conf=95)]
    repaired, uncertain = _cross_check(primary, check)
    assert repaired == 0 and uncertain == {(1, 1, 1): ["47"]}
    assert joined(primary) == "शुल्क 47. 11,800/-"   # flagged, not changed
    # The Hindi model may also produce Devanagari digits for "Rs.".
    primary = [w("शुल्क", 100, 180), w("४७.", 190, 240)]
    check = [w("Yeh", 100, 180, conf=60), w("Rs.", 190, 240, conf=93)]
    assert _cross_check(primary, check) == (0, {(1, 1, 1): ["४७"]})
    # ...but real Devanagari digits, which the English pass reads as junk, are fine.
    primary = [w("दिनांक", 100, 180), w("१२.०३.२०२६", 190, 400)]
    check = [w("feria", 100, 180, conf=60), w("RR.oR.ROR&", 190, 400, conf=90)]
    assert _cross_check(primary, check) == (0, {})


def test_cross_check_skips_devanagari_digits():
    primary = [w("१२.०३.२०२६", 100, 300)]
    check = [w("92.03.2028", 100, 300, conf=95)]
    assert _cross_check(primary, check) == (0, {})


def test_cross_check_needs_confidence_to_repair():
    primary = [w("234/2026", 100, 300)]
    assert _cross_check(primary, [w("1234/2026", 100, 300, conf=30)]) == (0, {})
    assert joined(primary) == "234/2026"
