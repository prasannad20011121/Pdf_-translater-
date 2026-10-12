"""Protect numbers, reference numbers, URLs, e-mails and English words from the LLM.

They are replaced with placeholders such as ⟦N1⟧ before translation and put back
afterwards, so a model cannot change "ज्ञापांक-1234/2026" or "Rs. 5,00,000/-".
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .normalize import ascii_digits

_DIGIT = "[0-9\\u0966-\\u096f]"

# Order matters: earlier patterns win where they overlap.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("U", re.compile(r"(?:https?://|www\.)[^\s<>\"']+[^\s<>\"'.,;:)]")),
    ("E", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    # Numbers, dates, amounts and reference numbers: 12.03.2026, 5,00,000/-, 1234/2026
    ("N", re.compile(f"{_DIGIT}+(?:[./,:\\-]{_DIGIT}+)*(?:/-)?")),
    # Runs of English words/acronyms: "RFP", "GeM portal", "Request for Proposal"
    ("L", re.compile(r"[A-Za-z][A-Za-z0-9&'.\-]*(?:[ ]+[A-Za-z][A-Za-z0-9&'.\-]*)*")),
]

PLACEHOLDER = re.compile(r"[⟦\[]{1,2}\s*([NULE])\s*(\d+)\s*[⟧\]]{1,2}")


@dataclass
class Item:
    key: str        # e.g. "N1"
    kind: str       # N | U | E | L
    original: str
    replacement: str  # what goes into the English output


@dataclass
class Protected:
    text: str
    items: list[Item] = field(default_factory=list)

    def token(self, item: Item) -> str:
        return f"⟦{item.key}⟧"


def protect(text: str) -> Protected:
    spans: list[tuple[int, int, str]] = []
    taken = [False] * len(text)
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            if any(taken[m.start():m.end()]):
                continue
            spans.append((m.start(), m.end(), kind))
            for i in range(m.start(), m.end()):
                taken[i] = True
    spans.sort()
    counters: Counter[str] = Counter()
    items: list[Item] = []
    out: list[str] = []
    pos = 0
    for start, end, kind in spans:
        counters[kind] += 1
        original = text[start:end]
        replacement = ascii_digits(original) if kind == "N" else original
        item = Item(f"{kind}{counters[kind]}", kind, original, replacement)
        items.append(item)
        out.append(text[pos:start])
        out.append(f"⟦{item.key}⟧")
        pos = end
    out.append(text[pos:])
    return Protected("".join(out), items)


@dataclass
class Restored:
    text: str
    missing: list[str]
    duplicated: list[str]
    unknown: list[str]


def restore(output: str, items: list[Item]) -> Restored:
    by_key = {it.key: it for it in items}
    seen: Counter[str] = Counter()
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        key = f"{m.group(1)}{m.group(2)}"
        if key not in by_key:
            unknown.append(key)
            return ""
        seen[key] += 1
        return by_key[key].replacement

    text = PLACEHOLDER.sub(sub, output)
    text = re.sub(r"\s{2,}", " ", text).strip()
    missing = [k for k in by_key if seen[k] == 0]
    duplicated = [k for k, n in seen.items() if n > 1]
    return Restored(text, missing, duplicated, unknown)


_NUMBER = re.compile("\\d+(?:[./,:\\-\u2013\u2014]\\d+)*")
_PART_SEP = re.compile("([./:\\-\u2013\u2014])")
# Thousands grouping, Western (11,800 / 1,000,000) or Indian (5,00,000 / 1,23,45,678).
_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3}")
_RANGE_SEPS = ("-", "\u2013", "\u2014", "/")


def _number_parts(match: str) -> list[str]:
    """Split one matched number into the numbers a reader sees in it.

    "12.03.2026" -> 12, 3, 2026; "5,00,000" -> 500000; "5,6" -> 5, 6;
    "2025-26" -> 2025, 2026 (a financial year, written the same as "2025-2026").
    """
    pieces = _PART_SEP.split(match)
    chunks, seps = pieces[0::2], [""] + pieces[1::2]
    out: list[str] = []
    prev = ""
    for chunk, sep in zip(chunks, seps):
        parts = [chunk.replace(",", "")] if _GROUPED.fullmatch(chunk) else [p for p in chunk.split(",") if p]
        for j, part in enumerate(parts):
            if (j == 0 and sep in _RANGE_SEPS and len(prev) == 4 and prev[:2] in ("19", "20")
                    and len(part) == 2 and int(part) == (int(prev) + 1) % 100):
                part = str(int(prev) + 1)
            out.append(part.lstrip("0") or "0")
            prev = part
    return out


def numbers_in(text: str) -> Counter[str]:
    """The numbers in a text, compared by value rather than by format.

    Devanagari digits count as ASCII, grouping commas are ignored ("5,00,000" equals
    "500000"), and dates, ranges and lists count as separate numbers, so "12.03.2026"
    equals "12/03/2026" and "5,6 एवं 7" equals "5, 6 and 7".
    """
    found: Counter[str] = Counter()
    for m in _NUMBER.finditer(ascii_digits(text)):
        for part in _number_parts(m.group()):
            found[part] += 1
    return found
