"""Settings, paths and hardware profiles.

Paths can be overridden with environment variables so the same code runs from a
source checkout, from the Windows installer, and inside tests:

- PDFT_HOME       data folder (jobs, database). Default: <repo>/data
- PDFT_PROFILE    force a profile (laptop-8gb, laptop-12gb, workstation, dev)
- PDFT_MODELS     model store folder. Default: <repo>/models/store
- PDFT_LLAMA_BIN  path to llama-server(.exe). Default: <repo>/bin/llama-server or PATH
- PDFT_TESSERACT  path to tesseract(.exe). Default: PATH
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import psutil
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = REPO_ROOT / "profiles"
CATALOG_PATH = REPO_ROOT / "models" / "catalog.yaml"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

CHOICES = ("auto", "fast", "balanced", "best")


@dataclass
class Profile:
    name: str
    label: str
    ram_budget_gb: float
    cpu_threads: int
    default_choice: str
    choices: dict[str, str | None]
    step_down: list[str]
    quick_draft_model: str | None
    low_memory_draft_model: str | None
    llm: dict[str, Any]
    limits: dict[str, Any]

    @classmethod
    def load(cls, name: str) -> "Profile":
        path = PROFILES_DIR / f"{name}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        threads = data.get("cpu_threads", "auto")
        if threads == "auto":
            threads = max(1, (os.cpu_count() or 2) - 1)
        return cls(
            name=data["name"],
            label=data.get("label", data["name"]),
            ram_budget_gb=float(data["ram_budget_gb"]),
            cpu_threads=int(threads),
            default_choice=data.get("default_choice", "auto"),
            choices=dict(data.get("choices", {})),
            step_down=list(data.get("step_down", [])),
            quick_draft_model=data.get("quick_draft_model"),
            low_memory_draft_model=data.get("low_memory_draft_model"),
            llm=dict(data.get("llm", {})),
            limits=dict(data.get("limits", {})),
        )


def total_ram_gb() -> float:
    return psutil.virtual_memory().total / 1024**3


def detect_profile_name() -> str:
    """Pick a profile from installed RAM. The workstation profile is never automatic."""
    forced = os.environ.get("PDFT_PROFILE")
    if forced:
        return forced
    return "laptop-8gb" if total_ram_gb() < 10 else "laptop-12gb"


@dataclass
class Settings:
    home: Path
    models_dir: Path
    profile: Profile
    llama_server_bin: str | None
    tesseract_cmd: str | None
    host: str = "127.0.0.1"
    port: int = 8080
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.home / "app.db"

    @property
    def jobs_dir(self) -> Path:
        return self.home / "jobs"

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    @property
    def is_dev(self) -> bool:
        return self.profile.name == "dev"


def _find_llama_server() -> str | None:
    env = os.environ.get("PDFT_LLAMA_BIN")
    if env:
        return env
    for name in ("llama-server.exe", "llama-server"):
        local = REPO_ROOT / "bin" / name
        if local.exists():
            return str(local)
    return shutil.which("llama-server")


def _find_tesseract() -> str | None:
    return os.environ.get("PDFT_TESSERACT") or shutil.which("tesseract")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    home = Path(os.environ.get("PDFT_HOME", REPO_ROOT / "data"))
    models_dir = Path(os.environ.get("PDFT_MODELS", REPO_ROOT / "models" / "store"))
    home.mkdir(parents=True, exist_ok=True)
    (home / "jobs").mkdir(exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        home=home,
        models_dir=models_dir,
        profile=Profile.load(detect_profile_name()),
        llama_server_bin=_find_llama_server(),
        tesseract_cmd=_find_tesseract(),
    )


def reset_settings_cache() -> None:
    """Used by tests after changing environment variables."""
    get_settings.cache_clear()
