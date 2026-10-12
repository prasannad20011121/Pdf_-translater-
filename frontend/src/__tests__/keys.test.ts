// Findings 54 and 55 (g): shortcuts leave buttons, links and fields alone; live updates reconnect.
import assert from "node:assert/strict";
import { test } from "node:test";
import { reviewKeyAction, type KeyInfo, type KeyTarget } from "../lib/keys.ts";
import { reconnectDelay } from "../lib/live.ts";

/** A stand-in for a focused element: matches simple selectors such as `button`, `a[href]`, `[role="button"]`. */
function el(tag: string, attrs: Record<string, string> = {}): KeyTarget {
  const matches = (sel: string): boolean => {
    const m = /^([a-z]*)((?:\[[^\]]+\])*)(?::not\(.*\))?$/.exec(sel.trim());
    if (!m) return false;
    const [, t, attrPart] = m;
    if (t && t !== tag) return false;
    for (const a of attrPart.match(/\[[^\]]+\]/g) ?? []) {
      const [, name, value] = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(a) ?? [];
      if (!(name in attrs)) return false;
      if (value !== undefined && attrs[name] !== value) return false;
    }
    return !!(t || attrPart);
  };
  return { closest: (selectors: string) => (selectors.split(",").some(matches) ? {} : null) };
}

const key = (k: string, mods: Partial<KeyInfo> = {}): KeyInfo => ({ key: k, ctrlKey: false, metaKey: false, altKey: false, ...mods });
const body = el("body");
const ids = [11, 12, 13];

test("arrows move the selection; E and Enter open the selected sentence", () => {
  assert.deepEqual(reviewKeyAction(key("ArrowDown"), body, ids, null, null), { type: "select", id: 11 });
  assert.deepEqual(reviewKeyAction(key("ArrowDown"), body, ids, 11, null), { type: "select", id: 12 });
  assert.deepEqual(reviewKeyAction(key("ArrowUp"), body, ids, 11, null), { type: "select", id: 11 });
  assert.deepEqual(reviewKeyAction(key("Enter"), body, ids, 12, null), { type: "edit", id: 12 });
  assert.deepEqual(reviewKeyAction(key("e"), body, ids, 12, null), { type: "edit", id: 12 });
});

test("Enter on a focused button or link is left to the button or link", () => {
  assert.equal(reviewKeyAction(key("Enter"), el("button"), ids, 11, null), null);
  assert.equal(reviewKeyAction(key("Enter"), el("a", { href: "/api/jobs/x/download/docx" }), ids, 11, null), null);
  assert.equal(reviewKeyAction(key("e"), el("div", { role: "button" }), ids, 11, null), null);
});

test("typing in a field is never taken over", () => {
  for (const target of [el("input"), el("textarea"), el("select"), el("div", { contenteditable: "true" })]) {
    assert.equal(reviewKeyAction(key("e"), target, ids, 11, null), null);
    assert.equal(reviewKeyAction(key("ArrowDown"), target, ids, 11, null), null);
  }
});

test("Ctrl, Alt and Windows-key shortcuts pass through", () => {
  assert.equal(reviewKeyAction(key("e", { ctrlKey: true }), body, ids, 11, null), null);
  assert.equal(reviewKeyAction(key("Enter", { altKey: true }), body, ids, 11, null), null);
  assert.equal(reviewKeyAction(key("ArrowDown", { metaKey: true }), body, ids, 11, null), null);
});

test("a sentence that is not listed (another page, filtered out) is never opened", () => {
  assert.equal(reviewKeyAction(key("Enter"), body, ids, 99, null), null);
  assert.equal(reviewKeyAction(key("Enter"), body, [], 11, null), null);
});

test("nothing happens while an editor is open", () => {
  assert.equal(reviewKeyAction(key("ArrowDown"), body, ids, 11, 12), null);
  assert.equal(reviewKeyAction(key("Enter"), body, ids, 11, 12), null);
});

test("live updates reconnect with a growing pause and never give up", () => {
  assert.deepEqual([1, 2, 3, 4, 5, 6, 50].map(reconnectDelay), [2000, 4000, 8000, 16000, 30000, 30000, 30000]);
});
