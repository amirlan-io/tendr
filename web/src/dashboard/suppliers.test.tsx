/**
 * Тесты UI агента поставщиков по критериям приёмки ТЗ.
 *
 * Проверяем то, что важно пользователю и что легко сломать:
 *  * объяснение по пунктам ТЗ показывается, а не только процент (F2);
 *  * честное «нет данных» вместо выдуманных характеристик;
 *  * предупреждения видны;
 *  * одобрение/отклонение отправляют фидбек;
 *  * без сгенерированного черновика страница не показывает ложных данных.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { SuppliersPage } from "./pages/Suppliers";
import { SupplierCandidateCard, summarizeMatches } from "./components/SupplierCandidateCard";
import type { SupplierCandidate } from "./suppliers.types";

function makeCandidate(overrides: Partial<SupplierCandidate> = {}): SupplierCandidate {
  return {
    id: 1,
    lot_id: "17699886",
    supplier: "ТОО Ромашка",
    domain: "romashka.kz",
    title: "Фильтр воздушный",
    status: "pending",
    score: 70,
    card: {
      url: "https://romashka.kz/filter",
      price_kzt: 45000,
      in_stock: true,
      city: "Астана",
      delivery_days: 5,
      email: "sales@romashka.kz",
      phone: "+7 727 000 00 00",
      certificates: [],
      warranty: "",
      sources: {},
      is_middleman: false,
    },
    requirement_matches: [
      {
        code: "1",
        title: "Материал: нержавеющая сталь",
        status: "fits",
        comment: "Производитель, сталь 304",
        source_url: "https://romashka.kz/filter",
      },
      {
        code: "2",
        title: "Ресурс не менее 5000 часов",
        status: "unknown",
        comment: "Нет данных от поставщика",
        source_url: "https://romashka.kz/filter",
      },
    ],
    warnings: ["Сертификаты не указаны — запросите подтверждение."],
    ...overrides,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SupplierCandidateCard: сверка по пунктам ТЗ", () => {
  it("показывает статусы по пунктам, а не только общий процент", async () => {
    render(
      <MemoryRouter>
        <SupplierCandidateCard candidate={makeCandidate()} />
      </MemoryRouter>,
    );
    // Общий балл виден, но раскрытая сверка — главное.
    expect(screen.getByText("/100")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /проверка по тз/i }));
    // Статус может встречаться и в сводке, и в списке — берём список пунктов.
    const statuses = screen.getAllByText("Подходит");
    expect(statuses.length).toBeGreaterThan(0);
    expect(screen.getByText("Нет данных")).toBeInTheDocument();
    expect(screen.getByText(/нержавеющая сталь/i)).toBeInTheDocument();
  });

  it("показывает честное «нет данных», а не выдуманную характеристику", async () => {
    render(
      <MemoryRouter>
        <SupplierCandidateCard candidate={makeCandidate()} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /проверка по тз/i }));
    expect(screen.getByText(/Нет данных от поставщика/i)).toBeInTheDocument();
  });

  it("выводит предупреждения поставщика", () => {
    render(
      <MemoryRouter>
        <SupplierCandidateCard candidate={makeCandidate()} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Сертификаты не указаны/i)).toBeInTheDocument();
  });

  it("вызывает фидбек «подходит» и «не подходит»", async () => {
    const onFeedback = vi.fn();
    render(
      <MemoryRouter>
        <SupplierCandidateCard candidate={makeCandidate()} onFeedback={onFeedback} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /как подходящего/i }));
    expect(onFeedback).toHaveBeenCalledWith(true);
    await userEvent.click(screen.getByRole("button", { name: /как не подходящего/i }));
    expect(onFeedback).toHaveBeenCalledWith(false);
  });

  it("источник характеристики открывается безопасно (noopener noreferrer)", async () => {
    render(
      <MemoryRouter>
        <SupplierCandidateCard candidate={makeCandidate()} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /проверка по тз/i }));
    const links = screen.getAllByRole("link", { name: /источник/i });
    const link = links[0];
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.getAttribute("rel")).toContain("noreferrer");
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("суммирует статусы сверки", () => {
    const summary = summarizeMatches([
      { status: "fits" },
      { status: "fits" },
      { status: "no" },
      { status: "unknown" },
    ]);
    expect(summary.fits).toBe(2);
    expect(summary.no).toBe(1);
    expect(summary.unknown).toBe(1);
  });
});

describe("SuppliersPage: пустое состояние и ошибки", () => {
  it("показывает пустое состояние без фейковых данных", () => {
    render(
      <MemoryRouter>
        <SuppliersPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Поиск ещё не запускался/i)).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("требует ID лота и не показывает выдуманных кандидатов", async () => {
    render(
      <MemoryRouter>
        <SuppliersPage />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /найти поставщиков/i }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Укажите ID лота/i);
    });
    expect(screen.queryByText(/Найдено поставщиков/i)).not.toBeInTheDocument();
  });

  it("ошибка API показывается понятно, без сырого detail бэкенда", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "traceback secret stack line 42" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(
      <MemoryRouter>
        <SuppliersPage />
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText(/ID лота/i), "17699886");
    await userEvent.click(screen.getByRole("button", { name: /найти поставщиков/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).not.toContain("traceback");
    expect(alert.textContent).not.toContain("stack");
  });

  it("при успешном поиске показывает карточки поставщиков", async () => {
    const candidate = makeCandidate();
    // Страница сначала спрашивает требования ТЗ, потом запускает поиск.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown) => {
        if (String(url).includes("/requirements")) {
          return new Response(
            JSON.stringify({
              lot_id: "17699886",
              title: "Поставка фильтров",
              customer: "Акимат",
              budget_kzt: 500000,
              requirements: [{ code: "1", title: "Сталь 304" }],
              has_analysis: true,
              message: "",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(
          JSON.stringify({
            lot_id: "17699886",
            candidates: [candidate],
            queries: ["фильтр воздушный купить"],
            summary: "Найдено поставщиков: 1",
            blocked_filtered: 0,
            costs_usd: { llm: 0.001, tavily: 0.008, browser: 0 },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );
    render(
      <MemoryRouter>
        <SuppliersPage />
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText(/ID лота/i), "17699886");
    await userEvent.click(screen.getByRole("button", { name: /найти поставщиков/i }));
    expect(await screen.findByText(/Найдено поставщиков/i)).toBeInTheDocument();
    expect(screen.getByRole("article")).toBeInTheDocument();
    // Показан лот, по которому искали, — с требованиями ТЗ.
    expect(screen.getByText("Поставка фильтров")).toBeInTheDocument();
    expect(screen.getByText("Сталь 304")).toBeInTheDocument();
  });

  it("без разбора ТЗ честно объясняет, что сначала нужен анализ", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown) => {
        if (String(url).includes("/requirements")) {
          return new Response(
            JSON.stringify({
              lot_id: "999",
              title: "",
              customer: "",
              budget_kzt: null,
              requirements: [],
              has_analysis: false,
              message: "Для этого лота ещё нет разбора ТЗ. Запустите AI-анализ.",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        throw new Error("поиск не должен запускаться без требований");
      }),
    );
    render(
      <MemoryRouter>
        <SuppliersPage />
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText(/ID лота/i), "999");
    await userEvent.click(screen.getByRole("button", { name: /найти поставщиков/i }));
    expect(await screen.findByText(/нет разбора ТЗ/i)).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });
});