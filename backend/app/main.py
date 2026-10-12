"""HTTP API and the web UI, served on http://127.0.0.1:8080 (PLAN.md §5, §9)."""

from __future__ import annotations

import asyncio
import codecs
import csv
import io
import json
import logging
import os
import random
import re
import shutil
import threading
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import psutil
import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from .config import CHOICES, FRONTEND_DIST, get_settings
from .db import get_engine, session_scope
from .model_manager import ModelManager, available_memory_gb
from .model_store import PackImportError
from .models import (
    DONE,
    FAILED,
    QUEUED,
    GlossaryTerm,
    Job,
    Page,
    Segment,
    TMEntry,
    new_id,
)
from .pipeline.normalize import has_devanagari
from .pipeline.ocr import tesseract
from .pipeline.render.outputs import output_name
from .pipeline.validate import MESSAGES
from .worker import (
    JobGone,
    JobRunner,
    cleanup_old_jobs,
    job_counts,
    output_path,
    remove_job_files,
)

log = logging.getLogger("pdft.api")

TIPS = [
    "Press ↑ and ↓ to move between sentences on the review screen, and E or Enter to correct one.",
    "Sentences you correct are remembered and reused automatically in later documents.",
    "Amber and red sentences are the only ones you need to check.",
    "Choose Fast for routine circulars and Best quality for tenders and contracts.",
    "You can leave this page and keep working. Keep this browser tab open to get a notification when the translation is ready.",
    "Add recurring terms to the glossary so every document uses the same English.",
]

JOB_ID = re.compile(r"[0-9a-f]{32}")
# The app only answers to this laptop's own names. Checking Host defeats DNS
# rebinding; checking Origin stops other websites from posting to the API (CSRF).
# "testserver" is the host name used by FastAPI's TestClient.
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_engine()
    try:
        cleanup_old_jobs(get_settings())
    except Exception:  # never stop the app from starting
        log.exception("clean-up of old jobs failed")
    yield


app = FastAPI(title="Hindi PDF Translator", lifespan=lifespan)

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)


def host_name(value: str | None) -> str | None:
    """The host part of a Host header ("127.0.0.1:8080", "[::1]:8080"), lower-cased."""
    value = (value or "").strip().lower()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        host, rest = value[1:end], value[end + 1:]
        if end < 0 or (rest and not (rest.startswith(":") and rest[1:].isdigit())):
            return None
        return host
    host, sep, port = value.partition(":")
    if sep and not port.isdigit():
        return None
    return host or None


def same_site(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is not None:
        try:
            if urlsplit(origin).hostname not in ALLOWED_HOSTS:
                return False
        except ValueError:
            return False
    return request.headers.get("sec-fetch-site", "").lower() != "cross-site"


@app.middleware("http")
async def guard_and_headers(request: Request, call_next):
    if host_name(request.headers.get("host")) not in ALLOWED_HOSTS:
        response: Response = JSONResponse(
            {"detail": "This address is not allowed. Open the translator at http://127.0.0.1"}, status_code=400)
    elif request.method in UNSAFE_METHODS and not same_site(request):
        response = JSONResponse({"detail": "Request from another website blocked"}, status_code=403)
    else:
        response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


def manager() -> ModelManager:
    return ModelManager(get_settings())


# ---- serialisers --------------------------------------------------------------------

def iso_utc(dt: datetime | None) -> str | None:
    """ISO-8601 with an explicit UTC offset, so browsers don't read it as local time."""
    if dt is None:
        return None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)).isoformat()


def job_dict(job: Job, store=None) -> dict[str, Any]:
    labels = {}
    if store is not None:
        for key in ("model_used", "draft_model", "model_requested"):
            model_id = getattr(job, key)
            if model_id and model_id in store.catalog:
                labels[key] = store.catalog[model_id].label
    return {
        "id": job.id,
        "filename": job.filename,
        "created_at": iso_utc(job.created_at),
        "updated_at": iso_utc(job.updated_at),
        "status": job.status,
        "stage": job.stage,
        "stage_progress": round(job.stage_progress or 0, 4),
        "message": job.message,
        "error": job.error,
        "choice": job.choice,
        "model_requested": job.model_requested,
        "model_used": job.model_used,
        "draft_model": job.draft_model,
        "model_labels": labels,
        "page_count": job.page_count,
        "pages_done": job.pages_done,
        "eta_seconds": job.eta_seconds,
        "draft_ready": job.draft_ready_at is not None,
        "final_ready": job.final_ready_at is not None,
        "counts": job.counts or {},
        "notes": job.notes or [],
    }


def segment_dict(s: Segment) -> dict[str, Any]:
    return {
        "id": s.id,
        "page_no": s.page_no,
        "para_no": s.para_no,
        "sent_no": s.sent_no,
        "source": s.source,
        "text": s.display_text,
        "engine": s.chosen_engine,
        "confidence": s.confidence,
        "issues": [{"code": c, "message": MESSAGES.get(c, c)} for c in (s.issues or [])],
        "draft": s.draft,
        "final": s.final,
        "edited": s.edited is not None,
        "needs_translation": s.needs_translation,
    }


def page_dict(p: Page) -> dict[str, Any]:
    return {
        "page_no": p.page_no, "kind": p.kind, "method": p.method, "quality": p.quality,
        "flagged": p.flagged, "note": p.note, "width": p.width, "height": p.height,
    }


def check_job_id(job_id: str) -> None:
    """Job ids are 32 hex characters. Anything else never reaches the file system
    (a crafted id such as \\\\server\\share would make Windows contact that server)."""
    if not JOB_ID.fullmatch(job_id or ""):
        raise HTTPException(404, "Job not found")


def get_job_or_404(db, job_id: str) -> Job:
    check_job_id(job_id)
    job = db.get(Job, job_id)
    if job is None or job.cancel_requested:  # being deleted: gone for the user
        raise HTTPException(404, "Job not found")
    return job


# ---- settings and models -----------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings")
def settings_info() -> dict[str, Any]:
    s = get_settings()
    mm = manager()
    return {
        "profile": {"name": s.profile.name, "label": s.profile.label, "ram_budget_gb": s.profile.ram_budget_gb},
        "dev_mode": s.is_dev,
        "ram_total_gb": round(psutil.virtual_memory().total / 1024**3, 1),
        "ram_available_gb": round(available_memory_gb(), 1),
        "default_choice": s.profile.default_choice,
        "choices": mm.choices(),
        "engines": {
            "tesseract": tesseract.available(s.tesseract_cmd),
            "llama_server": bool(s.llama_server_bin),
        },
        "limits": s.profile.limits,
    }


_downloads: dict[str, dict[str, Any]] = {}


@app.get("/api/models")
def list_models() -> list[dict[str, Any]]:
    mm = manager()
    out = []
    for model_id in mm.store.catalog:
        status = mm.store.status(model_id)
        if status["kind"] == "dev" and not get_settings().is_dev:
            continue
        status["download"] = _downloads.get(model_id)
        out.append(status)
    return out


@app.post("/api/models/{model_id}/download")
def download_model(model_id: str) -> dict[str, Any]:
    mm = manager()
    if model_id not in mm.store.catalog:
        raise HTTPException(404, "Not in the model catalog")
    if _downloads.get(model_id, {}).get("running"):
        return _downloads[model_id]
    state: dict[str, Any] = {"running": True, "log": [], "ok": None}
    _downloads[model_id] = state

    def work() -> None:
        try:
            mm.store.download(model_id, log=lambda m: state["log"].append(m))
            state["ok"] = True
        except Exception as e:  # network blocked, repo moved...
            state["log"].append(f"Failed: {e}")
            state["ok"] = False
        finally:
            state["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return state


class ImportRequest(BaseModel):
    path: str


@app.post("/api/models/import")
def import_pack(req: ImportRequest) -> dict[str, Any]:
    pack = Path(req.path)
    if not pack.is_dir():
        raise HTTPException(400, "Folder not found")
    try:
        report = manager().store.import_pack_report(pack, log=lambda m: None)
    except PackImportError as e:
        raise HTTPException(400, str(e)) from None
    return {"imported": report["imported"], "failed": report.get("failed", {})}


# ---- jobs -----------------------------------------------------------------------------

@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    choice: str = Form("auto"),
) -> dict[str, Any]:
    s = get_settings()
    if choice not in CHOICES:
        raise HTTPException(400, "Unknown model choice")
    name = Path(file.filename or "document.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file")
    max_mb = float(s.profile.limits.get("max_mb", 50))
    data = await file.read(int(max_mb * 1024 * 1024) + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"The file is larger than {max_mb:g} MB")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise HTTPException(400, "This file is not a readable PDF") from None
    try:
        if doc.needs_pass:
            raise HTTPException(400, "Password-protected PDFs are not supported yet. Remove the password and try again.")
        page_count = doc.page_count
    finally:
        doc.close()
    max_pages = int(s.profile.limits.get("max_pages", 100))
    if page_count > max_pages:
        raise HTTPException(400, f"The PDF has {page_count} pages; the limit is {max_pages}")

    # The file must be complete on disk before the worker can see the job: write it
    # first (to a temporary name, then rename), and only then add the queued row.
    job_id = new_id()
    job_dir = s.job_dir(job_id)
    try:
        job_dir.mkdir(parents=True)
        part = job_dir / "source.pdf.part"
        part.write_bytes(data)
        os.replace(part, job_dir / "source.pdf")
        with session_scope() as db:
            job = Job(id=job_id, filename=name[:255], choice=choice,
                      model_requested=s.profile.choices.get(choice), page_count=page_count)
            db.add(job)
            db.flush()
            return job_dict(job, manager().store)
    except BaseException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    store = manager().store
    with session_scope() as db:
        q = select(Job).where(Job.cancel_requested.is_(False)).order_by(Job.created_at.desc()).limit(200)
        return [job_dict(j, store) for j in db.scalars(q)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with session_scope() as db:
        job = get_job_or_404(db, job_id)
        data = job_dict(job, manager().store)
        data["pages"] = [page_dict(p) for p in sorted(job.pages, key=lambda p: p.page_no)]
        return data


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, str]:
    """A finished job is deleted at once. A queued or running one is cancelled: the
    worker stops at its next checkpoint, unloads its model and removes the job."""
    check_job_id(job_id)
    with session_scope() as db:
        # One conditional statement each, so a job can't change status in between.
        removed = db.execute(delete(Job).where(
            Job.id == job_id, Job.status.in_([DONE, FAILED]), Job.cancel_requested.is_(False))).rowcount
        if not removed:
            flagged = db.execute(update(Job).where(Job.id == job_id).values(cancel_requested=True)).rowcount
            if not flagged:
                raise HTTPException(404, "Job not found")
    if removed:  # pages and segments go with it (ON DELETE CASCADE)
        remove_job_files(get_settings(), job_id)
        return {"status": "deleted"}
    return {"status": "cancelling"}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict[str, Any]:
    """Try a failed job again, carrying on from the stage where it stopped."""
    store = manager().store
    with session_scope() as db:
        job = get_job_or_404(db, job_id)
        if job.status != FAILED:
            raise HTTPException(409, "Only a translation that failed can be tried again")
        values: dict[str, Any] = {"status": QUEUED, "error": None, "message": "Waiting to start",
                                  "eta_seconds": None, "stage_progress": 0.0}
        if job.stage in ("extract", "draft", "final"):
            values["final_fallback"] = False
        if job.stage in ("extract", "draft"):
            values["notes"] = []  # they described the attempt that failed
        changed = db.execute(update(Job).where(
            Job.id == job_id, Job.status == FAILED, Job.cancel_requested.is_(False)).values(**values)).rowcount
        if not changed:
            raise HTTPException(409, "Only a translation that failed can be tried again")
        db.refresh(job)
        return job_dict(job, store)


@app.get("/api/jobs/{job_id}/segments")
def get_segments(job_id: str, page: int | None = None) -> list[dict[str, Any]]:
    with session_scope() as db:
        get_job_or_404(db, job_id)
        q = select(Segment).where(Segment.job_id == job_id)
        if page is not None:
            q = q.where(Segment.page_no == page)
        return [segment_dict(s) for s in db.scalars(q.order_by(Segment.order))]


@app.get("/api/jobs/{job_id}/pages/{page_no}.png")
def page_image(job_id: str, page_no: int) -> FileResponse:
    check_job_id(job_id)
    if page_no < 1:
        raise HTTPException(404, "Page not found")
    with session_scope() as db:
        job = get_job_or_404(db, job_id)
        if page_no > max(job.page_count or 0, 0):
            raise HTTPException(404, "Page not found")
    path = get_settings().job_dir(job_id) / "pages" / f"{page_no}.png"
    if not path.is_file():
        raise HTTPException(404, "Page image not ready")
    return FileResponse(path, media_type="image/png")


@app.get("/api/jobs/{job_id}/download/{fmt}")
def download(job_id: str, fmt: str) -> FileResponse:
    if fmt not in ("docx", "txt"):
        raise HTTPException(400, "Unknown format")
    with session_scope() as db:
        job = get_job_or_404(db, job_id)
        if not job.draft_ready_at and job.status != DONE:
            raise HTTPException(409, "The translation is not ready yet")
        name = output_name(job, fmt)
        stale = job.outputs_stale
    settings = get_settings()
    path: Path | None = output_path(settings, job_id, fmt)
    if stale or not path.exists():
        try:
            path = JobRunner(settings, manager()).render(job_id).get(fmt)
        except JobGone:
            raise HTTPException(404, "Job not found") from None
    if path is None or not path.exists():
        detail = ("The Word file could not be created for this document. Download the text file instead."
                  if fmt == "docx" else "The text file could not be created")
        raise HTTPException(500, detail)
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if fmt == "docx" else "text/plain; charset=utf-8"
    )
    return FileResponse(path, media_type=media, filename=name)


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    """Server-Sent Events: a job snapshot whenever it changes."""
    with session_scope() as db:
        get_job_or_404(db, job_id)
    store = manager().store

    async def stream():
        last, idle = None, 0
        while not await request.is_disconnected():
            with session_scope() as db:
                job = db.get(Job, job_id)
                if job is None or job.cancel_requested:
                    break
                snapshot = job_dict(job, store)
            key = (snapshot["updated_at"], snapshot["status"])
            if key != last:
                last, idle = key, 0
                yield f"data: {json.dumps(snapshot)}\n\n"
                if snapshot["status"] in (DONE, FAILED):
                    break
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ---- review edits ------------------------------------------------------------------------

class SegmentUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@app.patch("/api/segments/{segment_id}")
def update_segment(segment_id: int, upd: SegmentUpdate) -> dict[str, Any]:
    """Save a person's correction. There is no separate approve step: a correction is
    remembered (translation memory) and reused for identical sentences, here and in
    later documents."""
    text = upd.text.strip()
    if not text:
        raise HTTPException(400, "The translation can't be empty")
    with session_scope() as db:
        seg = db.get(Segment, segment_id)
        if seg is None or seg.job.cancel_requested:
            raise HTTPException(404, "Sentence not found")
        seg.edited, seg.approved = text, True
        entry = db.scalars(select(TMEntry).where(TMEntry.source == seg.source)).first()
        if entry:
            entry.target = text
        else:
            db.add(TMEntry(source=seg.source, target=text))
        for twin in db.scalars(select(Segment).where(
            Segment.job_id == seg.job_id, Segment.source == seg.source, Segment.id != seg.id,
            Segment.edited.is_(None),
        )):
            twin.edited, twin.approved = text, True
        db.flush()
        # A corrected sentence no longer needs checking: keep the document summary in
        # step. edit_version lets a render that is running right now notice this edit.
        db.execute(update(Job).where(Job.id == seg.job_id).values(
            counts=job_counts(db, seg.job_id),
            outputs_stale=True,
            edit_version=func.coalesce(Job.edit_version, 0) + 1,
        ))
        return segment_dict(seg)


# ---- glossary and translation memory --------------------------------------------------------

class TermIn(BaseModel):
    hindi: str = Field(min_length=1, max_length=255)
    english: str = Field(min_length=1, max_length=255)
    note: str = ""


@app.get("/api/glossary")
def glossary_list() -> list[dict[str, Any]]:
    with session_scope() as db:
        return [{"id": g.id, "hindi": g.hindi, "english": g.english, "note": g.note}
                for g in db.scalars(select(GlossaryTerm).order_by(GlossaryTerm.hindi))]


@app.post("/api/glossary")
def glossary_add(term: TermIn) -> dict[str, Any]:
    with session_scope() as db:
        # One Unicode form (NFC) for every term, so lookups match however it was typed.
        hindi = unicodedata.normalize("NFC", term.hindi.strip())
        existing = db.scalars(select(GlossaryTerm).where(GlossaryTerm.hindi == hindi)).first()
        g = existing or GlossaryTerm(hindi=hindi)
        g.english, g.note = term.english.strip(), term.note.strip()
        db.add(g)
        db.flush()
        return {"id": g.id, "hindi": g.hindi, "english": g.english, "note": g.note}


@app.delete("/api/glossary/{term_id}")
def glossary_delete(term_id: int) -> dict[str, str]:
    with session_scope() as db:
        g = db.get(GlossaryTerm, term_id)
        if g is None:
            raise HTTPException(404, "Term not found")
        db.delete(g)
    return {"status": "deleted"}


MAX_GLOSSARY_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ERRORS = 20
CSV_UTF8_HINT = 'In Excel, choose File > Save As > "CSV UTF-8 (Comma delimited)" and import that file.'


def decode_csv(data: bytes) -> str:
    """Text of an uploaded CSV. Only UTF-8 and UTF-16 keep Hindi letters: Excel's plain
    "CSV (Comma delimited)" saves them as "?", which must not overwrite good terms."""
    try:
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return data.decode("utf-16")
        if b"\x00" in data[:4096]:
            raise UnicodeDecodeError("utf-8", data[:1], 0, 1, "NUL byte")
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            400, f"This file is not saved as UTF-8, so its Hindi text can't be read. {CSV_UTF8_HINT}") from None


def _delimiter(text: str) -> str:
    first = next((line for line in text.splitlines() if line.strip()), "")
    counts = {d: first.count(d) for d in (",", "\t", ";")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > counts[","] else ","


@app.post("/api/glossary/import")
async def glossary_import(file: UploadFile = File(...)) -> dict[str, Any]:
    """Import hindi,english[,note] rows. Returns how many were imported and skipped,
    and why rows were skipped."""
    data = await file.read(MAX_GLOSSARY_BYTES + 1)
    if len(data) > MAX_GLOSSARY_BYTES:
        raise HTTPException(413, "The file is larger than 2 MB")
    text = decode_csv(data)
    imported, skipped, errors = 0, 0, []

    def skip(row_no: int, reason: str) -> None:
        nonlocal skipped
        skipped += 1
        if len(errors) < MAX_IMPORT_ERRORS:
            errors.append(f"Row {row_no}: {reason}")

    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=_delimiter(text)))
    except csv.Error as e:
        raise HTTPException(400, f"This file could not be read as CSV ({e}). {CSV_UTF8_HINT}") from None
    with session_scope() as db:
        terms: dict[str, GlossaryTerm] = {}
        for row_no, row in enumerate(rows, start=1):
            cells = [c.strip() for c in row]
            if not any(cells):
                continue
            if cells[0].lower() == "hindi":
                continue  # header
            if len(cells) < 2 or not cells[0] or not cells[1]:
                skip(row_no, "needs both a Hindi term and its English")
                continue
            hindi, english = unicodedata.normalize("NFC", cells[0]), cells[1]
            note = cells[2] if len(cells) > 2 else ""
            if "\ufffd" in hindi or "?" in hindi or not has_devanagari(hindi):
                skip(row_no, f'"{hindi[:40]}" has no Hindi letters (was the file saved as CSV UTF-8?)')
                continue
            if "\ufffd" in english or "\ufffd" in note:
                skip(row_no, "contains unreadable characters (was the file saved as CSV UTF-8?)")
                continue
            if len(hindi) > 255 or len(english) > 255:
                skip(row_no, "a term is longer than 255 characters")
                continue
            g = terms.get(hindi) or db.scalars(select(GlossaryTerm).where(GlossaryTerm.hindi == hindi)).first()
            if g is None:
                g = GlossaryTerm(hindi=hindi)
                db.add(g)
            g.english, g.note = english, note
            terms[hindi] = g
            imported += 1
    if skipped > len(errors):
        errors.append(f"…and {skipped - len(errors)} more rows skipped")
    return {"imported": imported, "skipped": skipped, "errors": errors}


@app.get("/api/glossary/export")
def glossary_export() -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["hindi", "english", "note"])
    with session_scope() as db:
        for g in db.scalars(select(GlossaryTerm).order_by(GlossaryTerm.hindi)):
            writer.writerow([g.hindi, g.english, g.note])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="glossary.csv"'})


@app.get("/api/tips")
def tips() -> dict[str, Any]:
    """Offline content for the "While you wait" panel (PLAN.md §9.3)."""
    with session_scope() as db:
        terms = list(db.scalars(select(GlossaryTerm)))
        done = db.scalar(select(func.count()).select_from(Job).where(Job.status == DONE)) or 0
        sentences = db.scalar(select(func.count()).select_from(Segment)) or 0
        term = random.choice(terms) if terms else None
        return {
            "term": {"hindi": term.hindi, "english": term.english} if term else None,
            "tip": random.choice(TIPS),
            "stats": {"documents": done, "sentences": sentences},
        }


# ---- web UI ---------------------------------------------------------------------------

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


def _safe_relative(path: str) -> bool:
    """Reject before touching the disk: backslashes and drive letters (Windows UNC and
    absolute paths), NUL, and '..' segments."""
    if any(ch in path for ch in ("\\", ":", "\x00")):
        return False
    return ".." not in PurePosixPath(path).parts and not path.startswith("/")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if path and _safe_relative(path):
        candidate = FRONTEND_DIST / path
        if candidate.is_file() and FRONTEND_DIST.resolve() in candidate.resolve().parents:
            return FileResponse(candidate)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "The web UI has not been built yet (cd frontend && npm run build)"}, status_code=404)
