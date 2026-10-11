import { FileText, Languages, Moon, Settings2, Sun, BookOpen, Monitor } from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { getThemePreference, setThemePreference, type ThemePreference } from "@/lib/theme";

const NAV = [
  { to: "/", label: "Translate", Icon: Languages, end: true },
  { to: "/jobs", label: "Documents", Icon: FileText, end: false },
  { to: "/glossary", label: "Glossary", Icon: BookOpen, end: false },
  { to: "/settings", label: "Settings", Icon: Settings2, end: false },
];

const NEXT: Record<ThemePreference, ThemePreference> = { system: "light", light: "dark", dark: "system" };
const THEME_ICON = { light: Sun, dark: Moon, system: Monitor };

function ThemeToggle() {
  const [pref, setPref] = useState<ThemePreference>(getThemePreference());
  const Icon = THEME_ICON[pref];
  return (
    <button
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
      onClick={() => {
        const next = NEXT[pref];
        setThemePreference(next);
        setPref(next);
      }}
      title={`Theme: ${pref} (click to change)`}
      aria-label={`Theme: ${pref}. Click to change.`}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

export function Layout({ children, banner }: { children: ReactNode; banner?: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
          <NavLink to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <span className="hidden sm:inline">Hindi PDF Translator</span>
          </NavLink>
          <nav className="flex items-center gap-1 sm:ml-2" aria-label="Main">
            {NAV.map(({ to, label, Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors md:px-3",
                    isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )
                }
              >
                <Icon className="h-4 w-4" aria-hidden />
                <span className="sr-only md:not-sr-only">{label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </div>
        {banner}
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8">{children}</main>
      <footer className="border-t border-border py-4 text-center text-xs text-muted-foreground">
        Runs on this laptop · documents never leave it
      </footer>
    </div>
  );
}
