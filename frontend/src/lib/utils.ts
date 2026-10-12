import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatEta(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "";
  if (seconds < 60) return "less than a minute left";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `about ${minutes} min left`;
  const hours = Math.floor(minutes / 60);
  return `about ${hours} h ${minutes % 60} min left`;
}

export function formatBytes(n: number): string {
  if (!n) return "0 MB";
  const gb = n / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1024 ** 2))} MB`;
}

/** An error message as a full sentence, so it can be followed by another one. */
export function asSentence(message: string): string {
  const m = message.trim();
  return !m || /[.!?…]$/.test(m) ? m : `${m}.`;
}

/** True while the person is looking at this tab (visible and focused). */
export function pageHasAttention(): boolean {
  return document.visibilityState === "visible" && document.hasFocus();
}

/**
 * Show a desktop (Windows) notification. Returns false when the browser can't show one
 * (no permission, or not supported), so the caller can show an in-app message instead.
 */
export function notify(title: string, body: string, onClick?: () => void): boolean {
  if (!("Notification" in window) || Notification.permission !== "granted") return false;
  try {
    const n = new Notification(title, { body, icon: "/favicon.svg" });
    n.onclick = () => {
      window.focus();
      onClick?.();
      n.close();
    };
    return true;
  } catch {
    return false; // some browsers only allow notifications from a service worker
  }
}

export type NotificationSupport = "unsupported" | NotificationPermission;

export function notificationSupport(): NotificationSupport {
  return "Notification" in window ? Notification.permission : "unsupported";
}

export async function askNotificationPermission(): Promise<NotificationSupport> {
  if (!("Notification" in window)) return "unsupported";
  if (Notification.permission === "default") {
    try {
      return await Notification.requestPermission();
    } catch {
      return Notification.permission;
    }
  }
  return Notification.permission;
}
