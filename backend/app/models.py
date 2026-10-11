"""Database tables: jobs, pages, segments, glossary and translation memory."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


# Job.status values
QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"

# Job.stage values, in order. A job resumes from the first stage not yet completed.
STAGES = ("extract", "draft", "final", "check", "render", "done")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

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

    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    eta_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    draft_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outputs_stale: Mapped[bool] = mapped_column(Boolean, default=True)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)

    pages: Mapped[list["Page"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    segments: Mapped[list["Segment"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)  # 1-based
    kind: Mapped[str] = mapped_column(String(16))  # unicode | legacy | scan | english | empty
    method: Mapped[str] = mapped_column(String(32), default="")  # native | ocr-tesseract | none
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    width: Mapped[float] = mapped_column(Float, default=0)
    height: Mapped[float] = mapped_column(Float, default=0)

    job: Mapped[Job] = relationship(back_populates="pages")


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer, index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    para_no: Mapped[int] = mapped_column(Integer)
    sent_no: Mapped[int] = mapped_column(Integer)

    source: Mapped[str] = mapped_column(Text)  # normalised Hindi (or other) text
    needs_translation: Mapped[bool] = mapped_column(Boolean, default=True)

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
    approved: Mapped[bool] = mapped_column(Boolean, default=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TMEntry(Base):
    """Translation memory: approved sentence pairs, reused on exact match."""

    __tablename__ = "translation_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, unique=True)
    target: Mapped[str] = mapped_column(Text)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
