"""Pick the version of each sentence to show (PLAN.md §7.2).

Candidates arrive in preference order: the chosen model's final translation first,
then the IndicTrans2 draft. The first candidate that is usable and has no red issue
wins. If none is clean, the first usable one is kept but marked red. If nothing is
usable, the Hindi stays and the sentence is marked red for a human.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .validate import AMBER, RED, CheckResult


@dataclass
class Candidate:
    engine: str
    text: str | None
    checks: CheckResult
    is_fallback: bool = False


@dataclass
class Choice:
    text: str
    engine: str
    confidence: str
    issues: list[str] = field(default_factory=list)


def choose(source: str, candidates: list[Candidate], page_flagged: bool = False) -> Choice:
    usable = [c for c in candidates if c.text and c.checks.usable]
    clean = [c for c in usable if RED not in c.checks.issues.values()]
    pick = clean[0] if clean else (usable[0] if usable else None)
    if pick is None:
        return Choice(source, "untranslated", RED, ["untranslated"])

    issues = list(pick.checks.issues)
    confidence = pick.checks.confidence
    if pick.is_fallback and "fallback" not in issues:
        issues.append("fallback")
        if confidence != RED:
            confidence = AMBER
    if page_flagged and "ocr" not in issues:
        issues.append("ocr")
        if confidence != RED:
            confidence = AMBER
    return Choice(pick.text or source, pick.engine, confidence, issues)
