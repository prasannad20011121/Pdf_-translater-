import { Check } from "lucide-react";
import type { Job, Stage } from "@/lib/api";
import { cn } from "@/lib/utils";

const ORDER: Record<Stage, number> = { extract: 0, draft: 1, final: 2, check: 3, render: 3, done: 4 };

export function StageStepper({ job }: { job: Job }) {
  const finalLabel =
    job.choice === "fast"
      ? "Final (skipped: Fast)"
      : `Final · ${job.model_labels.model_used ?? job.model_labels.model_requested ?? "model"}`;
  const steps = ["Reading pages", "Quick draft", finalLabel, "Checking", "Ready"];
  const current = job.status === "done" ? 5 : ORDER[job.stage] ?? 0;

  return (
    <ol className="grid grid-cols-5 gap-2" aria-label="Translation progress">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current && job.status !== "failed";
        const skipped = i === 2 && job.choice === "fast";
        return (
          <li key={label} className="flex flex-col gap-2" aria-current={active ? "step" : undefined}>
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold transition-colors",
                  done && "border-primary bg-primary text-primary-foreground",
                  active && "border-primary bg-card text-primary",
                  !done && !active && "border-border bg-card text-muted-foreground",
                  skipped && "border-dashed",
                )}
              >
                {done ? <Check className="h-4 w-4" aria-hidden /> : i + 1}
              </span>
              {i < steps.length - 1 && (
                <span className={cn("h-0.5 flex-1 rounded-full", done ? "bg-primary" : "bg-border")} aria-hidden />
              )}
            </div>
            <span
              className={cn(
                "hidden text-xs leading-snug sm:block",
                active ? "font-semibold text-foreground" : "text-muted-foreground",
              )}
            >
              {label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
