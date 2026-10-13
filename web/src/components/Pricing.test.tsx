import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Pricing } from "./Pricing";
import { UsageCard } from "../dashboard/components/UsageCard";
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: null }) }));
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("new tariff policy", () => {
  it("shows the agreed prices and five-hour analysis limits without credits", () => {
    const { container } = render(<MemoryRouter><Pricing /></MemoryRouter>);
    for (const [name, price, limit] of [["Plus", "5 000", "5"], ["Pro", "10 000", "10"], ["Ultra", "25 000", "20"]]) {
      const card = screen.getByRole("heading", { name }).closest("article") ?? screen.getByRole("heading", { name }).parentElement!.parentElement!;
      expect(card?.textContent?.replace(/\u00a0/g, " ")).toContain(price);
      const limits = screen.getByLabelText(`Лимиты тарифа ${name}`);
      expect(within(limits).getByText(limit)).toBeInTheDocument();
      expect(within(limits).getByText("AI-анализов")).toBeInTheDocument();
    }
    expect(container.textContent).not.toMatch(/кредит/i);
    expect(screen.getByText(/Без месячного лимита анализов/)).toBeInTheDocument();
    expect(screen.getByText("Поиск поставщиков")).toBeInTheDocument();
  });

  it("shows remaining analyses and a live countdown to the full reset", () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
    render(<MemoryRouter><UsageCard tariffName="Plus" limit={5} used={2} remaining={3} renewsAt="2026-10-13T12:15:00Z" /></MemoryRouter>);
    expect(screen.getByText(/Использовано 2 из 5 анализов за 5 часов/)).toHaveTextContent("осталось 3");
    expect(screen.getByText("Обновление через 2 ч 15 мин")).toBeInTheDocument();
  });
});
