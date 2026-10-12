"""Common interface for every translation engine (PLAN.md §10)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field

# Per-sentence warnings an engine can report in Translator.last_flags.
TRUNCATED = "truncated"  # the output looks cut short (much shorter than the input)
SPLIT = "split"          # a very long sentence was translated in pieces and rejoined


class EngineUnavailable(RuntimeError):
    """The engine can't run here: model not installed, runtime missing, or it crashed.

    Engines raise this from load() and translate() for every "can't run" condition.
    Callers should still treat any other exception from an engine the same way.
    """


@dataclass
class DocContext:
    subject: str = ""
    previous_english: str = ""
    glossary: list[tuple[str, str]] = field(default_factory=list)
    examples: list[tuple[str, str]] = field(default_factory=list)  # similar approved pairs


class Translator(ABC):
    id: str
    label: str
    ram_gb: float = 0.0
    is_external: bool = False
    # "sentence": any batch of sentences; "paragraph": called once per paragraph with
    # its sentences numbered, and the input uses ⟦..⟧ placeholders (see protect.py).
    unit: str = "sentence"
    uses_placeholders: bool = False
    # After translate(): one set of warnings per input (TRUNCATED, SPLIT), or empty
    # when the engine doesn't report any. Read it right after the call.
    last_flags: Sequence[set[str]] = ()

    def load(self) -> None:  # noqa: B027  (optional hook)
        pass

    def unload(self) -> None:  # noqa: B027
        pass

    @abstractmethod
    def translate(self, texts: list[str], ctx: DocContext) -> list[str | None]:
        """Return one English string per input, or None where it failed."""
