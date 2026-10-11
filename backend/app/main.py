"""HTTP API and the web UI, served on http://127.0.0.1:8080 (PLAN.md §5, §9)."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import random
import shutil
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psutil
import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .config import CHOICES, FRONTEND_DIST, get_settings
from .db import get_engine, session_scope
from .model_manager import ModelManager, available_memory_gb
from .models import DONE, FAILED, GlossaryTerm, Job, Page, Segment, TMEntry
from .pipeline.ocr import tesseract
from .pipeline.render.outputs import output_name
from .pipeline.validate import MESSAGES
from .worker import JobRunner, cleanup_old_jobs

TIPS = [
    "Press ↑ and ↓ to move between sentences on the review screen, and E or Enter to correct one.",
    "Sentences you correct are remembered and reused automatically in later documents.",
    "Amber and red sentences are the only ones you need to check.",
    "Choose Fast for routine circulars and Best quality for tenders and contracts.",
    "You can close this page: a notification appears when the translation is ready.",
    "Add recurring terms to the glossary so every document uses the same English.",
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_engine()
    cleanup_old_jobs(get_settings())
    yield


app = FastAPI(title="Hindi PDF Translator", lifespan=lifespan)

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


def manager() -> ModelManager:
    return ModelManager(get_settings())


# ---- serialisers --------------------------------------------------------------------

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
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
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


def get_job_or_404(db, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
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
    imported = manager().store.import_pack(pack, log=lambda m: None)
    return {"imported": imported}


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
    if doc.needs_pass:
        raise HTTPException(400, "Password-protected PDFs are not supported yet. Remove the password and try again.")
    max_pages = int(s.profile.limits.get("max_pages", 100))
    if doc.page_count > max_pages:
        raise HTTPException(400, f"The PDF has {doc.page_count} pages; the limit is {max_pages}")

    job = Job(filename=name[:255], choice=choice, model_requested=s.profile.choices.get(choice),
              page_count=doc.page_count)
    with session_scope() as db:
        db.add(job)
        db.flush()
        job_id = job.id
    job_dir = s.job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "source.pdf").write_bytes(data)
    with session_scope() as db:
        return job_dict(db.get(Job, job_id), manager().store)


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    store = manager().store
    with session_scope() as db:
        return [job_dict(j, store) for j in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(200))]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with session_scope() as db:
        job = get_job_or_404(db, job_id)
        data = job_dict(job, manager().store)
        data["pages"] = [page_dict(p) for p in sorted(job.pages, key=lambda p: p.page_no)]
        return data


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, str]:
    with session_scope() as db:
        job = get_job_or_404(db, job_id)
        db.delete(job)
    shutil.rmtree(get_settings().job_dir(job_id), ignore_errors=True)
    return {"status": "deleted"}


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
    path = get_settings().job_dir(job_id) / "pages" / f"{page_no}.png"
    if not path.exists():
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
    path = get_settings().job_dir(job_id) / "out" / name
    if stale or not path.exists():
        path = JobRunner(get_settings(), manager()).render(job_id)[fmt]
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
                if job is None:
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
        if seg is None:
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
        # A corrected sentence no longer needs checking: keep the document summary in step.
        counts = {"green": 0, "amber": 0, "red": 0}
        for s in db.scalars(select(Segment).where(Segment.job_id == seg.job_id)):
            counts["green" if s.edited is not None else (s.confidence or "green")] += 1
        seg.job.counts = counts
        seg.job.outputs_stale = True
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
        existing = db.scalars(select(GlossaryTerm).where(GlossaryTerm.hindi == term.hindi.strip())).first()
        g = existing or GlossaryTerm(hindi=term.hindi.strip())
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


@app.post("/api/glossary/import")
async def glossary_import(file: UploadFile = File(...)) -> dict[str, int]:
    text = (await file.read(2 * 1024 * 1024)).decode("utf-8-sig", errors="replace")
    added = 0
    with session_scope() as db:
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 2 or not row[0].strip() or not row[1].strip():
                continue
            if row[0].strip().lower() == "hindi":
                continue  # header
            hindi, english = row[0].strip(), row[1].strip()
            note = row[2].strip() if len(row) > 2 else ""
            g = db.scalars(select(GlossaryTerm).where(GlossaryTerm.hindi == hindi)).first() or GlossaryTerm(hindi=hindi)
            g.english, g.note = english, note
            db.add(g)
            added += 1
    return {"imported": added}


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


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    candidate = FRONTEND_DIST / path
    if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.resolve().parents:
        return FileResponse(candidate)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "The web UI has not been built yet (cd frontend && npm run build)"}, status_code=404)
