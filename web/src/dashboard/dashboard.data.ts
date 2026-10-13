import { PAID_PLANS } from "../plans";
import { accountLocalStorage } from "../accountStorage";
import type {
  NavItem,
  PreparedDocument,
  SavedLot,
  Tariff,
} from "./dashboard.types";
import { loadWorkspaceState, saveWorkspaceState } from "../workspaceState";

export const DASHBOARD_NAV: NavItem[] = [
  { to: "/dashboard", label: "Обзор", description: "Рабочий стол", icon: "home" },
  { to: "/dashboard/analyze", label: "AI-чат", description: "Разобрать закупку", icon: "spark" },
  { to: "/dashboard/lots", label: "Поиск лотов", description: "Найти возможности", icon: "lots" },
    { to: "/dashboard/suppliers", label: "Поставщики", description: "Кто поставит под лот", icon: "suppliers" },
    { to: "/dashboard/sandbox", label: "Песочница", description: "Проверка агента вживую", icon: "spark" },
  { to: "/dashboard/history", label: "Мои закупки", description: "История анализов", icon: "history" },
  { to: "/dashboard/documents", label: "Документы", description: "Жалобы и отчёты", icon: "docs" },
  { to: "/dashboard/b2g", label: "Подготовка ТЗ", description: "Черновики заказчикам", icon: "briefcase" },
  { to: "/dashboard/billing", label: "Тариф и лимиты", description: "AI-анализы и оплата", icon: "billing" },
  { to: "/dashboard/settings", label: "Настройки", description: "Профиль и доступ", icon: "settings" },
];

export const TARIFFS: Tariff[] = PAID_PLANS;

const SAVED_LOTS_KEY = "tendr_saved_lots:v1";
const DOCUMENTS_KEY = "tendr_documents:v1";
const MAX_SAVED = 100;
const MAX_DOCS = 100;

function readJson<T>(key: string): T[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = accountLocalStorage.getItem(key);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function writeJson(key: string, value: unknown[]): void {
  if (typeof window === "undefined") return;
  try {
    accountLocalStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* переполнение или недоступность — молча пропускаем */
  }
}

function syncNamespace(namespace: string, value: unknown[]): void {
  void saveWorkspaceState(namespace, value).catch(() => {
    // Локальная копия остаётся offline-fallback; повторная синхронизация
    // произойдёт при следующем изменении или открытии кабинета.
  });
}

function isSavedLot(v: unknown): v is SavedLot {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return typeof o["id"] === "number" && typeof o["title"] === "string";
}

function isPreparedDocument(v: unknown): v is PreparedDocument {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o["id"] === "string" &&
    (o["kind"] === "complaint" || o["kind"] === "report") &&
    typeof o["filename"] === "string"
  );
}

export function loadSavedLots(): SavedLot[] {
  return readJson<unknown>(SAVED_LOTS_KEY).filter(isSavedLot).slice(0, MAX_SAVED);
}

export function saveLot(lot: SavedLot): SavedLot[] {
  const items = loadSavedLots().filter((i) => i.id !== lot.id);
  items.unshift({ ...lot, stage: lot.stage || "found" });
  const next = items.slice(0, MAX_SAVED);
  writeJson(SAVED_LOTS_KEY, next);
  syncNamespace("saved_lots", next);
  return next;
}

export function updateSavedLotStage(id: number, stage: SavedLot["stage"]): SavedLot[] {
  const next = loadSavedLots().map((item) => item.id === id ? { ...item, stage } : item);
  writeJson(SAVED_LOTS_KEY, next);
  syncNamespace("saved_lots", next);
  return next;
}

export function removeSavedLot(id: number): SavedLot[] {
  const next = loadSavedLots().filter((i) => i.id !== id);
  writeJson(SAVED_LOTS_KEY, next);
  syncNamespace("saved_lots", next);
  return next;
}

export function isLotSaved(id: number): boolean {
  return loadSavedLots().some((i) => i.id === id);
}

export function loadDocuments(): PreparedDocument[] {
  return readJson<unknown>(DOCUMENTS_KEY)
    .filter(isPreparedDocument)
    .slice(0, MAX_DOCS);
}

/** Фиксирует только реально скачанный файл. Вызывать после успеха downloadBlob. */
export function trackDocumentDownload(doc: PreparedDocument): PreparedDocument[] {
  const items = loadDocuments().filter((i) => i.id !== doc.id);
  items.unshift(doc);
  const next = items.slice(0, MAX_DOCS);
  writeJson(DOCUMENTS_KEY, next);
  syncNamespace("documents", next);
  return next;
}

export function removeDocument(id: string): PreparedDocument[] {
  const next = loadDocuments().filter((i) => i.id !== id);
  writeJson(DOCUMENTS_KEY, next);
  syncNamespace("documents", next);
  return next;
}

export async function hydrateCabinetFromServer(): Promise<{
  savedLots: SavedLot[];
  documents: PreparedDocument[];
}> {
  const [remoteLots, remoteDocuments] = await Promise.all([
    loadWorkspaceState<unknown[]>("saved_lots"),
    loadWorkspaceState<unknown[]>("documents"),
  ]);
  const savedLots = (remoteLots ?? []).filter(isSavedLot).slice(0, MAX_SAVED);
  const documents = (remoteDocuments ?? [])
    .filter(isPreparedDocument)
    .slice(0, MAX_DOCS);
  writeJson(SAVED_LOTS_KEY, savedLots);
  writeJson(DOCUMENTS_KEY, documents);
  return { savedLots, documents };
}
