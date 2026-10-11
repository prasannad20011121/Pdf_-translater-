import { ArrowLeft, ChevronLeft, ChevronRight, Download, Eye, FileType2, Filter, Info, ScanLine } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ConfidenceSummary } from "@/components/ConfidenceBadge";
import { SegmentCard } from "@/components/SegmentCard";
import { StageStepper } from "@/components/StageStepper";
import { StatusBadge } from "@/components/StatusBadge";
import { WhileYouWait } from "@/components/WhileYouWait";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { api, downloadUrl, pageImageUrl, type Job, type Segment } from "@/lib/api";
import { cn, formatEta, notify } from "@/lib/utils";

type View = "progress" | "review";

function useJob(id: string) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setJob(await api.job(id));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Live updates while the job runs (Server-Sent Events). The page list is
  // reloaded only when another page has been read, or when the job finishes.
  const running = job ? job.status === "running" || job.status === "queued" : false;
  const pagesSeen = useRef(-1);
  useEffect(() => {
    if (!running) return;
    const es = new EventSource(`/api/jobs/${id}/events`);
    es.onmessage = (ev) => {
      const snap = JSON.parse(ev.data) as Job;
      setJob((prev) => ({ ...snap, pages: prev?.pages }));
      if (snap.pages_done !== pagesSeen.current || snap.status === "done" || snap.status === "failed") {
        pagesSeen.current = snap.pages_done;
        void reload();
      }
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [id, running, reload]);

  return { job, error, reload };
}

export default function JobPage() {
  const { id = "" } = useParams();
  const { job, error } = useJob(id);
  const [view, setView] = useState<View | null>(null);
  const [page, setPage] = useState(1);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [onlyReview, setOnlyReview] = useState(false);
  const notified = useRef({ draft: false, final: false });

  // Pick the starting view once the job is known.
  useEffect(() => {
    if (job && view === null) setView(job.status === "done" ? "review" : "progress");
  }, [job, view]);

  // Desktop notifications at the two milestones.
  useEffect(() => {
    if (!job) return;
    if (job.draft_ready && job.status !== "done" && !notified.current.draft) {
      notified.current.draft = true;
      void notify("Quick draft ready", `${job.filename}: you can start reading.`);
    }
    if (job.status === "done" && !notified.current.final) {
      notified.current.final = true;
      void notify("Translation ready", job.filename);
    }
  }, [job]);

  const loadSegments = useCallback(async () => {
    try {
      setSegments(await api.segments(id, page));
    } catch {
      /* page not extracted yet */
    }
  }, [id, page]);

  // Refresh the visible page's sentences whenever the job reports progress.
  const lastLoad = useRef(0);
  useEffect(() => {
    const now = Date.now();
    const wait = Math.max(0, 1200 - (now - lastLoad.current));
    const t = setTimeout(() => {
      lastLoad.current = Date.now();
      void loadSegments();
    }, wait);
    return () => clearTimeout(t);
  }, [loadSegments, job?.updated_at, job?.status]);

  const visible = useMemo(
    () => (onlyReview ? segments.filter((s) => s.needs_translation && s.confidence !== "green" && !s.approved) : segments),
    [segments, onlyReview],
  );

  const replace = (s: Segment) => setSegments((all) => all.map((x) => (x.id === s.id ? s : x)));
  const save = async (seg: Segment, text: string) => {
    replace(await api.updateSegment(seg.id, { text, approved: true }));
    setEditing(null);
    void loadSegments();
  };
  const approve = async (seg: Segment) => {
    replace(await api.updateSegment(seg.id, { approved: true }));
    void loadSegments();
  };

  // Keyboard: ↑/↓ move, E edit, Enter approve.
  useEffect(() => {
    if (view !== "review") return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (editing !== null || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const idx = visible.findIndex((s) => s.id === selected);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const next = e.key === "ArrowDown" ? Math.min(visible.length - 1, idx + 1) : Math.max(0, idx - 1);
        if (visible[next]) setSelected(visible[next].id);
      } else if ((e.key === "e" || e.key === "E") && selected !== null) {
        e.preventDefault();
        setEditing(selected);
      } else if (e.key === "Enter" && selected !== null) {
        const seg = visible.find((s) => s.id === selected);
        if (seg && !seg.approved) void approve(seg);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, visible, selected, editing]);

  if (error) {
    return (
      <div className="space-y-4">
        <Link to="/jobs" className="text-sm text-primary hover:underline">← Documents</Link>
        <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>
      </div>
    );
  }
  if (!job || view === null) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner /> Loading…
      </div>
    );
  }

  const running = job.status === "running" || job.status === "queued";
  const pageCount = Math.max(job.page_count, 1);
  const pageInfo = job.pages?.find((p) => p.page_no === page);
  const canDownload = job.draft_ready || job.status === "done";
  const needsReview = (job.counts.amber ?? 0) + (job.counts.red ?? 0);

  const pager = (
    <div className="flex items-center gap-1">
      <Button variant="ghost" size="icon" onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1} aria-label="Previous page">
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <span className="min-w-[6.5rem] text-center text-sm tabular-nums">
        Page {page} of {pageCount}
      </span>
      <Button variant="ghost" size="icon" onClick={() => setPage(Math.min(pageCount, page + 1))} disabled={page >= pageCount} aria-label="Next page">
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );

  const pageImage = (
    <Card className="overflow-hidden">
      {page <= job.pages_done ? (
        <img
          src={pageImageUrl(job.id, page)}
          alt={`Original page ${page}`}
          className="w-full bg-white"
          style={pageInfo ? { aspectRatio: `${pageInfo.width} / ${pageInfo.height}` } : undefined}
        />
      ) : (
        <div className="flex aspect-[1/1.414] items-center justify-center text-sm text-muted-foreground">
          <Spinner className="mr-2" /> Reading page {page}…
        </div>
      )}
    </Card>
  );

  return (
    <div className="animate-fade-in space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <Link to="/jobs" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" aria-hidden /> Documents
          </Link>
          <h1 className="truncate text-2xl font-semibold tracking-tight">{job.filename}</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <StatusBadge job={job} />
            {job.model_labels.model_used && <Badge tone="primary">{job.model_labels.model_used}</Badge>}
            {!job.model_labels.model_used && job.model_labels.draft_model && <Badge>{job.model_labels.draft_model}</Badge>}
            <span>{job.page_count} page{job.page_count === 1 ? "" : "s"}</span>
            <ConfidenceSummary counts={job.counts} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {view === "progress" && job.draft_ready && (
            <Button onClick={() => setView("review")}>
              <Eye className="h-4 w-4" aria-hidden /> {running ? "Open quick draft now" : "Review"}
            </Button>
          )}
          {view === "review" && running && (
            <Button variant="outline" onClick={() => setView("progress")}>
              Show progress
            </Button>
          )}
          {canDownload && (
            <>
              <a href={downloadUrl(job.id, "docx")} className={buttonClasses("outline")}>
                <Download className="h-4 w-4" aria-hidden /> Word
              </a>
              <a href={downloadUrl(job.id, "txt")} className={buttonClasses("ghost")}>
                <FileType2 className="h-4 w-4" aria-hidden /> Text
              </a>
            </>
          )}
        </div>
      </div>

      {job.status === "failed" && (
        <p className="rounded-lg bg-bad-soft px-4 py-3 text-sm text-bad">Something went wrong: {job.error}</p>
      )}

      {job.notes.length > 0 && (
        <div className="flex gap-3 rounded-xl border border-border bg-muted/50 px-4 py-3 text-sm">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
          <ul className="space-y-0.5 text-muted-foreground">
            {job.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      )}

      {view === "progress" ? (
        <>
          <Card>
            <CardContent className="space-y-5 p-5 sm:p-6">
              <StageStepper job={job} />
              <div className="space-y-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium">{job.message || (job.status === "queued" ? "Waiting to start…" : "Working…")}</span>
                  <span className="text-muted-foreground">{running ? formatEta(job.eta_seconds) : ""}</span>
                </div>
                <Progress value={job.status === "done" ? 1 : job.stage_progress} indeterminate={job.status === "queued"} />
              </div>
              <p className="text-xs text-muted-foreground">
                You can close this page. A notification appears when the translation is ready.
              </p>
            </CardContent>
          </Card>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
            <Card>
              <CardContent className="space-y-4 p-5">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="font-semibold">Live preview</h2>
                  {pager}
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  {pageImage}
                  <div className="max-h-[70vh] space-y-2.5 overflow-y-auto pr-1">
                    {segments.length === 0 && (
                      <p className="text-sm text-muted-foreground">Sentences appear here as the page is read.</p>
                    )}
                    {segments.map((s) => (
                      <SegmentCard
                        key={s.id}
                        job={job}
                        segment={s}
                        compact
                        selected={false}
                        editing={false}
                        onSelect={() => {}}
                        onEdit={() => {}}
                        onCancel={() => {}}
                        onSave={() => {}}
                        onApprove={() => {}}
                      />
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
            <WhileYouWait />
          </div>
        </>
      ) : (
        <>
          {running && (
            <div className="space-y-1.5 rounded-xl border border-border bg-card px-4 py-3">
              <div className="flex justify-between text-sm">
                <span>{job.message} · sentences update as they finish</span>
                <span className="text-muted-foreground">{formatEta(job.eta_seconds)}</span>
              </div>
              <Progress value={job.stage_progress} />
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            {pager}
            <div className="flex items-center gap-2">
              {needsReview > 0 && <span className="text-sm text-muted-foreground">{needsReview} to check</span>}
              <Button variant={onlyReview ? "primary" : "outline"} size="sm" onClick={() => setOnlyReview(!onlyReview)}>
                <Filter className="h-3.5 w-3.5" aria-hidden /> Needs review only
              </Button>
            </div>
          </div>

          {pageInfo?.note && (
            <div className="flex items-center gap-2 rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">
              <ScanLine className="h-4 w-4 shrink-0" aria-hidden /> {pageInfo.note}
            </div>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            <div className="lg:sticky lg:top-20 lg:self-start">{pageImage}</div>
            <div className="space-y-2.5">
              {visible.length === 0 && (
                <Card className="px-5 py-10 text-center text-sm text-muted-foreground">
                  {onlyReview ? "Nothing to check on this page." : "No text on this page."}
                </Card>
              )}
              {visible.map((s) => (
                <SegmentCard
                  key={s.id}
                  job={job}
                  segment={s}
                  selected={selected === s.id}
                  editing={editing === s.id}
                  onSelect={() => setSelected(s.id)}
                  onEdit={() => (setSelected(s.id), setEditing(s.id))}
                  onCancel={() => setEditing(null)}
                  onSave={(text) => void save(s, text)}
                  onApprove={() => void approve(s)}
                />
              ))}
              <p className={cn("pt-2 text-center text-xs text-muted-foreground", !visible.length && "hidden")}>
                ↑ ↓ to move · E to edit · Enter to approve
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
