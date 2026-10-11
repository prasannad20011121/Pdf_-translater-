"""How trustworthy is a piece of extracted Hindi text?

PDFs often hold Hindi whose vowel signs come out in the wrong order or as unrelated
symbols (e.g. "बə हार" instead of "बिहार"). We score text by the share of
Devanagari words that are well-formed syllable sequences. A dictionary check
(PLAN.md §6.2) can be added later; this orthographic check needs no word list and
already catches broken extraction and most OCR garbage.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Building blocks of a Devanagari syllable (akshara).
_CONS = "[\u0915-\u0939\u0958-\u095f\u0978-\u097f]\u093c?"      # consonant (+ nukta)
_INDEP_VOWEL = "[\u0904-\u0914\u0960\u0961\u0972-\u0977]"        # independent vowel
_MATRA = "[\u093a\u093b\u093e-\u094c\u094e\u094f\u0955-\u0957\u0962\u0963]"  # vowel sign
_VIRAMA = "\u094d[\u200c\u200d]?"                                # halant (+ ZWNJ/ZWJ)
_MODIFIER = "[\u0900-\u0903]"                                    # chandrabindu, anusvara, visarga
_SYLLABLE = (
    f"(?:(?:{_CONS}{_VIRAMA})*{_CONS}(?:{_VIRAMA}|{_MATRA}{{1,2}})?{_MODIFIER}{{0,2}}"
    f"|{_INDEP_VOWEL}{_MODIFIER}{{0,2}}"
    "|\u093d|\u0950)"                                            # avagraha, om
)
_WORD_OK = re.compile(f"(?:{_SYLLABLE})+")

_TOKEN = re.compile(r"\S+")
_EDGE_PUNCT = "\u0964\u0965.,;:!?\"'()[]{}<>-\u2013\u2014/\\|\u201c\u201d\u2018\u2019\u2026*#%&+=_"
_INNER_SEPARATORS = re.compile("[0-9\u0966-\u096f\u0964\u0965.,/\\-:]+")


@dataclass
class TextQuality:
    deva_words: int
    valid_words: int
    garbage_tokens: int  # tokens with letters that are neither Devanagari nor basic Latin
    latin_letters: int
    deva_letters: int

    @property
    def score(self) -> float:
        """Share of Devanagari-bearing tokens that look well formed (0..1)."""
        total = self.deva_words + self.garbage_tokens
        if total == 0:
            return 1.0
        return self.valid_words / total

    @property
    def deva_ratio(self) -> float:
        letters = self.deva_letters + self.latin_letters
        return self.deva_letters / letters if letters else 0.0


def _is_deva(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def assess(text: str) -> TextQuality:
    deva_words = valid = garbage = latin = deva = 0
    for raw in _TOKEN.findall(text):
        tok = raw.strip(_EDGE_PUNCT)
        if not tok:
            continue
        has_d = False
        for c in tok:
            if _is_deva(c):
                has_d = True
                if c.isalpha() or unicodedata.category(c).startswith("M"):
                    deva += 1
            elif c.isascii() and c.isalpha():
                latin += 1
        if has_d:
            deva_words += 1
            # Digits and the danda may sit inside a token, e.g. "1234/2026।"
            core = _INNER_SEPARATORS.sub(" ", tok).split()
            if core and all(_WORD_OK.fullmatch(part) for part in core):
                valid += 1
        elif any(c.isalpha() and not c.isascii() for c in tok):
            # Letters from other scripts (IPA, Latin-1 accents) in a Hindi document
            # are almost always mis-mapped glyphs.
            garbage += 1
    return TextQuality(deva_words, valid, garbage, latin, deva)


QUALITY_THRESHOLD = 0.85


def quality_ok(text: str, threshold: float = QUALITY_THRESHOLD) -> bool:
    return assess(text).score >= threshold
