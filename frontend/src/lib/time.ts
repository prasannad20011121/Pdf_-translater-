// Server timestamps are ISO-8601 with a UTC offset ("2026-10-11T12:00:00+00:00").
// Older servers sent naive strings without one; those are UTC too. JavaScript would read
// a naive string as local time (5 h 30 min early in India), so it is never passed to
// `new Date()` as is.

const ISO = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2}))?(?:[.,](\d+))?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$/i;

/** Parse a server timestamp. Naive strings are treated as UTC. Returns null if unreadable. */
export function parseServerDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const m = ISO.exec(value.trim());
  let d: Date;
  if (m) {
    const [, date, hm, sec = "00", frac = "", zone = "Z"] = m;
    const ms = frac ? `.${(frac + "00").slice(0, 3)}` : "";
    let tz = "Z";
    if (zone.toUpperCase() !== "Z") {
      const digits = zone.slice(1).replace(":", "");
      tz = `${zone[0]}${digits.slice(0, 2)}:${digits.slice(2, 4) || "00"}`;
    }
    d = new Date(`${date}T${hm}:${sec}${ms}${tz}`);
  } else {
    d = new Date(value);
  }
  return isNaN(d.getTime()) ? null : d;
}

/** Milliseconds since the epoch, or NaN when the timestamp is missing or unreadable. */
export function serverTime(value: string | null | undefined): number {
  return parseServerDate(value)?.getTime() ?? NaN;
}

/** "Today, 14:00" for today, otherwise "11 Oct, 14:00", in the laptop's own time zone. */
export function formatDate(value: string | null | undefined, now: Date = new Date()): string {
  const d = parseServerDate(value);
  if (!d) return "";
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? `Today, ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : d.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
