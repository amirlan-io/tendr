import { beforeEach, describe, expect, it } from "vitest";
import {
  clearHistory,
  getHistoryStorageKey,
  loadHistory,
  pushHistory,
  saveHistory,
  type HistoryItem,
} from "./historyStore";

const item = (id: string): HistoryItem => ({
  lot_id: id,
  title: `Лот ${id}`,
  customer: "Заказчик",
  method: "конкурс",
  n_requirements: 1,
  n_red_flags: 0,
  created_at: new Date().toISOString(),
});

beforeEach(() => {
  window.localStorage.clear();
});

describe("historyStore", () => {
  it("использует версионированный ключ", () => {
    expect(getHistoryStorageKey()).toMatch(/^tendr_history:v\d+$/);
  });

  it("pushHistory сохраняет и возвращает в порядке LIFO без дублей", () => {
    pushHistory(item("1"));
    pushHistory(item("2"));
    pushHistory(item("1"));
    const items = loadHistory();
    expect(items.map((i) => i.lot_id)).toEqual(["1", "2"]);
  });

  it("ограничивает 20 записями", () => {
    for (let i = 0; i < 25; i++) pushHistory(item(String(i)));
    expect(loadHistory()).toHaveLength(20);
  });

  it("мигрирует со старого ключа один раз", () => {
    window.localStorage.setItem("tendr_history", JSON.stringify([item("9")]));
    expect(loadHistory().map((i) => i.lot_id)).toEqual(["9"]);
    // новый ключ записан, старый удалён
    expect(window.localStorage.getItem(getHistoryStorageKey())).not.toBeNull();
    expect(window.localStorage.getItem("tendr_history")).toBeNull();
  });

  it("отбрасывает повреждённые и невалидные записи", () => {
    window.localStorage.setItem(getHistoryStorageKey(), "not-json{{{");
    expect(loadHistory()).toEqual([]);
    saveHistory([item("1"), { broken: true } as unknown as HistoryItem]);
    expect(loadHistory().map((i) => i.lot_id)).toEqual(["1"]);
  });

  it("clearHistory очищает оба ключа", () => {
    pushHistory(item("1"));
    window.localStorage.setItem("tendr_history", "[]");
    clearHistory();
    expect(loadHistory()).toEqual([]);
    expect(window.localStorage.getItem(getHistoryStorageKey())).toBeNull();
  });
});
