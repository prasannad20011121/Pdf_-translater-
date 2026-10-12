"""IndicTrans2: built-in processor, failure handling, load peak and long sentences.

torch and transformers are not installed in the test environment, so the engine runs
against small fakes that record how they are called.
"""

from __future__ import annotations

import contextlib
import sys
import types
from pathlib import Path

import pytest

from app.pipeline.translate import indic_processor as ipm
from app.pipeline.translate import indictrans2 as it2
from app.pipeline.translate.base import SPLIT, TRUNCATED, DocContext, EngineUnavailable
from app.pipeline.translate.indic_processor import SimpleIndicProcessor, make_indic_processor, moses_detokenize_en

SRC = "निविदा की अंतिम तिथि 25.03.2026 तक बढ़ाई गई है।"


# ---- built-in processor -----------------------------------------------------------------------

def test_preprocess_adds_tags_and_protects_numbers():
    ip = SimpleIndicProcessor()
    [prepared] = ip.preprocess_batch([SRC], src_lang="hin_Deva", tgt_lang="eng_Latn")
    assert prepared.startswith("hin_Deva eng_Latn ")
    assert "25.03.2026" not in prepared and "< ID1 >" in prepared
    assert prepared.endswith("।")
    # The model answers with the placeholder (here in the tokenised form); it is restored.
    [out] = ip.postprocess_batch(["The last date of the tender has been extended to < ID1 > ."], lang="eng_Latn")
    assert out == "The last date of the tender has been extended to 25.03.2026."


def test_longest_numbers_are_replaced_first():
    ip = SimpleIndicProcessor()
    [prepared] = ip.preprocess_batch(["दिनांक 12.03.2026 और 12.03"], src_lang="hin_Deva", tgt_lang="eng_Latn")
    [out] = ip.postprocess_batch([prepared.split(" ", 2)[2]], lang="eng_Latn")
    assert "12.03.2026" in out and "12.03" in out.replace("12.03.2026", "")


def test_indic_normalisation():
    assert ipm.normalize_indic("ज़रूरी") == "ज़रूरी"  # ज़ decomposed
    assert ipm.normalize_indic("काम पूरा|") == "काम पूरा।"
    assert ipm.normalize_indic("क्‍ष") == "क्ष"
    assert ipm.trivial_tokenize("राशि 5,00,000 रुपये, दिनांक 12 . 03 . 2026") == \
        ["राशि", "5,00,000", "रुपये", ",", "दिनांक", "12.03.2026"]


def test_moses_detokeniser_english_rules():
    assert moses_detokenize_en("Rs. 5,00,000 ( five lakh ) was paid .") == "Rs. 5,00,000 (five lakh) was paid."
    assert moses_detokenize_en('He said " yes " .') == 'He said "yes".'
    assert moses_detokenize_en("the officer 's order") == "the officer's order"
    assert moses_detokenize_en("₹ 500") == "₹500"


def test_digit_space_digit_is_not_turned_into_a_decimal():
    """IndicTransToolkit turns "2 3" into "2.3"; the built-in processor must not."""
    ip = SimpleIndicProcessor()
    [prepared] = ip.preprocess_batch(["धारा 2 3 देखें"], src_lang="hin_Deva", tgt_lang="eng_Latn")
    assert "2 3" in prepared


def test_unsupported_source_scripts_are_refused():
    with pytest.raises(NotImplementedError):
        SimpleIndicProcessor().preprocess_batch(["x"], src_lang="ben_Beng", tgt_lang="eng_Latn")


def test_fallback_is_used_without_the_toolkit(monkeypatch):
    monkeypatch.setitem(sys.modules, "IndicTransToolkit", None)  # import fails
    monkeypatch.setitem(sys.modules, "IndicTransToolkit.processor", None)
    processor, kind = make_indic_processor()
    assert kind == "built-in" and isinstance(processor, SimpleIndicProcessor)
    monkeypatch.setenv("PDFT_INDIC_PROCESSOR", "builtin")
    assert make_indic_processor()[1] == "built-in"


def test_runtime_does_not_require_the_toolkit(monkeypatch):
    for name in ("torch", "transformers", "sentencepiece"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "IndicTransToolkit", None)
    assert it2.runtime_available() == (True, "")


# ---- long sentences ------------------------------------------------------------------------------

def words(text: str) -> int:
    return len(text.split())


def test_split_long_prefers_clause_boundaries():
    clause = "यह एक लंबा उपवाक्य है जिसमें कई शब्द हैं"  # 9 words
    text = ", ".join([clause] * 6) + " और राशि 5,00,000 रुपये है।"
    pieces = it2.split_long(text, words, limit=20)
    assert len(pieces) > 1 and all(words(p) <= 20 for p in pieces)
    assert " ".join(pieces) == text
    assert any("5,00,000" in p for p in pieces), "never split inside a number"


def test_split_long_falls_back_to_words():
    text = " ".join(["शब्द"] * 50)
    pieces = it2.split_long(text, words, limit=12)
    assert all(words(p) <= 12 for p in pieces) and " ".join(pieces) == text


def test_short_text_is_not_split():
    assert it2.split_long(SRC, words, limit=200) == [SRC]


def test_looks_truncated():
    long_src = "क" * 200
    assert it2.looks_truncated(long_src, "Short.")
    assert not it2.looks_truncated(long_src, "x" * 150)
    assert not it2.looks_truncated("छोटा", "A")


# ---- engine with fake torch / transformers ----------------------------------------------------

class FakeTensor:
    def __init__(self, rows):
        self.rows = rows

    def tolist(self):
        return [list(r) for r in self.rows]


EOS, PAD, START = 2, 1, 0


class FakeTokenizer:
    """One token per whitespace-separated word; remembers each text by an id."""

    def __init__(self):
        self.texts: dict[int, str] = {}

    def _encode(self, text: str) -> list[int]:
        tid = 1000 + len(self.texts)
        self.texts[tid] = text
        return [tid] + [5] * (len(text.split()) - 1)

    def __call__(self, texts, truncation=False, max_length=None, padding=None, return_tensors=None,
                 return_attention_mask=False):
        single = isinstance(texts, str)
        rows = [self._encode(t) for t in ([texts] if single else texts)]
        if truncation and max_length:
            rows = [r[:max_length] for r in rows]
        if return_tensors == "pt":
            width = max(len(r) for r in rows)
            return {"input_ids": FakeTensor([r + [PAD] * (width - len(r)) for r in rows]),
                    "attention_mask": FakeTensor([[1] * len(r) + [0] * (width - len(r)) for r in rows])}
        return {"input_ids": rows[0] if single else rows}

    def batch_decode(self, generated, **kw):
        out = []
        for row in generated.tolist():
            text = self.texts.get(row[1], "")
            out.append(text.split(" ", 2)[2] if text.count(" ") >= 2 else "loop loop loop")
        return out


class FakeModel:
    def __init__(self, behaviour: dict):
        self.behaviour = behaviour
        self.config = types.SimpleNamespace(max_source_positions=256, eos_token_id=EOS, pad_token_id=PAD)
        self.generation_config = None
        self.calls: list[dict] = []

    def eval(self):
        return self

    def generate(self, input_ids, attention_mask, max_new_tokens, **kw):
        self.calls.append({"batch": len(input_ids.rows), "max_new_tokens": max_new_tokens, **kw})
        fail = self.behaviour.get("generate_error")
        if fail is not None and (not callable(fail) or fail(input_ids.rows)):
            raise fail if isinstance(fail, BaseException) else RuntimeError("generate failed")
        rows = []
        for r in input_ids.rows:
            if self.behaviour.get("loop"):
                rows.append([START] + [7] * max_new_tokens)
            else:
                rows.append([START, r[0], EOS])
        width = max(len(r) for r in rows)
        return FakeTensor([r + [PAD] * (width - len(r)) for r in rows])


@pytest.fixture()
def fake_runtime(monkeypatch, tmp_path):
    """Install fake torch/transformers; returns (behaviour dict, call log, model dir)."""
    behaviour: dict = {}
    calls: dict = {"quantize": [], "from_pretrained": []}

    torch = types.ModuleType("torch")
    torch.set_num_threads = lambda n: None
    torch.no_grad = contextlib.nullcontext
    torch.qint8 = "qint8"
    torch.nn = types.SimpleNamespace(Linear="Linear")

    def quantize_dynamic(model, layers, dtype=None, inplace=False):
        calls["quantize"].append({"inplace": inplace, "dtype": dtype})
        if behaviour.get("quantize_error"):
            raise behaviour["quantize_error"]
        return model

    torch.quantization = types.SimpleNamespace(quantize_dynamic=quantize_dynamic)
    torch.ao = types.SimpleNamespace(quantization=torch.quantization)

    transformers = types.ModuleType("transformers")

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(path, **kw):
            calls["from_pretrained"].append(("tokenizer", kw))
            return FakeTokenizer()

    class AutoModelForSeq2SeqLM:
        @staticmethod
        def from_pretrained(path, **kw):
            calls["from_pretrained"].append(("model", kw))
            if behaviour.get("load_error"):
                raise behaviour["load_error"]
            model = FakeModel(behaviour)
            behaviour["model"] = model
            return model

    transformers.AutoTokenizer = AutoTokenizer
    transformers.AutoModelForSeq2SeqLM = AutoModelForSeq2SeqLM
    for name, module in (("torch", torch), ("transformers", transformers),
                         ("sentencepiece", types.ModuleType("sentencepiece"))):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("PDFT_INDIC_PROCESSOR", "builtin")
    model_dir = tmp_path / "it2"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}")
    return behaviour, calls, model_dir


def make_engine(model_dir: Path, **kw) -> it2.IndicTrans2Engine:
    return it2.IndicTrans2Engine("indictrans2-indic-en-200m", "IndicTrans2 200M", model_dir, 0.8, threads=2, **kw)


def test_load_keeps_one_fp32_copy(fake_runtime):
    behaviour, calls, model_dir = fake_runtime
    engine = make_engine(model_dir)
    engine.load()
    assert calls["quantize"] == [{"inplace": True, "dtype": "qint8"}]
    model_kw = dict(calls["from_pretrained"])["model"]
    assert model_kw["low_cpu_mem_usage"] is True and model_kw["local_files_only"] is True
    assert engine.processor_kind == "built-in"


@pytest.mark.parametrize("error,match", [
    (OSError("Unable to load weights from model.safetensors"), "could not start"),
    (RuntimeError("[enforce fail] DefaultCPUAllocator: not enough memory"), "ran out of memory"),
    (MemoryError(), "ran out of memory"),
])
def test_load_errors_become_engine_unavailable(fake_runtime, error, match):
    behaviour, _, model_dir = fake_runtime
    behaviour["load_error"] = error
    engine = make_engine(model_dir)
    with pytest.raises(EngineUnavailable, match=match):
        engine.load()
    assert engine._model is None and engine._tokenizer is None


def test_failed_quantisation_keeps_the_fp32_model(fake_runtime):
    behaviour, _, model_dir = fake_runtime
    behaviour["quantize_error"] = RuntimeError("NoQEngine")
    engine = make_engine(model_dir)
    engine.load()
    assert engine._model is not None and engine.notes


def test_translate_round_trip_restores_numbers(fake_runtime):
    _, _, model_dir = fake_runtime
    engine = make_engine(model_dir)
    engine.load()
    [out] = engine.translate([SRC], DocContext())
    assert "25.03.2026" in out and engine.last_flags == [set()]
    call = engine._model.calls[-1]
    assert call["max_new_tokens"] < 256  # sized from the input, not a fixed 256


def test_long_sentence_is_split_and_rejoined(fake_runtime):
    _, _, model_dir = fake_runtime
    engine = make_engine(model_dir)
    engine.load()
    clause = "यह एक लंबा उपवाक्य है जिसमें कई शब्द हैं"
    long_text = ", ".join([clause] * 40) + "।"  # ~360 words, over the 256-token limit
    out = engine.translate([long_text, SRC], DocContext())
    assert out[0] is not None and out[0].count("उपवाक्य") == 40, "nothing may be dropped"
    assert SPLIT in engine.last_flags[0] and engine.last_flags[1] == set()


def test_output_that_hits_the_length_cap_is_none(fake_runtime):
    behaviour, _, model_dir = fake_runtime
    engine = make_engine(model_dir)
    engine.load()
    behaviour["loop"] = True
    assert engine.translate([SRC], DocContext()) == [None]


def test_input_the_tokenizer_still_cuts_is_none(fake_runtime, monkeypatch):
    _, _, model_dir = fake_runtime
    engine = make_engine(model_dir)
    engine.load()
    monkeypatch.setattr(engine, "_count_tokens", lambda text: 10)  # the estimate is far off
    unsplittable = " ".join(["शब्द"] * 300)
    assert engine.translate([unsplittable], DocContext()) == [None]
    assert TRUNCATED in engine.last_flags[0]


def test_output_much_shorter_than_input_is_flagged(fake_runtime, monkeypatch):
    _, _, model_dir = fake_runtime
    engine = make_engine(model_dir)
    engine.load()
    monkeypatch.setattr(FakeTokenizer, "batch_decode", lambda self, g, **kw: ["Short ."] * len(g.rows))
    long_src = "उपर्युक्त विषय के संबंध में सूचित करना है कि निविदा की अंतिम तिथि बढ़ाई गई है और सभी एजेंसियाँ ध्यान दें।"
    [out] = engine.translate([long_src], DocContext())
    assert out == "Short." and TRUNCATED in engine.last_flags[0]


def test_one_bad_sentence_does_not_sink_the_batch(fake_runtime):
    behaviour, _, model_dir = fake_runtime
    engine = make_engine(model_dir)
    engine.load()
    # Fails for any batch containing the text with "खराब"; retried one by one.
    bad_ids = set()
    original = engine._tokenizer._encode

    def encode(text):
        ids = original(text)
        if "खराब" in text:
            bad_ids.add(ids[0])
        return ids

    engine._tokenizer._encode = encode
    behaviour["generate_error"] = lambda rows: any(r[0] in bad_ids for r in rows)
    out = engine.translate(["अच्छा वाक्य।", "खराब वाक्य।", SRC], DocContext())
    assert out[0] is not None and out[1] is None and "25.03.2026" in out[2]


def test_repeated_failures_raise_engine_unavailable(fake_runtime):
    behaviour, _, model_dir = fake_runtime
    engine = make_engine(model_dir, batch_size=1)
    engine.load()
    behaviour["generate_error"] = RuntimeError("Model is not initialized.")
    with pytest.raises(EngineUnavailable, match="keeps failing"):
        engine.translate(["एक।", "दो।", "तीन।"], DocContext())


def test_out_of_memory_while_translating_is_engine_unavailable(fake_runtime):
    behaviour, _, model_dir = fake_runtime
    engine = make_engine(model_dir)
    engine.load()
    behaviour["generate_error"] = RuntimeError("DefaultCPUAllocator: not enough memory: you tried to allocate")
    with pytest.raises(EngineUnavailable, match="out of memory"):
        engine.translate([SRC], DocContext())


def test_placeholder_maps_do_not_leak_after_a_failure(fake_runtime):
    behaviour, _, model_dir = fake_runtime
    engine = make_engine(model_dir)
    engine.load()
    behaviour["generate_error"] = RuntimeError("boom")
    assert engine.translate(["दिनांक 01.01.2020 को।"], DocContext()) == [None]
    del behaviour["generate_error"]
    [out] = engine.translate([SRC], DocContext())
    assert "25.03.2026" in out and "01.01.2020" not in out


def test_translate_before_load_is_engine_unavailable(tmp_path):
    with pytest.raises(EngineUnavailable):
        make_engine(tmp_path).translate(["x"], DocContext())
