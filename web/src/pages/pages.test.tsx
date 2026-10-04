import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("даёт переход на сам лот по source_url из ответа сервера", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            items: [
              {
                ...serverItem,
                lot_id: "17726443",
                url: "https://v3bl.goszakup.gov.kz/ru/announce/index/17726443-1",
              },
            ],
            total: 1,
            limit: 20,
            offset: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    renderWithRouter(<HistoryPage />);
    const link = await screen.findByRole("link", { name: /лот на госзакупках/i });
    expect(link).toHaveAttribute(
      "href",
      "https://v3bl.goszakup.gov.kz/ru/announce/index/17726443-1",
    );
  });

  it("строит ссылку из lot_id, когда сервер не прислал url", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            items: [{ ...serverItem, lot_id: "17726443" }],
            total: 1,
            limit: 20,
            offset: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    renderWithRouter(<HistoryPage />);
    const link = await screen.findByRole("link", { name: /лот на госзакупках/i });
    expect(link).toHaveAttribute(
      "href",
      "https://goszakup.gov.kz/ru/announce/index/17726443",
    );
  });

  it("не показывает переход, когда номер лота не похож на объявление", async () => {
    // Короткий/служебный ID не превращаем в ссылку: битых ссылок быть не должно.
    mockHistory(true);
    renderWithRouter(<HistoryPage />);
    expect(await screen.findByText("Поставка мебели")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /лот на госзакупках/i })).toBeNull();
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

  it("в dashboard автоматически загружает актуальные лоты", async () => {
    mockSearch(false);
    renderWithRouter(<LotsPage embedded />);
    expect(await screen.findByText(/найдено:/i)).toBeInTheDocument();
    expect(screen.queryByText(/демо-режим/i)).not.toBeInTheDocument();
  });

  it("передаёт выбранный histogram-диапазон в поиск в тенге", async () => {
    let searchBody: Record<string, unknown> | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: unknown, init?: RequestInit) => {
        searchBody = JSON.parse(String(init?.body || "{}"));
        return new Response(
          JSON.stringify({ lots: [], total: 0, source: "zakup.gov.kz", is_mock: false }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    renderWithRouter(<LotsPage />);
    fireEvent.change(screen.getByLabelText("Максимальная сумма лота"), {
      target: { value: "1000000000" },
    });
    await userEvent.click(screen.getByRole("button", { name: /найти лоты/i }));

    await waitFor(() => expect(searchBody).not.toBeNull());
    expect(searchBody).toEqual(
      expect.objectContaining({
        min_amount_kzt: 0,
        max_amount_kzt: 1_000_000_000,
      }),
    );
  });

  it("по умолчанию запрашивает только актуальные лоты и умеет открыть архив", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: unknown, init?: RequestInit) => {
        bodies.push(JSON.parse(String(init?.body || "{}")));
        return new Response(
          JSON.stringify({
            lots: [],
            total: 0,
            source: "zakup.gov.kz",
            is_mock: false,
            has_more: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    renderWithRouter(<LotsPage />);
    await userEvent.click(screen.getByRole("button", { name: /найти лоты/i }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual(expect.objectContaining({ status: "active", limit: 20 }));
    expect(bodies[0].published_from).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    await userEvent.click(screen.getByLabelText("Архив"));
    await userEvent.click(screen.getByRole("button", { name: /найти лоты/i }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual(expect.objectContaining({ status: "archive" }));
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
