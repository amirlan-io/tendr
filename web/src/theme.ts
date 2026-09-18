/**
 * Управление темой: light / dark / system.
 * Хранится в localStorage("tendr_theme"). Применяется через класс "dark" на <html>.
 */

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "tendr_theme";

function getSystemTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  const actual = theme === "system" ? getSystemTheme() : theme;
  if (actual === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
  document.documentElement.setAttribute("data-theme", actual);
}

export function getTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system")
    return stored;
  return "system";
}

export function setTheme(theme: Theme): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, theme);
  applyTheme(theme);
  window.dispatchEvent(new CustomEvent("tendr:theme", { detail: theme }));
}

import { useCallback, useEffect, useState } from "react";

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(getTheme());

  // Стабильная обёртка: пишет в storage, навешивает класс и обновляет state.
  const setTheme = useCallback((t: Theme) => {
    window.localStorage.setItem(STORAGE_KEY, t);
    applyTheme(t);
    setThemeState(t);
    window.dispatchEvent(new CustomEvent("tendr:theme", { detail: t }));
  }, []);

  useEffect(() => {
    applyTheme(theme);
    const onChange = (e: Event) => {
      const ce = e as CustomEvent<Theme>;
      if (
        ce.detail === "light" ||
        ce.detail === "dark" ||
        ce.detail === "system"
      ) {
        setThemeState(ce.detail);
        applyTheme(ce.detail);
      }
    };
    const onSystemChange = () => {
      if (getTheme() === "system") applyTheme("system");
    };
    window.addEventListener("tendr:theme", onChange);
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", onSystemChange);
    return () => {
      window.removeEventListener("tendr:theme", onChange);
      window
        .matchMedia("(prefers-color-scheme: dark)")
        .removeEventListener("change", onSystemChange);
    };
  }, [theme]);

  return [theme, setTheme];
}
