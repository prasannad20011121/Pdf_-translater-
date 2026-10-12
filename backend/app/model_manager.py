"""Which engines can run here, which one a user's choice maps to, and the memory guard.

Only one model is in memory at a time (PLAN.md §4.1): the worker loads an engine for
its stage, runs the whole document through it, and unloads it.

The memory guard (fits / memory_check) counts a model's peak while loading, not just
its running size: IndicTrans2 briefly holds fp32 weights before quantising them. A
model whose peak is above the profile's RAM budget is never used on that laptop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psutil

from .config import CHOICES, Settings
from .model_store import ModelStore
from .pipeline.translate.base import Translator
from .pipeline.translate.devstub import DevStandIn
from .pipeline.translate.indictrans2 import IndicTrans2Engine
from .pipeline.translate.indictrans2 import runtime_available as it2_runtime
from .pipeline.translate.llamacpp import LlamaServerEngine

MEMORY_MARGIN_GB = 0.5

CHOICE_LABELS = {
    "auto": "Auto (recommended)",
    "fast": "Fast",
    "balanced": "Balanced",
    "best": "Best quality",
}
CHOICE_HINTS = {
    "auto": "The best model that fits this laptop right now",
    "fast": "IndicTrans2 only: quickest, more literal English",
    "balanced": "Gemma 4 E2B: natural English, slower",
    "best": "Gemma 4 E4B: best quality, slowest",
}


def available_memory_gb() -> float:
    return psutil.virtual_memory().available / 1024**3


def fits_in_memory(ram_gb: float) -> bool:
    return available_memory_gb() >= ram_gb + MEMORY_MARGIN_GB


def _file_gb(path: Path | None) -> float:
    try:
        return path.stat().st_size / 1024**3 if path else 0.0
    except OSError:
        return 0.0


@dataclass
class Readiness:
    ready: bool
    reason: str = ""
    # True when the only obstacle is free memory right now: closing other apps can
    # help, so it's worth waiting. A model that is too big for this laptop is not.
    temporary: bool = False


class ModelManager:
    def __init__(self, settings: Settings, store: ModelStore | None = None):
        self.settings = settings
        self.store = store or ModelStore(settings.models_dir)

    # ---- readiness ---------------------------------------------------------------

    def readiness(self, model_id: str | None) -> Readiness:
        if model_id is None:
            return Readiness(False, "no model")
        try:
            entry = self.store.entry(model_id)
        except KeyError as e:
            return Readiness(False, str(e))
        if entry.kind == "dev":
            return Readiness(self.settings.is_dev, "" if self.settings.is_dev else "developer profile only")
        if self.store.is_downloading(model_id):
            return Readiness(False, f"{entry.label} is still downloading")
        if not self.store.is_installed(model_id):
            return Readiness(False, f"{entry.label} is not installed (Settings > Models)")
        if not self.store.is_verified(model_id):
            return Readiness(False, f"{entry.label} failed its file check: verify or download it again "
                                    "(Settings > Models)")
        budget = self.settings.profile.ram_budget_gb
        if budget and entry.peak_ram_gb > budget:
            return Readiness(False, f"{entry.label} needs about {entry.peak_ram_gb:g} GB, more than this "
                                    f"laptop's {budget:g} GB limit")
        if entry.kind == "llama-gguf" and not self.settings.llama_server_bin:
            return Readiness(False, "llama-server was not found")
        if entry.kind == "indictrans2-hf":
            ok, reason = it2_runtime()
            if not ok:
                return Readiness(False, reason)
        return Readiness(True)

    # ---- memory guard ------------------------------------------------------------

    def required_gb(self, model_id: str, vision: bool = False) -> float:
        """Free memory a model needs: its load peak, plus the vision projector if used."""
        entry = self.store.entry(model_id)
        if entry.kind == "dev":
            return 0.0
        need = entry.peak_ram_gb
        if vision:
            need += _file_gb(self.store.file_path(model_id, "mmproj")) * 1.1
        return need

    def memory_check(self, model_id: str, vision: bool = False) -> Readiness:
        """Can the model be loaded right now without the laptop starting to page?"""
        entry = self.store.entry(model_id)
        if entry.kind == "dev":
            return Readiness(True)
        need = self.required_gb(model_id, vision)
        budget = self.settings.profile.ram_budget_gb
        if budget and need > budget:
            return Readiness(False, f"{entry.label} needs about {need:.1f} GB, more than this laptop's "
                                    f"{budget:g} GB limit")
        free = available_memory_gb()
        if free < need + MEMORY_MARGIN_GB:
            return Readiness(False, f"not enough free memory for {entry.label} (needs about "
                                    f"{need + MEMORY_MARGIN_GB:.1f} GB, {free:.1f} GB free): close other apps",
                             temporary=True)
        return Readiness(True)

    def fits(self, model_id: str, vision: bool = False) -> bool:
        return self.memory_check(model_id, vision).ready

    def draft_model(self) -> str | None:
        """The quick-draft engine: IndicTrans2 1B when its load peak fits, else 200M.

        On 8 GB laptops the 1B model's fp32 load peak is above the 4.5 GB budget, so the
        200M model is used there unless a lighter 1B build (CTranslate2) is configured.
        """
        p = self.settings.profile
        for model_id in (p.quick_draft_model, p.low_memory_draft_model):
            if model_id and self.readiness(model_id).ready and self.fits(model_id):
                return model_id
        return None

    # ---- user choice -------------------------------------------------------------

    def final_candidates(self, choice: str) -> list[str]:
        """Models to try for the final translation, best first. Empty = IndicTrans2 only."""
        p = self.settings.profile
        target = p.choices.get(choice)
        if target is None:
            return []
        if choice == "auto":
            return [m for m in p.step_down if m]
        # An explicit choice is tried first; smaller models are only a safety net.
        rest = [m for m in p.step_down if m and m != target]
        smaller = [m for m in rest if self.store.entry(m).ram_gb <= self.store.entry(target).ram_gb]
        return [target, *smaller]

    def choices(self) -> list[dict]:
        """What the Upload page offers, with greyed-out options and reasons."""
        p = self.settings.profile
        draft_ready = any(
            self.readiness(m).ready for m in (p.quick_draft_model, p.low_memory_draft_model) if m
        )
        out = []
        for choice in CHOICES:
            if choice not in p.choices:
                out.append({
                    "id": choice, "label": CHOICE_LABELS[choice], "hint": CHOICE_HINTS[choice],
                    "available": False, "reason": "Needs a 12 GB laptop", "model": None,
                })
                continue
            model_id = p.choices[choice]
            if model_id is None:
                ready = Readiness(draft_ready, "" if draft_ready else "IndicTrans2 is not installed")
                label = "IndicTrans2"
            else:
                ready = self.readiness(model_id)
                label = self.store.entry(model_id).label
                if choice == "auto" and not ready.ready and draft_ready:
                    ready = Readiness(True, "Will use IndicTrans2 until Gemma 4 is installed")
            out.append({
                "id": choice, "label": CHOICE_LABELS[choice], "hint": CHOICE_HINTS[choice],
                "available": ready.ready, "reason": ready.reason, "model": label,
            })
        return out

    # ---- engines -----------------------------------------------------------------

    def create(self, model_id: str, vision: bool = False) -> Translator:
        """Build the engine for a model. vision=True only for page re-reading (Phase 2):
        it loads Gemma's vision projector, which text translation doesn't need."""
        entry = self.store.entry(model_id)
        p = self.settings.profile
        if entry.kind == "dev":
            unit = "paragraph" if "translate" in entry.roles else "sentence"
            return DevStandIn(entry.id, entry.label, unit=unit)
        if entry.kind == "indictrans2-hf":
            return IndicTrans2Engine(
                entry.id, entry.label, self.store.model_dir(model_id), entry.ram_gb,
                threads=p.cpu_threads, src_lang=entry.src_lang, tgt_lang=entry.tgt_lang,
            )
        if entry.kind == "llama-gguf":
            llm = p.llm
            return LlamaServerEngine(
                entry.id, entry.label, entry.ram_gb,
                server_bin=self.settings.llama_server_bin,
                model_path=self.store.file_path(model_id, "model"),
                mmproj_path=self.store.file_path(model_id, "mmproj") if vision else None,
                ctx=int(llm.get("ctx", 6144)),
                threads=p.cpu_threads,
                temperature=float(llm.get("temperature", 0.2)),
                timeout_s_per_sentence=float(llm.get("timeout_s_per_sentence", 90)),
                extra_args=entry.extra_args,
                vision=vision,
                parallel=_opt_int(llm, "parallel", 1),
                cache_ram_mib=_opt_int(llm, "cache_ram_mib", 0),
                ctx_checkpoints=_opt_int(llm, "ctx_checkpoints", 2),
                log_path=self.settings.logs_dir / "llama-server.log",
                run_dir=self.settings.run_dir,
            )
        raise KeyError(f"unknown engine kind '{entry.kind}'")


def _opt_int(options: dict, key: str, default: int | None) -> int | None:
    """A profile llm option; null in the YAML means "don't pass this flag"."""
    if key not in options:
        return default
    value = options[key]
    return None if value is None else int(value)
