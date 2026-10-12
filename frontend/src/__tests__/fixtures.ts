// Shared test data for the *.test.ts files (run with: node --test "src/**/*.test.ts").
import type { Job, Segment } from "../lib/api";

export function makeJob(over: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    filename: "letter.pdf",
    created_at: "2026-10-11T08:30:00+00:00",
    updated_at: "2026-10-11T08:31:00+00:00",
    status: "running",
    stage: "extract",
    stage_progress: 0,
    message: "",
    error: null,
    choice: "auto",
    model_requested: "gemma4-e2b",
    model_used: null,
    draft_model: null,
    model_labels: { model_requested: "Gemma 4 E2B" },
    page_count: 2,
    pages_done: 0,
    eta_seconds: null,
    draft_ready: false,
    final_ready: false,
    counts: {},
    notes: [],
    ...over,
  };
}

export function makeSegment(over: Partial<Segment> = {}): Segment {
  return {
    id: 1,
    page_no: 1,
    para_no: 0,
    sent_no: 0,
    source: "यह एक वाक्य है।",
    text: "This is a sentence.",
    engine: "indictrans2-1b",
    confidence: "green",
    issues: [],
    draft: "This is a sentence.",
    final: null,
    edited: false,
    needs_translation: true,
    ...over,
  };
}
