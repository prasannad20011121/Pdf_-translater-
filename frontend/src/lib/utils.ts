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

export function formatDate(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? `Today, ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : d.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function formatBytes(n: number): string {
  if (!n) return "0 MB";
  const gb = n / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1024 ** 2))} MB`;
}

export async function notify(title: string, body: string): Promise<void> {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (!document.hidden) return;
  try {
    new Notification(title, { body, icon: "/favicon.svg" });
  } catch {
    /* some browsers only allow notifications from a service worker */
  }
}

export function askNotificationPermission(): void {
  if ("Notification" in window && Notification.permission === "default") {
    void Notification.requestPermission();
  }
}
