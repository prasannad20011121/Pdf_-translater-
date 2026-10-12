// Contracts 2, 3 and 5, and readable errors (findings 38, 57).
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { api, ApiError, errorMessage, isNotFound } from "../lib/api.ts";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

type Call = { url: string; init?: RequestInit };
function fakeFetch(status: number, body: unknown, calls: Call[] = []): Call[] {
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  return calls;
}

test("422 validation errors become one readable sentence", () => {
  const body = { detail: [{ loc: ["body", "text"], msg: "String should have at most 5000 characters", type: "x" }] };
  assert.equal(errorMessage(body, 422), "String should have at most 5000 characters");
  assert.equal(errorMessage({ detail: "Job not found" }, 404), "Job not found");
  assert.equal(errorMessage(null, 500, "Internal Server Error"), "Internal Server Error");
  assert.equal(errorMessage(null, 502), "Request failed (502)");
});

test("deleting a running job reports 'cancelling'", async () => {
  const calls = fakeFetch(200, { status: "cancelling" });
  const r = await api.deleteJob("abc");
  assert.equal(r.status, "cancelling");
  assert.equal(calls[0].url, "/api/jobs/abc");
  assert.equal(calls[0].init?.method, "DELETE");
});

test("Try again posts to the retry endpoint; 409 surfaces as an ApiError", async () => {
  const calls = fakeFetch(200, { id: "abc", status: "queued" });
  const job = await api.retryJob("abc");
  assert.equal(job.status, "queued");
  assert.equal(calls[0].url, "/api/jobs/abc/retry");
  assert.equal(calls[0].init?.method, "POST");

  fakeFetch(409, { detail: "Only a failed job can be started again" });
  await assert.rejects(api.retryJob("abc"), (e: unknown) => e instanceof ApiError && e.status === 409);
});

test("glossary import returns imported, skipped and errors (older servers: zero and empty)", async () => {
  fakeFetch(200, { imported: 3, skipped: 2, errors: ["Row 4: no Hindi text"] });
  const file = new File(["hindi,english\n"], "glossary.csv", { type: "text/csv" });
  assert.deepEqual(await api.importGlossary(file), { imported: 3, skipped: 2, errors: ["Row 4: no Hindi text"] });

  fakeFetch(200, { imported: 1 });
  assert.deepEqual(await api.importGlossary(file), { imported: 1, skipped: 0, errors: [] });

  fakeFetch(400, { detail: 'This file is not UTF-8. In Excel, save it as "CSV UTF-8".' });
  await assert.rejects(api.importGlossary(file), /CSV UTF-8/);
});

test("a stopped service gives a clear message (status 0), and 404 is recognisable", async () => {
  globalThis.fetch = (async () => {
    throw new TypeError("Failed to fetch");
  }) as typeof fetch;
  await assert.rejects(api.jobs(), (e: unknown) => e instanceof ApiError && e.status === 0 && /still running/.test(e.message));

  fakeFetch(404, { detail: "Job not found" });
  await assert.rejects(api.job("gone"), (e: unknown) => isNotFound(e));
});
