import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SidebarNavPreview, { SidebarNav } from "./dashboard-sidebar";

afterEach(() => {
  cleanup();
});

describe("SidebarNav", () => {
  it("рендерит группы, заголовки и нижние пункты", () => {
    render(<SidebarNav />);
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(screen.getByText("Developers")).toBeInTheDocument();
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("Log out")).toBeInTheDocument();
  });

  it("показывает badge и shortcut", () => {
    render(<SidebarNav />);
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("⌘K")).toBeInTheDocument();
  });

  it("клик по пункту без детей вызывает onSelect", async () => {
    const onSelect = vi.fn();
    render(<SidebarNav onSelect={onSelect} />);
    await userEvent.click(screen.getByText("Calendar"));
    expect(onSelect).toHaveBeenCalledWith("calendar");
  });

  it("родительский пункт раскрывает/скрывает детей", async () => {
    render(<SidebarNav />);
    const teamRow = screen.getByText("Team").closest('[role="treeitem"]') as HTMLElement;
    expect(teamRow).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(screen.getByText("Team"));
    expect(teamRow).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Engineering")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Team"));
    expect(teamRow).toHaveAttribute("aria-expanded", "false");
  });

  it("пункты доступны с клавиатуры", async () => {
    const onSelect = vi.fn();
    render(<SidebarNav onSelect={onSelect} />);
    const row = screen.getByText("Calendar").closest('[role="treeitem"]') as HTMLElement;
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("calendar");
  });

  it("контролируемый activeId подсвечивает пункт", () => {
    render(<SidebarNav activeId="finance" />);
    expect(screen.getByText("Finance").closest("[aria-selected='true']")).not.toBeNull();
  });

  it("переключатель workspace открывает список и выбирает", async () => {
    const onWorkspaceSelect = vi.fn();
    render(<SidebarNav activeWorkspace="Acme Corp" onWorkspaceSelect={onWorkspaceSelect} />);
    await userEvent.click(screen.getByText("Acme Corp"));
    await userEvent.click(screen.getByText("Personal Workspace"));
    expect(onWorkspaceSelect).toHaveBeenCalledWith("Personal Workspace");
  });
});

describe("SidebarNavPreview", () => {
  it("клик Search открывает модалку поиска, X закрывает", async () => {
    render(<SidebarNavPreview />);
    await userEvent.click(screen.getByText("Search"));
    expect(screen.getByPlaceholderText(/Search projects/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Закрыть поиск" }));
    expect(screen.queryByPlaceholderText(/Search projects/i)).not.toBeInTheDocument();
  });

  it("кнопка сворачивает и разворачивает панель", async () => {
    render(<SidebarNavPreview />);
    const toggle = screen.getByRole("button", { name: "Свернуть панель" });
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Развернуть панель" })).toBeInTheDocument();
  });

  it("выбор пункта меняет заголовок breadcrumb", async () => {
    const { container } = render(<SidebarNavPreview />);
    const navCalendar = screen.getByText("Calendar", {
      selector: ".text-\\[13px\\]",
    });
    await userEvent.click(navCalendar);
    await waitFor(() => {
      const crumb = container.querySelector(".h-14 .font-medium.text-foreground.truncate");
      expect(crumb?.textContent).toBe("Calendar");
    });
  });
});
