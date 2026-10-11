import type { Job } from "@/lib/api";
import { Badge } from "./ui/badge";

export function StatusBadge({ job }: { job: Job }) {
  if (job.status === "done") return <Badge tone="good">Ready</Badge>;
  if (job.status === "failed") return <Badge tone="bad">Failed</Badge>;
  if (job.status === "queued") return <Badge>Waiting</Badge>;
  return <Badge tone="primary">{job.draft_ready ? "Draft ready" : "Translating"}</Badge>;
}
