import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Settings } from "./api";

interface SettingsState {
  settings: Settings | null;
  error: string | null;
  refresh: () => Promise<void>;
}

const Ctx = createContext<SettingsState>({ settings: null, error: null, refresh: async () => {} });

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      setSettings(await api.settings());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  return <Ctx.Provider value={{ settings, error, refresh }}>{children}</Ctx.Provider>;
}

export const useSettings = () => useContext(Ctx);
