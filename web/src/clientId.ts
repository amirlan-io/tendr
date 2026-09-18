/**
 * Хелпер для client_id (cookie для backend'а + localStorage fallback).
 * Backend читает X-Client-Id из заголовка или cookie tendr_cid.
 * Важно: X-Client-Id не является авторизацией и должен быть безопасным случайным ID.
 */

const KEY = "tendr_cid";
const COOKIE_NAME = "tendr_cid";
const CLIENT_ID_RE = /^[A-Za-z0-9_-]{16,128}$/;

function isValidClientId(value: string | null | undefined): boolean {
  if (!value) return false;
  const candidate = value.trim();
  if (!candidate || candidate === "anon") return false;
  return CLIENT_ID_RE.test(candidate);
}

function generateId(): string {
  const cryptoApi = typeof crypto !== "undefined" ? crypto : undefined;
  if (cryptoApi && "randomUUID" in cryptoApi) {
    return cryptoApi.randomUUID().replace(/-/g, "");
  }
  if (cryptoApi && "getRandomValues" in cryptoApi) {
    const bytes = new Uint8Array(16);
    cryptoApi.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  return "web_" + Math.random().toString(36).slice(2, 18);
}

function setCookie(name: string, value: string, days: number = 365): void {
  if (typeof document === "undefined") return;
  const expires = new Date(Date.now() + days * 86_400_000).toUTCString();
  document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
}

export function getOrCreateClientId(): string {
  if (typeof window === "undefined") return "ssr";
  let id = window.sessionStorage.getItem(KEY);
  if (!isValidClientId(id)) {
    id = generateId();
    while (!isValidClientId(id)) {
      id = generateId();
    }
    window.sessionStorage.setItem(KEY, id);
  }
  setCookie(COOKIE_NAME, id);
  return id;
}

/**
 * Обёртка над fetch, которая автоматически проставляет X-Client-Id.
 */
export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const cid = getOrCreateClientId();
  const headers = new Headers(init.headers || {});
  headers.set("X-Client-Id", cid);
  if (
    init.body &&
    !headers.has("Content-Type") &&
    !(init.body instanceof FormData)
  ) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(path, { ...init, headers });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const j = await resp.json();
      detail = j.detail || detail;
    } catch {
      detail = (await resp.text()) || detail;
    }
    throw new Error(detail);
  }
  const ct = resp.headers.get("Content-Type") || "";
  if (ct.includes("application/json")) {
    return (await resp.json()) as T;
  }
  return resp as unknown as T;
}
