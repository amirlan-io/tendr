import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SandboxPage } from "./Sandbox";
import { api } from "../../clientId";

vi.mock("../../clientId", () => ({ api: vi.fn(), ApiError: class extends Error {} }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("shows rejected and unconfirmed suppliers outside the shortlist", async () => {
  vi.mocked(api).mockResolvedValue({
    lot_id: "123", total: 0, duration_sec: 1, requirements: [], candidates: [],
    trace: { queries: [], direct_queries: [], found_before_filters: 2, blocked_filtered: 0,
      verification_gaps: [{ code: "r", title: "Регулятор", status: "specs_unconfirmed", reason: "Характеристики не подтверждены." }],
      pages_read: 1, personalization: "", filters_applied: {} },
    costs: { llm_usd: 0, tavily_usd: 0, browser_usd: 0, total_usd: 0,
      llm_calls: 1, tavily_calls: 1, browser_calls: 0, is_estimate: true },
    rejected_candidates: [
      { domain: "wrong.kz", url: "https://wrong.kz", title: "Стеллаж", rejection_reason: "mandatory_mismatch" },
      { domain: "unknown.kz", url: "https://unknown.kz", title: "Стол", rejection_reason: "unconfirmed" },
    ],
  });
  const user = userEvent.setup();
  render(<SandboxPage />);
  await user.type(screen.getByLabelText("ID лота"), "123");
  await user.click(screen.getByRole("button", { name: "Запустить" }));
  expect(await screen.findByText("Кандидаты (0)")).toBeInTheDocument();
  expect(screen.getByText("Регулятор: Характеристики не подтверждены.")).toBeInTheDocument();
  expect(screen.getByText("Отклонённые кандидаты (2)")).toBeInTheDocument();
  expect(screen.getByText(/Стеллаж — Не соответствует обязательным требованиям/)).toBeInTheDocument();
  expect(screen.getByText(/Стол — Не хватает подтверждённых данных/)).toBeInTheDocument();
});
