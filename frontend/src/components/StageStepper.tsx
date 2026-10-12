import { Check, Minus, X } from "lucide-react";
import type { Job } from "@/lib/api";
import { stageSteps, type StepState } from "@/lib/stages";
import { cn } from "@/lib/utils";

const STATE_TEXT: Record<StepState, string> = {
  done: "finished",
  active: "in progress",
  todo: "not started",
  skipped: "skipped",
  failed: "stopped with an error",
};

export function StageStepper({ job }: { job: Job }) {
  const steps = stageSteps(job);

  return (
    <ol className="grid grid-cols-5 gap-2" aria-label="Translation progress">
      {steps.map((step, i) => {
        const { state } = step;
        const filled = state === "done";
        return (
          <li
            key={i}
            className="flex flex-col gap-2"
            aria-current={state === "active" ? "step" : undefined}
            title={step.detail}
          >
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold transition-colors",
                  filled && "border-primary bg-primary text-primary-foreground",
                  state === "active" && "border-primary bg-card text-primary",
                  state === "todo" && "border-border bg-card text-muted-foreground",
                  state === "skipped" && "border-dashed border-muted-foreground/60 bg-card text-muted-foreground",
                  state === "failed" && "border-bad bg-bad-soft text-bad",
                )}
              >
                {state === "done" ? (
                  <Check className="h-4 w-4" aria-hidden />
                ) : state === "skipped" ? (
                  <Minus className="h-4 w-4" aria-hidden />
                ) : state === "failed" ? (
                  <X className="h-4 w-4" aria-hidden />
                ) : (
                  i + 1
                )}
              </span>
              {i < steps.length - 1 && (
                <span
                  className={cn("h-0.5 flex-1 rounded-full", state === "done" || state === "skipped" ? "bg-primary" : "bg-border")}
                  aria-hidden
                />
              )}
            </div>
            <span
              aria-hidden
              className={cn(
                "hidden text-xs leading-snug sm:block",
                state === "active" ? "font-semibold text-foreground" : "text-muted-foreground",
                state === "skipped" && "italic",
                state === "failed" && "font-semibold text-bad",
              )}
            >
              {step.label}
            </span>
            <span className="sr-only">
              {step.label}: {STATE_TEXT[state]}. {step.detail ?? ""}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
