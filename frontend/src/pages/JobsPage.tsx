import { Download, FileText, Inbox, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ConfidenceSummary } from "@/components/ConfidenceBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { api, downloadUrl, type Job } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.jobs().then(setJobs).catch((e) => setError((e as Error).message));
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    if (!jobs?.some((j) => j.status === "running" || j.status === "queued")) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [jobs, load]);

  const remove = async (job: Job) => {
    if (!confirm(`Delete "${job.filename}" and its translation?`)) return;
    await api.deleteJob(job.id);
    load();
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

      {error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>}
      {!jobs && !error && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> Loading…
        </div>
      )}
      {jobs?.length === 0 && (
        <Card className="flex flex-col items-center gap-3 px-6 py-14 text-center">
          <Inbox className="h-10 w-10 text-muted-foreground" aria-hidden />
          <p className="font-medium">No documents yet</p>
          <Link to="/" className="text-sm font-medium text-primary hover:underline">
            Translate your first PDF
          </Link>
        </Card>
      )}

      {jobs && jobs.length > 0 && (
        <Card className="overflow-hidden">
          <ul className="divide-y divide-border">
            {jobs.map((j) => (
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
                    {(j.status === "running" || j.status === "queued") && (
                      <div className="mt-2 max-w-sm space-y-1">
                        <Progress value={j.stage_progress} />
                        <p className="text-xs text-muted-foreground">{j.message || "Waiting to start"}</p>
                      </div>
                    )}
                  </div>
                </Link>
                <div className="flex items-center gap-2 sm:ml-auto">
                  <ConfidenceSummary counts={j.counts} />
                  <StatusBadge job={j} />
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
                  <Button variant="ghost" size="icon" onClick={() => remove(j)} aria-label={`Delete ${j.filename}`}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
