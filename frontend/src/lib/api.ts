export type ChoiceId = "auto" | "fast" | "balanced" | "best";

export interface Choice {
  id: ChoiceId;
  label: string;
  hint: string;
  available: boolean;
  reason: string;
  model: string | null;
}

export interface Settings {
  profile: { name: string; label: string; ram_budget_gb: number };
  dev_mode: boolean;
  ram_total_gb: number;
  ram_available_gb: number;
  default_choice: ChoiceId;
  choices: Choice[];
  engines: { tesseract: boolean; llama_server: boolean };
  limits: { max_mb: number; max_pages: number; retention_days: number };
}

export type Stage = "extract" | "draft" | "final" | "check" | "render" | "done";
export type Confidence = "green" | "amber" | "red";

export interface Job {
  id: string;
  filename: string;
  created_at: string;
  updated_at: string | null;
  status: "queued" | "running" | "done" | "failed";
  stage: Stage;
  stage_progress: number;
  message: string;
  error: string | null;
  choice: ChoiceId;
  model_requested: string | null;
  model_used: string | null;
  draft_model: string | null;
  model_labels: Partial<Record<"model_used" | "draft_model" | "model_requested", string>>;
  page_count: number;
  pages_done: number;
  eta_seconds: number | null;
  draft_ready: boolean;
  final_ready: boolean;
  counts: Partial<Record<Confidence, number>>;
  notes: string[];
  pages?: PageInfo[];
}

export interface PageInfo {
  page_no: number;
  kind: "unicode" | "legacy" | "scan" | "english" | "empty";
  method: string;
  quality: number | null;
  flagged: boolean;
  note: string;
  width: number;
  height: number;
}

export interface Segment {
  id: number;
  page_no: number;
  para_no: number;
  sent_no: number;
  source: string;
  text: string | null;
  engine: string | null;
  confidence: Confidence | null;
  issues: { code: string; message: string }[];
  draft: string | null;
  final: string | null;
  edited: boolean;
  needs_translation: boolean;
}

export interface Term {
  id: number;
  hindi: string;
  english: string;
  note: string;
}

export interface ModelInfo {
  id: string;
  label: string;
  kind: string;
  ram_gb: number;
  licence: string;
  roles: string[];
  min_profile: string;
  installed: boolean;
  size_bytes: number;
  verified: boolean;
  source: string | null;
  revision: string | null;
  download: { running: boolean; log: string[]; ok: boolean | null } | null;
}

export interface Tips {
  term: { hindi: string; english: string } | null;
  tip: string;
  stats: { documents: number; sentences: number };
}

export interface GlossaryImportResult {
  imported: number;
  skipped: number;
  errors: string[];
}

/** An API error. `status` is the HTTP status, or 0 when the service could not be reached. */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export const isNotFound = (e: unknown): boolean => e instanceof ApiError && e.status === 404;

/** Turns a FastAPI error body into one readable sentence (422 bodies hold a list of problems). */
export function errorMessage(body: unknown, status: number, statusText = ""): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => (d && typeof d === "object" && typeof (d as { msg?: unknown }).msg === "string" ? (d as { msg: string }).msg : ""))
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return statusText || `Request failed (${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Can't reach the translator service. Check that it is still running.");
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, errorMessage(body, res.status, res.statusText));
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  settings: () => request<Settings>("/api/settings"),
  jobs: () => request<Job[]>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  /**
   * Done or failed jobs are deleted at once ("deleted"). A queued or running job is
   * stopped first ("cancelling"): the worker removes it at its next checkpoint.
   */
  deleteJob: (id: string) => request<{ status: "deleted" | "cancelling" | string }>(`/api/jobs/${id}`, { method: "DELETE" }),
  /** Start a failed job again from the stage where it stopped. */
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),
  upload: (file: File, choice: ChoiceId) => {
    const form = new FormData();
    form.append("file", file);
    form.append("choice", choice);
    return request<Job>("/api/jobs", { method: "POST", body: form });
  },
  segments: (id: string, page?: number) =>
    request<Segment[]>(`/api/jobs/${id}/segments${page ? `?page=${page}` : ""}`),
  /** Save a correction. It is remembered and reused for identical sentences. */
  correctSegment: (id: number, text: string) =>
    request<Segment>(`/api/segments/${id}`, { method: "PATCH", ...json({ text }) }),
  glossary: () => request<Term[]>("/api/glossary"),
  addTerm: (t: Omit<Term, "id">) => request<Term>("/api/glossary", { method: "POST", ...json(t) }),
  deleteTerm: (id: number) => request<{ status: string }>(`/api/glossary/${id}`, { method: "DELETE" }),
  importGlossary: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Partial<GlossaryImportResult>>("/api/glossary/import", { method: "POST", body: form }).then(
      (r): GlossaryImportResult => ({ imported: r.imported ?? 0, skipped: r.skipped ?? 0, errors: r.errors ?? [] }),
    );
  },
  tips: () => request<Tips>("/api/tips"),
  models: () => request<ModelInfo[]>("/api/models"),
  downloadModel: (id: string) => request<unknown>(`/api/models/${id}/download`, { method: "POST" }),
  importPack: (path: string) =>
    request<{ imported: string[] }>("/api/models/import", { method: "POST", ...json({ path }) }),
};

export const pageImageUrl = (jobId: string, page: number) => `/api/jobs/${jobId}/pages/${page}.png`;
export const downloadUrl = (jobId: string, fmt: "docx" | "txt") => `/api/jobs/${jobId}/download/${fmt}`;
