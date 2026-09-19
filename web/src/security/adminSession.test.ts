import { beforeEach, describe, expect, it } from "vitest";
import {
  clearAdminSession,
  getAdminKey,
  isAdminAuthError,
  setAdminKey,
} from "./adminSession";

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

describe("adminSession", () => {
  it("сохраняет admin key в sessionStorage", () => {
    setAdminKey("secret-123");
    expect(getAdminKey()).toBe("secret-123");
    expect(window.sessionStorage.getItem("tendr_admin_key")).toBe("secret-123");
  });

  it("не сохраняет admin key в localStorage", () => {
    setAdminKey("secret-123");
    expect(window.localStorage.getItem("tendr_admin_key")).toBeNull();
    // убеждаемся, что ни один ключ localStorage не содержит секрет
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i) ?? "";
      expect(window.localStorage.getItem(k)).not.toContain("secret-123");
    }
  });

  it("clearAdminSession очищает сессию", () => {
    setAdminKey("secret-123");
    clearAdminSession();
    expect(getAdminKey()).toBeNull();
  });

  it("401 очищает административную сессию (isAdminAuthError)", () => {
    expect(isAdminAuthError(401)).toBe(true);
    setAdminKey("secret-123");
    if (isAdminAuthError(401)) clearAdminSession();
    expect(getAdminKey()).toBeNull();
  });

  it("403 очищает административную сессию (isAdminAuthError)", () => {
    expect(isAdminAuthError(403)).toBe(true);
    setAdminKey("secret-123");
    if (isAdminAuthError(403)) clearAdminSession();
    expect(getAdminKey()).toBeNull();
  });

  it("503 не является auth-ошибкой (показываем конфигурацию сервера)", () => {
    expect(isAdminAuthError(503)).toBe(false);
  });
});
