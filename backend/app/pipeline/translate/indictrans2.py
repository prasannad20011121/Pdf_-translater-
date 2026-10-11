"""IndicTrans2 (AI4Bharat) on CPU: the quick draft and first fallback (PLAN.md §4.2).

MVP runtime: Hugging Face transformers with dynamic int8 quantisation, loading the
model from the local, pinned model store. Phase 0 measures this against a
CTranslate2 int8 conversion on the 8 GB test laptop (PLAN.md §14) and the faster one
becomes the default.

Requires the optional dependencies: pip install -e ".[indictrans2]"
"""

from __future__ import annotations

import gc
import importlib.util
from pathlib import Path

from .base import DocContext, EngineUnavailable, Translator


def runtime_available() -> tuple[bool, str]:
    for module in ("torch", "transformers"):
        if importlib.util.find_spec(module) is None:
            return False, f"Python package '{module}' is not installed"
    if importlib.util.find_spec("IndicTransToolkit") is None:
        return False, "Python package 'IndicTransToolkit' is not installed"
    return True, ""


def _indic_processor():
    try:
        from IndicTransToolkit.processor import IndicProcessor  # older releases
    except ImportError:
        from IndicTransToolkit import IndicProcessor  # newer releases
    return IndicProcessor(inference=True)


class IndicTrans2Engine(Translator):
    unit = "sentence"
    uses_placeholders = False  # IndicProcessor protects numbers/URLs itself

    def __init__(
        self,
        model_id: str,
        label: str,
        model_dir: Path,
        ram_gb: float,
        threads: int,
        src_lang: str = "hin_Deva",
        tgt_lang: str = "eng_Latn",
        batch_size: int = 8,
        num_beams: int = 4,
        quantize: bool = True,
    ):
        self.id = model_id
        self.label = label
        self.model_dir = model_dir
        self.ram_gb = ram_gb
        self.threads = threads
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.batch_size = batch_size
        self.num_beams = num_beams
        self.quantize = quantize
        self._model = None
        self._tokenizer = None
        self._ip = None

    def load(self) -> None:
        ok, reason = runtime_available()
        if not ok:
            raise EngineUnavailable(reason)
        if not (self.model_dir / "config.json").exists():
            raise EngineUnavailable(f"model files not found in {self.model_dir}")
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        torch.set_num_threads(self.threads)
        # trust_remote_code runs the model's own Python files from the pinned,
        # checksum-verified local copy (never fetched at run time).
        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir), trust_remote_code=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(str(self.model_dir), trust_remote_code=True)
        model.eval()
        if self.quantize:
            model = torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
        self._model = model
        self._ip = _indic_processor()

    def unload(self) -> None:
        self._model = self._tokenizer = self._ip = None
        gc.collect()

    def translate(self, texts: list[str], ctx: DocContext) -> list[str | None]:
        if self._model is None:
            raise EngineUnavailable("engine not loaded")
        import torch

        out: list[str | None] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            prepared = self._ip.preprocess_batch(batch, src_lang=self.src_lang, tgt_lang=self.tgt_lang)
            inputs = self._tokenizer(
                prepared, truncation=True, padding="longest", return_tensors="pt", return_attention_mask=True
            )
            with torch.no_grad():
                generated = self._model.generate(
                    **inputs, use_cache=True, min_length=0, max_length=256, num_beams=self.num_beams
                )
            decoded = self._tokenizer.batch_decode(
                generated, skip_special_tokens=True, clean_up_tokenization_spaces=True
            )
            out.extend(self._ip.postprocess_batch(decoded, lang=self.tgt_lang))
        return out
