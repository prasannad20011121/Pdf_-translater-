"""Split paragraphs into sentences.

Hindi ends sentences with the danda (।). Typed documents also use ".", "?" and "!"
so we split on those too, but not after common abbreviations such as "डॉ." or "Rs.".
"""

from __future__ import annotations

import re

_END_STRONG = re.compile("(?<=[\\u0964\\u0965?!])\\s+")
_PERIOD_GAP = re.compile("\\.\\s+")

ABBREVIATIONS = {
    # Hindi
    "सं", "क्र", "डॉ", "श्री",
    "श्रीमती", "पृ", "नं",
    "प्रो", "मो", "फो", "दि",
    "ई", "वि",
    # English
    "dr", "mr", "mrs", "ms", "no", "nos", "rs", "ltd", "pvt", "st", "vs", "etc", "govt",
    "dept", "sl", "ref", "memo", "e.g", "i.e", "fig", "p", "pp", "vol", "sr", "jr", "co",
    "inc", "smt", "sh", "shri",
}

LONG_SENTENCE = 400


def _split_on_periods(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for m in _PERIOD_GAP.finditer(text):
        before = text[start:m.start()].split()
        last = before[-1].lower().rstrip(".") if before else ""
        # Keep abbreviations and initials ("A. K. Singh") inside the sentence.
        if not last or last in ABBREVIATIONS or len(last) == 1:
            continue
        parts.append(text[start:m.start() + 1].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _split_long(sentence: str) -> list[str]:
    """Very long run-on sentences overflow small models; split them at semicolons."""
    if len(sentence) <= LONG_SENTENCE or ";" not in sentence:
        return [sentence]
    pieces = [p.strip() for p in sentence.split(";")]
    out = [p + ";" for p in pieces[:-1] if p] + ([pieces[-1]] if pieces[-1] else [])
    return out or [sentence]


def split_sentences(paragraph: str) -> list[str]:
    text = " ".join(paragraph.split())
    if not text:
        return []
    sentences: list[str] = []
    for chunk in _END_STRONG.split(text):
        for piece in _split_on_periods(chunk):
            sentences.extend(_split_long(piece))
    return [s for s in sentences if s]
