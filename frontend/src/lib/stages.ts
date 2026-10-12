import type { Job, Stage } from "./api";

export type StepState = "done" | "active" | "todo" | "skipped" | "failed";

export interface Step {
  label: string;
  state: StepState;
  /** A longer explanation (tooltip and screen readers). */
  detail?: string;
}

const ORDER: Record<Stage, number> = { extract: 0, draft: 1, final: 2, check: 3, render: 3, done: 4 };

type JobFields = Pick<
  Job,
  "status" | "stage" | "choice" | "model_used" | "model_requested" | "draft_model" | "draft_ready" | "model_labels"
>;

const position = (job: JobFields): number => (job.status === "done" ? 5 : ORDER[job.stage] ?? 0);

/**
 * The final model never ran: the quick draft is the result. Fast skips it on purpose;
 * otherwise this is inferred from model_used staying empty once the stage has passed.
 */
export function finalSkipped(job: JobFields): boolean {
  if (job.choice === "fast") return true;
  return !job.model_used && (position(job) > 2 || job.status === "done");
}

/** The quick draft never ran (IndicTrans2 missing or not enough memory). */
export function draftSkipped(job: JobFields): boolean {
  return !job.draft_model && !job.draft_ready && (position(job) > 1 || job.status === "done");
}

export function stageSteps(job: JobFields): Step[] {
  const current = position(job);
  const failed = job.status === "failed";
  const labels = job.model_labels ?? {};
  const requested = labels.model_requested ?? job.model_requested ?? "the final model";

  let finalLabel: string;
  let finalDetail: string;
  if (job.choice === "fast") {
    finalLabel = "Final (skipped: Fast)";
    finalDetail = "Fast was chosen, so the quick draft is the final translation.";
  } else if (finalSkipped(job)) {
    finalLabel = "Final (skipped)";
    finalDetail = `${requested} did not run, so the quick draft is the final translation. The notes explain why.`;
  } else if (job.model_used) {
    finalLabel = `Final · ${labels.model_used ?? job.model_used}`;
    finalDetail = `Final translation with ${labels.model_used ?? job.model_used}.`;
  } else {
    finalLabel = `Final · ${requested}`;
    finalDetail = `Planned: final translation with ${requested}.`;
  }

  const draftOff = draftSkipped(job);
  const steps: Omit<Step, "state">[] = [
    { label: "Reading pages" },
    draftOff
      ? { label: "Quick draft (skipped)", detail: "The quick draft did not run. The notes explain why." }
      : { label: "Quick draft" },
    { label: finalLabel, detail: finalDetail },
    { label: "Checking" },
    { label: "Ready" },
  ];
  const skippedAt = new Set<number>();
  if (draftOff) skippedAt.add(1);
  if (finalSkipped(job)) skippedAt.add(2);

  return steps.map((step, i): Step => {
    let state: StepState;
    if (i === current && failed) state = "failed";
    else if (skippedAt.has(i) && (i < current || job.choice === "fast")) state = "skipped";
    else if (i < current) state = "done";
    else if (i === current && !failed) state = "active";
    else state = "todo";
    return { ...step, state };
  });
}
