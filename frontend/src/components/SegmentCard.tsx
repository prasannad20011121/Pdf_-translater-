import { Pencil, RefreshCw, UserCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Job, Segment } from "@/lib/api";
import { badgeLevel, isLive, sentenceState } from "@/lib/review";
import { cn } from "@/lib/utils";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Button } from "./ui/button";
import { Spinner } from "./ui/spinner";

export function engineLabel(job: Job, engine: string | null): string {
  if (!engine) return "";
  if (engine === "memory") return "From translation memory";
  if (engine === "copy") return "Copied (no Hindi)";
  if (engine === "untranslated") return "Not translated";
  if (engine === job.model_used) return job.model_labels.model_used ?? engine;
  if (engine === job.draft_model) return `${job.model_labels.draft_model ?? engine} (quick draft)`;
  return engine;
}

const EDGE = { green: "border-l-good", amber: "border-l-warn", red: "border-l-bad" } as const;

/** The longest correction the server accepts. */
export const MAX_CORRECTION = 5000;

interface Props {
  job: Job;
  segment: Segment;
  selected: boolean;
  editing: boolean;
  compact?: boolean;
  saving?: boolean;
  saveError?: string | null;
  onSelect: () => void;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (text: string) => void;
  /** Told whether the editor holds unsaved typing. */
  onDirty?: (dirty: boolean) => void;
}

/** The English to start the editor with: the current translation, never the Hindi. */
const startText = (s: Segment) => (s.edited || s.engine !== "untranslated" ? s.text ?? "" : "");

export function SegmentCard(props: Props) {
  const { job, segment, selected, editing, compact, saving, saveError, onSelect, onEdit, onCancel, onSave, onDirty } = props;
  const [text, setText] = useState(() => startText(segment));
  // What the editor was opened with. Live updates never replace what the person is
  // typing; a newer machine translation is only offered ("Use it").
  const [seeded, setSeeded] = useState<{ machine: string | null; start: string } | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const card = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!editing) {
      setSeeded(null);
      return;
    }
    const start = startText(segment);
    setText(start);
    setSeeded({ machine: segment.text, start });
    onDirty?.(false);
    requestAnimationFrame(() => area.current?.focus());
    // Seed only when the editor opens, not on later refreshes of the same sentence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing]);
  useEffect(() => {
    if (selected) card.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  const live = isLive(job);
  const state = sentenceState(segment, live);
  const level = badgeLevel(segment, live);
  const untranslated = state === "needs-human" && (segment.engine === "untranslated" || !segment.text);
  const newer =
    editing &&
    seeded !== null &&
    !segment.edited &&
    !!segment.text &&
    segment.engine !== "untranslated" &&
    segment.text !== seeded.machine &&
    segment.text !== text;
  const trimmed = text.trim();
  const tooLong = trimmed.length > MAX_CORRECTION;
  const canSave = !!trimmed && !tooLong && !saving;

  const change = (value: string) => {
    setText(value);
    onDirty?.(value !== (seeded?.start ?? ""));
  };
  const save = () => {
    if (canSave) onSave(text);
  };

  return (
    <div
      ref={card}
      onClick={onSelect}
      className={cn(
        "rounded-xl border border-l-4 border-border bg-card p-3.5 transition-shadow",
        segment.edited ? "border-l-good" : level ? EDGE[level] : "border-l-border",
        selected && "ring-2 ring-primary",
        compact && "p-3",
      )}
    >
      <p lang="hi" className="font-hindi text-sm leading-relaxed text-muted-foreground">
        {segment.source}
      </p>

      {editing ? (
        <div className="mt-2 space-y-2" onClick={(e) => e.stopPropagation()}>
          {newer && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg bg-accent px-2.5 py-1.5 text-xs text-accent-foreground">
              <RefreshCw className="h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1">A newer machine translation arrived: “{segment.text}”</span>
              <button
                type="button"
                className="font-medium underline-offset-2 hover:underline"
                onClick={() => {
                  const machine = segment.text ?? "";
                  setText(machine);
                  setSeeded({ machine: segment.text, start: machine });
                  onDirty?.(false);
                }}
              >
                Use it
              </button>
            </div>
          )}
          <textarea
            ref={area}
            value={text}
            onChange={(e) => change(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape" && !saving) onCancel();
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                save();
              }
            }}
            rows={Math.min(8, Math.max(2, Math.ceil(text.length / 80)))}
            className="w-full resize-y rounded-lg border border-border bg-background p-2.5 text-[15px] leading-relaxed"
            aria-label="Edit the English translation"
            aria-invalid={!!saveError || tooLong}
            placeholder={untranslated ? "Type the English translation" : undefined}
          />
          {(saveError || tooLong) && (
            <p className="rounded-lg bg-bad-soft px-2.5 py-1.5 text-sm text-bad" role="alert">
              {tooLong
                ? `This is too long to save (${trimmed.length.toLocaleString()} characters; the limit is ${MAX_CORRECTION.toLocaleString()}).`
                : saveError}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={save} disabled={!canSave}>
              {saving && <Spinner />}
              {saving ? "Saving…" : "Save"}
            </Button>
            <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
              Cancel
            </Button>
            <span className="ml-auto text-xs text-muted-foreground">
              Remembered for future documents · Ctrl+Enter to save · Esc to cancel
            </span>
          </div>
        </div>
      ) : state === "pending" ? (
        <div className="mt-2" role="status">
          <div className="h-5 w-3/4 animate-shimmer rounded bg-[linear-gradient(90deg,hsl(var(--muted)),hsl(var(--border)),hsl(var(--muted)))] bg-[length:200%_100%]" />
          <span className="sr-only">Still translating</span>
        </div>
      ) : untranslated ? (
        <p className="mt-1.5 text-[15px] italic leading-relaxed text-bad">
          Not translated. A person needs to translate this sentence{compact ? "." : ": click Edit."}
        </p>
      ) : (
        <p className="mt-1.5 text-[15px] leading-relaxed">{segment.text}</p>
      )}

      {!compact && !editing && state !== "pending" && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          {segment.edited ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-good-soft px-2.5 py-0.5 text-xs font-medium text-good">
              <UserCheck className="h-3.5 w-3.5" aria-hidden /> Corrected by you
            </span>
          ) : (
            <>
              <ConfidenceBadge level={level} />
              <span className="text-xs text-muted-foreground">{engineLabel(job, segment.engine)}</span>
            </>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={(e) => (e.stopPropagation(), onEdit())}
            aria-label="Correct this sentence"
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden /> Edit
          </Button>
          {!segment.edited && segment.issues.length > 0 && (
            <ul className="w-full space-y-0.5 text-xs text-muted-foreground">
              {segment.issues.map((i) => (
                <li key={i.code}>• {i.message}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
