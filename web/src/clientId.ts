import { getAccessToken } from "./supabase";
import { reportApiError } from "./monitoring/errorReporter";

/**
 * Хелпер для client_id.
 * Backend (require_client_id) читает cookie tendr_cid В ПЕРВУЮ ОЧЕРЕДЬ,
 * затем заголовок X-Client-Id, и отклоняет всё, кроме строгого формата.
 * Важно: X-Client-Id не является авторизацией и должен быть безопасным случайным ID.
 */

/** Стабильный код квоты, который возвращает backend (HTTP 429, detail=QUOTA_EXCEEDED). */
export const QUOTA_EXCEEDED_CODE = "QUOTA_EXCEEDED";

/**
 * Контролируемая ошибка client_id (нет Web Crypto, нет браузера).
 * Безопасна для показа: не содержит секретов.
 */
export class ClientIdError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ClientIdError";
  }
}

/**
 * Безопасная ошибка API: хранит HTTP status, стабильный код backend
 * и безопасное сообщение. Никогда не содержит stack trace, сырой detail,
 * внутренние ответы сервера, ключи или заголовки.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
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

/**
 * Стабильные machine-коды backend (поле detail в JSON-ответах ошибок).
 * Сырой detail НИКОГДА не показывается пользователю: код используется
 * только для поиска в этой карте, наружу идёт фиксированное сообщение.
 */
const ERROR_CODE_MESSAGES: Record<string, string> = {
  QUOTA_EXCEEDED:
    "Лимит бесплатных проверок исчерпан. Дождитесь следующего месяца или оформите подписку.",
  FILE_TOO_LARGE:
    "Файл слишком большой. Уменьшите размер файла и попробуйте снова.",
  EMPTY_FILE: "Файл пустой. Выберите другой файл.",
  INVALID_FILE:
    "Неподдерживаемый или повреждённый файл. Проверьте формат и попробуйте другой файл.",
  INVALID_DOWNLOAD_KIND: "Некорректный запрос. Проверьте введённые данные.",
  ANALYSIS_FAILED: "Не удалось выполнить анализ. Попробуйте позже.",
  ANALYSIS_NOT_READY: "Анализ ещё выполняется. Дождитесь завершения и задайте вопрос снова.",
  ANALYSIS_JOB_NOT_FOUND: "Сохранённый анализ не найден. Запустите новый разбор.",
  ASSISTANT_UNAVAILABLE: "AI-чат временно недоступен. Попробуйте позже.",
  FILE_PROCESSING_FAILED: "Не удалось обработать файл. Попробуйте позже.",
  BILLING_NOT_CONFIGURED: "Оплата ещё не настроена владельцем проекта.",
  BILLING_PROVIDER_ERROR: "Платёжный сервис временно недоступен. Попробуйте позже.",
  EMAIL_PROVIDER_NOT_CONFIGURED: "Отправка писем не настроена. Можно скопировать черновик и отправить вручную.",
  CALL_PROVIDER_NOT_CONFIGURED: "Сервис звонков не настроен. Можно позвонить вручную по номеру поставщика.",
  SEARCH_PROVIDER_NOT_CONFIGURED:
    "Поиск поставщиков пока не подключён. Владельцу проекта нужно добавить серверный ключ Tavily.",
  RATE_LIMIT_UNAVAILABLE:
    "Защита сервиса временно недоступна. Попробуйте снова через несколько секунд.",
  "Not found": "Данные не найдены.",
  "Lot not found": "Данные не найдены.",
  "Invalid client identifier": "Некорректный запрос. Проверьте введённые данные.",
};

/** true, если ошибка означает исчерпанную квоту (проверка по коду, не по тексту). */
export function isQuotaExceededError(e: unknown): boolean {
  return e instanceof ApiError && e.code === QUOTA_EXCEEDED_CODE;
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

function getCrypto(): Crypto {
  const cryptoApi: unknown =
    typeof crypto !== "undefined" ? crypto : undefined;
  if (
    typeof cryptoApi === "object" &&
    cryptoApi !== null &&
    (typeof (cryptoApi as Crypto).randomUUID === "function" ||
      typeof (cryptoApi as Crypto).getRandomValues === "function")
  ) {
    return cryptoApi as Crypto;
  }
  throw new ClientIdError(
    "Браузер не поддерживает безопасную генерацию ID. Обновите браузер и попробуйте снова.",
  );
}

function generateId(): string {
  // Только Web Crypto. Math.random() запрещён (слабый ID),
  // бесконечные циклы запрещены: оба конструктора дают валидный формат.
  const cryptoApi = getCrypto();
  let id: string;
  if (typeof cryptoApi.randomUUID === "function") {
    id = cryptoApi.randomUUID().replace(/-/g, "");
  } else {
    const bytes = new Uint8Array(16);
    cryptoApi.getRandomValues(bytes);
    id = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  if (!isValidClientId(id)) {
    throw new ClientIdError(
      "Не удалось создать идентификатор сессии. Обновите браузер и попробуйте снова.",
    );
  }
  return id;
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  try {
    const parts = document.cookie ? document.cookie.split(";") : [];
    for (const part of parts) {
      const eq = part.indexOf("=");
      if (eq < 0) continue;
      const k = part.slice(0, eq).trim();
      if (k !== name) continue;
      const v = decodeURIComponent(part.slice(eq + 1).trim());
      return v || null;
    }
  } catch {
    /* недоступно — игнорируем */
  }
  return null;
}

function setCookie(name: string, value: string, days: number = 365): void {
  if (typeof document === "undefined") return;
  const expires = new Date(Date.now() + days * 86_400_000).toUTCString();
  document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
}

function readSession(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function writeSession(id: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(KEY, id);
  } catch {
    /* игнорируем */
  }
}

export function getOrCreateClientId(): string {
  // Вне браузера (SSR) валидного ID нет — кидаем контролируемую ошибку,
  // а не возвращаем невалидный "ssr" в backend-запросы.
  if (typeof window === "undefined" || typeof document === "undefined") {
    throw new ClientIdError("Идентификатор сессии недоступен вне браузера.");
  }
  // 1. Сначала валидный tendr_cid из cookie (как делает backend).
  //    Cookie общий для вкладок → стабильность между вкладками.
  const fromCookie = readCookie(COOKIE_NAME);
  if (isValidClientId(fromCookie)) {
    const id = (fromCookie as string).trim();
    writeSession(id);
    return id;
  }
  // 2. Валидный ID текущей вкладки — переиспользуем и синхронизируем в cookie.
  const fromSession = readSession();
  if (isValidClientId(fromSession)) {
    const id = (fromSession as string).trim();
    setCookie(COOKIE_NAME, id);
    return id;
  }
  // 3. Генерируем новый (только Web Crypto) и сохраняем в оба места.
  const id = generateId();
  writeSession(id);
  setCookie(COOKIE_NAME, id);
  return id;
}

export async function getApiHeaders(initial?: HeadersInit): Promise<Headers> {
  const headers = new Headers(initial);
  headers.set("X-Client-Id", getOrCreateClientId());
  const accessToken = await getAccessToken();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  return headers;
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
  if (e instanceof ClientIdError) return e.message;
  const status = getApiErrorStatus(e);
  if (status !== undefined) return getSafeMessageForStatus(status);
  return fallback;
}

/**
 * Извлекает стабильный machine-код backend из тела ошибки.
 * FastAPI отдаёт {"detail": "<CODE>"}; сырой detail наружу не идёт —
 * код используется только для поиска в ERROR_CODE_MESSAGES.
 */
function extractErrorCode(body: unknown): string | undefined {
  if (typeof body !== "object" || body === null) return undefined;
  const o = body as Record<string, unknown>;
  for (const field of ["detail", "code"]) {
    const v = o[field];
    if (typeof v === "string" && v.length > 0 && v.length <= 128) return v;
  }
  return undefined;
}

async function throwSafeApiError(resp: Response, path = ""): Promise<never> {
  const status = resp.status;
  // Дожидаемся тела ответа, но НИКОГДА не показываем его пользователю:
  // внутренние detail/stack/ключи/заголовки не должны утекать в UI.
  // Стабильный machine-код (QUOTA_EXCEEDED и др.) используется только
  // для выбора фиксированного безопасного сообщения.
  let raw = "";
  try {
    raw = await resp.text();
  } catch {
    /* игнорируем — сообщение берём из безопасной карты */
  }
  let code: string | undefined;
  try {
    code = extractErrorCode(JSON.parse(raw));
  } catch {
    code = undefined;
  }
  // Нештатный ответ сервера — сообщаем владельцу, чтобы не искать причину
  // вручную. Штатные коды (401/403/404/409/422/429) репортер отбрасывает.
  try {
    if (path) reportApiError(status, path, code ?? "");
  } catch {
    /* репортер не должен влиять на поток запроса */
  }
  if (code !== undefined && code in ERROR_CODE_MESSAGES) {
    throw new ApiError(status, ERROR_CODE_MESSAGES[code], code);
  }
  throw new ApiError(status, getSafeMessageForStatus(status), code);
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
  const headers = await getApiHeaders(init.headers);
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
    reportApiError(0, path, "network");
    throw new ApiError(0, "Нет соединения с сервером. Проверьте интернет и попробуйте снова.");
  }
  if (!resp.ok) {
    await throwSafeApiError(resp, path);
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
  const headers = await getApiHeaders(init.headers);
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
    reportApiError(0, path, "network");
    throw new ApiError(0, "Нет соединения с сервером. Проверьте интернет и попробуйте снова.");
  }
  if (!resp.ok) {
    await throwSafeApiError(resp, path);
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
  let resp: Response;
  try {
    resp = await fetch(path, { headers: await getApiHeaders() });
  } catch {
    reportApiError(0, path, "network");
    throw new ApiError(0, "Нет соединения с сервером. Проверьте интернет и попробуйте снова.");
  }
  if (!resp.ok) {
    await throwSafeApiError(resp, path);
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
