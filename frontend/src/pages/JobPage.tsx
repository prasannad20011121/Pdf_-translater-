import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  FileType2,
  Filter,
  Info,
  RotateCcw,
  ScanLine,
  Trash2,
  WifiOff,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ConfidenceSummary } from "@/components/ConfidenceBadge";
import { NotificationHint } from "@/components/NotificationHint";
import { SegmentCard } from "@/components/SegmentCard";
import { StageStepper } from "@/components/StageStepper";
import { StatusBadge } from "@/components/StatusBadge";
import { WhileYouWait } from "@/components/WhileYouWait";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { api, downloadUrl, isNotFound, pageImageUrl, type Job, type Segment } from "@/lib/api";
import { useDocumentVisible } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs-context";
import { reviewKeyAction } from "@/lib/keys";
import { reconnectDelay } from "@/lib/live";
import { describeSummary, isLive, pageSummary, visibleSegments } from "@/lib/review";
import { asSentence, cn, formatEta } from "@/lib/utils";

type View = "progress" | "review";

const DISCARD = "Discard the correction you are typing?";

function useJob(id: string) {
  const [job, setJob] = useState<Job | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null); // only shown before the first load
  const [gone, setGone] = useState(false); // deleted (404)
  const [offline, setOffline] = useState<string | null>(null); // a refresh failed after the first load

  const reload = useCallback(async (): Promise<Job | null> => {
    try {
      const j = await api.job(id);
      setJob(j);
      setLoadError(null);
      setOffline(null);
      return j;
    } catch (e) {
      if (isNotFound(e)) {
        setGone(true);
      } else {
        setLoadError((e as Error).message);
        setOffline((e as Error).message);
      }
      return null;
    }
  }, [id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Live updates while the job runs (Server-Sent Events). The page list is reloaded only
  // when another page has been read, or when the job finishes. A dropped connection (the
  // app restarted, the laptop slept) reconnects with a growing pause. A background tab
  // keeps no connection open; it catches up when shown again.
  const live = job ? isLive(job) : false;
  const visible = useDocumentVisible();
  const [attempt, setAttempt] = useState(0);
  const failures = useRef(0);
  const pagesSeen = useRef(-1);
  useEffect(() => {
    if (!live || !visible || gone) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const es = new EventSource(`/api/jobs/${id}/events`);
    es.onmessage = (ev) => {
      failures.current = 0;
      setOffline(null);
      let snap: Job;
      try {
        snap = JSON.parse(ev.data) as Job;
      } catch {
        return;
      }
      setJob((prev) => ({ ...snap, pages: prev?.pages }));
      const finished = snap.status === "done" || snap.status === "failed";
      if (snap.pages_done !== pagesSeen.current || finished) {
        pagesSeen.current = snap.pages_done;
        void reload();
      }
      if (finished) {
        stopped = true;
        es.close();
      }
    };
    es.onerror = () => {
      if (stopped) return;
      stopped = true;
      es.close();
      failures.current += 1;
      void reload(); // is the service back, and does the job still exist?
      timer = setTimeout(() => setAttempt((n) => n + 1), reconnectDelay(failures.current));
    };
    return () => {
      stopped = true;
      es.close();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [id, live, visible, gone, attempt, reload]);

  return { job, setJob, loadError, gone, offline, reload };
}

export default function JobPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { refresh: refreshJobs } = useJobs();
  const { job, setJob, loadError, gone, offline, reload } = useJob(id);
  const [view, setView] = useState<View | null>(null);
  const [page, setPage] = useState(1);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loadedPage, setLoadedPage] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const dirty = useRef(false); // the open editor holds unsaved typing
  const [onlyReview, setOnlyReview] = useState(false);
  const [action, setAction] = useState<"retry" | "delete" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // Sentences corrected while the "needs review" filter is on stay visible (marked
  // "Corrected by you") until the page or filter changes, instead of vanishing on save.
  const [justCorrected, setJustCorrected] = useState<Set<number>>(new Set());
  useEffect(() => setJustCorrected(new Set()), [page, onlyReview]);

  // Pick the starting view once the job is known.
  useEffect(() => {
    if (job && view === null) setView(job.status === "done" ? "review" : "progress");
  }, [job, view]);

  // Only the newest request may fill the list, so a slow answer for another page (or an
  // older answer for this one) never shows up under the wrong page number.
  const request = useRef(0);
  const loadSegments = useCallback(async () => {
    const mine = ++request.current;
    try {
      const list = await api.segments(id, page);
      if (mine !== request.current) return;
      setSegments(list);
      setLoadedPage(page);
    } catch {
      /* page not extracted yet, or the service is restarting */
    }
  }, [id, page]);

  // Load at once when the page changes; while the job runs, refresh the page's sentences
  // whenever the job reports progress (at most about once a second).
  const latestLoad = useRef(loadSegments);
  latestLoad.current = loadSegments;
  const lastLoad = useRef(0);
  useEffect(() => {
    lastLoad.current = Date.now();
    void loadSegments();
  }, [loadSegments]);
  const progressKey = job ? `${job.updated_at}|${job.status}` : null;
  const firstProgress = useRef(true);
  useEffect(() => {
    if (progressKey === null) return;
    if (firstProgress.current) {
      firstProgress.current = false; // the load above already has this state
      return;
    }
    const wait = Math.max(0, 1200 - (Date.now() - lastLoad.current));
    const t = setTimeout(() => {
      lastLoad.current = Date.now();
      void latestLoad.current();
    }, wait);
    return () => clearTimeout(t);
  }, [progressKey]);

  const live = job ? isLive(job) : false;
  const pageReady = loadedPage === page;
  const shown = useMemo(() => (pageReady ? segments : []), [pageReady, segments]);
  const visible = useMemo(
    () => visibleSegments(shown, { onlyReview, live, editing, justCorrected }),
    [shown, onlyReview, justCorrected, editing, live],
  );
  const summary = pageSummary(shown, live);

  const discardTyping = () => editing === null || !dirty.current || window.confirm(DISCARD);

  const goToPage = (n: number) => {
    if (n === page || !discardTyping()) return;
    setEditing(null);
    setSelected(null);
    setSaveError(null);
    dirty.current = false;
    setPage(n);
  };

  const openEditor = (segmentId: number) => {
    if (editing === segmentId) return;
    if (!discardTyping()) return;
    setSelected(segmentId);
    setEditing(segmentId);
    setSaveError(null);
    dirty.current = false;
  };

  const closeEditor = () => {
    setEditing(null);
    setSaveError(null);
    dirty.current = false;
  };

  const replace = (s: Segment) => setSegments((all) => all.map((x) => (x.id === s.id ? s : x)));
  const save = async (seg: Segment, text: string) => {
    if (saving) return;
    const clean = text.trim();
    if (!clean) {
      setSaveError("The translation can't be empty.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      replace(await api.correctSegment(seg.id, clean));
    } catch (e) {
      // Keep the editor open with the text, so nothing typed is lost.
      setSaveError(`Not saved. ${asSentence((e as Error).message)} Your text is still here, so you can try again.`);
      setSaving(false);
      return;
    }
    setSaving(false);
    setJustCorrected((prev) => new Set(prev).add(seg.id));
    closeEditor();
    void loadSegments(); // identical sentences on the page pick up the correction too
    void reload(); // the document summary counts change
  };

  // Keyboard: ↑/↓ move, E or Enter to correct the selected sentence. Keys meant for a
  // focused button, link or text box are left alone, and so are Ctrl/Alt shortcuts.
  useEffect(() => {
    if (view !== "review") return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target instanceof Element ? e.target : null;
      const act = reviewKeyAction(e, target, visible.map((s) => s.id), selected, editing);
      if (!act) return;
      e.preventDefault();
      if (act.type === "select") setSelected(act.id);
      else openEditor(act.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, visible, selected, editing]);

  if (gone) {
    return (
      <div className="space-y-4">
        <Link to="/jobs" className="text-sm text-primary hover:underline">← Documents</Link>
        <p className="rounded-lg bg-muted px-3 py-2 text-sm">This document no longer exists. It may have been deleted.</p>
      </div>
    );
  }
  if (!job && loadError) {
    return (
      <div className="space-y-4">
        <Link to="/jobs" className="text-sm text-primary hover:underline">← Documents</Link>
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">
          <span className="flex-1">{loadError}</span>
          <Button size="sm" variant="outline" onClick={() => void reload()}>
            Try again
          </Button>
        </div>
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

  const pageCount = Math.max(job.page_count, 1);
  const pageInfo = job.pages?.find((p) => p.page_no === page);
  const canDownload = job.draft_ready || job.status === "done";

  const retry = async () => {
    setAction("retry");
    setActionError(null);
    try {
      const fresh = await api.retryJob(job.id);
      setJob((prev) => ({ ...fresh, pages: prev?.pages }));
      setView("progress");
      void refreshJobs();
    } catch (e) {
      setActionError(`Could not start it again. ${asSentence((e as Error).message)}`);
      void reload();
    } finally {
      setAction(null);
    }
  };

  const remove = async () => {
    const question = live
      ? `Stop and delete "${job.filename}"? The translation stops and its files are removed.`
      : `Delete "${job.filename}" and its translation?`;
    if (!window.confirm(question)) return;
    setAction("delete");
    setActionError(null);
    try {
      await api.deleteJob(job.id);
      void refreshJobs();
      navigate("/jobs");
    } catch (e) {
      setActionError(`Could not delete it. ${asSentence((e as Error).message)}`);
      setAction(null);
    }
  };

  const pager = (
    <div className="flex items-center gap-1">
      <Button variant="ghost" size="icon" onClick={() => goToPage(Math.max(1, page - 1))} disabled={page <= 1} aria-label="Previous page">
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <span className="min-w-[6.5rem] text-center text-sm tabular-nums">
        Page {page} of {pageCount}
      </span>
      <Button variant="ghost" size="icon" onClick={() => goToPage(Math.min(pageCount, page + 1))} disabled={page >= pageCount} aria-label="Next page">
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
          {live ? (
            <>
              <Spinner className="mr-2" /> Reading page {page}…
            </>
          ) : (
            "This page was not read."
          )}
        </div>
      )}
    </Card>
  );

  const loadingSentences = (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Spinner /> Loading sentences…
    </p>
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
              <Eye className="h-4 w-4" aria-hidden /> {live ? "Open quick draft now" : "Review"}
            </Button>
          )}
          {view === "review" && live && (
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
          <Button
            variant="ghost"
            onClick={() => void remove()}
            disabled={action !== null}
            title={live ? "Stop this translation and delete it" : "Delete this document and its translation"}
          >
            {action === "delete" ? <Spinner /> : <Trash2 className="h-4 w-4" aria-hidden />}
            {live ? "Stop and delete" : "Delete"}
          </Button>
        </div>
      </div>

      {offline && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-warn-soft px-4 py-2.5 text-sm text-warn" role="status">
          <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
          <span className="flex-1">
            Can't update this page right now. {asSentence(offline)}
            {live ? " Trying again…" : ""}
          </span>
          <Button size="sm" variant="outline" onClick={() => void reload()}>
            Try again
          </Button>
        </div>
      )}

      {job.status === "failed" && (
        <div className="flex flex-col gap-3 rounded-xl border border-bad/30 bg-bad-soft px-4 py-3 text-sm text-bad sm:flex-row sm:items-center" role="alert">
          <XCircle className="hidden h-5 w-5 shrink-0 sm:block" aria-hidden />
          <div className="min-w-0 flex-1 space-y-0.5">
            <p className="font-semibold">This translation stopped because of an error.</p>
            <p className="break-words">{job.error || "No details were recorded."}</p>
            <p className="text-xs opacity-90">Try again continues from where it stopped; finished work is kept.</p>
          </div>
          <Button onClick={() => void retry()} disabled={action !== null} className="shrink-0">
            {action === "retry" ? <Spinner /> : <RotateCcw className="h-4 w-4" aria-hidden />} Try again
          </Button>
        </div>
      )}
      {actionError && <p className="rounded-lg bg-bad-soft px-4 py-2.5 text-sm text-bad" role="alert">{actionError}</p>}

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
                  <span className="font-medium">
                    {job.message || (job.status === "queued" ? "Waiting to start…" : live ? "Working…" : "")}
                  </span>
                  <span className="text-muted-foreground">{live ? formatEta(job.eta_seconds) : ""}</span>
                </div>
                <Progress value={job.status === "done" ? 1 : job.stage_progress} indeterminate={job.status === "queued"} />
              </div>
              {live && <NotificationHint />}
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
                    {!pageReady
                      ? loadingSentences
                      : shown.length === 0 && (
                          <p className="text-sm text-muted-foreground">
                            {live ? "Sentences appear here as the page is read." : "No text on this page."}
                          </p>
                        )}
                    {shown.map((s) => (
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
          {live && (
            <div className="space-y-1.5 rounded-xl border border-border bg-card px-4 py-3">
              <div className="flex justify-between gap-2 text-sm">
                <span>{job.message || "Working…"} · sentences update as they finish</span>
                <span className="shrink-0 text-muted-foreground">{formatEta(job.eta_seconds)}</span>
              </div>
              <Progress value={job.stage_progress} indeterminate={job.status === "queued"} />
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            {pager}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">{pageReady ? describeSummary(summary) : ""}</span>
              <Button
                variant={onlyReview ? "primary" : "outline"}
                size="sm"
                onClick={() => setOnlyReview(!onlyReview)}
                aria-pressed={onlyReview}
              >
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
              {!pageReady && loadingSentences}
              {pageReady && visible.length === 0 && (
                <Card className="px-5 py-10 text-center text-sm text-muted-foreground">
                  {onlyReview
                    ? summary.pending
                      ? "Nothing to check yet. Sentences still being translated appear when they finish."
                      : "Nothing to check on this page."
                    : live
                      ? "Sentences appear here as the page is read."
                      : "No text on this page."}
                </Card>
              )}
              {visible.map((s) => (
                <SegmentCard
                  key={s.id}
                  job={job}
                  segment={s}
                  selected={selected === s.id}
                  editing={editing === s.id}
                  saving={editing === s.id && saving}
                  saveError={editing === s.id ? saveError : null}
                  onSelect={() => setSelected(s.id)}
                  onEdit={() => openEditor(s.id)}
                  onCancel={closeEditor}
                  onSave={(text) => void save(s, text)}
                  onDirty={(d) => {
                    if (editing === s.id) dirty.current = d;
                  }}
                />
              ))}
              <p className={cn("pt-2 text-center text-xs text-muted-foreground", !visible.length && "hidden")}>
                ↑ ↓ to move · E or Enter to correct a sentence
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
