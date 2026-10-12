import { AlertCircle, ArrowRight, CheckCircle2, FileText, Gauge, Lock, Sparkles, Trophy, UploadCloud, Wand2, X } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ConfidenceSummary } from "@/components/ConfidenceBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { api, type ChoiceId, type Job } from "@/lib/api";
import { useJobs } from "@/lib/jobs-context";
import { useSettings } from "@/lib/settings-context";
import { formatDate } from "@/lib/time";
import { uploadAll, type FileUploadState } from "@/lib/upload";
import { askNotificationPermission, cn } from "@/lib/utils";

const CHOICE_ICONS: Record<ChoiceId, typeof Wand2> = { auto: Wand2, fast: Gauge, balanced: Sparkles, best: Trophy };

export default function UploadPage() {
  const { settings } = useSettings();
  const { jobs, refresh: refreshJobs } = useJobs();
  const navigate = useNavigate();
  const [files, setFiles] = useState<File[]>([]);
  const [fileState, setFileState] = useState<Map<File, FileUploadState>>(new Map());
  const [choice, setChoice] = useState<ChoiceId>("auto");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false); // blocks a second click before the button re-renders as disabled
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState<Job[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const recent = (jobs ?? []).slice(0, 5);

  useEffect(() => {
    if (settings) setChoice(settings.default_choice);
  }, [settings]);
  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const pdfs = Array.from(list).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length < list.length) setError("Only PDF files can be translated.");
    else setError(null);
    setFiles((prev) => [...prev, ...pdfs.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))]);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (!busyRef.current) addFiles(e.dataTransfer.files);
  };

  const selected = settings?.choices.find((c) => c.id === choice);

  const start = async () => {
    if (busyRef.current || !files.length) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setQueued([]);
    void askNotificationPermission(); // asked while the click still counts as the person's own action
    const result = await uploadAll(files, (f) => api.upload(f, choice), (f, state) => {
      setFileState((prev) => new Map(prev).set(f, state));
      // Off the list as soon as it is queued, so trying again never uploads it twice.
      if (state.state === "queued") setFiles((prev) => prev.filter((x) => x !== f));
    });
    busyRef.current = false;
    setBusy(false);
    void refreshJobs();
    if (result.queued.length && !result.failed.length) {
      navigate(result.queued.length === 1 ? `/jobs/${result.queued[0].job.id}` : "/jobs");
      return;
    }
    setQueued(result.queued.map((q) => q.job));
    const n = result.failed.length;
    setError(
      n === 1
        ? "1 file could not be uploaded. The reason is shown next to it."
        : `${n} files could not be uploaded. The reasons are shown next to them.`,
    );
  };

  const removeFile = (f: File) => {
    setFiles((prev) => prev.filter((x) => x !== f));
    setFileState((prev) => {
      const next = new Map(prev);
      next.delete(f);
      return next;
    });
  };

  return (
    <div className="mx-auto max-w-4xl animate-fade-in space-y-8">
      <section className="space-y-2 text-center">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Translate Hindi PDFs to English</h1>
        <p className="mx-auto max-w-2xl text-muted-foreground">
          Drop in letters, tenders or orders. You get an editable Word file and a side-by-side review.
        </p>
        <p className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Lock className="h-3.5 w-3.5" aria-hidden /> Runs on this laptop. Documents never leave it.
        </p>
      </section>

      <Card>
        <CardContent className="space-y-6 p-5 sm:p-6">
          <div
            role="button"
            tabIndex={0}
            aria-disabled={busy}
            onClick={() => !busy && input.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !busy) {
                e.preventDefault();
                input.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragging ? "border-primary bg-accent" : "border-border hover:border-primary/60 hover:bg-muted/50",
            )}
          >
            <div className="rounded-full bg-accent p-3 text-accent-foreground">
              <UploadCloud className="h-7 w-7" aria-hidden />
            </div>
            <div>
              <p className="font-medium">Drag PDFs here, or click to choose</p>
              <p className="text-sm text-muted-foreground">
                Up to {settings?.limits.max_mb ?? 50} MB and {settings?.limits.max_pages ?? 100} pages each
              </p>
            </div>
            <input
              ref={input}
              type="file"
              accept="application/pdf,.pdf"
              multiple
              className="hidden"
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          {files.length > 0 && (
            <ul className="space-y-2">
              {files.map((f) => {
                const st = fileState.get(f);
                const failed = st?.state === "failed";
                return (
                  <li
                    key={f.name + f.size}
                    className={cn(
                      "rounded-lg border px-3 py-2",
                      failed ? "border-bad/40 bg-bad-soft/40" : "border-border",
                    )}
                  >
                    <div className="flex items-center gap-3">
                      {st?.state === "uploading" ? (
                        <Spinner className="shrink-0 text-primary" />
                      ) : failed ? (
                        <AlertCircle className="h-4 w-4 shrink-0 text-bad" aria-hidden />
                      ) : st?.state === "queued" ? (
                        <CheckCircle2 className="h-4 w-4 shrink-0 text-good" aria-hidden />
                      ) : (
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                      )}
                      <span className="truncate text-sm font-medium">{f.name}</span>
                      <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                        {busy && st?.state === "uploading"
                          ? "Uploading…"
                          : busy && st?.state === "waiting"
                            ? "Waiting"
                            : `${(f.size / 1024 / 1024).toFixed(1)} MB`}
                      </span>
                      <button
                        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
                        onClick={() => removeFile(f)}
                        disabled={busy}
                        aria-label={`Remove ${f.name}`}
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                    {failed && (
                      <p className="mt-1 pl-7 text-sm text-bad">
                        Not uploaded: {st.message}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {queued.length > 0 && (
            <div className="rounded-lg bg-good-soft px-3 py-2 text-sm text-good" role="status">
              {queued.length === 1 ? "1 file is" : `${queued.length} files are`} being translated:{" "}
              {queued.map((j, i) => (
                <span key={j.id}>
                  {i > 0 && ", "}
                  <Link to={`/jobs/${j.id}`} className="font-medium underline-offset-2 hover:underline">
                    {j.filename}
                  </Link>
                </span>
              ))}
              .
            </div>
          )}

          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold">Model</legend>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {(settings?.choices ?? []).map((c) => {
                const Icon = CHOICE_ICONS[c.id];
                const active = c.id === choice;
                return (
                  <label
                    key={c.id}
                    className={cn(
                      "relative flex cursor-pointer flex-col gap-1.5 rounded-xl border p-3.5 transition-all",
                      active ? "border-primary bg-accent/60 ring-1 ring-primary" : "border-border hover:border-primary/50",
                      !c.available && "cursor-not-allowed opacity-55 hover:border-border",
                    )}
                    title={c.available ? c.hint : c.reason}
                  >
                    <input
                      type="radio"
                      name="choice"
                      value={c.id}
                      className="sr-only"
                      checked={active}
                      disabled={!c.available}
                      onChange={() => setChoice(c.id)}
                    />
                    <span className="flex items-center gap-2 text-sm font-semibold">
                      <Icon className={cn("h-4 w-4", active ? "text-primary" : "text-muted-foreground")} aria-hidden />
                      {c.label}
                    </span>
                    <span className="text-xs leading-snug text-muted-foreground">{c.available ? c.hint : c.reason}</span>
                    {c.available && c.reason && <span className="text-xs leading-snug text-warn">{c.reason}</span>}
                  </label>
                );
              })}
              {!settings && <div className="col-span-full flex items-center gap-2 text-sm text-muted-foreground"><Spinner /> Loading…</div>}
            </div>
          </fieldset>

          {error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad" role="alert">{error}</p>}

          <div className="flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muted-foreground">
              A quick draft appears within minutes; the final version follows. You can keep working meanwhile.
            </p>
            <Button size="lg" onClick={() => void start()} disabled={!files.length || busy || !selected?.available}>
              {busy ? <Spinner /> : <ArrowRight className="h-4 w-4" aria-hidden />}
              {busy ? "Uploading…" : `Translate ${files.length > 1 ? `${files.length} files` : ""}`.trim()}
            </Button>
          </div>
        </CardContent>
      </Card>

      {recent.length > 0 && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Recent documents</CardTitle>
              <CardDescription>Open one to review or download it</CardDescription>
            </div>
            <Link to="/jobs" className="text-sm font-medium text-primary hover:underline">
              View all
            </Link>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-border border-t border-border">
              {recent.map((j) => (
                <li key={j.id}>
                  <Link to={`/jobs/${j.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-muted/50">
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{j.filename}</span>
                      <span className="text-xs text-muted-foreground">{formatDate(j.created_at)}</span>
                    </span>
                    <span className="hidden sm:block">
                      <ConfidenceSummary counts={j.counts} />
                    </span>
                    <StatusBadge job={j} />
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
