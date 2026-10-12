"""Model manager: memory guard on load peaks, verified-only readiness, engine creation."""

from __future__ import annotations

import pytest

from app import config, model_manager
from app.model_manager import ModelManager
from app.pipeline.translate.indictrans2 import IndicTrans2Engine
from app.pipeline.translate.llamacpp import LlamaServerEngine

from test_engine_store import write_gemma, write_it2

IT2_1B = "indictrans2-indic-en-1b"
IT2_200M = "indictrans2-indic-en-200m"
GEMMA = "gemma4-e2b"


@pytest.fixture()
def laptop(app_env, monkeypatch):
    """A manager for a given profile, with IndicTrans2 'runnable' and fake memory."""
    def make(profile: str, free_gb: float = 16.0, installed=(IT2_1B, IT2_200M, GEMMA)) -> ModelManager:
        monkeypatch.setenv("PDFT_PROFILE", profile)
        monkeypatch.setenv("PDFT_LLAMA_BIN", "/opt/llama-server")
        config.reset_settings_cache()
        monkeypatch.setattr(model_manager, "it2_runtime", lambda: (True, ""))
        monkeypatch.setattr(model_manager, "available_memory_gb", lambda: free_gb)
        mm = ModelManager(config.get_settings())
        for model_id in installed:
            (write_gemma if model_id == GEMMA else write_it2)(mm.store.model_dir(model_id))
            assert mm.store.verify(model_id, record=True, log=lambda m: None)
        return mm
    return make


def test_draft_uses_1b_when_its_load_peak_fits(laptop):
    assert laptop("laptop-12gb", free_gb=8.0).draft_model() == IT2_1B


def test_draft_falls_back_to_200m_when_the_load_peak_does_not_fit(laptop):
    # 3 GB free would pass the old check (1B ram_gb 1.8 + 0.5) but not the fp32 load peak.
    mm = laptop("laptop-12gb", free_gb=3.0)
    assert not mm.fits(IT2_1B) and mm.fits(IT2_200M)
    assert mm.draft_model() == IT2_200M
    assert "not enough free memory" in mm.memory_check(IT2_1B).reason


def test_8gb_laptop_prefers_200m_even_with_free_memory(laptop):
    mm = laptop("laptop-8gb", free_gb=7.0)
    assert mm.draft_model() == IT2_200M
    ready = mm.readiness(IT2_1B)
    assert not ready.ready and "4.5 GB limit" in ready.reason
    assert {c["id"]: c for c in mm.choices()}["fast"]["available"]


def test_no_draft_when_nothing_fits(laptop):
    assert laptop("laptop-12gb", free_gb=1.0).draft_model() is None


def test_unverified_model_is_not_ready(laptop):
    mm = laptop("laptop-12gb")
    (mm.store.model_dir(IT2_200M) / "modeling_indictrans.py").write_text("tampered = True\n")
    assert not mm.store.verify(IT2_200M, log=lambda m: None)
    ready = mm.readiness(IT2_200M)
    assert not ready.ready and "file check" in ready.reason


def test_partial_download_is_not_ready(laptop):
    mm = laptop("laptop-12gb", installed=())
    d = mm.store.model_dir(IT2_1B)
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")  # what snapshot_download finishes first
    assert not mm.readiness(IT2_1B).ready
    assert mm.draft_model() is None


def test_text_engine_has_no_projector_and_bounded_server(laptop, app_env):
    mm = laptop("laptop-8gb")
    engine = mm.create(GEMMA)
    assert isinstance(engine, LlamaServerEngine)
    assert engine.vision is False and engine.mmproj_path is None
    assert (engine.parallel, engine.cache_ram_mib, engine.ctx_checkpoints) == (1, 0, 2)
    settings = config.get_settings()
    assert engine.log_path == settings.home / "logs" / "llama-server.log"
    assert engine.run_dir == settings.home / "run"


def test_vision_engine_gets_the_projector_and_counts_it(laptop):
    mm = laptop("laptop-12gb")
    engine = mm.create(GEMMA, vision=True)
    assert engine.vision is True and engine.mmproj_path.name == "mmproj-gemma-4-E2B-it-f16.gguf"
    assert mm.required_gb(GEMMA, vision=True) > mm.required_gb(GEMMA)


def test_indictrans2_engine_is_created(laptop):
    engine = laptop("laptop-12gb").create(IT2_200M)
    assert isinstance(engine, IndicTrans2Engine) and engine.ram_gb == 0.8


def test_dev_models_always_fit(app_env):
    mm = ModelManager(app_env)
    assert mm.fits("dev-standin-draft") and mm.draft_model() == "dev-standin-draft"


def test_profile_threads_count_physical_cores(monkeypatch):
    monkeypatch.setattr(config.psutil, "cpu_count", lambda logical=True: 4 if not logical else 8)
    assert config.auto_cpu_threads() == 3
    monkeypatch.setattr(config.psutil, "cpu_count", lambda logical=True: None)
    monkeypatch.setattr(config.os, "cpu_count", lambda: 6)
    assert config.auto_cpu_threads() == 5
    monkeypatch.setattr(config.psutil, "cpu_count", lambda logical=True: 1)
    assert config.auto_cpu_threads() == 1


def test_tesseract_found_in_windows_install_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    exe = tmp_path / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    env = {"ProgramFiles": str(tmp_path / "PF"), "LOCALAPPDATA": str(tmp_path / "Local")}
    assert config._find_tesseract(env, windows=True) == str(exe)
    pf = tmp_path / "PF" / "Tesseract-OCR" / "tesseract.exe"
    pf.parent.mkdir(parents=True)
    pf.write_text("")
    assert config._find_tesseract(env, windows=True) == str(pf)
    assert config._find_tesseract(env, windows=False) is None
    assert config._find_tesseract({**env, "PDFT_TESSERACT": "C:/t.exe"}, windows=True) == "C:/t.exe"
