import { CheckCircle2, FileText, X, XCircle } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useJobs, type Toast } from "@/lib/jobs-context";
import { cn } from "@/lib/utils";

const ICON = { draft: FileText, done: CheckCircle2, failed: XCircle } as const;
const TONE = { draft: "text-primary", done: "text-good", failed: "text-bad" } as const;

function ToastCard({ toast, onClose }: { toast: Toast; onClose: () => void }) {
  const close = useRef(onClose);
  close.current = onClose;
  // Good news fades away after a while, but only once it could have been seen.
  // A failure stays until it is dismissed.
  useEffect(() => {
    if (toast.kind === "failed") return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      if (document.visibilityState === "visible" && timer === undefined) {
        timer = setTimeout(() => close.current(), 15000);
      }
    };
    arm();
    document.addEventListener("visibilitychange", arm);
    return () => {
      document.removeEventListener("visibilitychange", arm);
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [toast.kind]);

  const Icon = ICON[toast.kind];
  return (
    <div className="pointer-events-auto flex w-full items-start gap-3 rounded-xl border border-border bg-card p-4 shadow-lg animate-fade-in">
      <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", TONE[toast.kind])} aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-semibold">{toast.title}</p>
        <p className="break-words text-sm text-muted-foreground">{toast.body}</p>
        <Link to={`/jobs/${toast.jobId}`} onClick={onClose} className="inline-block text-sm font-medium text-primary hover:underline">
          Open
        </Link>
      </div>
      <button
        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        onClick={onClose}
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

/** In-app messages for job milestones, shown when no desktop notification was shown. */
export function Toasts() {
  const { toasts, dismissToast } = useJobs();
  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
      role="status"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <ToastCard key={t.key} toast={t} onClose={() => dismissToast(t.key)} />
      ))}
    </div>
  );
}
