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


_NUMBER = re.compile(r"\d+(?:[./,:\-]\d+)*")


def numbers_in(text: str) -> Counter[str]:
    """Numbers as digit strings, so "5,00,000" and "500000" compare equal."""
    found: Counter[str] = Counter()
    for m in _NUMBER.finditer(ascii_digits(text)):
        digits = re.sub(r"\D", "", m.group())
        if digits:
            found[digits.lstrip("0") or "0"] += 1
    return found
