import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, type Job } from "./api";
import { diffJobs, pollInterval, type Milestone, type SeenMap } from "./milestones";
import { notify, pageHasAttention } from "./utils";

/**
 * App-wide job watcher (PLAN.md §9.2, §9.4). It polls the job list from every page while
 * something is being translated, and announces the milestones ("Quick draft ready",
 * "Translation ready", "Translation stopped") with a desktop notification, or with an
 * in-app message when the tab is being looked at or notifications are off. It runs only
 * while this browser tab is open.
 */

export interface Toast extends Milestone {
  key: number;
}

interface JobsState {
  jobs: Job[] | null;
  error: string | null;
  /** Fetch the job list now (after an upload, delete or retry). */
  refresh: () => Promise<void>;
  toasts: Toast[];
  dismissToast: (key: number) => void;
}

const Ctx = createContext<JobsState>({
  jobs: null,
  error: null,
  refresh: async () => {},
  toasts: [],
  dismissToast: () => {},
});

const SEEN_KEY = "pdft-seen-jobs";

function loadSeen(): SeenMap | null {
  try {
    const raw = sessionStorage.getItem(SEEN_KEY);
    return raw ? (JSON.parse(raw) as SeenMap) : null;
  } catch {
    return null;
  }
}

function saveSeen(map: SeenMap): void {
  try {
    sessionStorage.setItem(SEEN_KEY, JSON.stringify(map));
  } catch {
    /* storage can be unavailable */
  }
}

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const navigate = useNavigate();
  const location = useLocation();

  const seen = useRef<SeenMap | null>(loadSeen());
  const startedAt = useRef(Date.now());
  const path = useRef(location.pathname);
  path.current = location.pathname;
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const toastKey = useRef(0);

  const announce = useCallback((m: Milestone) => {
    const attention = pageHasAttention();
    if (!attention && notify(m.title, m.body, () => navigateRef.current(`/jobs/${m.jobId}`))) return;
    // Someone looking at that very document sees the change on the page itself.
    if (attention && path.current === `/jobs/${m.jobId}`) return;
    toastKey.current += 1;
    const toast: Toast = { ...m, key: toastKey.current };
    setToasts((all) => [...all.filter((t) => t.jobId !== m.jobId || t.kind !== m.kind).slice(-2), toast]);
  }, []);

  // One request at a time; a refresh asked for during a request runs right after it.
  const running = useRef<Promise<void> | null>(null);
  const again = useRef(false);
  const refresh = useCallback((): Promise<void> => {
    if (running.current) {
      again.current = true;
      return running.current;
    }
    const run = async () => {
      do {
        again.current = false;
        try {
          const list = await api.jobs();
          setJobs(list);
          setError(null);
          const { next, events } = diffJobs(seen.current, list, { startedAt: startedAt.current });
          seen.current = next;
          saveSeen(next);
          events.forEach(announce);
        } catch (e) {
          setError((e as Error).message);
        }
      } while (again.current);
    };
    running.current = run().finally(() => {
      running.current = null;
    });
    return running.current;
  }, [announce]);

  const interval = pollInterval(jobs);
  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), interval);
    return () => clearInterval(t);
  }, [refresh, interval]);

  // Catch up straight away when the person comes back to the tab.
  useEffect(() => {
    const onVisible = () => document.visibilityState === "visible" && void refresh();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [refresh]);

  const dismissToast = useCallback((key: number) => setToasts((all) => all.filter((t) => t.key !== key)), []);

  return <Ctx.Provider value={{ jobs, error, refresh, toasts, dismissToast }}>{children}</Ctx.Provider>;
}

export const useJobs = () => useContext(Ctx);
