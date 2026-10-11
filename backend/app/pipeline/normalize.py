"""Unicode clean-up for Hindi text coming out of PDFs and OCR."""

from __future__ import annotations

import re
import unicodedata

DEVANAGARI_DIGITS = str.maketrans("\u0966\u0967\u0968\u0969\u096a\u096b\u096c\u096d\u096e\u096f", "0123456789")

# Characters that only cause trouble downstream (BOM, soft hyphen, zero-width space,
# word joiner). ZWJ/ZWNJ (U+200D/U+200C) are kept: they change how conjuncts render.
_INVISIBLE = re.compile("[\ufeff\xad\u200b\u2060]")
# Control characters (PDF text layers sometimes contain NUL bytes); keep tab and newline.
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SPACES = re.compile("[ \t\xa0\u2000-\u200a\u202f\u205f\u3000]+")
# Typists often use "|" as the full stop (purna viram) after a Devanagari word.
_PIPE_DANDA = re.compile("(?<=[\u0900-\u097f])\\s*\\|(?=\\s|$)", re.MULTILINE)

DANDA = "\u0964"


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub("", text)
    text = _PIPE_DANDA.sub(DANDA, text)
    text = _SPACES.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def strip_control(text: str) -> str:
    """Remove characters that Word and XML reject (used on model output too)."""
    return _CONTROL.sub("", text)


def ascii_digits(text: str) -> str:
    return text.translate(DEVANAGARI_DIGITS)


def has_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" for ch in text)
