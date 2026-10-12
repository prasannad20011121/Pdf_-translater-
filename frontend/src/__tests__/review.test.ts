// Findings 35 and 58 (f): what the review screen counts and lists.
import assert from "node:assert/strict";
import { test } from "node:test";
import { badgeLevel, describeSummary, needsReview, pageSummary, sentenceState, visibleSegments } from "../lib/review.ts";
import { makeSegment } from "./fixtures.ts";

test("a sentence still being translated is pending, not 'to check'", () => {
  const s = makeSegment({ text: null, confidence: null, engine: null });
  assert.equal(sentenceState(s, true), "pending");
  assert.equal(needsReview(s, true), false);
  assert.equal(badgeLevel(s, true), null);
});

test("once the job has stopped, a sentence without English needs a human", () => {
  const s = makeSegment({ text: null, confidence: null, engine: null });
  assert.equal(sentenceState(s, false), "needs-human");
  assert.equal(needsReview(s, false), true);
  assert.equal(badgeLevel(s, false), "red");
});

test("an 'untranslated' sentence needs a human, even while the job runs", () => {
  const s = makeSegment({ text: "यह एक वाक्य है।", engine: "untranslated", confidence: "red" });
  assert.equal(sentenceState(s, true), "needs-human");
  assert.equal(sentenceState(s, false), "needs-human");
});

test("amber is 'check', red is 'needs human', green and corrected are fine", () => {
  assert.equal(sentenceState(makeSegment({ confidence: "amber" }), false), "check");
  assert.equal(sentenceState(makeSegment({ confidence: "red" }), false), "needs-human");
  assert.equal(sentenceState(makeSegment({ confidence: "green" }), false), "good");
  assert.equal(sentenceState(makeSegment({ confidence: "red", edited: true }), false), "corrected");
  assert.equal(sentenceState(makeSegment({ needs_translation: false, engine: "copy", text: "Ref 12/2026" }), true), "good");
});

test("the page summary separates checks, human work and sentences still translating", () => {
  const segs = [
    makeSegment({ id: 1, confidence: "amber" }),
    makeSegment({ id: 2, confidence: "amber" }),
    makeSegment({ id: 3, engine: "untranslated", confidence: "red" }),
    makeSegment({ id: 4, text: null, confidence: null, engine: null }),
    makeSegment({ id: 5, text: null, confidence: null, engine: null }),
    makeSegment({ id: 6 }),
  ];
  const live = pageSummary(segs, true);
  assert.deepEqual(live, { check: 2, human: 1, pending: 2 });
  assert.equal(describeSummary(live), "2 to check · 1 needs a human · 2 still translating");
  assert.deepEqual(pageSummary(segs, false), { check: 2, human: 3, pending: 0 });
  assert.equal(describeSummary({ check: 0, human: 0, pending: 0 }), "Nothing to check on this page");
});

test("'Needs review only' keeps the sentence being edited even when it turns green", () => {
  const editingId = 7;
  const segs = [
    makeSegment({ id: 7, confidence: "green" }), // Gemma's newer result came back green
    makeSegment({ id: 8, confidence: "amber" }),
    makeSegment({ id: 9, confidence: "green" }),
    makeSegment({ id: 10, text: null, confidence: null, engine: null }),
  ];
  const opts = { onlyReview: true, live: true, editing: editingId, justCorrected: new Set<number>() };
  assert.deepEqual(visibleSegments(segs, opts).map((s) => s.id), [7, 8]);
  assert.deepEqual(visibleSegments(segs, { ...opts, editing: null }).map((s) => s.id), [8]);
  assert.deepEqual(visibleSegments(segs, { ...opts, editing: null, justCorrected: new Set([9]) }).map((s) => s.id), [8, 9]);
  assert.equal(visibleSegments(segs, { ...opts, onlyReview: false }).length, 4);
});
