"""Background worker: runs jobs stage by stage, one model in memory at a time.

Stages (PLAN.md §6.1): extract -> draft (IndicTrans2 quick draft) -> final (chosen
model, Gemma 4 by default) -> check (pick the best version of each sentence) ->
render -> done. Every sentence is saved as soon as it is processed, so a job that is
interrupted (sleep, shutdown, crash) carries on from where it stopped.

The worker must survive anything (PLAN.md N3): an engine that fails to start or
crashes is a fallback, never a failed job; a broken page is skipped with a note; a job
deleted while it runs is stopped at the next checkpoint and cleaned up; and a stop
request (SIGTERM / Ctrl+Break) unloads the engine (and its llama-server) before exit.

Run with:  python -m app.worker
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TypeVar

import psutil
import pymupdf
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, or_, select, update

from .config import Settings, get_settings
from .db import session_scope
from .model_manager import ModelManager, fits_in_memory
from .models import (
    DONE,
    FAILED,
    QUEUED,
    RUNNING,
    STAGES,
    GlossaryTerm,
    Job,
    Page,
    Segment,
    TMEntry,
    utcnow,
)
from .pipeline.classify import LEGACY_FONT, classify_page
from .pipeline.extract import native_blocks, page_image, render_png
from .pipeline.normalize import has_devanagari
from .pipeline.ocr import tesseract
from .pipeline.protect import protect, restore
from .pipeline.quality import QUALITY_THRESHOLD, assess
from .pipeline.render.outputs import render_docx, render_txt
from .pipeline.segment import split_sentences
from .pipeline.select import Candidate, choose
from .pipeline.translate.base import DocContext, Translator
from .pipeline.validate import AMBER, GREEN, RED, CheckResult, check

log = logging.getLogger("pdft.worker")

T = TypeVar("T")

DRAFT_BATCH = 16
CIRCUIT_BREAKER_FAILURES = 3
# Starting guesses (seconds per sentence) until this laptop has measured its own speed.
DEFAULT_RATES = {"draft": 0.8, "final": 6.0}
SKIP_ENGINES = ("memory", "copy")
# When no engine fits in free memory and nothing has been translated yet, wait this
# many times for the user to close other apps before giving up (PLAN.md §7.1, Memory).
MEMORY_WAIT_ATTEMPTS = 5
MEMORY_WAIT_SECONDS = 30.0
# Exit code of a worker that found another worker already running.
LOCK_EXIT_CODE = 3
# Job folders without a database row (left by a failed delete) are removed after this.
ORPHAN_MIN_AGE_S = 3600
JOB_ID_RE = re.compile(r"[0-9a-f]{32}")
OUTPUT_FILES = {"docx": "translation.docx", "txt": "translation.txt"}

STAGE_MESSAGES = {
    "extract": "Reading pages",
    "draft": "Starting the quick draft",
    "final": "Starting the final translation",
    "check": "Checking every sentence",
    "render": "Preparing the Word file",
}
LEGACY_NO_OCR_NOTE = (
    "This page uses an old Hindi font (such as Kruti Dev) whose text copies out as "
    "gibberish, and OCR (Tesseract) is not installed. Install Tesseract to read it, "
    "or translate this page by hand."
)
LEGACY_SOME_NO_OCR_NOTE = (
    "Text in an old Hindi font (such as Kruti Dev) on this page was left out: it can't "
    "be read without OCR (Tesseract). Please check this page."
)
LEGACY_PART_NOTE = (
    "Some text on this page uses an old Hindi font (such as Kruti Dev) and could not "
    "be read. It is marked red."
)
# Characters Word's XML (and UTF-8) can't hold: lone surrogates, U+FFFE/U+FFFF, controls.
_XML_BAD = re.compile("[^\t\n\r\x20-\x7e\xa0-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


class JobGone(Exception):
    """The job's row no longer exists (it was deleted)."""


class JobCancelled(Exception):
    """The job was deleted while it was queued or running."""


class JobFailed(Exception):
    """Stop the job with a message the user can act on (the UI offers Try again)."""

    def __init__(self, message: str, stage: str | None = None):
        super().__init__(message)
        self.stage = stage


def stored_checks(data: dict | None) -> CheckResult:
    """Rebuild a CheckResult saved on a segment (draft_checks / final_checks)."""
    if not data:
        return CheckResult(False, {"empty": "red"})
    return CheckResult(bool(data.get("usable")), dict(data.get("issues", {})))


def with_source_issues(seg: Segment, confidence: str | None, issues: list[str]) -> tuple[str | None, list[str]]:
    """Add doubts about the source text (seg.source_issues) to a chosen version. A number
    the OCR read two different ways makes the sentence red, whichever engine won."""
    extra = list(seg.source_issues or [])
    if not extra:
        return confidence, list(issues or [])
    issues = [*(issues or []), *(c for c in extra if c not in (issues or []))]
    if "ocr_numbers" in extra:
        confidence = RED
    return confidence, issues


def job_counts(db, job_id: str) -> dict[str, int]:
    """The document summary: sentences per colour.

    A sentence a person corrected counts as green; one that has no colour yet (still
    waiting for a translation) is not counted. Used by the worker after every batch and
    by the API after every correction, so the two can't disagree.
    """
    counts = {GREEN: 0, AMBER: 0, RED: 0}
    edited = Segment.edited.is_not(None)
    rows = db.execute(
        select(Segment.confidence, edited, func.count())
        .where(Segment.job_id == job_id)
        .group_by(Segment.confidence, edited)
    )
    for confidence, was_edited, n in rows:
        if was_edited:
            counts[GREEN] += n
        elif confidence in counts:
            counts[confidence] += n
    return counts


def output_path(settings: Settings, job_id: str, fmt: str) -> Path:
    """Outputs use short fixed names (long file names break Windows' 260-character
    path limit); the friendly name is only used for the download."""
    return settings.job_dir(job_id) / "out" / OUTPUT_FILES[fmt]


def legacy_font_blocks(page: pymupdf.Page, blocks: list) -> set[int]:
    """Indexes of native text blocks written mostly in a legacy Hindi font.

    Text in Kruti Dev and similar fonts copies out as Latin gibberish ("fcgkj ljdkj"),
    so it must never be passed through as if it were English.
    """
    try:
        data = page.get_text("dict")
    except Exception:
        return set()
    spans: list[tuple[pymupdf.Point, int, bool]] = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                n = len(span.get("text", "").strip())
                if n:
                    r = pymupdf.Rect(span["bbox"])
                    centre = pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
                    spans.append((centre, n, bool(LEGACY_FONT.search(span.get("font", "")))))
    if not any(legacy for _, _, legacy in spans):
        return set()
    found: set[int] = set()
    for i, block in enumerate(blocks):
        if getattr(block, "bbox", None) is None:
            continue
        area = pymupdf.Rect(block.bbox)
        legacy_chars = total = 0
        for centre, n, legacy in spans:
            if centre in area:
                total += n
                legacy_chars += n if legacy else 0
        if total and legacy_chars * 2 > total:
            found.add(i)
    return found


def _clean_outputs(outputs: Iterable | None, n: int) -> list[str | None]:
    """Exactly one str-or-None per input, whatever the engine returned."""
    out = [o if isinstance(o, str) else None for o in list(outputs or [])[:n]]
    return out + [None] * (n - len(out))


def _describe(error: BaseException) -> str:
    text = str(error).strip() or type(error).__name__
    return text if len(text) <= 300 else text[:297] + "..."


def _xml_clean(value):
    return _XML_BAD.sub("", value) if isinstance(value, str) else value


def _xml_safe_copy(obj, extra: dict | None = None) -> SimpleNamespace:
    """A detached copy of a row with characters Word rejects removed."""
    data = {c.key: _xml_clean(getattr(obj, c.key)) for c in type(obj).__table__.columns}
    data.update(extra or {})
    return SimpleNamespace(**data)


def _replace(src: Path, dst: Path) -> None:
    """os.replace, retried: on Windows the target may be open for a download."""
    for attempt in range(10):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1)


def _write_atomic(path: Path, write: Callable[[Path], object]) -> Path:
    """Write to a temporary file and move it into place, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp{path.suffix}")
    try:
        write(tmp)
        _replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


_render_locks: dict[str, threading.Lock] = {}
_render_locks_guard = threading.Lock()


def _render_lock(job_id: str) -> threading.Lock:
    with _render_locks_guard:
        return _render_locks.setdefault(job_id, threading.Lock())


def remove_job_files(settings: Settings, job_id: str) -> bool:
    """Delete a job's folder. On Windows a file may be open for a moment: retry."""
    path = settings.job_dir(job_id)
    for attempt in range(5):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        time.sleep(0.2 * (attempt + 1))
    log.warning("could not remove %s; it will be retried later", path)
    return False


def remove_job(settings: Settings, job_id: str) -> None:
    """Delete a job's rows and files. The caller makes sure nothing is working on it."""
    with session_scope() as db:
        db.execute(sql_delete(Segment).where(Segment.job_id == job_id))
        db.execute(sql_delete(Page).where(Page.job_id == job_id))
        db.execute(sql_delete(Job).where(Job.id == job_id))
    remove_job_files(settings, job_id)


class JobRunner:
    def __init__(self, settings: Settings | None = None, manager: ModelManager | None = None):
        self.settings = settings or get_settings()
        self.manager = manager or ModelManager(self.settings)
        self.rates = self._load_rates()
        self.memory_wait_attempts = int(_env_number("PDFT_MEMORY_WAIT_ATTEMPTS", MEMORY_WAIT_ATTEMPTS))
        self.memory_wait_seconds = _env_number("PDFT_MEMORY_WAIT_SECONDS", MEMORY_WAIT_SECONDS)
        self._active: list[Translator] = []  # loaded engines; always unloaded on the way out
        self._trouble: set[str] = set()  # "memory" / "engine" problems seen in this run
        self._final_memory_blocked = False

    # ---- helpers -----------------------------------------------------------------

    def _rates_path(self) -> Path:
        return self.settings.home / "speed.json"

    def _load_rates(self) -> dict[str, float]:
        try:
            data = json.loads(self._rates_path().read_text())
            return {**DEFAULT_RATES, **{k: float(v) for k, v in data.items()}}
        except (OSError, ValueError, TypeError, AttributeError):
            return dict(DEFAULT_RATES)

    def _rate(self, kind: str, model_id: str | None) -> float:
        """Seconds per sentence measured on this laptop, per model where known."""
        return self.rates.get(f"{kind}:{model_id}", self.rates.get(kind, DEFAULT_RATES[kind]))

    def _save_rate(self, kind: str, model_id: str | None, seconds_per_sentence: float) -> None:
        for key in (kind, f"{kind}:{model_id}") if model_id else (kind,):
            old = self.rates.get(key, seconds_per_sentence)
            self.rates[key] = round(0.5 * old + 0.5 * seconds_per_sentence, 3)
        try:
            self._rates_path().write_text(json.dumps(self.rates))
        except OSError:
            pass

    @staticmethod
    def _job(db, job_id: str) -> Job:
        job = db.get(Job, job_id)
        if job is None:
            raise JobGone(job_id)
        return job

    def _update(self, job_id: str, **fields) -> None:
        with session_scope() as db:
            job = self._job(db, job_id)
            for k, v in fields.items():
                setattr(job, k, v)

    def _note(self, job_id: str, note: str) -> None:
        log.info("job %s: %s", job_id, note)
        with session_scope() as db:
            job = self._job(db, job_id)
            if note not in (job.notes or []):
                job.notes = [*(job.notes or []), note]

    def _checkpoint(self, job_id: str) -> None:
        """Stop here if the job was deleted (row gone) or its deletion was requested."""
        with session_scope() as db:
            row = db.execute(select(Job.cancel_requested).where(Job.id == job_id)).first()
        if row is None:
            raise JobGone(job_id)
        if row[0]:
            raise JobCancelled(job_id)

    def _gone_or_cancelled(self, job_id: str) -> bool:
        try:
            self._checkpoint(job_id)
        except (JobGone, JobCancelled):
            return True
        except Exception:
            return False
        return False

    def _sleep(self, job_id: str, seconds: float) -> None:
        """Wait, but notice a delete straight away."""
        deadline = time.monotonic() + seconds
        while True:
            self._checkpoint(job_id)
            left = deadline - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 1.0))

    def _label(self, model_id: str) -> str:
        try:
            return self.manager.store.entry(model_id).label
        except KeyError:
            return model_id

    # ---- main entry ----------------------------------------------------------------

    def run(self, job_id: str) -> None:
        self._trouble = set()
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            cancelled = bool(job.cancel_requested)
            if not cancelled:
                if job.status in (DONE, FAILED):
                    return
                job.status = RUNNING
                start_stage = job.stage if job.stage in STAGES else "extract"
        if cancelled:
            self._discard(job_id)
            return
        try:
            for stage in STAGES[STAGES.index(start_stage):]:
                self._checkpoint(job_id)
                self._update(job_id, stage=stage, stage_progress=0.0, message=STAGE_MESSAGES.get(stage, ""))
                if stage == "extract":
                    self.stage_extract(job_id)
                elif stage == "draft":
                    self.stage_draft(job_id)
                elif stage == "final":
                    self.stage_final(job_id)
                    self._ensure_translated(job_id)
                elif stage == "check":
                    self.stage_check(job_id)
                elif stage == "render":
                    self.render(job_id)
                elif stage == "done":
                    self._update(job_id, status=DONE, stage="done", stage_progress=1.0,
                                 message="Final ready", eta_seconds=0, final_ready_at=utcnow())
        except (JobGone, JobCancelled):
            self._unload_all()
            log.info("job %s was deleted; removing its files", job_id)
            self._discard(job_id)
        except JobFailed as e:
            self._unload_all()
            self._fail(job_id, str(e), stage=e.stage)
        except Exception as e:  # unexpected: keep the error visible on the job
            self._unload_all()
            if self._gone_or_cancelled(job_id):
                self._discard(job_id)
                return
            log.exception("job %s failed", job_id)
            self._fail(job_id, f"{type(e).__name__}: {e}")
        finally:
            # Also on SystemExit (stop requested) and KeyboardInterrupt: never leave a
            # model (or its llama-server process) running.
            self._unload_all()

    def _fail(self, job_id: str, error: str, stage: str | None = None) -> None:
        if self._gone_or_cancelled(job_id):
            self._discard(job_id)
            return
        fields: dict = {"status": FAILED, "error": error, "eta_seconds": None}
        if stage:
            fields.update(stage=stage, stage_progress=0.0)
        try:
            self._update(job_id, **fields)
        except JobGone:
            self._discard(job_id)
        except Exception:
            log.exception("job %s: could not record the failure", job_id)

    def _discard(self, job_id: str) -> None:
        try:
            remove_job(self.settings, job_id)
        except Exception:
            log.exception("job %s: could not remove it", job_id)

    # ---- engines -----------------------------------------------------------------------

    def _load_engine(self, job_id: str, model_id: str) -> Translator | None:
        """Load an engine. ANY error is a fallback (note, unload, None), never a failed job."""
        try:
            engine = self.manager.create(model_id)
        except Exception as e:
            log.warning("job %s: could not create %s", job_id, model_id, exc_info=True)
            self._trouble.add("engine")
            self._note(job_id, f"{self._label(model_id)} could not start: {_describe(e)}")
            return None
        self._active.append(engine)
        try:
            engine.load()
        except Exception as e:
            log.warning("job %s: %s could not start", job_id, model_id, exc_info=True)
            self._trouble.add("memory" if _is_memory_error(e) else "engine")
            self._unload(engine)
            self._note(job_id, f"{engine.label} could not start: {_describe(e)}")
            return None
        except BaseException:
            self._unload(engine)
            raise
        return engine

    def _unload(self, engine: Translator) -> None:
        try:
            engine.unload()
        except Exception:
            log.exception("could not unload %s", getattr(engine, "id", engine))
        # Only forgotten once unload() returned: if a stop signal interrupts it, the
        # engine stays listed and run()'s `finally` unloads it again.
        self._active = [e for e in self._active if e is not engine]

    def _unload_all(self) -> None:
        for engine in list(self._active):
            self._unload(engine)

    def _engine_failed(self, job_id: str, engine: Translator, error: Exception, rest: str) -> None:
        log.warning("job %s: %s failed", job_id, engine.id, exc_info=error)
        self._trouble.add("memory" if _is_memory_error(error) else "engine")
        self._note(job_id, f"{engine.label} stopped: {_describe(error)}. {rest}")

    def _ready_and_fits(self, model_id: str) -> tuple[bool, bool]:
        try:
            ready = self.manager.readiness(model_id).ready
            return ready, ready and fits_in_memory(self.manager.store.entry(model_id).ram_gb)
        except KeyError:
            return False, False

    def _any_ready(self, model_ids: Iterable[str | None]) -> bool:
        return any(self._ready_and_fits(m)[0] for m in model_ids if m)

    def _retry_for_memory(self, job_id: str, what: str, attempt: Callable[[], T | None],
                          blocked: Callable[[], bool]) -> T | None:
        """Try, and while memory is the only obstacle, ask the user to close apps and retry."""
        result = attempt()
        tries = 0
        while result is None and tries < self.memory_wait_attempts and blocked():
            tries += 1
            self._trouble.add("memory")
            self._update(job_id, eta_seconds=None, message=(
                f"Waiting for free memory to start {what}: close other apps to continue "
                f"(check {tries} of {self.memory_wait_attempts})"))
            self._sleep(job_id, self.memory_wait_seconds)
            result = attempt()
        return result

    def _final_candidates(self, choice: str) -> list[str]:
        try:
            return self.manager.final_candidates(choice)
        except KeyError:
            return []

    def _expected_final_model(self, choice: str) -> str | None:
        """The final model that will most likely run (for the time estimate)."""
        if choice == "fast":
            return None
        return next((m for m in self._final_candidates(choice) if self._ready_and_fits(m)[1]), None)

    # ---- stage 1: extract ----------------------------------------------------------------

    def stage_extract(self, job_id: str) -> None:
        source = self.settings.job_dir(job_id) / "source.pdf"
        try:
            doc = pymupdf.open(str(source))
        except Exception as e:
            raise JobFailed(f"The PDF could not be opened: {_describe(e)}", stage="extract") from e
        try:
            self._extract_pages(job_id, doc)
        finally:
            doc.close()  # Windows can't delete an open file

    def _extract_pages(self, job_id: str, doc: pymupdf.Document) -> None:
        ocr_cmd = self.settings.tesseract_cmd if tesseract.available(self.settings.tesseract_cmd) else None
        with session_scope() as db:
            done_pages = set(db.scalars(select(Page.page_no).where(Page.job_id == job_id)))
            tm = {e.source: e.target for e in db.scalars(select(TMEntry))}
            last = db.scalar(select(func.max(Segment.order)).where(Segment.job_id == job_id))
            order = 0 if last is None else last + 1
            self._job(db, job_id).page_count = doc.page_count

        total = doc.page_count
        for index in range(total):
            page_no = index + 1
            if page_no in done_pages:
                continue
            self._checkpoint(job_id)
            self._update(job_id, message=f"Reading page {page_no} of {total}", stage_progress=index / total)
            try:
                order = self._extract_page(job_id, doc, index, ocr_cmd, tm, order)
            except (JobGone, JobCancelled):
                raise
            except Exception as e:  # one broken page must not stop the document
                log.exception("job %s: page %s could not be read", job_id, page_no)
                self._record_broken_page(job_id, doc, index, e)
        self._update(job_id, stage_progress=1.0)

    def _extract_page(self, job_id: str, doc: pymupdf.Document, index: int, ocr_cmd: str | None,
                      tm: dict[str, str], order: int) -> int:
        """Read one page and save it with its sentences. Returns the next sentence number."""
        page_no = index + 1
        page = doc.load_page(index)
        render_png(page, self.settings.job_dir(job_id) / "pages" / f"{page_no}.png")
        info = classify_page(page)
        blocks, method, flagged, note = [], "none", False, ""
        legacy_blocks: set[int] = set()
        if info.kind == "empty":
            note = "Empty page"
        elif not info.needs_ocr:
            blocks, method = native_blocks(page), "native"
            legacy_blocks = legacy_font_blocks(page, blocks)
        elif ocr_cmd:
            result = tesseract.ocr_image(page_image(page), ocr_cmd)
            blocks, method = result.blocks, "ocr-tesseract"
            text = " ".join(b.text for b in blocks)
            # A single OCR engine can't cross-check its numbers yet (dual OCR is
            # Phase 2), so OCR pages are always marked for a quick human look.
            flagged = True
            note = "Text read by OCR: please check numbers and names"
            if assess(text).score < QUALITY_THRESHOLD:
                note = "OCR could not read this page reliably: please check it"
        elif info.kind == "legacy":
            # Never pass legacy-font gibberish on as if it were English text. Keep only
            # Unicode Hindi on the page (e.g. a letter with a Kruti Dev letterhead).
            native = native_blocks(page)
            skip = legacy_font_blocks(page, native)
            blocks = [b for i, b in enumerate(native) if i not in skip and has_devanagari(b.text)]
            method, flagged = ("native" if blocks else "none"), True
            note = LEGACY_SOME_NO_OCR_NOTE if blocks else LEGACY_NO_OCR_NOTE
        elif info.kind == "unicode":
            blocks, method, flagged = native_blocks(page), "native-unreliable", True
            legacy_blocks = legacy_font_blocks(page, blocks)
            note = "The PDF's text looks garbled and OCR is not installed"
        else:
            note = "Scanned page: OCR (Tesseract) is not installed"
        if legacy_blocks and not note:
            note = LEGACY_PART_NOTE
        note = note or getattr(info, "note", "") or ""

        with session_scope() as db:
            db.add(Page(job_id=job_id, page_no=page_no, kind=info.kind, method=method,
                        quality=info.quality, flagged=flagged, note=note,
                        width=page.rect.width, height=page.rect.height))
            for para_no, block in enumerate(blocks):
                # Numbers two OCR readings disagreed on (when the OCR reports them).
                uncertain = [n for n in (getattr(block, "uncertain_numbers", None) or []) if n]
                for sent_no, sentence in enumerate(split_sentences(block.text)):
                    seg = Segment(job_id=job_id, order=order, page_no=page_no, para_no=para_no,
                                  sent_no=sent_no, source=sentence, issues=[],
                                  needs_translation=has_devanagari(sentence))
                    order += 1
                    if any(n in sentence for n in uncertain):
                        seg.source_issues = ["ocr_numbers"]
                    if not seg.needs_translation:
                        if para_no in legacy_blocks:
                            # Legacy-font gibberish: keep it visible, red, for a human.
                            seg.chosen, seg.chosen_engine = sentence, "untranslated"
                            seg.confidence, seg.issues = RED, ["untranslated"]
                        else:
                            # Numbers and English are copied. On an OCR or garbled page
                            # they may be misread (1234 read as 234), so never green.
                            seg.chosen, seg.chosen_engine = sentence, "copy"
                            seg.confidence, seg.issues = (AMBER, ["ocr"]) if flagged else (GREEN, [])
                    elif sentence in tm:
                        seg.chosen, seg.chosen_engine, seg.confidence = tm[sentence], "memory", GREEN
                    if seg.chosen is not None:
                        seg.confidence, seg.issues = with_source_issues(seg, seg.confidence, seg.issues)
                    db.add(seg)
            db.flush()
            job = self._job(db, job_id)
            job.pages_done = page_no
            job.counts = job_counts(db, job_id)
        return order

    def _record_broken_page(self, job_id: str, doc: pymupdf.Document, index: int, error: Exception) -> None:
        page_no = index + 1
        width = height = 0.0
        try:
            rect = doc.load_page(index).rect
            width, height = rect.width, rect.height
        except Exception:
            pass
        with session_scope() as db:
            exists = db.scalar(select(Page.id).where(Page.job_id == job_id, Page.page_no == page_no))
            if exists is None:
                db.add(Page(job_id=job_id, page_no=page_no, kind="error", method="failed", flagged=True,
                            note=f"This page could not be read and was skipped ({_describe(error)})",
                            width=width, height=height))
            self._job(db, job_id).pages_done = page_no
        self._note(job_id, f"Page {page_no} could not be read and was skipped")

    # ---- shared ----------------------------------------------------------------------

    def _pending(self, db, job_id: str, field: str) -> list[Segment]:
        """Sentences that still need this stage (not copied, remembered or corrected)."""
        q = select(Segment).where(
            Segment.job_id == job_id,
            Segment.needs_translation.is_(True),
            Segment.edited.is_(None),
            getattr(Segment, field).is_(None),
        ).order_by(Segment.order)
        return [s for s in db.scalars(q) if s.chosen_engine not in SKIP_ENGINES]

    def _glossary(self) -> list[tuple[str, str]]:
        with session_scope() as db:
            return [(g.hindi, g.english) for g in db.scalars(select(GlossaryTerm))]

    def _flagged_pages(self, job_id: str) -> set[int]:
        with session_scope() as db:
            return set(db.scalars(select(Page.page_no).where(Page.job_id == job_id, Page.flagged.is_(True))))

    def _count_translated(self, job_id: str, column) -> int:
        with session_scope() as db:
            return db.scalar(select(func.count()).select_from(Segment).where(
                Segment.job_id == job_id, column.is_not(None))) or 0

    def _any_output(self, job_id: str) -> bool:
        """Has any engine produced anything for this job yet?"""
        with session_scope() as db:
            return db.scalar(select(func.count()).select_from(Segment).where(
                Segment.job_id == job_id,
                or_(Segment.draft_engine.is_not(None), Segment.final_engine.is_not(None)))) > 0

    # ---- stage 2: quick draft --------------------------------------------------------

    def stage_draft(self, job_id: str) -> None:
        with session_scope() as db:
            job = self._job(db, job_id)
            choice, already_ready = job.choice, job.draft_ready_at is not None
            total = len(self._pending(db, job_id, "draft"))
        if total == 0:
            # Nothing to translate (English, remembered sentences) or resumed after
            # the last batch: don't load a model just to do nothing.
            if not already_ready:
                self._update(job_id, draft_ready_at=utcnow(), message="Quick draft ready")
            return
        p = self.settings.profile
        draft_ids = [p.quick_draft_model, p.low_memory_draft_model]
        # draft_model() picks an installed draft model that fits in free memory, so if
        # one is installed but none was picked, memory is what's missing.
        model_id = self._retry_for_memory(job_id, "the quick draft", self.manager.draft_model,
                                          lambda: self._any_ready(draft_ids))
        if model_id is None:
            if self._any_ready(draft_ids):
                self._trouble.add("memory")
                self._note(job_id, "Quick draft skipped: not enough free memory (close other apps)")
            else:
                self._note(job_id, "Quick draft skipped: IndicTrans2 is not installed")
            return
        engine = self._load_engine(job_id, model_id)
        if engine is None:
            return
        done, started = 0, time.monotonic()
        try:
            self._update(job_id, draft_model=model_id)
            glossary = self._glossary()
            flagged_pages = self._flagged_pages(job_id)
            final_model = self._expected_final_model(choice)
            final_rate = self._rate("final", final_model) if final_model else 0.0
            error: Exception | None = None
            while error is None:
                self._checkpoint(job_id)
                with session_scope() as db:
                    batch = self._pending(db, job_id, "draft")[:DRAFT_BATCH]
                    if not batch:
                        break
                    job = self._job(db, job_id)
                    job.message = f"Quick draft: {done} of {total} sentences"
                    db.commit()  # show progress before the (slow) batch starts
                    try:
                        outputs = _clean_outputs(
                            engine.translate([s.source for s in batch], DocContext(glossary=glossary)), len(batch))
                    except Exception as e:  # out of memory, crash...: keep what we have
                        error = e
                        continue
                    for seg, out in zip(batch, outputs):
                        result = check(seg.source, out, glossary=glossary)
                        seg.draft, seg.draft_engine, seg.draft_checks = out or "", engine.id, result.to_dict()
                        # Show the draft straight away; the check stage makes the final choice.
                        if result.usable:
                            shown = choose(seg.source, [Candidate(engine.id, out, result)],
                                           page_flagged=seg.page_no in flagged_pages)
                            seg.chosen, seg.chosen_engine = shown.text, shown.engine
                            seg.confidence, seg.issues = with_source_issues(seg, shown.confidence, shown.issues)
                    done += len(batch)
                    job = self._job(db, job_id)
                    job.stage_progress = done / max(total, 1)
                    job.message = f"Quick draft: {done} of {total} sentences"
                    rate = (time.monotonic() - started) / done
                    # Only count final-stage time if a final model will actually run.
                    job.eta_seconds = (total - done) * rate + total * final_rate
                    job.counts = job_counts(db, job_id)
            if error is not None:
                self._engine_failed(job_id, engine, error,
                                    "The sentences it did not reach are left to the final translation.")
        finally:
            self._unload(engine)
        if done:
            self._save_rate("draft", model_id, (time.monotonic() - started) / done)
        if done or self._count_translated(job_id, Segment.draft_engine):
            self._update(job_id, draft_ready_at=utcnow(), message="Quick draft ready")

    # ---- stage 3: final translation (Gemma 4 by default) ------------------------------

    def _pick_final_engine(self, job_id: str, choice: str) -> Translator | None:
        """Load the first final candidate that is ready and fits. Sets
        self._final_memory_blocked when a candidate was skipped only for memory."""
        candidates = self._final_candidates(choice)
        self._final_memory_blocked = False
        for model_id in candidates:
            try:
                entry = self.manager.store.entry(model_id)
            except KeyError:
                continue
            ready = self.manager.readiness(model_id)
            if not ready.ready:
                self._note(job_id, f"{entry.label} not used: {ready.reason}")
                continue
            if not fits_in_memory(entry.ram_gb):
                self._trouble.add("memory")
                self._final_memory_blocked = True
                self._note(job_id, f"{entry.label} not used: not enough free memory (close other apps)")
                continue
            engine = self._load_engine(job_id, model_id)
            if engine is not None:
                if model_id != candidates[0]:
                    self._note(job_id, f"Used {entry.label} instead of the first choice")
                return engine
        return None

    def stage_final(self, job_id: str) -> None:
        with session_scope() as db:
            job = self._job(db, job_id)
            choice = job.choice
            subject = next((s.source for s in db.scalars(
                select(Segment).where(Segment.job_id == job_id).order_by(Segment.order))
                if s.source.startswith("विषय")), "")
            pending_total = len(self._pending(db, job_id, "final"))
        if choice == "fast" or pending_total == 0:
            return
        candidates = self._final_candidates(choice)
        engine = self._pick_final_engine(job_id, choice)
        if engine is None and candidates and not self._any_output(job_id):
            # Nothing has been translated at all, so the draft can't stand in: wait for
            # the user to free some memory instead of finishing with only Hindi.
            engine = self._retry_for_memory(job_id, "the translation",
                                            lambda: self._pick_final_engine(job_id, choice),
                                            lambda: self._final_memory_blocked)
        if engine is None:
            # The chosen model was wanted but couldn't run: the quick draft stands in
            # for it and is marked amber. ("Auto" with no final model installed is
            # IndicTrans2 by design, as the Upload page says.)
            wanted = bool(candidates) and (choice != "auto" or any(self._ready_and_fits(m)[0] for m in candidates))
            if wanted:
                self._update(job_id, final_fallback=True)
            if self._count_translated(job_id, Segment.draft_engine):
                self._note(job_id, "Final translation used the quick draft (IndicTrans2) only")
            return

        good_time, good_done = 0.0, 0
        try:
            self._update(job_id, model_used=engine.id, final_fallback=False)
            glossary = self._glossary()
            flagged_pages = self._flagged_pages(job_id)
            max_sent = max(1, int(self.settings.profile.llm.get("paragraph_max_sentences", 10)))
            with session_scope() as db:
                groups: dict[tuple[int, int], list[int]] = defaultdict(list)
                for s in self._pending(db, job_id, "final"):
                    groups[(s.page_no, s.para_no)].append(s.id)
            chunks = [ids[i:i + max_sent] for key in sorted(groups) for ids in [groups[key]]
                      for i in range(0, len(ids), max_sent)]
            total = sum(len(c) for c in chunks)
            default_rate = self._rate("final", engine.id)
            done, failures, previous = 0, 0, ""
            for ids in chunks:
                self._checkpoint(job_id)
                error: Exception | None = None
                with session_scope() as db:
                    segs = [s for s in (db.get(Segment, i) for i in ids) if s is not None]
                    if not segs:
                        continue
                    protected = [protect(s.source) for s in segs]
                    hits = [(hi, en) for hi, en in glossary if any(hi in s.source for s in segs)]
                    ctx = DocContext(subject=subject, previous_english=previous, glossary=hits)
                    texts = [p.text for p in protected] if engine.uses_placeholders else [s.source for s in segs]
                    t0 = time.monotonic()
                    try:
                        outputs = _clean_outputs(engine.translate(texts, ctx), len(segs))
                    except Exception as e:  # EngineUnavailable, crash, out of memory...
                        error = e
                    if error is None:
                        all_failed = all(o is None for o in outputs)
                        failures = failures + 1 if all_failed else 0
                        if not all_failed:  # timed-out chunks would skew the speed estimate
                            good_time += time.monotonic() - t0
                            good_done += len(segs)
                        for seg, prot, out in zip(segs, protected, outputs):
                            restored = restore(out, prot.items) if (out and engine.uses_placeholders) else None
                            text = restored.text if restored else out
                            result = check(seg.source, text, restored=restored, glossary=glossary)
                            seg.final, seg.final_engine, seg.final_checks = text or "", engine.id, result.to_dict()
                            best = choose(seg.source, [
                                Candidate(engine.id, text, result),
                                Candidate(seg.draft_engine or "draft", seg.draft, stored_checks(seg.draft_checks),
                                          is_fallback=True),
                            ], page_flagged=seg.page_no in flagged_pages)
                            seg.chosen, seg.chosen_engine = best.text, best.engine
                            seg.confidence, seg.issues = with_source_issues(seg, best.confidence, best.issues)
                        previous = " ".join(o for o in (s.final for s in segs) if o)[-600:]
                        done += len(segs)
                        job = self._job(db, job_id)
                        job.stage_progress = done / max(total, 1)
                        job.message = f"{engine.label}: {done} of {total} sentences"
                        rate = good_time / good_done if good_done else default_rate
                        job.eta_seconds = (total - done) * rate
                        job.counts = job_counts(db, job_id)
                if error is not None:
                    self._engine_failed(job_id, engine, error, "The quick draft is used for the rest.")
                    break
                if failures >= CIRCUIT_BREAKER_FAILURES:
                    self._note(job_id, f"{engine.label} kept failing. The quick draft is used for the rest.")
                    break
        finally:
            self._unload(engine)
        if good_done:
            self._save_rate("final", engine.id, good_time / good_done)

    def _ensure_translated(self, job_id: str) -> None:
        """Don't call a job 'Final ready' when no engine translated anything at all."""
        with session_scope() as db:
            segs = list(db.scalars(select(Segment).where(
                Segment.job_id == job_id, Segment.needs_translation.is_(True))))
        needing = [s for s in segs if s.chosen_engine not in SKIP_ENGINES and s.edited is None]
        if not needing or any(s.draft_engine or s.final_engine for s in segs):
            return
        if "memory" in self._trouble:
            message = ("There was not enough free memory to run a translation model, so nothing was "
                       "translated. Close other apps (for example Chrome, Teams or Outlook), then click Try again.")
        elif "engine" in self._trouble:
            message = ("The translation models could not start on this laptop, so nothing was translated. "
                       "See the notes for details, then click Try again.")
        else:
            message = ("No translation model is installed, so nothing was translated. Install IndicTrans2 "
                       "or Gemma 4 in Settings > Models, then click Try again.")
        raise JobFailed(message, stage="draft")

    # ---- stage 4: choose the best version of every sentence ------------------------------

    def stage_check(self, job_id: str) -> None:
        with session_scope() as db:
            job = self._job(db, job_id)
            flagged_pages = {p.page_no for p in db.scalars(select(Page).where(Page.job_id == job_id, Page.flagged.is_(True)))}
            # The draft is a fallback whenever a final model was wanted: it ran but this
            # sentence failed, or it could not run at all (memory guard, failed start).
            draft_is_fallback = job.model_used is not None or bool(job.final_fallback)
            segs = list(db.scalars(select(Segment).where(Segment.job_id == job_id).order_by(Segment.order)))
            for seg in segs:
                if seg.chosen_engine in SKIP_ENGINES:
                    continue
                candidates = []
                if seg.final_checks is not None:
                    candidates.append(Candidate(seg.final_engine, seg.final, stored_checks(seg.final_checks)))
                if seg.draft_checks is not None:
                    candidates.append(Candidate(seg.draft_engine, seg.draft, stored_checks(seg.draft_checks),
                                                is_fallback=draft_is_fallback))
                best = choose(seg.source, candidates, page_flagged=seg.page_no in flagged_pages)
                seg.chosen, seg.chosen_engine = best.text, best.engine
                seg.confidence, seg.issues = with_source_issues(seg, best.confidence, best.issues)
            db.flush()
            job.counts = job_counts(db, job_id)
            job.message = "Checking finished"

    # ---- stage 5: outputs ---------------------------------------------------------------

    def render(self, job_id: str) -> dict[str, Path]:
        """Write the TXT and DOCX. Returns the files that could be written.

        The TXT is written first, so it exists even if Word output fails (PLAN.md §7.1).
        outputs_stale is only cleared if no correction arrived while rendering.
        """
        with _render_lock(job_id):
            with session_scope() as db:
                job = self._job(db, job_id)
                seen = job.edit_version or 0
                pages = list(db.scalars(select(Page).where(Page.job_id == job_id).order_by(Page.page_no)))
                segs = list(db.scalars(select(Segment).where(Segment.job_id == job_id).order_by(Segment.order)))
                model = job.model_used or job.draft_model
                label = self._label(model) if model else ""
            paths: dict[str, Path] = {}
            renderers = {
                "txt": lambda j, s: (lambda tmp: render_txt(j, pages, s, tmp)),
                "docx": lambda j, s: (lambda tmp: render_docx(j, pages, s, tmp, label)),
            }
            for fmt in ("txt", "docx"):
                target = output_path(self.settings, job_id, fmt)
                try:
                    paths[fmt] = _write_atomic(target, renderers[fmt](job, segs))
                    continue
                except Exception:
                    log.warning("job %s: %s output failed; retrying with cleaned text", job_id, fmt, exc_info=True)
                try:
                    clean_job = _xml_safe_copy(job)
                    clean_segs = [_xml_safe_copy(s, {"display_text": _xml_clean(s.display_text)}) for s in segs]
                    paths[fmt] = _write_atomic(target, renderers[fmt](clean_job, clean_segs))
                except Exception as e:
                    log.exception("job %s: %s output failed", job_id, fmt)
                    kind = "Word" if fmt == "docx" else "text"
                    self._note(job_id, f"The {kind} file could not be created: {_describe(e)}")
            if len(paths) == len(OUTPUT_FILES):
                with session_scope() as db:
                    db.execute(update(Job).where(Job.id == job_id, Job.edit_version == seen)
                               .values(outputs_stale=False))
        return paths


def _env_number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def _is_memory_error(error: BaseException) -> bool:
    return isinstance(error, MemoryError) or "memory" in str(error).lower()


# ---- queue loop ---------------------------------------------------------------------

def next_job_id() -> str | None:
    with session_scope() as db:
        return db.scalar(
            select(Job.id)
            .where(Job.status.in_([QUEUED, RUNNING]), Job.cancel_requested.is_(False))
            .order_by(Job.created_at)
            .limit(1)
        )


def purge_cancelled(settings: Settings) -> int:
    """Remove jobs deleted while queued or running. Only the worker calls this, between
    jobs, so nothing is using them."""
    with session_scope() as db:
        ids = list(db.scalars(select(Job.id).where(Job.cancel_requested.is_(True))))
    for job_id in ids:
        remove_job(settings, job_id)
    return len(ids)


def _remove_orphan_dirs(settings: Settings) -> int:
    """Job folders with no database row (a delete that couldn't remove every file)."""
    jobs_dir = settings.jobs_dir
    if not jobs_dir.is_dir():
        return 0
    with session_scope() as db:
        known = set(db.scalars(select(Job.id)))
    removed, now = 0, time.time()
    for child in jobs_dir.iterdir():
        if child.name in known or not JOB_ID_RE.fullmatch(child.name) or not child.is_dir():
            continue
        try:
            age = now - child.stat().st_mtime
        except OSError:
            continue
        # A brand-new folder may be an upload whose row isn't written yet.
        if age > ORPHAN_MIN_AGE_S:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def cleanup_old_jobs(settings: Settings) -> int:
    """Delete finished jobs older than the retention period. Queued and running jobs are
    never touched: the worker may be using them."""
    days = int(settings.profile.limits.get("retention_days", 30))
    cutoff = utcnow() - timedelta(days=days)
    with session_scope() as db:
        ids = list(db.scalars(select(Job.id).where(Job.created_at < cutoff, Job.status.in_([DONE, FAILED]))))
    for job_id in ids:
        remove_job(settings, job_id)
    try:
        _remove_orphan_dirs(settings)
    except Exception:
        log.exception("could not clean up old job folders")
    return len(ids)


# ---- single worker lock -----------------------------------------------------------

def _try_lock(fd: int) -> bool | None:
    """Exclusive, non-blocking OS lock. True/False, or None if the OS can't lock here.
    The OS drops the lock when the process dies, so a crash never leaves it stuck."""
    try:
        import fcntl
    except ImportError:
        fcntl = None  # type: ignore[assignment]
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
        except OSError:
            return None
    try:
        import msvcrt
    except ImportError:
        return None
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


class WorkerLock:
    """Only one worker per data folder, so two never process the same job (a stray
    worker can survive a launcher that was killed from Task Manager)."""

    def __init__(self, home: Path):
        self.lock_path = home / "worker.lock"
        self.pid_path = home / "worker.pid"
        self._fd: int | None = None

    def holder(self) -> int | None:
        try:
            return int(self.pid_path.read_text().strip())
        except (OSError, ValueError):
            return None

    def _holder_alive(self) -> bool:
        """Fallback when the OS can't lock: is the PID in worker.pid a live worker?"""
        pid = self.holder()
        if not pid or pid == os.getpid() or not psutil.pid_exists(pid):
            return False
        try:
            return any("app.worker" in part for part in psutil.Process(pid).cmdline())
        except psutil.AccessDenied:
            return True
        except psutil.Error:
            return False

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        locked = _try_lock(fd)
        if locked is None:
            locked = not self._holder_alive()
        if not locked:
            os.close(fd)
            return False
        self._fd = fd
        try:
            self.pid_path.write_text(str(os.getpid()))
        except OSError:
            pass
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        if self.holder() == os.getpid():
            try:
                self.pid_path.unlink()
            except OSError:
                pass
        try:
            os.close(self._fd)  # closing the file releases the OS lock
        finally:
            self._fd = None


# ---- process lifecycle ------------------------------------------------------------

_stopping = False


def _stop_handler(signum, _frame) -> None:
    """SIGTERM / SIGBREAK / SIGINT: unwind through every `finally`, so the engine (and
    its llama-server) is unloaded before the process exits. A second signal during that
    clean-up is ignored so it can finish."""
    global _stopping
    if _stopping:
        return
    _stopping = True
    log.info("worker: stop requested (signal %s)", signum)
    raise SystemExit(0)


def install_signal_handlers() -> None:
    for name in ("SIGTERM", "SIGBREAK", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _stop_handler)
        except (ValueError, OSError):  # not the main thread, or not supported here
            pass


def _wait(stop: threading.Event | None, seconds: float) -> None:
    if stop is not None:
        stop.wait(seconds)
    else:
        time.sleep(seconds)


def _give_up(job_id: str) -> None:
    try:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is not None and job.status in (QUEUED, RUNNING):
                job.status = FAILED
                job.error = "The translation stopped because of an internal error. Click Try again."
    except Exception:
        log.exception("could not mark job %s as failed", job_id)


def run_forever(poll_seconds: float = 1.0, stop: threading.Event | None = None) -> int:
    """Process jobs until stopped. Returns an exit code (LOCK_EXIT_CODE if another
    worker already runs). One job can never stop the loop."""
    settings = get_settings()
    lock = WorkerLock(settings.home)
    if not lock.acquire():
        holder = lock.holder()
        log.error("another worker is already running%s; this one exits", f" (pid {holder})" if holder else "")
        return LOCK_EXIT_CODE
    try:
        runner = JobRunner(settings)
        log.info("worker started (profile %s)", settings.profile.name)
        last_cleanup: float | None = None
        crashes: dict[str, int] = {}
        while stop is None or not stop.is_set():
            job_id = None
            try:
                if last_cleanup is None or time.monotonic() - last_cleanup > 3600:
                    last_cleanup = time.monotonic()
                    cleanup_old_jobs(settings)
                purge_cancelled(settings)
                job_id = next_job_id()
                if job_id:
                    runner.run(job_id)
                    crashes.pop(job_id, None)
            except Exception:
                log.exception("worker error%s", f" on job {job_id}" if job_id else "")
                if job_id:
                    crashes[job_id] = crashes.get(job_id, 0) + 1
                    if crashes[job_id] >= 3:
                        _give_up(job_id)
                        crashes.pop(job_id, None)
                _wait(stop, max(poll_seconds, 1.0) * 5)
                continue
            if not job_id:
                _wait(stop, poll_seconds)
        return 0
    finally:
        lock.release()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    install_signal_handlers()
    return run_forever()


if __name__ == "__main__":
    sys.exit(main())
