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

describe("HistoryPage: только локальная история, без серверного endpoint", () => {
  it("рендерит записи из localStorage и не ходит в /api/lots/history", async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error("must not be called");
    });
    vi.stubGlobal("fetch", fetchMock);
    window.localStorage.setItem(
      getHistoryStorageKey(),
      JSON.stringify([
        {
          lot_id: "123",
          title: "Поставка мебели",
          customer: "Акимат",
          method: "конкурс",
          n_requirements: 5,
          n_red_flags: 1,
          created_at: new Date().toISOString(),
        },
      ]),
    );
    renderWithRouter(<HistoryPage />);
    expect(await screen.findByText("Поставка мебели")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("показывает пустое состояние без запроса к серверу", async () => {
    const fetchMock = vi.fn(async () => new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<HistoryPage />);
    await waitFor(() => {
      expect(fetchMock).not.toHaveBeenCalled();
    });
    expect(screen.getByText(/пока нет ни одной проверки/i)).toBeInTheDocument();
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
