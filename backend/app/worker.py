"""Background worker: runs jobs stage by stage, one model in memory at a time.

Stages (PLAN.md §6.1): extract -> draft (IndicTrans2 quick draft) -> final (chosen
model, Gemma 4 by default) -> check (pick the best version of each sentence) ->
render -> done. Every sentence is saved as soon as it is processed, so a job that is
interrupted (sleep, shutdown, crash) carries on from where it stopped.

Run with:  python -m app.worker
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymupdf
from sqlalchemy import select

from .config import Settings, get_settings
from .db import session_scope
from .model_manager import ModelManager, fits_in_memory
from .models import DONE, FAILED, QUEUED, RUNNING, STAGES, GlossaryTerm, Job, Page, Segment, TMEntry, utcnow
from .pipeline.classify import classify_page
from .pipeline.extract import native_blocks, page_image, render_png
from .pipeline.normalize import has_devanagari
from .pipeline.ocr import tesseract
from .pipeline.protect import protect, restore
from .pipeline.quality import QUALITY_THRESHOLD, assess
from .pipeline.render.outputs import output_name, render_docx, render_txt
from .pipeline.segment import split_sentences
from .pipeline.select import Candidate, choose
from .pipeline.translate.base import DocContext, EngineUnavailable, Translator
from .pipeline.validate import GREEN, CheckResult, check

log = logging.getLogger("pdft.worker")

DRAFT_BATCH = 16
CIRCUIT_BREAKER_FAILURES = 3
# Starting guesses (seconds per sentence) until this laptop has measured its own speed.
DEFAULT_RATES = {"draft": 0.8, "final": 6.0}
SKIP_ENGINES = ("memory", "copy")


def stored_checks(data: dict | None) -> CheckResult:
    """Rebuild a CheckResult saved on a segment (draft_checks / final_checks)."""
    if not data:
        return CheckResult(False, {"empty": "red"})
    return CheckResult(bool(data.get("usable")), dict(data.get("issues", {})))


class JobRunner:
    def __init__(self, settings: Settings | None = None, manager: ModelManager | None = None):
        self.settings = settings or get_settings()
        self.manager = manager or ModelManager(self.settings)
        self.rates = self._load_rates()

    # ---- helpers -----------------------------------------------------------------

    def _rates_path(self) -> Path:
        return self.settings.home / "speed.json"

    def _load_rates(self) -> dict[str, float]:
        try:
            return {**DEFAULT_RATES, **json.loads(self._rates_path().read_text())}
        except (OSError, ValueError):
            return dict(DEFAULT_RATES)

    def _save_rate(self, key: str, seconds_per_sentence: float) -> None:
        old = self.rates.get(key, seconds_per_sentence)
        self.rates[key] = round(0.5 * old + 0.5 * seconds_per_sentence, 3)
        try:
            self._rates_path().write_text(json.dumps(self.rates))
        except OSError:
            pass

    def _update(self, job_id: str, **fields) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            for k, v in fields.items():
                setattr(job, k, v)

    def _note(self, job_id: str, note: str) -> None:
        log.info("job %s: %s", job_id, note)
        with session_scope() as db:
            job = db.get(Job, job_id)
            if note not in job.notes:
                job.notes = [*job.notes, note]

    # ---- main entry ----------------------------------------------------------------

    def run(self, job_id: str) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None or job.status in (DONE, FAILED):
                return
            job.status = RUNNING
            start_stage = job.stage
        try:
            stages = STAGES[STAGES.index(start_stage):]
            for stage in stages:
                self._update(job_id, stage=stage, stage_progress=0.0)
                if stage == "extract":
                    self.stage_extract(job_id)
                elif stage == "draft":
                    self.stage_draft(job_id)
                elif stage == "final":
                    self.stage_final(job_id)
                elif stage == "check":
                    self.stage_check(job_id)
                elif stage == "render":
                    self.render(job_id)
                elif stage == "done":
                    self._update(job_id, status=DONE, stage="done", stage_progress=1.0,
                                 message="Final ready", eta_seconds=0, final_ready_at=utcnow())
        except Exception as e:  # unexpected: keep the error visible on the job
            log.exception("job %s failed", job_id)
            self._update(job_id, status=FAILED, error=f"{type(e).__name__}: {e}")

    # ---- stage 1: extract ----------------------------------------------------------------

    def stage_extract(self, job_id: str) -> None:
        job_dir = self.settings.job_dir(job_id)
        doc = pymupdf.open(str(job_dir / "source.pdf"))
        ocr_cmd = self.settings.tesseract_cmd if tesseract.available(self.settings.tesseract_cmd) else None
        with session_scope() as db:
            done_pages = {p.page_no for p in db.scalars(select(Page).where(Page.job_id == job_id))}
            tm = {e.source: e.target for e in db.scalars(select(TMEntry))}
            order = db.query(Segment).filter(Segment.job_id == job_id).count()
            job = db.get(Job, job_id)
            job.page_count = doc.page_count

        for index, page in enumerate(doc):
            page_no = index + 1
            if page_no in done_pages:
                continue
            self._update(job_id, message=f"Reading page {page_no} of {doc.page_count}",
                         stage_progress=index / doc.page_count)
            render_png(page, job_dir / "pages" / f"{page_no}.png")
            info = classify_page(page)
            blocks, method, flagged, note = [], "none", False, ""
            if info.kind == "empty":
                note = "Empty page"
            elif not info.needs_ocr:
                blocks, method = native_blocks(page), "native"
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
            elif info.kind in ("unicode", "legacy"):
                blocks, method, flagged = native_blocks(page), "native-unreliable", True
                note = "The PDF's text looks garbled and OCR is not installed"
            else:
                note = "Scanned page: OCR (Tesseract) is not installed"

            with session_scope() as db:
                db.add(Page(job_id=job_id, page_no=page_no, kind=info.kind, method=method,
                            quality=info.quality, flagged=flagged, note=note,
                            width=page.rect.width, height=page.rect.height))
                for para_no, block in enumerate(blocks):
                    for sent_no, sentence in enumerate(split_sentences(block.text)):
                        seg = Segment(job_id=job_id, order=order, page_no=page_no, para_no=para_no,
                                      sent_no=sent_no, source=sentence,
                                      needs_translation=has_devanagari(sentence))
                        order += 1
                        if not seg.needs_translation:
                            seg.chosen, seg.chosen_engine, seg.confidence = sentence, "copy", GREEN
                        elif sentence in tm:
                            seg.chosen, seg.chosen_engine, seg.confidence = tm[sentence], "memory", GREEN
                        db.add(seg)
                job = db.get(Job, job_id)
                job.pages_done = page_no
        self._update(job_id, stage_progress=1.0)

    # ---- shared ----------------------------------------------------------------------

    def _pending(self, db, job_id: str, field: str) -> list[Segment]:
        q = select(Segment).where(Segment.job_id == job_id, Segment.needs_translation.is_(True))
        segs = [s for s in db.scalars(q.order_by(Segment.order)) if s.chosen_engine not in SKIP_ENGINES]
        return [s for s in segs if getattr(s, field) is None]

    def _glossary(self) -> list[tuple[str, str]]:
        with session_scope() as db:
            return [(g.hindi, g.english) for g in db.scalars(select(GlossaryTerm))]

    def _load_engine(self, job_id: str, model_id: str) -> Translator | None:
        engine = self.manager.create(model_id)
        try:
            engine.load()
            return engine
        except EngineUnavailable as e:
            self._note(job_id, f"{engine.label} could not start: {e}")
            engine.unload()
            return None

    # ---- stage 2: quick draft --------------------------------------------------------

    def stage_draft(self, job_id: str) -> None:
        model_id = self.manager.draft_model()
        if model_id is None:
            self._note(job_id, "Quick draft skipped: IndicTrans2 is not installed or there is not enough free memory")
            return
        engine = self._load_engine(job_id, model_id)
        if engine is None:
            return
        glossary = self._glossary()
        with session_scope() as db:
            job = db.get(Job, job_id)
            job.draft_model = model_id
            choice = job.choice
            total = len(self._pending(db, job_id, "draft"))
        done, started = 0, time.monotonic()
        try:
            while True:
                with session_scope() as db:
                    batch = self._pending(db, job_id, "draft")[:DRAFT_BATCH]
                    if not batch:
                        break
                    outputs = engine.translate([s.source for s in batch], DocContext(glossary=glossary))
                    for seg, out in zip(batch, outputs):
                        result = check(seg.source, out, glossary=glossary)
                        seg.draft, seg.draft_engine, seg.draft_checks = out or "", engine.id, result.to_dict()
                        # Show the draft straight away; the check stage makes the final choice.
                        if result.usable:
                            seg.chosen, seg.chosen_engine = out, engine.id
                            seg.confidence, seg.issues = result.confidence, list(result.issues)
                    done += len(batch)
                    job = db.get(Job, job_id)
                    job.stage_progress = done / max(total, 1)
                    job.message = f"Quick draft: {done} of {total} sentences"
                    rate = (time.monotonic() - started) / done
                    job.eta_seconds = (total - done) * rate + (total * self.rates["final"] if choice != "fast" else 0)
        finally:
            engine.unload()
        if done:
            self._save_rate("draft", (time.monotonic() - started) / done)
        self._update(job_id, draft_ready_at=utcnow(), message="Quick draft ready")

    # ---- stage 3: final translation (Gemma 4 by default) ------------------------------

    def _pick_final_engine(self, job_id: str, choice: str) -> Translator | None:
        candidates = self.manager.final_candidates(choice)
        if not candidates:
            return None
        for model_id in candidates:
            entry = self.manager.store.entry(model_id)
            ready = self.manager.readiness(model_id)
            if not ready.ready:
                self._note(job_id, f"{entry.label} not used: {ready.reason}")
                continue
            if not fits_in_memory(entry.ram_gb):
                self._note(job_id, f"{entry.label} not used: not enough free memory (close other apps)")
                continue
            engine = self._load_engine(job_id, model_id)
            if engine is not None:
                if model_id != candidates[0]:
                    self._note(job_id, f"Used {entry.label} instead of the first choice")
                return engine
        self._note(job_id, "Final translation used the quick draft (IndicTrans2) only")
        return None

    def stage_final(self, job_id: str) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            choice = job.choice
            subject = next((s.source for s in db.scalars(
                select(Segment).where(Segment.job_id == job_id).order_by(Segment.order))
                if s.source.startswith("विषय")), "")
        if choice == "fast":
            return
        engine = self._pick_final_engine(job_id, choice)
        if engine is None:
            return
        glossary = self._glossary()
        max_sent = int(self.settings.profile.llm.get("paragraph_max_sentences", 10))
        self._update(job_id, model_used=engine.id)
        with session_scope() as db:
            pending = self._pending(db, job_id, "final")
            groups: dict[tuple[int, int], list[int]] = defaultdict(list)
            for s in pending:
                groups[(s.page_no, s.para_no)].append(s.id)
        chunks = [ids[i:i + max_sent] for key in sorted(groups) for ids in [groups[key]]
                  for i in range(0, len(ids), max_sent)]
        total = sum(len(c) for c in chunks)
        done, failures, previous, started = 0, 0, "", time.monotonic()
        try:
            for ids in chunks:
                with session_scope() as db:
                    segs = [db.get(Segment, i) for i in ids]
                    protected = [protect(s.source) for s in segs]
                    hits = [(hi, en) for hi, en in glossary if any(hi in s.source for s in segs)]
                    ctx = DocContext(subject=subject, previous_english=previous, glossary=hits)
                    texts = [p.text for p in protected] if engine.uses_placeholders else [s.source for s in segs]
                    try:
                        outputs = engine.translate(texts, ctx)
                    except EngineUnavailable as e:
                        self._note(job_id, f"{engine.label} stopped: {e}. The quick draft is used for the rest.")
                        break
                    failures = failures + 1 if all(o is None for o in outputs) else 0
                    for seg, prot, out in zip(segs, protected, outputs):
                        restored = restore(out, prot.items) if (out and engine.uses_placeholders) else None
                        text = restored.text if restored else out
                        result = check(seg.source, text, restored=restored, glossary=glossary)
                        seg.final, seg.final_engine, seg.final_checks = text or "", engine.id, result.to_dict()
                        best = choose(seg.source, [
                            Candidate(engine.id, text, result),
                            Candidate(seg.draft_engine or "draft", seg.draft, stored_checks(seg.draft_checks),
                                      is_fallback=True),
                        ])
                        seg.chosen, seg.chosen_engine = best.text, best.engine
                        seg.confidence, seg.issues = best.confidence, best.issues
                    previous = " ".join(o for o in (s.final for s in segs) if o)[-600:]
                    done += len(segs)
                    job = db.get(Job, job_id)
                    job.stage_progress = done / max(total, 1)
                    job.message = f"{engine.label}: {done} of {total} sentences"
                    job.eta_seconds = (total - done) * (time.monotonic() - started) / done
                if failures >= CIRCUIT_BREAKER_FAILURES:
                    self._note(job_id, f"{engine.label} kept failing. The quick draft is used for the rest.")
                    break
        finally:
            engine.unload()
        if done:
            self._save_rate("final", (time.monotonic() - started) / done)

    # ---- stage 4: choose the best version of every sentence ------------------------------

    def stage_check(self, job_id: str) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            flagged_pages = {p.page_no for p in db.scalars(select(Page).where(Page.job_id == job_id, Page.flagged.is_(True)))}
            counts = {"green": 0, "amber": 0, "red": 0}
            final_ran = job.model_used is not None
            segs = list(db.scalars(select(Segment).where(Segment.job_id == job_id).order_by(Segment.order)))
            for seg in segs:
                if seg.chosen_engine in SKIP_ENGINES:
                    counts[seg.confidence or GREEN] += 1
                    continue
                candidates = []
                if seg.final_checks is not None:
                    candidates.append(Candidate(seg.final_engine, seg.final, stored_checks(seg.final_checks)))
                if seg.draft_checks is not None:
                    candidates.append(Candidate(seg.draft_engine, seg.draft, stored_checks(seg.draft_checks),
                                                is_fallback=final_ran))
                best = choose(seg.source, candidates, page_flagged=seg.page_no in flagged_pages)
                seg.chosen, seg.chosen_engine = best.text, best.engine
                seg.confidence, seg.issues = best.confidence, best.issues
                counts[best.confidence] += 1
            job.counts = counts
            job.message = "Checking finished"

    # ---- stage 5: outputs ---------------------------------------------------------------

    def render(self, job_id: str) -> dict[str, Path]:
        with session_scope() as db:
            job = db.get(Job, job_id)
            pages = list(db.scalars(select(Page).where(Page.job_id == job_id).order_by(Page.page_no)))
            segs = list(db.scalars(select(Segment).where(Segment.job_id == job_id).order_by(Segment.order)))
            label = ""
            if job.model_used:
                label = self.manager.store.entry(job.model_used).label
            elif job.draft_model:
                label = self.manager.store.entry(job.draft_model).label
            out_dir = self.settings.job_dir(job_id) / "out"
            paths = {
                "docx": render_docx(job, pages, segs, out_dir / output_name(job, "docx"), label),
                "txt": render_txt(job, pages, segs, out_dir / output_name(job, "txt")),
            }
            job.outputs_stale = False
        return paths


# ---- queue loop ---------------------------------------------------------------------

def next_job_id() -> str | None:
    with session_scope() as db:
        job = db.scalars(
            select(Job).where(Job.status.in_([QUEUED, RUNNING])).order_by(Job.created_at).limit(1)
        ).first()
        return job.id if job else None


def cleanup_old_jobs(settings: Settings) -> int:
    days = int(settings.profile.limits.get("retention_days", 30))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0
    with session_scope() as db:
        for job in db.scalars(select(Job).where(Job.created_at < cutoff)):
            shutil.rmtree(settings.job_dir(job.id), ignore_errors=True)
            db.delete(job)
            removed += 1
    return removed


def run_forever(poll_seconds: float = 1.0) -> None:
    settings = get_settings()
    runner = JobRunner(settings)
    log.info("worker started (profile %s)", settings.profile.name)
    last_cleanup = 0.0
    while True:
        if time.monotonic() - last_cleanup > 3600:
            cleanup_old_jobs(settings)
            last_cleanup = time.monotonic()
        job_id = next_job_id()
        if job_id:
            runner.run(job_id)
        else:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    run_forever()
