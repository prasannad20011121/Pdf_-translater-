import { Download, Plus, Search, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type Term } from "@/lib/api";

const inputClass = "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm placeholder:text-muted-foreground";

export default function GlossaryPage() {
  const [terms, setTerms] = useState<Term[]>([]);
  const [hindi, setHindi] = useState("");
  const [english, setEnglish] = useState("");
  const [note, setNote] = useState("");
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const load = () => api.glossary().then(setTerms).catch((e) => setMessage({ kind: "error", text: e.message }));
  useEffect(() => {
    void load();
  }, []);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.addTerm({ hindi, english, note });
      setHindi("");
      setEnglish("");
      setNote("");
      setMessage({ kind: "ok", text: "Saved. New translations will use this term." });
      void load();
    } catch (err) {
      setMessage({ kind: "error", text: (err as Error).message });
    }
  };

  const importCsv = async (f: File | undefined) => {
    if (!f) return;
    try {
      const r = await api.importGlossary(f);
      setMessage({ kind: "ok", text: `Imported ${r.imported} terms.` });
      void load();
    } catch (err) {
      setMessage({ kind: "error", text: (err as Error).message });
    }
  };

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? terms.filter((t) => t.hindi.includes(q) || t.english.toLowerCase().includes(q)) : terms;
  }, [terms, query]);

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Glossary</h1>
          <p className="text-sm text-muted-foreground">
            Terms that must always be translated the same way, e.g. ज्ञापांक → Memo No.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => file.current?.click()}>
            <Upload className="h-4 w-4" aria-hidden /> Import CSV
          </Button>
          <a href="/api/glossary/export" className={buttonClasses("outline")}>
            <Download className="h-4 w-4" aria-hidden /> Export CSV
          </a>
          <input ref={file} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => void importCsv(e.target.files?.[0])} />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Add a term</CardTitle>
          <CardDescription>Adding a Hindi term that already exists updates its English.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={add} className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]">
            <input className={`${inputClass} font-hindi`} lang="hi" placeholder="Hindi, e.g. कार्यादेश" value={hindi} onChange={(e) => setHindi(e.target.value)} required aria-label="Hindi term" />
            <input className={inputClass} placeholder="English, e.g. Work Order" value={english} onChange={(e) => setEnglish(e.target.value)} required aria-label="English term" />
            <input className={inputClass} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note" />
            <Button type="submit">
              <Plus className="h-4 w-4" aria-hidden /> Add
            </Button>
          </form>
          {message && (
            <p className={`mt-3 text-sm ${message.kind === "ok" ? "text-good" : "text-bad"}`}>{message.text}</p>
          )}
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        <div className="flex items-center gap-2 border-b border-border px-5 py-3">
          <Search className="h-4 w-4 text-muted-foreground" aria-hidden />
          <input
            className="h-8 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            placeholder={`Search ${terms.length} terms`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search glossary"
          />
        </div>
        {shown.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-muted-foreground">
            {terms.length ? "No matching terms." : "No terms yet. Add one above or import a CSV (hindi,english,note)."}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-5 py-2.5 font-medium">Hindi</th>
                <th className="px-5 py-2.5 font-medium">English</th>
                <th className="hidden px-5 py-2.5 font-medium md:table-cell">Note</th>
                <th className="w-12 px-3 py-2.5"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {shown.map((t) => (
                <tr key={t.id} className="hover:bg-muted/40">
                  <td lang="hi" className="px-5 py-2.5 font-hindi">{t.hindi}</td>
                  <td className="px-5 py-2.5">{t.english}</td>
                  <td className="hidden px-5 py-2.5 text-muted-foreground md:table-cell">{t.note}</td>
                  <td className="px-3 py-1.5">
                    <Button variant="ghost" size="icon" aria-label={`Delete ${t.hindi}`} onClick={() => api.deleteTerm(t.id).then(load)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
