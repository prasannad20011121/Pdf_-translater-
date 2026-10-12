import shutil

import pymupdf
import pytest

from app.pipeline.classify import classify_page
from app.pipeline.extract import native_blocks, page_image
from app.pipeline.normalize import ascii_digits, normalize_text
from app.pipeline.ocr import tesseract
from app.pipeline.protect import numbers_in, protect, restore
from app.pipeline.quality import assess
from app.pipeline.segment import split_sentences

GOOD = "बिहार सरकार, सूचना प्रावैधिकी विभाग। ज्ञापांक-1234/2026, दिनांक 12.03.2026। निविदा की अंतिम तिथि बढ़ाई गई है।"
BROKEN = "बə हार सरकार, सूचना Śावैध ɚ कʡ वə भाग। \\ापांक-1234/2026, दɘ नांक 12.03.2026।"


# --- normalise -----------------------------------------------------------------

def test_normalize_pipe_danda_and_invisibles():
    assert normalize_text("बिहार सरकार |  नया\u200b पत्र") == "बिहार सरकार। नया पत्र"
    assert ascii_digits("२०२६") == "2026"


# --- quality -------------------------------------------------------------------

def test_quality_scores_good_text_high_and_garbled_text_low():
    assert assess(GOOD).score == 1.0
    assert assess(BROKEN).score < 0.6


@pytest.mark.parametrize("word", ["प्रावैधिकी", "ज्ञापांक", "बढ़ाई", "अधोहस्ताक्षरी", "श्रीमान्", "ऑफिस", "क्षेत्र", "कार्यालय"])
def test_quality_accepts_well_formed_words(word):
    assert assess(word).score == 1.0


# --- sentences -------------------------------------------------------------------

def test_split_sentences_handles_danda_and_abbreviations():
    text = "पहला वाक्य। डॉ. राजेश कुमार आए। क्या आप तैयार हैं? Rs. 500 देय है. अंतिम."
    assert split_sentences(text) == [
        "पहला वाक्य।",
        "डॉ. राजेश कुमार आए।",
        "क्या आप तैयार हैं?",
        "Rs. 500 देय है.",
        "अंतिम.",
    ]


def test_split_keeps_dates_together():
    assert split_sentences("तिथि 12.03.2026 है।") == ["तिथि 12.03.2026 है।"]


# --- protection ------------------------------------------------------------------

def test_protect_and_restore_round_trip():
    p = protect("ज्ञापांक-1234/2026, दिनांक १२.०३.२०२६ को RFP हेतु Rs. 5,00,000/- beltron@bihar.gov.in")
    kinds = [(i.kind, i.original) for i in p.items]
    assert ("N", "1234/2026") in kinds
    assert ("N", "१२.०३.२०२६") in kinds
    assert ("L", "RFP") in kinds
    assert ("E", "beltron@bihar.gov.in") in kinds
    assert "1234" not in p.text

    english = "Memo No. ⟦N1⟧ dated ⟦N2⟧ for ⟦L1⟧: ⟦L2⟧ ⟦N3⟧, write to ⟦E1⟧"
    r = restore(english, p.items)
    assert r.missing == [] and r.unknown == []
    assert "1234/2026" in r.text and "12.03.2026" in r.text and "5,00,000/-" in r.text


def test_restore_reports_missing_placeholders():
    p = protect("दिनांक 12.03.2026 और 25.03.2026")
    r = restore("Date ⟦N1⟧", p.items)
    assert r.missing == ["N2"]


def test_numbers_compare_across_formats():
    assert numbers_in("5,00,000 और १२.०३.२०२६") == numbers_in("500000 on 12/03/2026")


# --- classify + extract ------------------------------------------------------------

def test_clean_pdf_is_unicode_and_good(pdfs):
    page = pymupdf.open(pdfs["clean"])[0]
    info = classify_page(page)
    assert info.kind == "unicode"
    assert info.quality == 1.0
    assert not info.needs_ocr
    blocks = native_blocks(page)
    assert any("ज्ञापांक" in b.text for b in blocks)


def test_broken_pdf_is_detected_and_sent_to_ocr(pdfs):
    info = classify_page(pymupdf.open(pdfs["broken"])[0])
    assert info.kind == "unicode"
    assert info.quality < 0.85
    assert info.needs_ocr


def test_scanned_pdf_is_detected(pdfs):
    info = classify_page(pymupdf.open(pdfs["scan"])[0])
    assert info.kind == "scan"
    assert info.needs_ocr


def test_english_pdf_is_detected(pdfs):
    info = classify_page(pymupdf.open(pdfs["english"])[0])
    assert info.kind == "english"
    assert not info.needs_ocr


@pytest.mark.skipif(not tesseract.available(shutil.which("tesseract")), reason="tesseract with Hindi not installed")
def test_tesseract_reads_scanned_hindi(pdfs):
    page = pymupdf.open(pdfs["scan"])[0]
    result = tesseract.ocr_image(page_image(page), shutil.which("tesseract"))
    text = " ".join(b.text for b in result.blocks)
    assert "निविदा" in text
    assert assess(text).score > 0.85
    # Every number must come through exactly. With "hin+eng" Tesseract dropped the
    # digit 1 everywhere ("1234/2026" -> "234/2026", "12.03.2026" -> "2.03.2026").
    for number in ("1234/2026", "12.03.2026", "25.03.2026", "5,00,000/-"):
        assert number in text, (number, text)
