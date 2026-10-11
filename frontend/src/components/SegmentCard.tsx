import { Pencil, UserCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Job, Segment } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Button } from "./ui/button";

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

interface Props {
  job: Job;
  segment: Segment;
  selected: boolean;
  editing: boolean;
  compact?: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (text: string) => void;
}

export function SegmentCard({ job, segment, selected, editing, compact, onSelect, onEdit, onCancel, onSave }: Props) {
  const [text, setText] = useState(segment.text ?? "");
  const area = useRef<HTMLTextAreaElement>(null);
  const card = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (editing) {
      setText(segment.text ?? "");
      requestAnimationFrame(() => area.current?.focus());
    }
  }, [editing, segment.text]);
  useEffect(() => {
    if (selected) card.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  const pending = segment.needs_translation && !segment.text;

  return (
    <div
      ref={card}
      onClick={onSelect}
      className={cn(
        "rounded-xl border border-l-4 border-border bg-card p-3.5 transition-shadow",
        segment.confidence ? EDGE[segment.confidence] : "border-l-border",
        selected && "ring-2 ring-primary",
        compact && "p-3",
      )}
    >
      <p lang="hi" className="font-hindi text-sm leading-relaxed text-muted-foreground">
        {segment.source}
      </p>

      {editing ? (
        <div className="mt-2 space-y-2" onClick={(e) => e.stopPropagation()}>
          <textarea
            ref={area}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onCancel();
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onSave(text);
            }}
            rows={Math.min(8, Math.max(2, Math.ceil(text.length / 80)))}
            className="w-full resize-y rounded-lg border border-border bg-background p-2.5 text-[15px] leading-relaxed"
            aria-label="Edit the English translation"
          />
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => onSave(text)} disabled={!text.trim()}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <span className="ml-auto text-xs text-muted-foreground">
              Remembered for future documents · Ctrl+Enter to save · Esc to cancel
            </span>
          </div>
        </div>
      ) : pending ? (
        <div className="mt-2 h-5 w-3/4 animate-shimmer rounded bg-[linear-gradient(90deg,hsl(var(--muted)),hsl(var(--border)),hsl(var(--muted)))] bg-[length:200%_100%]" />
      ) : (
        <p className={cn("mt-1.5 text-[15px] leading-relaxed", segment.engine === "untranslated" && "text-bad")}>
          {segment.text}
        </p>
      )}

      {!compact && !editing && !pending && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          {segment.edited ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-good-soft px-2.5 py-0.5 text-xs font-medium text-good">
              <UserCheck className="h-3.5 w-3.5" aria-hidden /> Corrected by you
            </span>
          ) : (
            <>
              <ConfidenceBadge level={segment.confidence} />
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
