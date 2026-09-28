import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { HistoryPage } from "./History";
import { LotsPage } from "./Lots";
import { NotFoundPage } from "./NotFound";
import { getHistoryStorageKey } from "../historyStore";
import { AuthProvider } from "../auth/AuthContext";

function renderWithRouter(ui: React.ReactNode) {
  return render(
    <AuthProvider>
      <MemoryRouter>{ui}</MemoryRouter>
    </AuthProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

afterEach(() => {
  cleanup();
});

describe("HistoryPage: серверная история + честный offline fallback", () => {
  const serverItem = {
    lot_id: "777",
    title: "Поставка мебели",
    customer: "Акимат",
    method: "конкурс",
    overall_risk: "medium",
    n_requirements: 5,
    n_red_flags: 1,
    created_at: new Date().toISOString(),
  };

  function mockHistory(ok: boolean, status = 200) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        ok
          ? new Response(
              JSON.stringify({ items: [serverItem], total: 1, limit: 20, offset: 0 }),
              { status, headers: { "Content-Type": "application/json" } },
            )
          : new Response(JSON.stringify({ detail: "ANALYSIS_FAILED" }), {
              status,
              headers: { "Content-Type": "application/json" },
            }),
      ),
    );
  }

  it("успешно загружает серверную историю", async () => {
    mockHistory(true);
    renderWithRouter(<HistoryPage />);
    expect(await screen.findByText("Поставка мебели")).toBeInTheDocument();
    expect(screen.getByText(/всего записей: 1/i)).toBeInTheDocument();
  });

  it("пустой результат показывает пустое состояние", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ items: [], total: 0, limit: 20, offset: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    renderWithRouter(<HistoryPage />);
    expect(await screen.findByText(/пока нет ни одной проверки/i)).toBeInTheDocument();
  });

  it("ошибка сервера показывает безопасное сообщение и локальную копию", async () => {
    mockHistory(false, 500);
    window.localStorage.setItem(
      getHistoryStorageKey(),
      JSON.stringify([{ ...serverItem, title: "Локальная копия" }]),
    );
    renderWithRouter(<HistoryPage />);
    // Безопасное сообщение без сырого detail.
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("ANALYSIS_FAILED")).not.toBeInTheDocument();
    // Локальная копия явно обозначена как offline.
    expect(await screen.findByText("Локальная копия")).toBeInTheDocument();
    expect(screen.getAllByText(/локальная копия/i).length).toBeGreaterThan(1);
  });
});

describe("LotsPage: честный mock/demo-режим", () => {
  function mockSearch(isMock: boolean) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown) => {
        const u = String(url);
        if (u === "/api/lots/search") {
          return new Response(
            JSON.stringify({
              lots: [],
              total: 0,
              source: "mock",
              is_mock: isMock,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
  }

  it("при is_mock=true предупреждает о демо и не утверждает реальность", async () => {
    mockSearch(true);
    renderWithRouter(<LotsPage />);
    await userEvent.click(screen.getByRole("button", { name: /найти/i }));
    expect(await screen.findByText(/демо-режим/i)).toBeInTheDocument();
    expect(screen.getAllByText(/не реальные лоты/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/GOSZAKUP_API_TOKEN отсутствует/i)).toBeInTheDocument();
  });

  it("при is_mock=false демо-баннера нет", async () => {
    mockSearch(false);
    renderWithRouter(<LotsPage />);
    await userEvent.click(screen.getByRole("button", { name: /найти/i }));
    await waitFor(() => {
      expect(screen.getByText(/найдено:/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/демо-режим/i)).not.toBeInTheDocument();
  });
});

describe("NotFoundPage", () => {
  it("рендерит 404 со ссылкой на главную", () => {
    renderWithRouter(<NotFoundPage />);
    expect(screen.getByText("404")).toBeInTheDocument();
    expect(screen.getByText("Страница не найдена")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /на главную/i })).toHaveAttribute("href", "/");
  });
});
