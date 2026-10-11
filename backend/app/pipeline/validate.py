"""Checks on every translated sentence (PLAN.md §7.3).

A candidate is *unusable* when it isn't a translation at all (empty, still Hindi,
chatter, a loop). Otherwise it is usable, and its issues set the confidence colour:
red for wrong numbers or lost placeholders, amber for softer doubts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
    "placeholders": "A protected number, name or link went missing",
    "some_hindi": "Some Hindi left in the output",
    "length": "Length is unusual for a faithful translation (possible omission or addition)",
    "glossary": "A glossary term was not used",
    "fallback": "Produced by a fallback engine",
    "ocr": "Page text came from OCR that may be unreliable",
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


def _has_loop(text: str) -> bool:
    words = [w.lower() for w in _WORD.findall(text)]
    run = 1
    for a, b in zip(words, words[1:]):
        run = run + 1 if a == b else 1
        if run > 4:
            return True
    grams: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - 3):
        g = tuple(words[i:i + 4])
        grams[g] = grams.get(g, 0) + 1
        if grams[g] >= 3:
            return True
    return False


def glossary_hits(source: str, glossary: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Glossary entries whose Hindi term appears in the source as whole words."""
    hits = []
    for hi, en in glossary:
        pattern = f"(?<![\\u0900-\\u097f]){re.escape(hi)}(?![\\u0900-\\u097f])"
        if re.search(pattern, source):
            hits.append((hi, en))
    return hits


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
    if _has_loop(output):
        return CheckResult(False, {"loop": RED})

    if numbers_in(source) != numbers_in(output):
        issues["numbers"] = RED
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
