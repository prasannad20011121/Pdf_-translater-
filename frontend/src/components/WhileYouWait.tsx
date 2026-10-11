import { BookOpen, Lightbulb, BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Tips } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

/**
 * Side panel shown while a document translates (PLAN.md §9.2-9.3). For now it shows
 * offline content; the tech-news headlines are added in Phase 3.
 */
export function WhileYouWait() {
  const [tips, setTips] = useState<Tips | null>(null);
  useEffect(() => {
    const load = () => api.tips().then(setTips).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>While you wait</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {tips?.term && (
          <div className="rounded-xl bg-accent/70 p-4">
            <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-accent-foreground">
              <BookOpen className="h-3.5 w-3.5" aria-hidden /> Glossary term of the day
            </p>
            <p lang="hi" className="font-hindi text-lg font-medium">
              {tips.term.hindi}
            </p>
            <p className="text-sm text-muted-foreground">{tips.term.english}</p>
          </div>
        )}
        {tips && (
          <div className="flex gap-3 text-sm">
            <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />
            <p className="text-muted-foreground">{tips.tip}</p>
          </div>
        )}
        {tips && tips.stats.documents > 0 && (
          <div className="flex gap-3 text-sm">
            <BarChart3 className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
            <p className="text-muted-foreground">
              {tips.stats.documents} document{tips.stats.documents === 1 ? "" : "s"} and{" "}
              {tips.stats.sentences.toLocaleString()} sentences translated on this laptop.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
