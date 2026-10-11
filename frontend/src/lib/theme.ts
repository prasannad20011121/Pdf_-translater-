export type ThemePreference = "light" | "dark" | "system";

const KEY = "pdft-theme";

export function getThemePreference(): ThemePreference {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage can be unavailable */
  }
  return "system";
}

export function setThemePreference(pref: ThemePreference): void {
  try {
    localStorage.setItem(KEY, pref);
  } catch {
    /* ignore */
  }
  applyTheme(pref);
}

export function applyTheme(pref: ThemePreference): void {
  const dark =
    pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

// Follow Windows when the preference is "system".
window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => getThemePreference() === "system" && applyTheme("system"));
