// Finding 58 / contract 7: the stage tracker never claims a model ran when it did not.
import assert from "node:assert/strict";
import { test } from "node:test";
import { draftSkipped, finalSkipped, stageSteps } from "../lib/stages.ts";
import { makeJob } from "./fixtures.ts";

const labels = (job: Parameters<typeof stageSteps>[0]) => stageSteps(job).map((s) => `${s.label}:${s.state}`);

test("Gemma missing on Auto: the final step reads 'skipped', with no tick and no Gemma label", () => {
  const job = makeJob({
    status: "done",
    stage: "done",
    draft_model: "indictrans2-1b",
    draft_ready: true,
    model_used: null,
    model_labels: { model_requested: "Gemma 4 E2B", draft_model: "IndicTrans2 1B" },
  });
  assert.equal(finalSkipped(job), true);
  const final = stageSteps(job)[2];
  assert.equal(final.label, "Final (skipped)");
  assert.equal(final.state, "skipped");
  assert.doesNotMatch(final.label, /Gemma/);
});

test("skipped is inferred as soon as the job is past the final stage", () => {
  const job = makeJob({ stage: "check", draft_model: "indictrans2-1b", draft_ready: true });
  assert.deepEqual(labels(job), [
    "Reading pages:done",
    "Quick draft:done",
    "Final (skipped):skipped",
    "Checking:active",
    "Ready:todo",
  ]);
});

test("before and during the final stage, the planned model is named but not ticked", () => {
  const before = makeJob({ stage: "draft", draft_model: "indictrans2-1b" });
  assert.equal(finalSkipped(before), false);
  assert.deepEqual(stageSteps(before)[2], {
    label: "Final · Gemma 4 E2B",
    state: "todo",
    detail: "Planned: final translation with Gemma 4 E2B.",
  });
  const during = makeJob({
    stage: "final",
    draft_model: "indictrans2-1b",
    draft_ready: true,
    model_used: "gemma4-e2b",
    model_labels: { model_used: "Gemma 4 E2B" },
  });
  assert.equal(stageSteps(during)[2].state, "active");
});

test("when Gemma really ran, the finished step names it with a tick", () => {
  const job = makeJob({
    status: "done",
    stage: "done",
    draft_model: "indictrans2-1b",
    draft_ready: true,
    model_used: "gemma4-e4b",
    model_labels: { model_used: "Gemma 4 E4B", model_requested: "Gemma 4 E2B" },
  });
  assert.deepEqual(labels(job), [
    "Reading pages:done",
    "Quick draft:done",
    "Final · Gemma 4 E4B:done",
    "Checking:done",
    "Ready:done",
  ]);
});

test("Fast always shows the final step as skipped", () => {
  const job = makeJob({ choice: "fast", stage: "draft", model_requested: null, model_labels: {} });
  assert.equal(stageSteps(job)[2].label, "Final (skipped: Fast)");
  assert.equal(stageSteps(job)[2].state, "skipped");
});

test("a missing quick draft is shown as skipped too", () => {
  const job = makeJob({ stage: "final", draft_model: null, draft_ready: false });
  assert.equal(draftSkipped(job), true);
  assert.deepEqual(stageSteps(job)[1], {
    label: "Quick draft (skipped)",
    state: "skipped",
    detail: "The quick draft did not run. The notes explain why.",
  });
});

test("a failed job marks the stage where it stopped", () => {
  const job = makeJob({ status: "failed", stage: "draft", error: "boom" });
  const steps = stageSteps(job);
  assert.equal(steps[1].state, "failed");
  assert.equal(steps.filter((s) => s.state === "active").length, 0);
});
