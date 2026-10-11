import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import type { Confidence } from "@/lib/api";
import { Badge } from "./ui/badge";

// Colour is never the only signal: each level also has an icon and a word.
const LEVELS: Record<Confidence, { tone: "good" | "warn" | "bad"; label: string; Icon: typeof CheckCircle2 }> = {
  green: { tone: "good", label: "Good", Icon: CheckCircle2 },
  amber: { tone: "warn", label: "Check", Icon: AlertTriangle },
  red: { tone: "bad", label: "Needs human", Icon: XCircle },
};

export function ConfidenceBadge({ level }: { level: Confidence | null }) {
  if (!level) return null;
  const { tone, label, Icon } = LEVELS[level];
  return (
    <Badge tone={tone}>
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {label}
    </Badge>
  );
}

export function ConfidenceSummary({ counts }: { counts: Partial<Record<Confidence, number>> }) {
  const total = (counts.green ?? 0) + (counts.amber ?? 0) + (counts.red ?? 0);
  if (!total) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {(["green", "amber", "red"] as Confidence[]).map((c) =>
        counts[c] ? (
          <Badge key={c} tone={LEVELS[c].tone}>
            {counts[c]} {LEVELS[c].label.toLowerCase()}
          </Badge>
        ) : null,
      )}
    </div>
  );
}
