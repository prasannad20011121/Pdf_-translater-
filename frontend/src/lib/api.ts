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
  approved: boolean;
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail || `Request failed (${res.status})`);
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
  deleteJob: (id: string) => request<{ status: string }>(`/api/jobs/${id}`, { method: "DELETE" }),
  upload: (file: File, choice: ChoiceId) => {
    const form = new FormData();
    form.append("file", file);
    form.append("choice", choice);
    return request<Job>("/api/jobs", { method: "POST", body: form });
  },
  segments: (id: string, page?: number) =>
    request<Segment[]>(`/api/jobs/${id}/segments${page ? `?page=${page}` : ""}`),
  updateSegment: (id: number, body: { text?: string; approved?: boolean }) =>
    request<Segment>(`/api/segments/${id}`, { method: "PATCH", ...json(body) }),
  glossary: () => request<Term[]>("/api/glossary"),
  addTerm: (t: Omit<Term, "id">) => request<Term>("/api/glossary", { method: "POST", ...json(t) }),
  deleteTerm: (id: number) => request<{ status: string }>(`/api/glossary/${id}`, { method: "DELETE" }),
  importGlossary: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ imported: number }>("/api/glossary/import", { method: "POST", body: form });
  },
  tips: () => request<Tips>("/api/tips"),
  models: () => request<ModelInfo[]>("/api/models"),
  downloadModel: (id: string) => request<unknown>(`/api/models/${id}/download`, { method: "POST" }),
  importPack: (path: string) =>
    request<{ imported: string[] }>("/api/models/import", { method: "POST", ...json({ path }) }),
};

export const pageImageUrl = (jobId: string, page: number) => `/api/jobs/${jobId}/pages/${page}.png`;
export const downloadUrl = (jobId: string, fmt: "docx" | "txt") => `/api/jobs/${jobId}/download/${fmt}`;
