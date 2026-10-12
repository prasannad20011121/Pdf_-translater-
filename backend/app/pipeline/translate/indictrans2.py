"""IndicTrans2 (AI4Bharat) on CPU: the quick draft and first fallback (PLAN.md §4.2).

MVP runtime: Hugging Face transformers with dynamic int8 quantisation, loading the
model from the local, pinned model store. Phase 0 measures this against a
CTranslate2 int8 conversion on the 8 GB test laptop (PLAN.md §14) and the faster one
becomes the default.

Memory: the checkpoint is fp32, so loading briefly needs about the fp32 size (about
4.5 GB for the 1B model) before int8 quantisation shrinks it (about 1.8 GB). The
model is loaded with low_cpu_mem_usage and quantised in place, so there is only ever
one fp32 copy; the catalog's load_ram_gb is that peak and the memory guard checks it.

Failures: every problem while loading or translating is raised as EngineUnavailable,
so the job carries on without the draft (or with Gemma) instead of failing.

Long sentences: IndicTrans2 was trained on inputs of up to 256 tokens. Longer
sentences are split at clause boundaries, translated in pieces and rejoined (flag
SPLIT in `last_flags`). The output length cap is sized from the input. An output
that looks cut short (much shorter than the Hindi) is flagged TRUNCATED; one that
certainly is (it ran into the cap, or its input still had to be cut) is returned as
None, so the sentence shows red instead of silently missing its end.

Requires the optional dependencies: pip install -e ".[indictrans2]". IndicTransToolkit
is used when it imports; otherwise a built-in processor (see indic_processor.py).
"""

from __future__ import annotations

import gc
import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Callable

from .base import SPLIT, TRUNCATED, DocContext, EngineUnavailable, Translator
from .indic_processor import make_indic_processor

log = logging.getLogger("pdft.indictrans2")

MAX_POSITIONS = 256           # model_max_length in the IndicTrans2 tokenizer config
PIECE_TOKENS = 200            # split sentences longer than this (leaves room for tags)
TRUNCATION_RATIO = 0.35       # English shorter than this share of the Hindi = cut short
TRUNCATION_MIN_CHARS = 80     # ...for sources at least this long


def _has_module(name: str) -> bool:
    if sys.modules.get(name) is not None:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def runtime_available() -> tuple[bool, str]:
    # sentencepiece is imported by the model's own tokenizer code.
    for module in ("torch", "transformers", "sentencepiece"):
        if not _has_module(module):
            return False, f"Python package '{module}' is not installed"
    return True, ""


def _is_oom(e: BaseException) -> bool:
    text = str(e).lower()
    return isinstance(e, MemoryError) or "out of memory" in text or "not enough memory" in text \
        or "defaultcpuallocator" in text


# ---- long sentences ------------------------------------------------------------------------

# Split points, strongest first. Each pattern matches the gap where a piece may end.
_SPLIT_LEVELS = [
    re.compile(r"(?<=[।॥?!])\s+"),                 # danda / sentence ends missed earlier
    re.compile(r"(?<=[;:])\s+"),
    re.compile(r"(?<=,)\s+"),                                 # ", " (never "5,00,000")
    re.compile(r"\s+(?=(?:और|तथा|एवं|एवम्|किंतु|किन्तु|परंतु|परन्तु|लेकिन|अथवा|या|जबकि|क्योंकि|ताकि|जिससे|जिसमें|जो)\s)"),
    re.compile(r"\s+"),                                       # last resort: between words
]


def split_long(text: str, count: Callable[[str], int], limit: int = PIECE_TOKENS, level: int = 0) -> list[str]:
    """Split `text` into pieces of at most `limit` tokens, at the strongest boundaries."""
    if count(text) <= limit or level >= len(_SPLIT_LEVELS):
        return [text]
    parts = [p for p in _SPLIT_LEVELS[level].split(text) if p.strip()]
    if len(parts) <= 1:
        return split_long(text, count, limit, level + 1)
    pieces: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current} {part}".strip() if current else part
        if current and count(candidate) > limit:
            pieces.append(current)
            current = part
        else:
            current = candidate
    if current:
        pieces.append(current)
    out: list[str] = []
    for piece in pieces:
        out += split_long(piece, count, limit, level + 1) if count(piece) > limit else [piece]
    return out


def looks_truncated(source: str, output: str | None) -> bool:
    if not output:
        return False
    src, out = len(source.strip()), len(output.strip())
    return src >= TRUNCATION_MIN_CHARS and out < TRUNCATION_RATIO * src


# ---- engine --------------------------------------------------------------------------------

class IndicTrans2Engine(Translator):
    unit = "sentence"
    uses_placeholders = False  # the IndicProcessor protects numbers/URLs itself

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
        self.model_dir = Path(model_dir)
        self.ram_gb = ram_gb
        self.threads = threads
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.batch_size = batch_size
        self.num_beams = num_beams
        self.quantize = quantize
        self.processor_kind = ""     # "IndicTransToolkit" or "built-in", once loaded
        self.notes: list[str] = []   # things worth showing on the job (e.g. not quantised)
        self.last_flags: list[set[str]] = []
        self._model = None
        self._tokenizer = None
        self._ip = None
        self._max_positions = MAX_POSITIONS
        self._stop_ids: set[int] = set()

    # ---- lifecycle -----------------------------------------------------------------

    def load(self) -> None:
        ok, reason = runtime_available()
        if not ok:
            raise EngineUnavailable(reason)
        if not (self.model_dir / "config.json").exists():
            raise EngineUnavailable(f"model files not found in {self.model_dir}")
        try:
            self._load()
        except EngineUnavailable:
            self.unload()
            raise
        except Exception as e:  # OSError, torch OOM, broken files, toolkit import...
            self.unload()
            what = "ran out of memory while loading" if _is_oom(e) else "could not start"
            raise EngineUnavailable(f"IndicTrans2 {what}: {type(e).__name__}: {e}") from e

    def _load(self) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        torch.set_num_threads(self.threads)
        # trust_remote_code runs the model's own Python files from the local copy, which
        # the model store only marks usable when their checksums are known (never fetched
        # at run time: local_files_only).
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_dir), trust_remote_code=True, local_files_only=True)
        # low_cpu_mem_usage: build the model empty and fill it from the (memory-mapped)
        # safetensors file, instead of random-initialising a second fp32 copy first.
        model = AutoModelForSeq2SeqLM.from_pretrained(
            str(self.model_dir), trust_remote_code=True, local_files_only=True, low_cpu_mem_usage=True)
        model.eval()
        if self.quantize:
            self._quantize_in_place(torch, model)
        self._model = model
        config = getattr(model, "config", None)
        self._max_positions = int(getattr(config, "max_source_positions", 0) or MAX_POSITIONS)
        self._stop_ids = self._special_ids(model)
        self._ip, self.processor_kind = make_indic_processor()

    def _quantize_in_place(self, torch, model) -> None:
        """int8 dynamic quantisation, in place: quantize_dynamic's default (inplace=False)
        deep-copies the whole fp32 model first, doubling the load peak."""
        quantization = getattr(getattr(torch, "ao", None), "quantization", None) or torch.quantization
        try:
            quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)
        except Exception as e:
            if _is_oom(e):
                raise
            # The fp32 model still works and the memory guard already allowed its size.
            log.warning("int8 quantisation failed, keeping fp32: %s", e)
            self.notes.append("IndicTrans2 runs without int8 quantisation (slower)")
        gc.collect()

    @staticmethod
    def _special_ids(model) -> set[int]:
        ids: set[int] = set()
        for source in (getattr(model, "generation_config", None), getattr(model, "config", None)):
            for attr in ("eos_token_id", "pad_token_id"):
                value = getattr(source, attr, None)
                if isinstance(value, int):
                    ids.add(value)
                elif isinstance(value, (list, tuple)):
                    ids.update(v for v in value if isinstance(v, int))
        return ids

    def unload(self) -> None:
        self._model = self._tokenizer = self._ip = None
        gc.collect()

    # ---- translation ---------------------------------------------------------------

    def _count_tokens(self, text: str) -> int:
        """Approximate source length in model tokens (before the processor's changes)."""
        try:
            ids = self._tokenizer(f"{self.src_lang} {self.tgt_lang} {text}")["input_ids"]
            return len(ids)
        except Exception:
            return len(text) // 3  # rough: a Hindi token is about 3 characters

    def _reset_processor(self) -> None:
        """A batch failed between preprocess and postprocess: the processor still holds
        that batch's placeholder maps, which would be applied to the next batch."""
        try:
            self._ip, self.processor_kind = make_indic_processor()
        except Exception:
            pass

    def _run_batch(self, pieces: list[str]) -> list[tuple[str | None, bool]]:
        """Translate up to batch_size pieces. Returns (text or None, input was cut)."""
        import torch

        prepared = self._ip.preprocess_batch(pieces, src_lang=self.src_lang, tgt_lang=self.tgt_lang)
        full_lengths = [len(ids) for ids in self._tokenizer(prepared, padding=False)["input_ids"]]
        inputs = self._tokenizer(
            prepared, truncation=True, max_length=self._max_positions, padding="longest",
            return_tensors="pt", return_attention_mask=True,
        )
        longest = min(max(full_lengths, default=1), self._max_positions)
        max_new = min(int(1.5 * longest) + 20, 2 * self._max_positions)
        with torch.no_grad():
            generated = self._model.generate(
                **inputs, use_cache=True, min_length=0, max_new_tokens=max_new, num_beams=self.num_beams,
            )
        rows = generated.tolist() if hasattr(generated, "tolist") else list(generated)
        # A row that is max_new tokens long and doesn't end in EOS/padding ran into the cap.
        hit_cap = [len(r) - 1 >= max_new and (not r or r[-1] not in self._stop_ids) for r in rows]
        decoded = self._tokenizer.batch_decode(generated, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        texts = self._ip.postprocess_batch(decoded, lang=self.tgt_lang)
        if len(texts) != len(pieces) or len(rows) != len(pieces):
            raise RuntimeError(f"got {len(texts)} translations for {len(pieces)} sentences")
        out: list[tuple[str | None, bool]] = []
        for text, capped, n in zip(texts, hit_cap, full_lengths):
            cut = n > self._max_positions  # the tokenizer had to drop the end of the input
            out.append((None if (capped or cut) else ((text or "").strip() or None), cut))
        return out

    def _translate_pieces(self, pieces: list[str]) -> list[tuple[str | None, bool]]:
        results: list[tuple[str | None, bool]] = []
        failed_batches = 0
        for i in range(0, len(pieces), self.batch_size):
            batch = pieces[i:i + self.batch_size]
            try:
                batch_out = self._run_batch(batch)
            except Exception as e:
                self._reset_processor()
                if _is_oom(e):
                    gc.collect()
                log.warning("IndicTrans2 batch failed (%s); retrying one sentence at a time", e)
                batch_out = []
                last_error: Exception = e
                for piece in batch:  # isolate the sentence that breaks it
                    try:
                        batch_out += self._run_batch([piece])
                    except Exception as e2:
                        self._reset_processor()
                        if _is_oom(e2):
                            raise EngineUnavailable(f"IndicTrans2 ran out of memory: {e2}") from e2
                        last_error = e2
                        batch_out.append((None, False))
                if all(text is None for text, _ in batch_out):
                    failed_batches += 1
                    if failed_batches >= 2:
                        raise EngineUnavailable(f"IndicTrans2 keeps failing: {type(last_error).__name__}: "
                                                f"{last_error}") from last_error
                else:
                    failed_batches = 0
            results += batch_out
        return results

    def translate(self, texts: list[str], ctx: DocContext) -> list[str | None]:
        if self._model is None or self._tokenizer is None or self._ip is None:
            raise EngineUnavailable("engine not loaded")
        flags: list[set[str]] = [set() for _ in texts]
        pieces: list[str] = []
        owners: list[int] = []
        for i, text in enumerate(texts):
            parts = split_long(text, self._count_tokens) if text.strip() else [text]
            if len(parts) > 1:
                flags[i].add(SPLIT)
            pieces += parts
            owners += [i] * len(parts)
        grouped: list[list[tuple[str | None, bool]]] = [[] for _ in texts]
        for result, owner in zip(self._translate_pieces(pieces), owners):
            grouped[owner].append(result)

        out: list[str | None] = []
        for i, text in enumerate(texts):
            mine = grouped[i]
            if any(cut for _, cut in mine):
                flags[i].add(TRUNCATED)
            if not mine or any(t is None for t, _ in mine):
                out.append(None)  # a missing piece would silently drop part of the sentence
                continue
            joined = " ".join(t.strip() for t, _ in mine if t)
            if looks_truncated(text, joined):
                flags[i].add(TRUNCATED)
            out.append(joined)
        self.last_flags = flags
        return out
