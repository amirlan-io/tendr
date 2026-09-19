/**
 * Хелпер для client_id (cookie для backend'а + sessionStorage fallback).
 * Backend читает X-Client-Id из заголовка или cookie tendr_cid.
 * Важно: X-Client-Id не является авторизацией и должен быть безопасным случайным ID.
 */

/**
 * Безопасная ошибка API: хранит HTTP status и безопасное сообщение.
 * Никогда не содержит stack trace, внутренние ответы сервера, ключи или заголовки.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const STATUS_MESSAGES: Record<number, string> = {
  400: "Некорректный запрос. Проверьте введённые данные.",
  401: "Требуется авторизация. Войдите снова.",
  403: "Доступ запрещён.",
  404: "Данные не найдены.",
  413: "Файл слишком большой. Уменьшите размер файла и попробуйте снова.",
  422: "Неподдерживаемый или повреждённый файл. Проверьте формат и попробуйте другой файл.",
  429: "Слишком много запросов. Подождите немного и попробуйте снова.",
  502: "Внешний сервис временно недоступен. Попробуйте позже.",
  503: "Сервис не настроен или временно недоступен. Попробуйте позже.",
  504: "Превышено время ожидания. Попробуйте повторить запрос.",
};

export function getSafeMessageForStatus(status: number): string {
  if (status in STATUS_MESSAGES) return STATUS_MESSAGES[status];
  if (status >= 500) return "Внутренняя ошибка сервера. Попробуйте позже.";
  if (status >= 400) return "Произошла ошибка запроса. Попробуйте снова.";
  return "Произошла ошибка. Попробуйте снова.";
}

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
  const cryptoApi: Crypto | undefined = typeof crypto !== "undefined" ? crypto : undefined;
  if (cryptoApi && "randomUUID" in cryptoApi && typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID().replace(/-/g, "");
  }
  if (cryptoApi && typeof cryptoApi.getRandomValues === "function") {
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
  let id: string;
  if (isValidClientId(stored)) {
    id = (stored as string).trim();
  } else {
    id = generateId();
    while (!isValidClientId(id)) {
      id = generateId();
    }
    window.sessionStorage.setItem(KEY, id);
  }
  setCookie(COOKIE_NAME, id);
  return id;
}

function isJsonContentType(resp: Response): boolean {
  const ct = resp.headers.get("Content-Type") || "";
  return ct.includes("application/json");
}

/**
 * Безопасно извлекает HTTP status из неизвестной ошибки.
 * Возвращает undefined, если статус определить нельзя.
 */
export function getApiErrorStatus(e: unknown): number | undefined {
  if (e instanceof ApiError) return e.status;
  if (typeof e === "object" && e !== null && "status" in e) {
    const s = (e as { status: unknown }).status;
    if (typeof s === "number" && Number.isInteger(s)) return s;
  }
  return undefined;
}

export function toSafeApiMessage(e: unknown, fallback = "Произошла ошибка. Попробуйте снова."): string {
  if (e instanceof ApiError) return e.message;
  const status = getApiErrorStatus(e);
  if (status !== undefined) return getSafeMessageForStatus(status);
  return fallback;
}

async function throwSafeApiError(resp: Response): Promise<never> {
  const status = resp.status;
  // Дожидаемся тела ответа, но НИКОГДА не показываем его пользователю:
  // внутренние detail/stack/ключи/заголовки не должны утекать в UI.
  // Единственное исключение — сигнал исчерпанной квоты: его детектим
  // по ключевым словам и маппим в фиксированное безопасное сообщение.
  let raw = "";
  try {
    raw = await resp.text();
  } catch {
    /* игнорируем — сообщение берём из безопасной карты */
  }
  if (/лимит|исчерпан|quota|бесплатных заявок/i.test(raw.slice(0, 2000))) {
    throw new ApiError(
      status,
      "Лимит бесплатных проверок исчерпан. Дождитесь следующего месяца или оформите подписку.",
    );
  }
  throw new ApiError(status, getSafeMessageForStatus(status));
}

/**
 * Обёртка над fetch, которая автоматически проставляет X-Client-Id.
 *
 * Безопасность:
 * - сохраняет HTTP status в ApiError.status;
 * - возвращает только безопасное сообщение из фиксированной карты;
 * - не показывает stack trace, внутренние ответы сервера, ключи и заголовки;
 * - НИКОГДА не добавляет X-Admin-Key (для admin-запросов используйте adminApi).
 */
export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const cid = getOrCreateClientId();
  const headers = new Headers(init.headers || {});
  headers.set("X-Client-Id", cid);
  headers.delete("X-Admin-Key");
  if (
    init.body &&
    !headers.has("Content-Type") &&
    !(init.body instanceof FormData)
  ) {
    headers.set("Content-Type", "application/json");
  }
  let resp: Response;
  try {
    resp = await fetch(path, { ...init, headers });
  } catch {
    // Сеть недоступна / CORS / DNS — без деталей наружу.
    throw new ApiError(0, "Нет соединения с сервером. Проверьте интернет и попробуйте снова.");
  }
  if (!resp.ok) {
    await throwSafeApiError(resp);
  }
  if (isJsonContentType(resp)) {
    return (await resp.json()) as T;
  }
  return resp as unknown as T;
}

const ADMIN_PATH_PREFIX = "/api/admin/";

export function isAdminPath(path: string): boolean {
  return path === "/api/admin" || path.startsWith(ADMIN_PATH_PREFIX);
}

/**
 * Отдельный безопасный helper для административных запросов.
 *
 * - X-Admin-Key передаётся ТОЛЬКО явно через аргумент adminKey;
 * - вызывается только для путей /api/admin/* (иначе бросает ошибку);
 * - ключ никогда не логируется и не попадает в сообщения об ошибках;
 * - ошибки маппятся в безопасные сообщения (см. STATUS_MESSAGES).
 */
export async function adminApi<T = unknown>(
  path: string,
  adminKey: string,
  init: RequestInit = {},
): Promise<T> {
  if (!isAdminPath(path)) {
    throw new ApiError(400, "Некорректный запрос. Проверьте введённые данные.");
  }
  if (!adminKey) {
    throw new ApiError(401, getSafeMessageForStatus(401));
  }
  const cid = getOrCreateClientId();
  const headers = new Headers(init.headers || {});
  headers.set("X-Client-Id", cid);
  headers.set("X-Admin-Key", adminKey);
  if (
    init.body &&
    !headers.has("Content-Type") &&
    !(init.body instanceof FormData)
  ) {
    headers.set("Content-Type", "application/json");
  }
  let resp: Response;
  try {
    resp = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "Нет соединения с сервером. Проверьте интернет и попробуйте снова.");
  }
  if (!resp.ok) {
    await throwSafeApiError(resp);
  }
  if (isJsonContentType(resp)) {
    return (await resp.json()) as T;
  }
  return resp as unknown as T;
}

function sanitizeDownloadName(name: string, fallback: string): string {
  const cleaned = name.replace(/[/\\]/g, "_").trim();
  return cleaned || fallback;
}

/**
 * Общий helper для скачивания файлов (Blob).
 *
 * Единая обработка ошибок для всех скачиваний (Analyze, B2G):
 * - 401/403/413/429/503 маппятся в безопасные сообщения через ApiError;
 * - сырые ответы сервера и stack trace пользователю не показываются;
 * - object URL освобождается с задержкой, чтобы браузер успел начать скачивание.
 */
export async function downloadBlob(path: string, filename: string): Promise<void> {
  const cid = getOrCreateClientId();
  let resp: Response;
  try {
    resp = await fetch(path, { headers: { "X-Client-Id": cid } });
  } catch {
    throw new ApiError(0, "Нет соединения с сервером. Проверьте интернет и попробуйте снова.");
  }
  if (!resp.ok) {
    await throwSafeApiError(resp);
  }
  const blob = await resp.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = sanitizeDownloadName(filename, "tendr_download");
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Освобождаем память после старта скачивания, а не синхронно.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}
