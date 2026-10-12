/**
 * Автосообщения об ошибках: отчёт уходит на /api/errors,
 * оттуда backend пересылает его владельцу в Telegram.
 *
 * Что здесь принципиально:
 *  - отправка не должна сама ломать приложение, поэтому все вызовы
 *    обёрнуты и проглатывают собственные сбои;
 *  - повторы ограничены: одна и та же ошибка уходит не чаще раза в
 *    15 минут, иначе цикл сбоев завалит канал;
 *  - из отчёта вычищаются токены, ключи и контакты — на сервере это
 *    делается ещё раз, но лишнее не передавать;
 *  - ответы 401/403/404/409/422/429 не считаем сбоем приложения:
 *    это штатные ответы сервера на проверку прав и лимитов.
 */

import { getAccessToken } from "../supabase";

const ENDPOINT = "/api/errors";
const DEDUP_WINDOW_MS = 15 * 60 * 1000;
const MAX_QUEUE = 20;

/** Что маскировать прямо в браузере — двойная защита перед отправкой. */
const SECRET_PATTERNS: RegExp[] = [
  /bu_[A-Za-z0-9_-]{16,}/g,
  /tvly-[A-Za-z0-9_-]{16,}/g,
  /eyJ[A-Za-z0-9_-]{20,}/g, // JWT
  /sk-[A-Za-z0-9]{16,}/g,
  /\+7[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}/g,
  /[\w.+-]+@[\w-]+\.[\w.-]{2,}/g,
];

const seen = new Map<string, number>();
let queue: string[] = [];
let flushTimer: number | null = null;
let installed = false;

function scrub(value: string): string {
  let out = value ?? "";
  for (const pattern of SECRET_PATTERNS) out = out.replace(pattern, "[скрыто]");
  return out.slice(0, 2000);
}

function fingerprint(name: string, message: string, where: string): string {
  const raw = `${name}|${where}|${message.slice(0, 300)}`;
  let hash = 0;
  for (let i = 0; i < raw.length; i += 1) {
    hash = (hash * 31 + raw.charCodeAt(i)) | 0;
  }
  return String(hash);
}

function isExpectedStatus(status: number): boolean {
  return [401, 403, 404, 409, 422, 429].includes(status);
}

async function send(payload: string): Promise<void> {
  try {
    const token = await getAccessToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    await fetch(ENDPOINT, { method: "POST", headers, body: payload, keepalive: true });
  } catch {
    // Отчёт об ошибке не должен порождать новую ошибку.
  }
}

function report(
  name: string,
  message: string,
  where: string,
  stack: string,
  context: Record<string, unknown> = {},
): void {
  try {
    const key = fingerprint(name, message, where);
    const now = Date.now();
    for (const [k, t] of seen) if (now - t > DEDUP_WINDOW_MS) seen.delete(k);
    if (seen.has(key)) return;
    seen.set(key, now);

    queue = queue
      .concat(
        JSON.stringify({
          name: scrub(name).slice(0, 120),
          message: scrub(message),
          stack: scrub(stack).slice(0, 4000),
          where: scrub(where).slice(0, 300),
          source: "frontend",
          context,
        }),
      )
      .slice(-MAX_QUEUE);

    if (flushTimer === null) {
      // Пачкой: при загрузке страницы ошибок бывает несколько.
      flushTimer = window.setTimeout(() => {
        flushTimer = null;
        const batch = queue;
        queue = [];
        for (const item of batch) void send(item);
      }, 1500);
    }
  } catch {
    // Полностью подавляем сбой в обработчике сбоев.
  }
}

/** Отчёт об ошибке в HTTP-вызове — вызывается из api-хелпера. */
export function reportApiError(status: number, path: string, detail = ""): void {
  if (isExpectedStatus(status)) return; // штатный ответ, не сбой
  report("ApiError", `HTTP ${status} ${detail}`.slice(0, 500), path, "");
}

/** Установить глобальные обработчики. Вызывается один раз при старте. */
export function installErrorReporting(route = ""): void {
  if (installed || typeof window === "undefined") return;
  installed = true;

  window.addEventListener("error", (event: ErrorEvent) => {
    // Ошибка загрузки ресурса (картинка, скрипт) не информативна и
    // засоряет канал — интересуют только JS-ошибки с текстом.
    if (!event.message) return;
    const stack = event.error instanceof Error ? event.error.stack ?? "" : "";
    report("window.onerror", event.message, route || window.location.pathname, stack);
  });

  window.addEventListener("unhandledrejection", (event: PromiseRejectionEvent) => {
    const reason: unknown = event.reason;
    const message = reason instanceof Error ? reason.message : String(reason ?? "");
    const stack = reason instanceof Error ? reason.stack ?? "" : "";
    report("UnhandledRejection", message, route || window.location.pathname, stack);
  });

  // Уходя со страницы, отправляем накопленное — иначе таймер может не сработать.
  window.addEventListener("pagehide", () => {
    if (queue.length === 0) return;
    const batch = queue;
    queue = [];
    for (const item of batch) void send(item);
  });
}

/** Отправить накопленное немедленно (например, в тестах). */
export function flushErrorReports(): void {
  if (flushTimer !== null) {
    window.clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (queue.length === 0) return;
  const batch = queue;
  queue = [];
  for (const item of batch) void send(item);
}

/** Сбросить состояние — только для тестов. */
export function resetErrorReportingForTests(): void {
  seen.clear();
  queue = [];
  flushTimer = null;
  installed = false;
}
