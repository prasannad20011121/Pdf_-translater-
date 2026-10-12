// Finding 34 (c): the app-wide watcher announces milestones from any page, once each.
import assert from "node:assert/strict";
import { test } from "node:test";
import { diffJobs, pollInterval, type SeenMap } from "../lib/milestones.ts";
import { makeJob } from "./fixtures.ts";

const STARTED = Date.UTC(2026, 9, 11, 9, 0, 0);
const opts = { startedAt: STARTED };
const iso = (ms: number) => new Date(ms).toISOString().replace("Z", "+00:00");

test("the first look records everything silently (old jobs never notify)", () => {
  const jobs = [
    makeJob({ id: "a", status: "done", draft_ready: true, created_at: iso(STARTED - 86_400_000) }),
    makeJob({ id: "b", status: "running", draft_ready: true }),
  ];
  const { next, events } = diffJobs(null, jobs, opts);
  assert.deepEqual(events, []);
  assert.deepEqual(next, { a: { draft: true, status: "done" }, b: { draft: true, status: "running" } });
});

test("quick draft, then translation ready, each announced once", () => {
  let seen: SeenMap | null = diffJobs(null, [makeJob({ id: "a", status: "running" })], opts).next;

  let r = diffJobs(seen, [makeJob({ id: "a", status: "running", draft_ready: true })], opts);
  assert.deepEqual(r.events.map((e) => [e.kind, e.title]), [["draft", "Quick draft ready"]]);
  seen = r.next;

  r = diffJobs(seen, [makeJob({ id: "a", status: "running", draft_ready: true })], opts);
  assert.deepEqual(r.events, []);
  seen = r.next;

  r = diffJobs(seen, [makeJob({ id: "a", status: "done", draft_ready: true, counts: { green: 5, amber: 2, red: 1 } })], opts);
  assert.deepEqual(r.events.map((e) => e.title), ["Translation ready"]);
  assert.equal(r.events[0].body, "letter.pdf · 3 sentences to check");
  assert.equal(r.events[0].jobId, "a");
});

test("a failure is announced with its reason", () => {
  const seen = diffJobs(null, [makeJob({ id: "a", status: "running" })], opts).next;
  const r = diffJobs(seen, [makeJob({ id: "a", status: "failed", error: "Out of memory" })], opts);
  assert.deepEqual(r.events.map((e) => [e.title, e.body]), [["Translation stopped", "letter.pdf: Out of memory"]]);
});

test("a new job that finished between two polls still notifies (only 'ready')", () => {
  const seen = diffJobs(null, [], opts).next;
  const r = diffJobs(seen, [makeJob({ id: "new", status: "done", draft_ready: true, created_at: iso(STARTED + 60_000) })], opts);
  assert.deepEqual(r.events.map((e) => e.kind), ["done"]);
});

test("an old job appearing later (e.g. list limit) does not notify", () => {
  const seen = diffJobs(null, [], opts).next;
  const r = diffJobs(seen, [makeJob({ id: "old", status: "done", created_at: iso(STARTED - 86_400_000) })], opts);
  assert.deepEqual(r.events, []);
  assert.ok(r.next.old);
});

test("Fast jobs skip the separate quick-draft notification", () => {
  const seen = diffJobs(null, [makeJob({ id: "a", choice: "fast", status: "running" })], opts).next;
  const r = diffJobs(seen, [makeJob({ id: "a", choice: "fast", status: "running", draft_ready: true })], opts);
  assert.deepEqual(r.events, []);
});

test("a retried job notifies again when it finishes; deleted jobs are forgotten", () => {
  let seen = diffJobs(null, [makeJob({ id: "a", status: "failed" }), makeJob({ id: "b", status: "running" })], opts).next;
  seen = diffJobs(seen, [makeJob({ id: "a", status: "queued" })], opts).next; // b deleted, a retried
  assert.deepEqual(Object.keys(seen), ["a"]);
  const r = diffJobs(seen, [makeJob({ id: "a", status: "done", draft_ready: true })], opts);
  assert.deepEqual(r.events.map((e) => e.kind), ["done"]);
});

test("polls every 5 s while something runs, rarely otherwise", () => {
  assert.equal(pollInterval([makeJob({ status: "queued" })]), 5000);
  assert.equal(pollInterval([makeJob({ status: "done" })]), 30000);
  assert.equal(pollInterval(null), 30000);
});
