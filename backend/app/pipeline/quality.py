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
_CONS = "[क-हक़-य़ॸ-ॿ]़?"      # consonant (+ nukta)
_INDEP_VOWEL = "[ऄ-औॠॡॲ-ॷ]"        # independent vowel
_MATRA = "[ऺऻा-ौॎॏॕ-ॗॢॣ]"  # vowel sign
_VIRAMA = "्[‌‍]?"                                # halant (+ ZWNJ/ZWJ)
_MODIFIER = "[ऀ-ः]"                                    # chandrabindu, anusvara, visarga
_SYLLABLE = (
    f"(?:(?:{_CONS}{_VIRAMA})*{_CONS}(?:{_VIRAMA}|{_MATRA}{{1,2}})?{_MODIFIER}{{0,2}}"
    f"|{_INDEP_VOWEL}{_MODIFIER}{{0,2}}"
    "|ऽ|ॐ)"                                            # avagraha, om
)
_WORD_OK = re.compile(f"(?:{_SYLLABLE})+")

_TOKEN = re.compile(r"\S+")
_EDGE_PUNCT = (
    "।॥॰.,;:!?\"'()[]{}<>-‐‑‒–—―/\\|"
    "“”‘’…*#%&+=_"
    "•·₹‌‍"
)
# Devanagari letters and signs. The danda (U+0964/5), the Devanagari digits
# (U+0966-096F) and the abbreviation sign ॰ (U+0970) are separators, not letters.
_DEVA_LETTER = re.compile("[ऀ-ॣॱ-ॿ]")
# Runs of Devanagari letters inside a token: "GeM-पोर्टल", "धारा-4(1)", "243(क)",
# "₹5,000/-का", "सूचना/Tender" are judged on their Devanagari part only.
_DEVA_RUN = re.compile("[ऀ-ॣॱ-ॿ‌‍]+")
_ZW = "‌‍"

# Below this many Devanagari words, a page is scored over all its tokens, so a
# bilingual header on an English page can't pull the score down to 0.
MIN_DEVA_WORDS_FOR_RATIO = 10


@dataclass
class TextQuality:
    deva_words: int
    valid_words: int
    garbage_tokens: int  # tokens with letters that are neither Devanagari nor Latin
    latin_letters: int
    deva_letters: int
    tokens: int = 0      # all non-empty tokens

    @property
    def score(self) -> float:
        """Share of tokens that look well formed (0..1).

        Mostly-Hindi text is scored over its Devanagari-bearing and garbage tokens.
        Text with only a few Hindi words (an English page with a bilingual header)
        is scored over all tokens.
        """
        if self.deva_words >= MIN_DEVA_WORDS_FOR_RATIO or not self.tokens:
            total = self.deva_words + self.garbage_tokens
            if total == 0:
                return 1.0
            return self.valid_words / total
        bad = (self.deva_words - self.valid_words) + self.garbage_tokens
        return max(0.0, 1.0 - bad / self.tokens)

    @property
    def deva_ratio(self) -> float:
        letters = self.deva_letters + self.latin_letters
        return self.deva_letters / letters if letters else 0.0


def _is_deva(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def _latin_like(ch: str) -> bool:
    """Accented Latin letters (Latin-1 Supplement, Latin Extended-A/B): é, ü, Ø, ß."""
    return "À" <= ch <= "ɏ"


def assess(text: str) -> TextQuality:
    tokens = deva_words = valid = garbage = latin = deva = 0
    for raw in _TOKEN.findall(text):
        # NFKC turns ligatures ("ﬁnancial") and full-width forms into plain letters.
        # It leaves Devanagari as NFC has it.
        tok = unicodedata.normalize("NFKC", raw).strip(_EDGE_PUNCT)
        if not tok:
            continue
        tokens += 1
        has_d = False
        foreign: list[str] = []  # letters that are neither Devanagari nor ASCII
        has_ascii_letter = False
        for c in tok:
            if _is_deva(c):
                if _DEVA_LETTER.match(c):
                    has_d = True
                if c.isalpha() or unicodedata.category(c).startswith("M"):
                    deva += 1
            elif c.isascii():
                if c.isalpha():
                    latin += 1
                    has_ascii_letter = True
            elif c.isalpha():
                foreign.append(c)
                if _latin_like(c):
                    latin += 1
        if has_d:
            deva_words += 1
            runs = [r.strip(_ZW) for r in _DEVA_RUN.findall(tok)]
            runs = [r for r in runs if r]
            # A letter from another script inside a Hindi word ("Śावैध", "बə") is the
            # typical sign of a broken text layer.
            if runs and not foreign and all(_WORD_OK.fullmatch(r) for r in runs):
                valid += 1
        elif foreign:
            # Letters from other scripts (IPA, Greek...) are almost always mis-mapped
            # glyphs. Accented Latin in a Latin word ("Café") and a lone symbol-font
            # bullet extracted as a letter ("Ø") are fine.
            latin_word = all(_latin_like(c) for c in foreign) and (has_ascii_letter or len(tok) == 1)
            if not latin_word:
                garbage += 1
    return TextQuality(deva_words, valid, garbage, latin, deva, tokens)


QUALITY_THRESHOLD = 0.85


def quality_ok(text: str, threshold: float = QUALITY_THRESHOLD) -> bool:
    return assess(text).score >= threshold
