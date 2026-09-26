/**
 * Локальное хранилище истории анализов.
 *
 * История содержит чувствительные данные (заказчики, номера лотов,
 * результаты проверок), поэтому:
 * - хранится только в этом браузере (localStorage), на сервер не отправляется;
 * - формат версионирован: при смене схемы старый ключ мигрируется один раз;
 * - размер ограничен последними 20 записями.
 */

export type HistoryItem = {
  lot_id: string;
  title: string;
  customer: string;
  method: string;
  overall_risk?: string;
  n_requirements: number;
  n_red_flags: number;
  url?: string;
  created_at: string;
};

const HISTORY_VERSION = 2;
const HISTORY_KEY = `tendr_history:v${HISTORY_VERSION}`;
const LEGACY_KEY = "tendr_history";
const MAX_ITEMS = 20;

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isValidItem(v: unknown): v is HistoryItem {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o["lot_id"] === "string" &&
    typeof o["title"] === "string" &&
    typeof o["created_at"] === "string"
  );
}

function parseItems(raw: string | null): HistoryItem[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidItem).slice(0, MAX_ITEMS);
  } catch {
    return [];
  }
}

export function loadHistory(): HistoryItem[] {
  const s = storage();
  if (!s) return [];
  try {
    const current = s.getItem(HISTORY_KEY);
    if (current !== null) return parseItems(current);
    // Однократная миграция со старого неверсионированного ключа.
    const legacy = parseItems(s.getItem(LEGACY_KEY));
    if (legacy.length > 0) {
      s.setItem(HISTORY_KEY, JSON.stringify(legacy));
      s.removeItem(LEGACY_KEY);
    }
    return legacy;
  } catch {
    return [];
  }
}

export function saveHistory(items: HistoryItem[]): void {
  const s = storage();
  if (!s) return;
  try {
    s.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)));
  } catch {
    // localStorage может быть переполнен или недоступен — молча пропускаем.
  }
}

export function pushHistory(item: HistoryItem): void {
  const items = loadHistory().filter((i) => i.lot_id !== item.lot_id);
  items.unshift(item);
  saveHistory(items);
}

export function clearHistory(): void {
  const s = storage();
  if (!s) return;
  try {
    s.removeItem(HISTORY_KEY);
    s.removeItem(LEGACY_KEY);
  } catch {
    /* игнорируем */
  }
}

export function getHistoryStorageKey(): string {
  return HISTORY_KEY;
}
