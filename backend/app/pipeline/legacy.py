"""Detect text in legacy Hindi fonts (Kruti Dev, DevLys, Chanakya, Shree Lipi...).

These fonts draw Devanagari glyphs on Latin code points, so the PDF's text layer
holds gibberish such as "fcgkj ljdkj" for बिहार सरकार. Conversion to Unicode is
planned (PLAN.md §3, type B); until then such text must never reach a segment: the
page goes to OCR, and native extraction leaves these spans out.

Two signals are used:
- the font name (KrutiDev010, DevLys 010, Walkman-Chanakya, SHREE-DEV-0714...);
- the text itself, for fonts renamed by the PDF producer ("F1", "T3Font_0"): Latin
  text with no English words and the letter patterns of the Kruti Dev keyboard
  layout (ि typed before the consonant as "f", ा as "k", reph as "Z", "/" for ध...).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

LEGACY_FONT = re.compile(
    r"kruti|devlys|dev[\s_-]?lys|chanakya|walkman|shusha|aps[\s_-]?dv|akruti|dv[\s_-]?tt|dvbw[\s_-]?tt"
    r"|agra|shivaji|shree[\s_-]?(?:dev|lipi)|sree[\s_-]?lipi|shreelipi|kundli|amar[\s_-]?ujala"
    r"|krishna[\s_-]?dev|richa\b|naidunia",
    re.IGNORECASE,
)

# Common English words, including the vocabulary of Indian government letters. Real
# English text has many of them; Kruti Dev gibberish has almost none.
ENGLISH_WORDS = set("""
a about above after against all also am among an and any appendix are as at be been before being below
between both but by can could did do does done due during each either for from further had has have he
her here him his how i if in into is it its may might more most must my no nor not now of off on once
only or other our out over own same shall she should so some such than that the their them then there
these they this those through to too under until up upon very was we were what when where which while
who whom why will with within without would you your yes per via vide w.e.f etc please kindly hereby
herein thereof whereas
annexure appendix office order letter memo no date dated subject ref reference sir madam dear secretary
department government govt bihar india patna state district officer director managing chairman member
corporation limited ltd pvt private electronics development company tender bid bidder bids proposal
notice rfp rfq eoi nit work works contract agreement amount rs rupees lakh crore total tax gst price rate
cost payment fee fees deposit emd security bank guarantee account name address phone mobile email fax
website portal online submission submit last time copy forwarded information necessary action signed
sd sl qty unit nos item items description specification specifications technical financial document
documents certificate registration experience year years month months day days page pages section
clause terms conditions scheme project programme program services service supply installation system
data computer hardware software network report reports meeting committee approval approved sanction
sanctioned issued issue general manager deputy assistant joint additional chief principal under engineer
mr mrs ms dr shri smt sh kumar singh prasad sinha jha mishra yadav sharma ram devi
""".split())

# Short English abbreviations without vowels that must not count as Kruti signs.
_NO_VOWEL_OK = {"pvt", "ltd", "hrs", "mrs", "mr", "dr", "sh", "smt", "st", "nth", "kms", "kgs", "rs",
                "sq", "ft", "nm", "pls", "dt", "dtd", "sd", "msg", "qty", "govt", "dept", "mgmt",
                "mgr", "bldg", "pkg", "tds", "gst", "cst", "vat", "pdf", "www", "http", "https"}

# Kruti Dev typing leaves these inside words: ; (य) / (ध) ' (श) " (ष) ~ (्) + (nukta)
# < (ढ) > (झ) [ (ख) { (क्ष) = (त्र) # (रु) @ (/) & (-) ] (,) Z (reph) \ (ऋ)
_INNER_PUNCT = re.compile(r"[A-Za-z][;/'\"~+<>\[{=#@&\]\\|^][A-Za-z]")
_F_PREFIX = re.compile(r"^f[bcdghjkmnpqstvwxzBCDFGHJKLMNPQSTVWXZ'\"\[{=;]")  # ि before the consonant
_K_PATTERNS = re.compile(r"kk|kj|kd|kx|kZ|qZ|bZ|Hk|Fk|Kk|Ys|Ms|Vk|/k|'k|\"k|\[k|=k|\{k|;k")
_MID_UPPER = re.compile(r"[a-z][A-Z]")
_WORDISH = re.compile(r"\S+")
_EDGE = "\"'()[]{}<>.,;:!?*-_|"
_VOWELS = set("aeiouyAEIOUY")


_WEB = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?:https?://|www\.)\S+|\S+\.(?:com|in|org|net|gov|nic)\b", re.I)
_SLASH_WORDS = {"and/or", "m/s", "w/o", "s/o", "d/o", "c/o", "his/her", "he/she", "n/a"}

STRONG, WEAK = 2, 1


def _kruti_signal(token: str) -> int:
    """0 = not Kruti-like, WEAK = odd for English, STRONG = typical Kruti Dev typing."""
    letters = [c for c in token if c.isascii() and c.isalpha()]
    if len(letters) < 2:
        return 0
    core = token.strip(_EDGE)
    low = core.lower()
    if low in ENGLISH_WORDS or low in _NO_VOWEL_OK or core.isupper() or _WEB.fullmatch(core):
        return 0
    if _INNER_PUNCT.search(core) and low not in _SLASH_WORDS:
        if not re.search(r"'(?:s|t|ll|re|ve|d|m)$", low):     # English contractions
            return STRONG
    if _F_PREFIX.match(core) or _K_PATTERNS.search(core):
        return STRONG
    if _MID_UPPER.search(core) and len(letters) >= 3:
        return WEAK                                         # also "GeM", "eOffice"
    if len(letters) >= 3 and core.islower() and not (_VOWELS & set(letters)):
        return WEAK
    return 0


def _kruti_like(token: str) -> bool:
    return _kruti_signal(token) > 0


def legacy_scores(text: str) -> tuple[int, float, float]:
    """(Latin word count, share of Kruti-like words, share of English words)."""
    words = [w for w in _WORDISH.findall(text) if sum(c.isascii() and c.isalpha() for c in w) >= 2]
    if not words:
        return 0, 0.0, 0.0
    kruti = sum(_kruti_like(w) for w in words)
    english = sum(w.strip(_EDGE).lower() in ENGLISH_WORDS for w in words)
    return len(words), kruti / len(words), english / len(words)


def looks_like_legacy(text: str) -> bool:
    """Latin text that reads like a legacy Hindi font rather than English."""
    if any("ऀ" <= c <= "ॿ" for c in text):
        return False
    words = [w for w in _WORDISH.findall(text) if sum(c.isascii() and c.isalpha() for c in w) >= 2]
    if not words:
        return False
    n, kruti, english = legacy_scores(text)
    if n <= 3:
        # Little evidence: every word must be Kruti-like and one must be typical of it.
        return kruti >= 0.99 and english == 0.0 and any(_kruti_signal(w) == STRONG for w in words)
    return kruti >= 0.4 and english < 0.2


def english_like(text: str) -> bool:
    """Does Latin text read as English (rather than OCR noise or a legacy font)?"""
    n, kruti, english = legacy_scores(text)
    return n > 0 and english >= 0.2 and kruti < 0.4


CONTENT_MIN_LETTERS = 6   # judging a font or line by its text needs at least this much


def _letters(text: str) -> int:
    return sum(c.isascii() and c.isalpha() for c in text)


def _has_deva(text: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in text)


def legacy_spans(lines: Sequence[Sequence[tuple[str, str]]]) -> tuple[set[tuple[int, int]], set[str]]:
    """Find the spans of a page that are in a legacy font encoding.

    lines: the page's text lines, each a sequence of (font name, text) spans.
    Returns the (line index, span index) of every legacy span, and the legacy font names.
    A span with Devanagari in it is real Unicode and never counts.
    """
    by_font: dict[str, list[str]] = {}
    for line in lines:
        for font, text in line:
            if not _has_deva(text):
                by_font.setdefault(font, []).append(text)
    fonts: set[str] = set()
    for font, texts in by_font.items():
        text = " ".join(texts)
        if not _letters(text):
            continue  # digits or symbols only: nothing to misread
        if LEGACY_FONT.search(font) or (_letters(text) >= CONTENT_MIN_LETTERS and looks_like_legacy(text)):
            fonts.add(font)

    found: set[tuple[int, int]] = set()
    for li, line in enumerate(lines):
        latin = [(si, font, text) for si, (font, text) in enumerate(line) if not _has_deva(text) and text.strip()]
        for si, font, _text in latin:
            if font in fonts:
                found.add((li, si))
        # A renamed font that also carries English is judged line by line.
        line_text = " ".join(text for _si, _font, text in latin)
        if _letters(line_text) >= CONTENT_MIN_LETTERS and looks_like_legacy(line_text):
            for si, font, text in latin:
                if _letters(text):
                    found.add((li, si))
                    fonts.add(font)
    return found, fonts


def legacy_font_names(font_texts: Iterable[tuple[str, str]]) -> set[str]:
    """Fonts whose text is in a legacy encoding, by name or by content.

    font_texts: (font name, text) pairs, e.g. one per span.
    """
    return legacy_spans([[pair] for pair in font_texts])[1]
