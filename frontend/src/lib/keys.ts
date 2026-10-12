/** Keys typed here belong to the element, not to the review shortcuts. */
export const TEXT_ENTRY =
  'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="listbox"], [role="slider"], [role="radio"]';

/** Enter and E on these activate the element itself (a button, a link...). */
export const INTERACTIVE = `a[href], button, summary, [role="button"], [role="link"], [role="checkbox"], [role="switch"], [role="tab"], [role="menuitem"], ${TEXT_ENTRY}`;

export interface KeyInfo {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  isComposing?: boolean;
  defaultPrevented?: boolean;
}

/** Only `closest` is needed, so tests can pass a stand-in for a DOM element. */
export interface KeyTarget {
  closest(selectors: string): unknown;
}

export type ReviewKeyAction = { type: "select"; id: number } | { type: "edit"; id: number } | null;

/**
 * Review shortcuts: ↑/↓ select the previous or next listed sentence, E or Enter opens the
 * selected one for correcting. Nothing happens while an editor is open, with Ctrl, Alt or
 * the Windows key held, while typing in a field, or (for Enter and E) when a button or
 * link has the focus: those keys are theirs. Only a listed sentence can be opened.
 */
export function reviewKeyAction(
  e: KeyInfo,
  target: KeyTarget | null,
  visibleIds: readonly number[],
  selected: number | null,
  editing: number | null,
): ReviewKeyAction {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return null;
  if (editing !== null) return null;
  if (target?.closest(TEXT_ENTRY)) return null;
  const idx = selected === null ? -1 : visibleIds.indexOf(selected);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (!visibleIds.length) return null;
    const next = e.key === "ArrowDown" ? Math.min(visibleIds.length - 1, idx + 1) : Math.max(0, idx - 1);
    return { type: "select", id: visibleIds[next] };
  }
  if (e.key === "e" || e.key === "E" || e.key === "Enter") {
    if (target?.closest(INTERACTIVE)) return null;
    if (idx < 0) return null; // nothing selected among the listed sentences
    return { type: "edit", id: visibleIds[idx] };
  }
  return null;
}
