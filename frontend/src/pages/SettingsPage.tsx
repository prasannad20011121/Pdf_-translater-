import { CheckCircle2, Cpu, Download, FolderInput, HardDrive, Monitor, Moon, Sun, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { api, type ModelInfo } from "@/lib/api";
import { useSettings } from "@/lib/settings-context";
import { getThemePreference, setThemePreference, type ThemePreference } from "@/lib/theme";
import { cn, formatBytes } from "@/lib/utils";

const ROLE_LABEL: Record<string, string> = { translate: "Translation", reread: "Reads scanned pages", draft: "Quick draft" };

function Status({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return ok ? (
    <span className="inline-flex items-center gap-1.5 text-sm text-good">
      <CheckCircle2 className="h-4 w-4" aria-hidden /> {yes}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-sm text-bad">
      <XCircle className="h-4 w-4" aria-hidden /> {no}
    </span>
  );
}

export default function SettingsPage() {
  const { settings, refresh } = useSettings();
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [theme, setTheme] = useState<ThemePreference>(getThemePreference());
  const [packPath, setPackPath] = useState("");
  const [packMsg, setPackMsg] = useState<string | null>(null);

  const loadModels = useCallback(() => api.models().then(setModels).catch(() => {}), []);
  useEffect(() => {
    void loadModels();
  }, [loadModels]);
  useEffect(() => {
    if (!models.some((m) => m.download?.running)) return;
    const t = setInterval(() => {
      void loadModels();
      void refresh();
    }, 2000);
    return () => clearInterval(t);
  }, [models, loadModels, refresh]);

  const importPack = async () => {
    setPackMsg("Importing…");
    try {
      const r = await api.importPack(packPath);
      setPackMsg(r.imported.length ? `Imported: ${r.imported.join(", ")}` : "No catalog models found in that folder.");
      void loadModels();
      void refresh();
    } catch (e) {
      setPackMsg((e as Error).message);
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">This laptop, its translation engines and models.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-4 w-4" aria-hidden /> This laptop
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {settings ? (
              <>
                <p className="font-medium">{settings.profile.label}</p>
                <p className="text-muted-foreground">
                  {settings.ram_total_gb} GB memory, {settings.ram_available_gb} GB free now
                </p>
                <p className="text-muted-foreground">App memory budget: about {settings.profile.ram_budget_gb} GB</p>
              </>
            ) : (
              <Spinner />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <HardDrive className="h-4 w-4" aria-hidden /> Engines
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {settings && (
              <>
                <Status ok={settings.engines.tesseract} yes="OCR (Tesseract) installed" no="OCR (Tesseract) not found" />
                <Status ok={settings.engines.llama_server} yes="llama-server found" no="llama-server not found" />
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Theme">
              {([
                ["light", "Light", Sun],
                ["dark", "Dark", Moon],
                ["system", "Windows", Monitor],
              ] as const).map(([value, label, Icon]) => (
                <button
                  key={value}
                  role="radio"
                  aria-checked={theme === value}
                  onClick={() => (setThemePreference(value), setTheme(value))}
                  className={cn(
                    "flex flex-col items-center gap-1.5 rounded-xl border p-3 text-sm transition-colors",
                    theme === value ? "border-primary bg-accent text-accent-foreground" : "border-border hover:bg-muted",
                  )}
                >
                  <Icon className="h-4 w-4" aria-hidden />
                  {label}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Models</CardTitle>
          <CardDescription>
            Only tested models are listed. They download from Hugging Face once; after that everything runs offline.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {models.map((m) => (
            <div key={m.id} className="flex flex-col gap-3 rounded-xl border border-border p-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{m.label}</span>
                  {m.installed ? <Badge tone="good">Installed</Badge> : <Badge>Not installed</Badge>}
                  {m.installed && m.kind !== "dev" && (m.verified ? <Badge tone="good">Checksum OK</Badge> : <Badge tone="warn">Not verified</Badge>)}
                </div>
                <p className="text-xs text-muted-foreground">
                  {m.roles.map((r) => ROLE_LABEL[r] ?? r).join(" · ")} · needs ~{m.ram_gb} GB memory · {m.licence}
                  {m.installed && m.size_bytes ? ` · ${formatBytes(m.size_bytes)} on disk` : ""}
                  {m.source ? ` · ${m.source}` : ""}
                </p>
                {m.download && (
                  <p className={cn("text-xs", m.download.ok === false ? "text-bad" : "text-muted-foreground")}>
                    {m.download.log[m.download.log.length - 1]}
                  </p>
                )}
              </div>
              {m.kind !== "dev" && !m.installed && (
                <Button variant="outline" disabled={!!m.download?.running} onClick={() => api.downloadModel(m.id).then(loadModels)}>
                  {m.download?.running ? <Spinner /> : <Download className="h-4 w-4" aria-hidden />}
                  {m.download?.running ? "Downloading…" : "Download"}
                </Button>
              )}
            </div>
          ))}

          <div className="rounded-xl border border-dashed border-border p-4">
            <p className="mb-2 flex items-center gap-2 text-sm font-medium">
              <FolderInput className="h-4 w-4" aria-hidden /> Import a model pack
            </p>
            <p className="mb-3 text-xs text-muted-foreground">
              For offices where huggingface.co is blocked: IT prepares a pack once and shares it on a drive or USB.
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                className="h-10 flex-1 rounded-lg border border-border bg-background px-3 text-sm"
                placeholder="Folder, e.g. D:\model-pack"
                value={packPath}
                onChange={(e) => setPackPath(e.target.value)}
                aria-label="Model pack folder"
              />
              <Button variant="outline" onClick={importPack} disabled={!packPath.trim()}>
                Import
              </Button>
            </div>
            {packMsg && <p className="mt-2 text-xs text-muted-foreground">{packMsg}</p>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
