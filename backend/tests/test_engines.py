import os
import stat
import sys
from pathlib import Path

import pytest

from app.pipeline.protect import protect, restore
from app.pipeline.select import Candidate, choose
from app.pipeline.translate.base import DocContext, EngineUnavailable
from app.pipeline.translate.devstub import transliterate
from app.pipeline.translate.llamacpp import LlamaServerEngine
from app.pipeline.translate.prompts import output_schema, parse_output, user_prompt
from app.pipeline.validate import AMBER, GREEN, RED, check

SRC = "निविदा की अंतिम तिथि 25.03.2026 तक बढ़ाई गई है।"


# --- validators ------------------------------------------------------------------

def test_good_translation_is_green():
    r = check(SRC, "The last date of the tender has been extended to 25.03.2026.")
    assert r.usable and r.confidence == GREEN


def test_wrong_number_is_red_but_usable():
    r = check(SRC, "The last date of the tender has been extended to 26.03.2026.")
    assert r.usable and r.issues == {"numbers": RED}


@pytest.mark.parametrize("output,code", [
    ("", "empty"),
    (SRC, "still_hindi"),
    ("Here is the translation: tender extended to 25.03.2026.", "chatter"),
    ("the date the date the date the date the date the date 25.03.2026", "loop"),
])
def test_unusable_outputs(output, code):
    r = check(SRC, output)
    assert not r.usable and code in r.issues


def test_glossary_and_length_are_amber():
    glossary = [("निविदा", "tender")]
    r = check(SRC, "The last date of the bid has been extended to 25.03.2026.", glossary=glossary)
    assert r.issues == {"glossary": AMBER}
    r = check(SRC, "Extended 25.03.2026.")
    assert r.issues == {"length": AMBER}


def test_placeholder_loss_is_red():
    p = protect(SRC)
    restored = restore("The tender date has been extended.", p.items)
    r = check(SRC, restored.text, restored=restored)
    assert r.issues["placeholders"] == RED


# --- selection --------------------------------------------------------------------

def test_choose_prefers_clean_final_then_draft_then_hindi():
    good = check(SRC, "The last date of the tender has been extended to 25.03.2026.")
    bad_num = check(SRC, "The last date of the tender has been extended to 26.03.2026.")
    unusable = check(SRC, SRC)

    c = choose(SRC, [Candidate("gemma", "x 26.03.2026", bad_num), Candidate("it2", "y 25.03.2026", good, is_fallback=True)])
    assert c.engine == "it2" and c.confidence == AMBER and "fallback" in c.issues

    c = choose(SRC, [Candidate("gemma", "x", good)])
    assert c.engine == "gemma" and c.confidence == GREEN

    c = choose(SRC, [Candidate("gemma", "x", bad_num)])
    assert c.confidence == RED and "numbers" in c.issues

    c = choose(SRC, [Candidate("gemma", SRC, unusable)])
    assert c.engine == "untranslated" and c.text == SRC and c.confidence == RED


def test_flagged_ocr_page_is_never_green():
    good = check(SRC, "The last date of the tender has been extended to 25.03.2026.")
    assert choose(SRC, [Candidate("gemma", "x", good)], page_flagged=True).confidence == AMBER


# --- prompts ----------------------------------------------------------------------

def test_prompt_numbers_sentences_and_includes_glossary():
    ctx = DocContext(subject="निविदा विस्तार", glossary=[("निविदा", "Tender")])
    text = user_prompt(["पहला।", "दूसरा।"], ctx)
    assert "[1] पहला।" in text and "[2] दूसरा।" in text and "निविदा = Tender" in text
    assert output_schema(2)["required"] == ["1", "2"]


def test_parse_output_tolerates_fences_and_missing_keys():
    assert parse_output('```json\n{"1": "One.", "2": "Two."}\n```', 2) == ["One.", "Two."]
    assert parse_output('{"1": "One."}', 2) == ["One.", None]
    assert parse_output("not json", 2) == [None, None]


def test_dev_standin_keeps_placeholders_and_numbers():
    out = transliterate("ज्ञापांक ⟦N1⟧ दिनांक 12.03.2026")
    assert "⟦N1⟧" in out and "12.03.2026" in out
    assert not any("ऀ" <= ch <= "ॿ" for ch in out)


# --- llama-server adapter, with a fake server binary --------------------------------

@pytest.fixture()
def fake_server_bin(tmp_path) -> Path:
    script = Path(__file__).with_name("fake_llama_server.py")
    launcher = tmp_path / "llama-server"
    launcher.write_text(f"#!{sys.executable}\nimport runpy, sys\nrunpy.run_path({str(script)!r}, run_name='__main__')\n")
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return launcher


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shebang launcher")
def test_llama_server_engine_full_lifecycle(fake_server_bin, tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    engine = LlamaServerEngine("gemma4-e2b", "Gemma 4 E2B", 4.0, server_bin=str(fake_server_bin), model_path=model)
    engine.load()
    try:
        p = protect(SRC)
        [out] = engine.translate([p.text], DocContext())
        restored = restore(out, p.items)
        assert restored.missing == []
        assert "25.03.2026" in restored.text
        assert engine._proc is not None and engine._proc.poll() is None
    finally:
        engine.unload()
    assert engine._proc is None


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shebang launcher")
def test_llama_server_garbage_output_gives_none(fake_server_bin, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_MODE", "garbage")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    engine = LlamaServerEngine("x", "x", 1.0, server_bin=str(fake_server_bin), model_path=model)
    engine.load()
    try:
        assert engine.translate(["एक।", "दो।"], DocContext()) == [None, None]
    finally:
        engine.unload()


def test_llama_server_missing_binary_is_unavailable(tmp_path):
    engine = LlamaServerEngine("x", "x", 1.0, server_bin=str(tmp_path / "nope"), model_path=tmp_path / "m.gguf")
    with pytest.raises(EngineUnavailable):
        engine.load()


# --- model manager ----------------------------------------------------------------

def test_dev_profile_choices_and_candidates(app_env):
    from app.model_manager import ModelManager

    mm = ModelManager(app_env)
    choices = {c["id"]: c for c in mm.choices()}
    assert choices["auto"]["available"] and choices["fast"]["available"]
    assert mm.final_candidates("fast") == []
    assert mm.final_candidates("auto") == ["dev-standin-llm"]
    assert mm.draft_model() == "dev-standin-draft"


def test_laptop_profile_reports_missing_models(app_env, monkeypatch):
    from app import config
    from app.model_manager import ModelManager

    monkeypatch.setenv("PDFT_PROFILE", "laptop-8gb")
    config.reset_settings_cache()
    mm = ModelManager(config.get_settings())
    choices = {c["id"]: c for c in mm.choices()}
    assert not choices["best"]["available"] and choices["best"]["reason"] == "Needs a 12 GB laptop"
    assert not choices["balanced"]["available"]
    assert "not installed" in choices["balanced"]["reason"]
    assert mm.final_candidates("balanced") == ["gemma4-e2b"]
