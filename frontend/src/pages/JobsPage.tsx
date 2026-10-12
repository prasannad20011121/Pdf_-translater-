import { Download, FileText, Inbox, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ConfidenceSummary } from "@/components/ConfidenceBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { api, downloadUrl, type Job } from "@/lib/api";
import { useJobs } from "@/lib/jobs-context";
import { isLive } from "@/lib/review";
import { formatDate } from "@/lib/time";
import { asSentence } from "@/lib/utils";

type Busy = { id: string; action: "delete" | "retry" };

export default function JobsPage() {
  // The list comes from the app-wide watcher, which refreshes it every few seconds while
  // something is being translated (and announces the milestones from any page).
  const { jobs, error, refresh } = useJobs();
  const [busy, setBusy] = useState<Busy | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  // Hidden at once after a delete, without waiting for the next refresh.
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  useEffect(() => {
    void refresh(); // up to date when the page opens
  }, [refresh]);

  const list = jobs?.filter((j) => !removed.has(j.id)) ?? null;

  const remove = async (job: Job) => {
    const live = isLive(job);
    const question = live
      ? `Stop and delete "${job.filename}"? The translation stops and its files are removed.`
      : `Delete "${job.filename}" and its translation?`;
    if (!window.confirm(question)) return;
    setBusy({ id: job.id, action: "delete" });
    setMessage(null);
    try {
      const r = await api.deleteJob(job.id);
      setRemoved((prev) => new Set(prev).add(job.id));
      setMessage({
        kind: "ok",
        text: r.status === "cancelling" ? `Stopping "${job.filename}". It is removed in a moment.` : `Deleted "${job.filename}".`,
      });
    } catch (e) {
      setMessage({ kind: "error", text: `Could not delete "${job.filename}". ${asSentence((e as Error).message)}` });
    } finally {
      setBusy(null);
      void refresh();
    }
  };

  const retry = async (job: Job) => {
    setBusy({ id: job.id, action: "retry" });
    setMessage(null);
    try {
      await api.retryJob(job.id);
      setMessage({ kind: "ok", text: `"${job.filename}" is queued again. It continues from where it stopped.` });
    } catch (e) {
      setMessage({ kind: "error", text: `Could not start "${job.filename}" again. ${asSentence((e as Error).message)}` });
    } finally {
      setBusy(null);
      void refresh();
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
          <p className="text-sm text-muted-foreground">Translations on this laptop. Old ones are removed automatically.</p>
        </div>
        <Link to="/" className={buttonClasses()}>
          New translation
        </Link>
      </div>

      {error && (
        <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">
          {list ? "Can't refresh the list right now. " : ""}
          {error}
        </p>
      )}
      {message && (
        <p
          className={`rounded-lg px-3 py-2 text-sm ${message.kind === "ok" ? "bg-good-soft text-good" : "bg-bad-soft text-bad"}`}
          role={message.kind === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}
      {!list && !error && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> Loading…
        </div>
      )}
      {list?.length === 0 && (
        <Card className="flex flex-col items-center gap-3 px-6 py-14 text-center">
          <Inbox className="h-10 w-10 text-muted-foreground" aria-hidden />
          <p className="font-medium">No documents yet</p>
          <Link to="/" className="text-sm font-medium text-primary hover:underline">
            Translate your first PDF
          </Link>
        </Card>
      )}

      {list && list.length > 0 && (
        <Card className="overflow-hidden">
          <ul className="divide-y divide-border">
            {list.map((j) => {
              const live = isLive(j);
              const rowBusy = busy?.id === j.id;
              return (
                <li key={j.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
                  <Link to={`/jobs/${j.id}`} className="flex min-w-0 flex-1 items-center gap-3">
                    <div className="rounded-lg bg-accent p-2 text-accent-foreground">
                      <FileText className="h-4 w-4" aria-hidden />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium hover:underline">{j.filename}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatDate(j.created_at)} · {j.page_count} page{j.page_count === 1 ? "" : "s"}
                        {j.model_labels.model_used ? ` · ${j.model_labels.model_used}` : ""}
                      </p>
                      {live && (
                        <div className="mt-2 max-w-sm space-y-1">
                          <Progress value={j.stage_progress} indeterminate={j.status === "queued"} />
                          <p className="text-xs text-muted-foreground">{j.message || "Waiting to start"}</p>
                        </div>
                      )}
                      {j.status === "failed" && (
                        <p className="mt-1 line-clamp-2 break-words text-xs text-bad" title={j.error ?? undefined}>
                          Stopped: {j.error || "an error occurred"}
                        </p>
                      )}
                    </div>
                  </Link>
                  <div className="flex items-center gap-2 sm:ml-auto">
                    <ConfidenceSummary counts={j.counts} />
                    <StatusBadge job={j} />
                    {j.status === "failed" && (
                      <Button variant="outline" size="sm" onClick={() => void retry(j)} disabled={busy !== null}>
                        {rowBusy && busy?.action === "retry" ? <Spinner /> : <RotateCcw className="h-3.5 w-3.5" aria-hidden />}
                        Try again
                      </Button>
                    )}
                    {(j.draft_ready || j.status === "done") && (
                      <a
                        href={downloadUrl(j.id, "docx")}
                        className={buttonClasses("ghost", "icon")}
                        title="Download Word file"
                        aria-label={`Download ${j.filename} as Word`}
                      >
                        <Download className="h-4 w-4" />
                      </a>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => void remove(j)}
                      disabled={busy !== null}
                      title={live ? "Stop and delete" : "Delete"}
                      aria-label={live ? `Stop and delete ${j.filename}` : `Delete ${j.filename}`}
                    >
                      {rowBusy && busy?.action === "delete" ? <Spinner /> : <Trash2 className="h-4 w-4" />}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}
