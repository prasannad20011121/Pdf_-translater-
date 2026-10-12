// Finding 37 / contract 1: server timestamps are UTC, with or without an offset.
import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDate, parseServerDate, serverTime } from "../lib/time.ts";

const UTC_0830 = Date.UTC(2026, 9, 11, 8, 30, 0);

test("an offset timestamp is read as that instant", () => {
  assert.equal(serverTime("2026-10-11T08:30:00+00:00"), UTC_0830);
  assert.equal(serverTime("2026-10-11T14:00:00+05:30"), UTC_0830);
  assert.equal(serverTime("2026-10-11T08:30:00Z"), UTC_0830);
  assert.equal(serverTime("2026-10-11T14:00:00+0530"), UTC_0830);
});

test("a naive timestamp is UTC, not local time", () => {
  assert.equal(serverTime("2026-10-11T08:30:00"), UTC_0830);
  // Python's isoformat() writes microseconds.
  assert.equal(serverTime("2026-10-11T08:30:00.745944"), UTC_0830 + 745);
  assert.equal(serverTime("2026-10-11T08:30:00.745944+00:00"), UTC_0830 + 745);
  assert.equal(serverTime("2026-10-11 08:30:00"), UTC_0830);
});

test("missing or unreadable timestamps give null / NaN, not a wrong date", () => {
  assert.equal(parseServerDate(null), null);
  assert.equal(parseServerDate(""), null);
  assert.equal(parseServerDate("not a date"), null);
  assert.ok(Number.isNaN(serverTime(undefined)));
  assert.equal(formatDate(null), "");
});

test("in India, a job created at 20:00 UTC shows as today (01:30 IST the next day)", () => {
  const old = process.env.TZ;
  process.env.TZ = "Asia/Kolkata";
  try {
    const now = new Date(Date.UTC(2026, 9, 11, 21, 0, 0)); // 02:30 IST on 12 Oct
    const label = formatDate("2026-10-11T20:00:00", now);
    assert.match(label, /^Today, /);
    assert.match(label, /01:30/);
    // A job from 08:30 UTC on 11 Oct is 14:00 IST on the previous day.
    const earlier = formatDate("2026-10-11T08:30:00", now);
    assert.doesNotMatch(earlier, /^Today/);
    assert.match(earlier, /(14:00|02:00)/);
  } finally {
    if (old === undefined) delete process.env.TZ;
    else process.env.TZ = old;
  }
});
