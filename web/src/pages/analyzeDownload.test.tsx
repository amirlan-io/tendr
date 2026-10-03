import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AnalyzePage } from "./Analyze";
import { AuthProvider } from "../auth/AuthContext";

function renderPage() {
  return render(
    <AuthProvider>
      <MemoryRouter>
        <AnalyzePage />
      </MemoryRouter>
    </AuthProvider>,
  );
}

const ANALYSIS = {
  lot: {
    lot_id: "17266377",
    title: "Поставка мебели",
    customer: "Акимат",
    method: "конкурс",
    requirements: [],
    documents_required: [],
    summary: "Сводка",
    red_flags: [],
  },
  legal: {
    items: [],
    overall_risk: "medium",
    summary: "Юридическая сводка",
    complaint_draft: "Текст жалобы",
  },
};

function stubBlobUrls() {
  if (!window.URL.createObjectURL) {
    Object.defineProperty(window.URL, "createObjectURL", {
      value: vi.fn(() => "blob:fake"),
      writable: true,
      configurable: true,
    });
  }
  if (!window.URL.revokeObjectURL) {
    Object.defineProperty(window.URL, "revokeObjectURL", {
      value: vi.fn(),
      writable: true,
      configurable: true,
    });
  }
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
  stubBlobUrls();
});

afterEach(() => {
  cleanup();
});

describe("AnalyzePage: скачивание через downloadBlob", () => {
  function mockApi(downloadStatus: number) {
    const calls: string[] = [];
    let jobCreated = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown, init?: RequestInit) => {
        const u = String(url);
        calls.push(u);
        if (u === "/api/lots/analysis-jobs/active") {
          return new Response("null", {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (u === "/api/lots/analysis-jobs" && init?.method === "POST") {
          jobCreated = true;
          return new Response(JSON.stringify({
            id: "job-1",
            kind: "url",
            status: "queued",
            progress: 3,
            stage: "Задание сохранено",
            input_label: "https://goszakup.gov.kz/ru/announce/show/17266377",
            result: null,
          }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (u === "/api/lots/analysis-jobs/job-1" && jobCreated) {
          return new Response(JSON.stringify({
            id: "job-1",
            kind: "url",
            status: "completed",
            progress: 100,
            stage: "Разбор готов",
            input_label: "https://goszakup.gov.kz/ru/announce/show/17266377",
            result: ANALYSIS,
          }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (u.startsWith("/api/lots/17266377/download")) {
          if (downloadStatus === 200) return new Response(new Blob(["x"]), { status: 200 });
          return new Response(JSON.stringify({ detail: "Not found" }), {
            status: downloadStatus,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    return calls;
  }

  async function runAnalysis() {
    renderPage();
    await userEvent.type(screen.getByLabelText("Анализ лота"), "https://goszakup.gov.kz/ru/announce/show/17266377");
    await waitFor(() => expect(screen.getByRole("button", { name: "Анализировать" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Анализировать" }));
    await userEvent.click(await screen.findByText("Открыть полный разбор и скачать документы"));
    expect(await screen.findByText("Скачать отчёт DOCX")).toBeInTheDocument();
  }

  it("кнопка отчёта качает через /download?kind=report", async () => {
    const calls = mockApi(200);
    await runAnalysis();
    await userEvent.click(screen.getByRole("button", { name: /Скачать отчёт/ }));
    await waitFor(() => {
      expect(calls).toContain("/api/lots/17266377/download?kind=report");
    });
  });

  it("жалоба показана только при наличии draft и качает kind=complaint", async () => {
    const calls = mockApi(200);
    await runAnalysis();
    await userEvent.click(screen.getByRole("button", { name: /Скачать жалобу/ }));
    await waitFor(() => {
      expect(calls).toContain("/api/lots/17266377/download?kind=complaint");
    });
  });

  it("404 показывает безопасное сообщение без сырого detail", async () => {
    mockApi(404);
    await runAnalysis();
    await userEvent.click(screen.getByRole("button", { name: /Скачать отчёт/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).not.toContain("Not found");
  });
});

describe("AnalyzePage: диалог с AI-аналитиком", () => {
  it("отправляет обычный вопрос в чат и показывает ответ", async () => {
    let chatBody: Record<string, unknown> | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown, init?: RequestInit) => {
        const path = String(url);
        if (path === "/api/lots/analysis-jobs/active") {
          return new Response("null", {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (path === "/api/lots/assistant/chat") {
          chatBody = JSON.parse(String(init?.body || "{}"));
          return new Response(JSON.stringify({ answer: "Пришлите ссылку или ID лота с Госзакупок." }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    renderPage();
    await userEvent.type(screen.getByLabelText("Анализ лота"), "Как со мной работать?");
    await userEvent.click(screen.getByRole("button", { name: "Анализировать" }));

    expect(await screen.findByText("Пришлите ссылку или ID лота с Госзакупок.")).toBeInTheDocument();
    expect(chatBody).toMatchObject({
      message: "Как со мной работать?",
      job_id: null,
      history: [],
    });
  });
});
