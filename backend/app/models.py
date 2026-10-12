"""Database tables: jobs, pages, segments, glossary and translation memory."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator):
    """A datetime stored as naive UTC and always read back *with* the UTC offset.

    SQLite has no time-zone type, so a plain DateTime(timezone=True) comes back naive
    and the browser would read it as local time (5 h 30 min off in India).
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# Job.status values
QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"

# Job.stage values, in order. A job resumes from the first stage not yet completed.
STAGES = ("extract", "draft", "final", "check", "render", "done")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    status: Mapped[str] = mapped_column(String(16), default=QUEUED)
    stage: Mapped[str] = mapped_column(String(16), default="extract")
    stage_progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    choice: Mapped[str] = mapped_column(String(16), default="auto")
    careful_reread: Mapped[bool] = mapped_column(Boolean, default=False)
    model_requested: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    draft_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The chosen final model was wanted but could not run (memory guard, failed to
    # start), so the quick draft stands in for it and is marked amber.
    final_fallback: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))

    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    eta_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    draft_ready_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    final_ready_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    outputs_stale: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on every correction; a render only clears outputs_stale if no correction
    # arrived while it was writing the files.
    edit_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # Set by DELETE on a queued or running job. The worker stops at its next
    # checkpoint, unloads its engine and removes the job's rows and files.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)

    pages: Mapped[list[Page]] = relationship(back_populates="job", cascade="all, delete-orphan")
    segments: Mapped[list[Segment]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (Index("ux_pages_job_page", "job_id", "page_no", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)  # 1-based
    kind: Mapped[str] = mapped_column(String(16))  # unicode | legacy | scan | english | empty | error
    method: Mapped[str] = mapped_column(String(32), default="")  # native | ocr-tesseract | none | failed
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    width: Mapped[float] = mapped_column(Float, default=0)
    height: Mapped[float] = mapped_column(Float, default=0)

    job: Mapped[Job] = relationship(back_populates="pages")


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (Index("ux_segments_job_order", "job_id", "order", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer, index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    para_no: Mapped[int] = mapped_column(Integer)
    sent_no: Mapped[int] = mapped_column(Integer)

    source: Mapped[str] = mapped_column(Text)  # normalised Hindi (or other) text
    needs_translation: Mapped[bool] = mapped_column(Boolean, default=True)
    # Doubts about the source text itself, found while reading the page (e.g.
    # "ocr_numbers": two OCR readings disagreed on a number). They are added to every
    # version of the sentence, whichever engine wins.
    source_issues: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_engine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    draft_checks: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    final: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_engine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_checks: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    chosen: Mapped[str | None] = mapped_column(Text, nullable=True)
    chosen_engine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(8), nullable=True)  # green | amber | red
    issues: Mapped[list[str]] = mapped_column(JSON, default=list)

    edited: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)  # a person corrected this sentence

    job: Mapped[Job] = relationship(back_populates="segments")

    @property
    def display_text(self) -> str | None:
        return self.edited if self.edited is not None else self.chosen


class GlossaryTerm(Base):
    __tablename__ = "glossary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hindi: Mapped[str] = mapped_column(String(255), unique=True)
    english: Mapped[str] = mapped_column(String(255))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class TMEntry(Base):
    """Translation memory: sentences people corrected, reused on exact match."""

    __tablename__ = "translation_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, unique=True)
    target: Mapped[str] = mapped_column(Text)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
