import "@testing-library/jest-dom/vitest";

// В некоторых окружениях jsdom не предоставляет window.localStorage.
// Даём минимальный in-memory полифилл только для тестов.
function ensureLocalStorage(): void {
  if (typeof globalThis === "undefined") return;
  const g = globalThis as unknown as Record<string, unknown>;
  if (typeof g["localStorage"] !== "undefined" && g["localStorage"] !== null) return;
  const store = new Map<string, string>();
  const polyfill: Storage = {
    get length() {
      return store.size;
    },
    clear: () => {
      store.clear();
    },
    getItem: (key: string) => (store.has(key) ? (store.get(key) as string) : null),
    key: (index: number) => [...store.keys()][index] ?? null,
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
  };
  try {
    Object.defineProperty(g, "localStorage", {
      value: polyfill,
      writable: true,
      configurable: true,
    });
  } catch {
    g["localStorage"] = polyfill;
  }
  // jsdom window может отличаться от globalThis — дублируем туда же.
  try {
    const w = (g["window"] ?? g) as Record<string, unknown>;
    if (typeof w["localStorage"] === "undefined" || w["localStorage"] === null) {
      w["localStorage"] = polyfill;
    }
  } catch {
    /* игнорируем */
  }
}

ensureLocalStorage();

// jsdom не реализует window.matchMedia (нужен theme.ts).
// Минимальный стаб только для тестов.
function ensureMatchMedia(): void {
  if (typeof window === "undefined") return;
  const w = window as unknown as Record<string, unknown>;
  if (typeof w["matchMedia"] === "function") return;
  w["matchMedia"] = () => ({
    matches: false,
    media: "",
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

ensureMatchMedia();
