"""Common interface for every translation engine (PLAN.md §10)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class EngineUnavailable(RuntimeError):
    """The engine can't run here: model not installed, runtime missing, or it crashed."""


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

    def load(self) -> None:  # noqa: B027  (optional hook)
        pass

    def unload(self) -> None:  # noqa: B027
        pass

    @abstractmethod
    def translate(self, texts: list[str], ctx: DocContext) -> list[str | None]:
        """Return one English string per input, or None where it failed."""
