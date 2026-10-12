import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  adminApi,
  api,
  ApiError,
  ClientIdError,
  getOrCreateClientId,
  getSafeMessageForStatus,
  isQuotaExceededError,
} from "./clientId";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.localStorage.clear();
});

describe("api: безопасные ошибки", () => {
  it("сохраняет HTTP status и возвращает безопасное сообщение (404)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(404, { detail: "INTERNAL Lot not found db=secret" })),
    );
    try {
      await api("/api/lots/search", { method: "POST", body: "{}" });
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(404);
      expect((e as ApiError).message).toBe("Данные не найдены.");
      // внутренние ответы сервера не утекают
      expect((e as ApiError).message).not.toContain("INTERNAL");
      expect((e as ApiError).message).not.toContain("secret");
      expect((e as ApiError).stack).not.toContain("INTERNAL");
    }
  });

  it("413 показывает ошибку большого файла", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(413, { detail: "too large" })));
    try {
      await api("/api/lots/analyze-upload", { method: "POST", body: new FormData() });
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).status).toBe(413);
      expect((e as ApiError).message).toMatch(/слишком большой/i);
    }
  });

  it("429 показывает просьбу повторить позже", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(429, { detail: "slow down" })));
    try {
      await api("/api/lots/search", { method: "POST", body: "{}" });
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).status).toBe(429);
      expect((e as ApiError).message).toMatch(/подождите|повторите|много запросов/i);
    }
  });

  it("503 показывает ошибку конфигурации сервера", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(503, { detail: "Admin API is not configured" })));
    try {
      await api("/api/admin/stats");
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).status).toBe(503);
      expect((e as ApiError).message).toMatch(/не настроен|недоступен/i);
    }
  });

  it("покрывает карту статусов без утечек", () => {
    expect(getSafeMessageForStatus(400)).toMatch(/некорректный/i);
    expect(getSafeMessageForStatus(401)).toMatch(/авторизация/i);
    expect(getSafeMessageForStatus(403)).toMatch(/запрещён/i);
    expect(getSafeMessageForStatus(404)).toMatch(/не найдены/i);
    expect(getSafeMessageForStatus(413)).toMatch(/слишком большой/i);
    expect(getSafeMessageForStatus(422)).toMatch(/повреждён/i);
    expect(getSafeMessageForStatus(429)).toMatch(/много запросов/i);
    expect(getSafeMessageForStatus(502)).toMatch(/временно недоступен/i);
    expect(getSafeMessageForStatus(503)).toMatch(/не настроен|недоступен/i);
    expect(getSafeMessageForStatus(504)).toMatch(/время ожидания/i);
  });

  it("обычный api НЕ отправляет X-Admin-Key автоматически", async () => {
    window.sessionStorage.setItem("tendr_admin_key", "SUPERSECRET");
    const fetchMock = vi.fn(async () => jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/api/lots/search", { method: "POST", body: "{}" });
    const calls = fetchMock.mock.calls as unknown as Array<[unknown, RequestInit?]>;
    const call = calls[0];
    if (!call) throw new Error("fetch not called");
    const headers = call[1]?.headers as Headers;
    expect(headers.get("X-Admin-Key")).toBeNull();
    expect(headers.get("X-Client-Id")).toBeTruthy();
  });
});

describe("adminApi: заголовок только для /api/admin/*", () => {
  it("отправляет X-Admin-Key на /api/admin/*", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await adminApi("/api/admin/stats", "k123");
    const calls = fetchMock.mock.calls as unknown as Array<[unknown, RequestInit?]>;
    const call = calls[0];
    if (!call) throw new Error("fetch not called");
    const headers = call[1]?.headers as Headers;
    expect(headers.get("X-Admin-Key")).toBe("k123");
  });

  it("отклоняет не-admin пути", async () => {
    await expect(adminApi("/api/lots/search", "k123")).rejects.toBeInstanceOf(ApiError);
  });

  it("401/403 от adminApi несут status для очистки сессии", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, { detail: "Invalid admin key" })));
    try {
      await adminApi("/api/admin/stats", "bad");
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).status).toBe(401);
      expect((e as ApiError).message).not.toContain("bad");
    }
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(403, { detail: "nope" })));
    try {
      await adminApi("/api/admin/recent", "bad");
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).status).toBe(403);
    }
  });
});

describe("getOrCreateClientId: cookie-first и Web Crypto", () => {
  const VALID = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2";

  beforeEach(() => {
    document.cookie.split(";").forEach((c) => {
      const name = c.split("=")[0].trim();
      if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
    });
  });

  it("сначала использует валидный tendr_cid из cookie", () => {
    document.cookie = `tendr_cid=${VALID}; path=/`;
    window.sessionStorage.setItem("tendr_cid", "f".repeat(32));
    expect(getOrCreateClientId()).toBe(VALID);
  });

  it("игнорирует невалидный cookie и генерирует новый", () => {
    document.cookie = "tendr_cid=anon; path=/";
    const id = getOrCreateClientId();
    expect(id).not.toBe("anon");
    expect(id).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
  });

  it("стабилен между вкладками: пустой sessionStorage + cookie даёт тот же ID", () => {
    document.cookie = `tendr_cid=${VALID}; path=/`;
    window.sessionStorage.clear();
    expect(getOrCreateClientId()).toBe(VALID);
    expect(getOrCreateClientId()).toBe(VALID);
  });

  it("без Web Crypto бросает контролируемую ошибку, без Math.random и зависаний", () => {
    const randomSpy = vi.spyOn(Math, "random");
    vi.stubGlobal("crypto", undefined);
    expect(() => getOrCreateClientId()).toThrowError(ClientIdError);
    expect(randomSpy).not.toHaveBeenCalled();
    randomSpy.mockRestore();
  });

  it("не возвращает невалидный 'ssr' в backend-запросы", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const calls = fetchMock.mock.calls as unknown as Array<[unknown, RequestInit?]>;
    await api("/api/lots/search", { method: "POST", body: "{}" });
    const headers = calls[0]?.[1]?.headers as Headers;
    const sent = headers.get("X-Client-Id");
    expect(sent).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(sent).not.toBe("ssr");
    expect(sent).not.toBe("anon");
  });
});

describe("ApiError: стабильные коды backend вместо сырого detail", () => {
  it("QUOTA_EXCEEDED определяется по коду и несёт code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(429, { detail: "QUOTA_EXCEEDED" })),
    );
    try {
      await api("/api/lots/analyze", { method: "POST", body: "{}" });
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).code).toBe("QUOTA_EXCEEDED");
      expect(isQuotaExceededError(e)).toBe(true);
      expect((e as ApiError).message).toMatch(/лимит/i);
    }
  });

  it("сырой detail никогда не показывается пользователю", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(500, { detail: "super secret traceback line 42" })),
    );
    try {
      await api("/api/lots/analyze", { method: "POST", body: "{}" });
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).message).not.toContain("secret");
      expect((e as ApiError).message).not.toContain("traceback");
    }
  });

  it("FILE_TOO_LARGE и INVALID_FILE маппятся по коду", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(413, { detail: "FILE_TOO_LARGE" })),
    );
    try {
      await api("/api/lots/analyze-upload", { method: "POST", body: new FormData() });
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).code).toBe("FILE_TOO_LARGE");
      expect((e as ApiError).message).toMatch(/слишком большой/i);
    }
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(422, { detail: "INVALID_FILE" })),
    );
    try {
      await api("/api/lots/analyze-upload", { method: "POST", body: new FormData() });
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).code).toBe("INVALID_FILE");
      expect((e as ApiError).message).toMatch(/повреждён/i);
    }
  });
});
