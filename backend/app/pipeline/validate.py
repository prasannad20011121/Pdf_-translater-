"""Checks on every translated sentence (PLAN.md §7.3).

A candidate is *unusable* when it isn't a translation at all (empty, still Hindi,
chatter, a loop). Otherwise it is usable, and its issues set the confidence colour:
red for wrong numbers or lost placeholders, amber for softer doubts.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .normalize import ascii_digits, normalize_text
from .protect import Restored, numbers_in
from .quality import assess

GREEN, AMBER, RED = "green", "amber", "red"

LENGTH_RATIO = (0.6, 2.0)   # English chars / Hindi chars; tune on the golden set
MIN_LEN_FOR_RATIO = 20
_CHATTER = re.compile(
    r"^\s*(here is|here's|sure[,!]|translation\s*:|the translation|i have translated|as an ai)",
    re.IGNORECASE,
)
_WORD = re.compile(r"\w+", re.UNICODE)

MESSAGES = {
    "empty": "No output",
    "still_hindi": "Output is still Hindi",
    "chatter": "Output contains comments instead of a translation",
    "loop": "Output repeats itself",
    "numbers": "Numbers differ from the Hindi",
    "extra_numbers": "The English has numbers that are not in the Hindi",
    "placeholders": "A protected number, name or link went missing",
    "some_hindi": "Some Hindi left in the output",
    "length": "Length is unusual for a faithful translation (possible omission or addition)",
    "glossary": "A glossary term was not used",
    "fallback": "Produced by a fallback engine",
    "ocr": "Page text came from OCR that may be unreliable",
    "ocr_numbers": "OCR read a number in two different ways: check it against the page",
    "legacy": "Text in an old Hindi font (Kruti Dev or similar) could not be read",
    "untranslated": "Not translated: needs a human",
}


@dataclass
class CheckResult:
    usable: bool
    issues: dict[str, str] = field(default_factory=dict)  # code -> severity (red|amber)

    @property
    def confidence(self) -> str:
        if not self.usable or RED in self.issues.values():
            return RED
        return AMBER if self.issues else GREEN

    def to_dict(self) -> dict:
        return {"usable": self.usable, "issues": self.issues, "confidence": self.confidence}


# ---- loops ----------------------------------------------------------------------------

MAX_SAME_WORD_RUN = 4     # "the the the the the" is a loop
TANDEM_COPIES = 3         # the same phrase three times back to back is a loop
TANDEM_MAX_N = 8


def _explained_by_source(unit: tuple[str, ...], copies: int, source: str | None) -> bool:
    """A run of repeated numbers ("0 0 0 0 0" in a table row) that the source has too."""
    if source is None or not all(w.isdigit() for w in unit):
        return False
    src = Counter(w.lstrip("0") or "0" for w in _WORD.findall(ascii_digits(source)) if w.isdigit())
    need = Counter(w.lstrip("0") or "0" for w in unit)
    return all(src[w] >= n * copies for w, n in need.items())


def _has_loop(text: str, source: str | None = None) -> bool:
    """Real degeneration only: the same word or phrase repeated back to back.

    A phrase that recurs with other words in between ("..., Government of Bihar,
    Patna 2. Secretary, ..., Government of Bihar, Patna 3. ...") is normal in a
    distribution list, so it only counts as a loop when the output is also far
    longer than the source.
    """
    words = [w.lower() for w in _WORD.findall(text)]
    # 1. The same word many times in a row.
    run = 1
    for i in range(1, len(words)):
        run = run + 1 if words[i] == words[i - 1] else 1
        if run > MAX_SAME_WORD_RUN and not _explained_by_source((words[i],), run, source):
            return True
    # 2. The same phrase of 2..8 words repeated back to back.
    for n in range(2, TANDEM_MAX_N + 1):
        for i in range(len(words) - n * TANDEM_COPIES + 1):
            unit = tuple(words[i:i + n])
            if all(tuple(words[i + k * n:i + (k + 1) * n]) == unit for k in range(1, TANDEM_COPIES)):
                if not _explained_by_source(unit, TANDEM_COPIES, source):
                    return True
    # 3. Scattered repetition, only when the output is also abnormally long.
    if source is not None and len(source) >= MIN_LEN_FOR_RATIO and len(text) > LENGTH_RATIO[1] * len(source):
        grams = Counter(tuple(words[i:i + 4]) for i in range(len(words) - 3))
        if grams and max(grams.values()) >= 3:
            return True
    return False


# ---- numbers ----------------------------------------------------------------------------

def _nfc(words: str) -> list[str]:
    return [unicodedata.normalize("NFC", w) for w in words.split()]


# Hindi number and ordinal words. When the source has one, an English digit that has
# no counterpart in the Hindi digits ("प्रथम तल" -> "1st floor", "दो प्रतियों" ->
# "2 copies") is expected.
_HINDI_NUMBER_WORDS = _nfc(
    "एक दो तीन चार पांच पाँच छह छः सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह पन्द्रह "
    "सोलह सत्रह अठारह उन्नीस बीस पच्चीस तीस चालीस पचास साठ सत्तर अस्सी नब्बे सौ हजार "
    "हज़ार लाख करोड़ प्रथम द्वितीय तृतीय चतुर्थ पंचम षष्ठ सप्तम अष्टम नवम दशम पहला पहली "
    "पहले दूसरा दूसरी दूसरे तीसरा तीसरी तीसरे चौथा चौथी चौथे पांचवां पाँचवाँ पांचवीं "
    "पाँचवीं छठा छठी आधा आधी डेढ़ ढाई दोनों तीनों चारों दुगुना दोगुना तिगुना"
)
_DEVA_LETTER = "ऀ-ॣॱ-ॿ"
_NUMBER_WORD = re.compile(
    f"(?<![{_DEVA_LETTER}])(?:{'|'.join(sorted(map(re.escape, _HINDI_NUMBER_WORDS), key=len, reverse=True))})"
    f"(?![{_DEVA_LETTER}])"
)
_MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december"]
_MONTH_EN = {name: str(i + 1) for i, full in enumerate(_MONTHS_EN) for name in (full, full[:3])}
_MONTH_EN["sept"] = "9"
_MONTH_EN_RE = re.compile(r"\b(" + "|".join(sorted(_MONTH_EN, key=len, reverse=True)) + r")\b", re.IGNORECASE)
_MONTHS_HI = [
    ["जनवरी"], ["फरवरी", "फ़रवरी"], ["मार्च"], ["अप्रैल", "अप्रेल"], ["मई"], ["जून"],
    ["जुलाई"], ["अगस्त"], ["सितंबर", "सितम्बर"], ["अक्टूबर", "अक्तूबर"], ["नवंबर", "नवम्बर"],
    ["दिसंबर", "दिसम्बर"],
]
_MONTH_HI = {unicodedata.normalize("NFC", name): str(i + 1) for i, names in enumerate(_MONTHS_HI) for name in names}
_MONTH_HI_RE = re.compile(
    f"(?<![{_DEVA_LETTER}])({'|'.join(map(re.escape, _MONTH_HI))})(?![{_DEVA_LETTER}])"
)
_NUM_BEFORE = re.compile(r"[0-9०-९](?:st|nd|rd|th)?[\s,.\-]*$", re.IGNORECASE)
_NUM_AFTER = re.compile(r"\.?[\s,\-]*[0-9०-९]")


def _month_numbers(text: str, hindi: bool) -> Counter[str]:
    """Month names written next to a number ("12 March 2026", "12 मार्च 2026").

    They count as the month's number, so "12.03.2026" and "12 March 2026" agree.
    """
    found: Counter[str] = Counter()
    pattern, table = (_MONTH_HI_RE, _MONTH_HI) if hindi else (_MONTH_EN_RE, _MONTH_EN)
    for m in pattern.finditer(text):
        name = m.group(1)
        if not hindi and not name[0].isupper():   # "may" the verb, "march" the noun
            continue
        before, after = text[max(0, m.start() - 6):m.start()], text[m.end():m.end() + 4]
        if _NUM_BEFORE.search(before) or _NUM_AFTER.match(after):
            found[table[name if hindi else name.lower()]] += 1
    return found


def number_issue(source: str, output: str) -> str | None:
    """RED when a number of the source is missing or changed in the output.

    Extra numbers in the output are only AMBER, and are expected when the source
    writes a number as a word ("प्रथम" -> "1st").
    """
    src = numbers_in(source) + _month_numbers(source, hindi=True)
    out = numbers_in(output) + _month_numbers(output, hindi=False)
    if src - out:
        return RED
    if out - src and not _NUMBER_WORD.search(source):
        return AMBER
    return None


# ---- glossary ---------------------------------------------------------------------------

# Plural and oblique endings a glossary term may carry: निविदा -> निविदाओं, विभाग -> विभागों.
_INFLECTION = "(?:ों|ें|ाओं|ओं|ाएं|ाएँ|एं|एँ|ियों|ियां|ियाँ|यों|यां|याँ)?"


def glossary_hits(source: str, glossary: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Glossary entries whose Hindi term appears in the source as whole words.

    Terms are normalised like document text (NFC, the abbreviation zero), so a term
    typed with a precomposed nukta letter (ड़ as U+095C) or as "क्र0सं0" still
    matches. A danda, digit or punctuation right after the term ends the word.
    """
    text = unicodedata.normalize("NFC", source)
    hits = []
    for hi, en in glossary:
        term = " ".join(normalize_text(hi).split())
        if not term:
            continue
        pattern = f"(?<![{_DEVA_LETTER}]){re.escape(term)}{_INFLECTION}(?![{_DEVA_LETTER}])"
        if re.search(pattern, text):
            hits.append((hi, en))
    return hits


# ---- the check ----------------------------------------------------------------------------

def check(
    source: str,
    output: str | None,
    *,
    restored: Restored | None = None,
    glossary: list[tuple[str, str]] | None = None,
) -> CheckResult:
    if not output or not output.strip():
        return CheckResult(False, {"empty": RED})
    issues: dict[str, str] = {}

    q = assess(output)
    deva_share = q.deva_ratio
    if deva_share > 0.15:
        return CheckResult(False, {"still_hindi": RED})
    if _CHATTER.search(output):
        return CheckResult(False, {"chatter": RED})
    if _has_loop(output, source):
        return CheckResult(False, {"loop": RED})

    severity = number_issue(source, output)
    if severity == RED:
        issues["numbers"] = RED
    elif severity == AMBER:
        issues["extra_numbers"] = AMBER
    if restored is not None and (restored.missing or restored.duplicated or restored.unknown):
        issues["placeholders"] = RED
    if deva_share > 0.05:
        issues["some_hindi"] = AMBER
    if len(source) >= MIN_LEN_FOR_RATIO:
        ratio = len(output) / len(source)
        if not LENGTH_RATIO[0] <= ratio <= LENGTH_RATIO[1]:
            issues["length"] = AMBER
    for _hi, en in glossary_hits(source, glossary or []):
        if en.lower() not in output.lower():
            issues["glossary"] = AMBER
            break
    return CheckResult(True, issues)
