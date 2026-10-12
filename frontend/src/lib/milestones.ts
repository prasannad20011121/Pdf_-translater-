import type { Job } from "./api";
import { serverTime } from "./time.ts";

/** What the watcher last saw of a job. */
export interface Seen {
  draft: boolean;
  status: Job["status"];
}
export type SeenMap = Record<string, Seen>;

export type MilestoneKind = "draft" | "done" | "failed";

export interface Milestone {
  jobId: string;
  kind: MilestoneKind;
  title: string;
  body: string;
}

type JobFields = Pick<Job, "id" | "filename" | "status" | "draft_ready" | "choice" | "created_at" | "error" | "counts">;

/** A job created this long before the watcher started still counts as new. */
export const NEW_JOB_SLACK_MS = 2 * 60 * 1000;

function milestone(job: JobFields, kind: MilestoneKind): Milestone {
  if (kind === "draft") {
    return { jobId: job.id, kind, title: "Quick draft ready", body: `${job.filename}: you can start reading.` };
  }
  if (kind === "failed") {
    const why = job.error ? `: ${job.error}` : "";
    return { jobId: job.id, kind, title: "Translation stopped", body: `${job.filename}${why}` };
  }
  const toCheck = (job.counts?.amber ?? 0) + (job.counts?.red ?? 0);
  const extra = toCheck ? ` · ${toCheck} sentence${toCheck === 1 ? "" : "s"} to check` : "";
  return { jobId: job.id, kind, title: "Translation ready", body: `${job.filename}${extra}` };
}

/**
 * Compare a fresh job list with what was seen before and return the milestones reached
 * in between. `prev` is null on the first look: everything is then recorded silently, so
 * jobs that finished long ago never notify. A job seen for the first time later on (or
 * created around the time the watcher started) starts from "queued, no draft", so a small
 * document that finished between two polls still notifies.
 */
export function diffJobs(
  prev: SeenMap | null,
  jobs: JobFields[],
  opts: { startedAt: number },
): { next: SeenMap; events: Milestone[] } {
  const next: SeenMap = {};
  const events: Milestone[] = [];
  for (const job of jobs) {
    const now: Seen = { draft: !!job.draft_ready, status: job.status };
    next[job.id] = now;
    let before = prev?.[job.id];
    if (!before) {
      const created = serverTime(job.created_at);
      const fresh = Number.isFinite(created) && created >= opts.startedAt - NEW_JOB_SLACK_MS;
      if (prev !== null && fresh) before = { draft: false, status: "queued" };
      else continue; // first look, or an old job: nothing to announce
    }
    if (now.status === "done" && before.status !== "done") {
      events.push(milestone(job, "done"));
    } else if (now.status === "failed" && before.status !== "failed") {
      events.push(milestone(job, "failed"));
    } else if (
      now.draft &&
      !before.draft &&
      job.choice !== "fast" && // Fast has no separate final: "Translation ready" follows within seconds
      (now.status === "running" || now.status === "queued")
    ) {
      events.push(milestone(job, "draft"));
    }
  }
  return { next, events };
}

/** Polling interval: often while something is being translated, rarely otherwise. */
export function pollInterval(jobs: Pick<Job, "status">[] | null): number {
  return jobs?.some((j) => j.status === "running" || j.status === "queued") ? 5000 : 30000;
}
