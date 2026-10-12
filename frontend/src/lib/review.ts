import type { Confidence, Job, Segment } from "./api";

/**
 * What a sentence needs from the reviewer:
 * - pending: still being translated (the job is running and there is no English yet)
 * - needs-human: no usable machine translation, or the checks found a serious problem
 * - check: translated, but the checks raised a doubt
 * - good: translated and the checks passed (or there was nothing to translate)
 * - corrected: a person already corrected it
 */
export type SentenceState = "pending" | "needs-human" | "check" | "good" | "corrected";

export const isLive = (job: Pick<Job, "status">): boolean => job.status === "running" || job.status === "queued";

type SegmentFields = Pick<Segment, "text" | "engine" | "confidence" | "edited" | "needs_translation">;

/** True when the sentence has no machine translation at all (only the Hindi). */
export const isUntranslated = (s: SegmentFields): boolean =>
  !s.edited && (s.engine === "untranslated" || (s.needs_translation && !s.text));

export function sentenceState(s: SegmentFields, live: boolean): SentenceState {
  if (s.edited) return "corrected";
  if (s.engine === "untranslated") return "needs-human";
  if (!s.text) {
    if (!s.needs_translation) return "good";
    return live ? "pending" : "needs-human";
  }
  if (s.confidence === "red") return "needs-human";
  if (s.confidence === "amber") return "check";
  if (s.confidence === "green") return "good";
  return s.needs_translation ? "check" : "good";
}

/** Sentences shown by the "Needs review only" filter. Ones still translating are not included. */
export const needsReview = (s: SegmentFields, live: boolean): boolean => {
  const state = sentenceState(s, live);
  return state === "check" || state === "needs-human";
};

/** The badge level to show for a sentence (null: no badge). */
export function badgeLevel(s: SegmentFields, live: boolean): Confidence | null {
  switch (sentenceState(s, live)) {
    case "needs-human":
      return "red";
    case "check":
      return "amber";
    case "good":
      return s.confidence ?? null;
    default:
      return null;
  }
}

/**
 * The sentences listed on the review screen. With "Needs review only", the sentence being
 * edited and ones just corrected stay listed, so a live update can never pull an open
 * editor (and the typing in it) off the screen.
 */
export function visibleSegments<S extends SegmentFields & { id: number }>(
  segments: S[],
  opts: { onlyReview: boolean; live: boolean; editing: number | null; justCorrected: ReadonlySet<number> },
): S[] {
  if (!opts.onlyReview) return segments;
  return segments.filter((s) => needsReview(s, opts.live) || opts.justCorrected.has(s.id) || s.id === opts.editing);
}

export interface PageSummary {
  check: number;
  human: number;
  pending: number;
}

export function pageSummary(segments: SegmentFields[], live: boolean): PageSummary {
  const out: PageSummary = { check: 0, human: 0, pending: 0 };
  for (const s of segments) {
    const state = sentenceState(s, live);
    if (state === "check") out.check += 1;
    else if (state === "needs-human") out.human += 1;
    else if (state === "pending") out.pending += 1;
  }
  return out;
}

/** "2 to check · 1 needs a human · 3 still translating", or "Nothing to check on this page". */
export function describeSummary(sum: PageSummary): string {
  const parts: string[] = [];
  if (sum.check) parts.push(`${sum.check} to check`);
  if (sum.human) parts.push(`${sum.human} need${sum.human === 1 ? "s" : ""} a human`);
  if (sum.pending) parts.push(`${sum.pending} still translating`);
  return parts.length ? parts.join(" · ") : "Nothing to check on this page";
}
