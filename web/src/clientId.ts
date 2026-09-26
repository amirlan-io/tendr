import { getAccessToken } from "./supabase";

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
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === "function") {
    return cryptoApi.randomUUID().replace(/-/g, "");
  }
  if (typeof cryptoApi?.getRandomValues === "function") {
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
  const stored = window.sessionStorage.getItem(KEY);
  let resolvedId: string;
  if (isValidClientId(stored)) {
    resolvedId = stored as string;
  } else {
    resolvedId = generateId();
    while (!isValidClientId(resolvedId)) {
      resolvedId = generateId();
    }
    window.sessionStorage.setItem(KEY, resolvedId);
  }
  setCookie(COOKIE_NAME, resolvedId);
  return resolvedId;
}

export async function getApiHeaders(
  initial?: HeadersInit,
): Promise<Headers> {
  const headers = new Headers(initial);
  headers.set("X-Client-Id", getOrCreateClientId());
  const accessToken = await getAccessToken();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  return headers;
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await fetch(path, { headers: await getApiHeaders() });
  if (!response.ok) throw new Error("Не удалось скачать файл.");
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  try {
    anchor.href = objectUrl;
    anchor.download = filename.replace(/[/\\]/g, "_");
    document.body.appendChild(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}

/**
 * Обёртка над fetch, которая автоматически проставляет X-Client-Id.
 */
export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = await getApiHeaders(init.headers);
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
      const raw = await resp.text();
      const parsed = raw ? (JSON.parse(raw) as { detail?: string }) : null;
      detail = parsed?.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  const ct = resp.headers.get("Content-Type") || "";
  if (ct.includes("application/json")) {
    return (await resp.json()) as T;
  }
  return resp as unknown as T;
}
