"""Split paragraphs into sentences.

Hindi ends sentences with the danda (।). Typed documents also use ".", "?" and "!"
so we split on those too, but not after common abbreviations such as "डॉ." or "Rs.",
initials ("आर. के. सिंह", "A. K. Singh") or list numbers ("2. सचिव").
"""

from __future__ import annotations

import re
import unicodedata

_END_STRONG = re.compile("(?<=[\\u0964\\u0965?!])\\s+")
_PERIOD_GAP = re.compile("\\.\\s+")


def _nfc(words: str) -> set[str]:
    return {unicodedata.normalize("NFC", w) for w in words.split()}


# Hindi abbreviations written with a period.
HINDI_ABBREVIATIONS = _nfc(
    "सं क्र डॉ डा श्री श्रीमती पृ नं प्रो मो फो दि ई वि रु रू कु पं प्र नि मु जि सा ह उ म भा "
    "मि सु अनु ज्ञा पत्रां"
)
# English letters spelled in Devanagari, used as initials: "आर. के. सिंह" (R. K. Singh),
# "जे.पी. सिंह". Postpositions such as के and से never end a Hindi sentence, so these
# are safe; verbs that can end one (आई "came") are left out.
HINDI_INITIALS = _nfc(
    "ए बी सी डी ई एफ जी एच जे के एल एम एन ओ पी क्यू आर एस टी यू वी डब्ल्यू एक्स वाई जेड ज़ेड"
)
ENGLISH_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "no", "nos", "rs", "ltd", "pvt", "st", "vs", "etc", "govt",
    "dept", "sl", "ref", "memo", "e.g", "i.e", "fig", "p", "pp", "vol", "sr", "jr", "co",
    "inc", "smt", "sh", "shri",
}
ABBREVIATIONS = HINDI_ABBREVIATIONS | HINDI_INITIALS | ENGLISH_ABBREVIATIONS

_LIST_NUMBER = re.compile("[0-9\u0966-\u096f]{1,2}")
_HAS_DIGIT = re.compile("[0-9\u0966-\u096f]")
_LEAD_PUNCT = "(\"'[{\u201c\u2018"

LONG_SENTENCE = 400   # longer sentences are split further (IndicTrans2 reads 256 tokens)
MAX_PIECE = 300       # target length of the pieces of a long sentence
MIN_PIECE = 60        # don't cut off fragments shorter than this


def _keeps_period(token: str) -> bool:
    """Is the period after this token part of an abbreviation, an initial or a list number?"""
    last = token.lstrip(_LEAD_PUNCT).rstrip(".")
    low = last.lower()
    if not last or low in ABBREVIATIONS or len(last) == 1:
        return True
    if _LIST_NUMBER.fullmatch(last):          # "पटना 10. सचिव": a list number
        return True
    if "." in last and not _HAS_DIGIT.search(last):
        # Dotted acronyms: "जे.पी", "भा.प्र.से", "U.P", "i.e" (but not "www.bihar.gov").
        parts = last.split(".")
        return all(p and (p.lower() in ABBREVIATIONS or len(p) <= 3) for p in parts)
    return False


def _split_on_periods(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for m in _PERIOD_GAP.finditer(text):
        before = text[start:m.start()].split()
        if not before or _keeps_period(before[-1]):
            continue
        parts.append(text[start:m.start() + 1].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


# Where a long sentence may be cut, best first. Each pattern marks the cut position
# (the end of the match): after a colon or comma, before a conjunction or a list number.
_CUT_LEVELS = [
    re.compile(":\\s+(?=\\S)"),
    # "2. सचिव", "10) ...", "(क) ...", "(ii) ..." (a letter followed by "." is an initial)
    re.compile(
        "\\s+(?=(?:[0-9\u0966-\u096f]{1,2}[.)]"
        "|\\(?(?:[a-z]|[\u0915-\u0939]|[ivx]{1,4}|[0-9\u0966-\u096f]{1,2})\\))\\s)"
    ),
    re.compile("(?<![0-9\u0966-\u096f]),\\s+(?![0-9\u0966-\u096f])|(?<=[0-9\u0966-\u096f]),\\s+(?=\\D)"),
    re.compile("\\s+(?=(?:तथा|एवं|एवम्|अथवा|और|या|किंतु|किन्तु|परंतु|परन्तु|लेकिन|जिसमें|जिससे|ताकि)\\s)"),
    re.compile("\\s+"),
]


def _pack(text: str, cuts: list[int]) -> list[str]:
    """Cut text at some of the given positions into pieces of MIN_PIECE..MAX_PIECE chars."""
    pieces: list[str] = []
    start = 0
    while len(text) - start > MAX_PIECE:
        fitting = [p for p in cuts if MIN_PIECE <= p - start <= MAX_PIECE and len(text) - p >= MIN_PIECE]
        if fitting:
            cut = fitting[-1]
        else:
            # Nothing fits: take the first usable cut; the next level splits the rest.
            later = [p for p in cuts if p - start >= MIN_PIECE and len(text) - p >= MIN_PIECE]
            if not later:
                break
            cut = later[0]
        pieces.append(text[start:cut].strip())
        start = cut
    pieces.append(text[start:].strip())
    return [p for p in pieces if p]


def _split_at_levels(text: str, level: int = 0) -> list[str]:
    if len(text) <= MAX_PIECE or level >= len(_CUT_LEVELS):
        return [text]
    cuts = [m.end() for m in _CUT_LEVELS[level].finditer(text)]
    out: list[str] = []
    for piece in _pack(text, cuts):
        out.extend(_split_at_levels(piece, level + 1) if len(piece) > MAX_PIECE else [piece])
    return out


def _split_long(sentence: str) -> list[str]:
    """Very long run-on sentences overflow small models (IndicTrans2 silently cuts
    off what doesn't fit in 256 tokens). Split them at semicolons first, then at
    colons, list numbers, commas and conjunctions, and as a last resort between words."""
    if len(sentence) <= LONG_SENTENCE:
        return [sentence]
    if ";" in sentence:
        pieces = [p.strip() for p in sentence.split(";")]
        parts = [p + ";" for p in pieces[:-1] if p] + ([pieces[-1]] if pieces[-1] else [])
    else:
        parts = [sentence]
    out: list[str] = []
    for part in parts or [sentence]:
        out.extend(_split_at_levels(part))
    return out


def split_sentences(paragraph: str) -> list[str]:
    text = " ".join(paragraph.split())
    if not text:
        return []
    sentences: list[str] = []
    for chunk in _END_STRONG.split(text):
        for piece in _split_on_periods(chunk):
            sentences.extend(_split_long(piece))
    return [s for s in sentences if s]
