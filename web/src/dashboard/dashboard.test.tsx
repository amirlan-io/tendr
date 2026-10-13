import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { User } from "@supabase/supabase-js";
import { RequireAuth } from "../auth/RequireAuth";
import { DashboardLayout } from "./DashboardLayout";
import { OverviewPage } from "./pages/Overview";
import { BillingPage } from "./pages/Billing";
import { SettingsPage } from "./pages/Settings";

const { mockUseAuth } = vi.hoisted(() => ({ mockUseAuth: vi.fn() }));

vi.mock("../auth/AuthContext", () => ({
  useAuth: mockUseAuth,
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const updateUserMock = vi.fn();
const signOutMock = vi.fn();
const resetPasswordMock = vi.fn();

vi.mock("../supabase", () => ({
  isSupabaseConfigured: true,
  supabase: {
    auth: {
      updateUser: (...args: unknown[]) => updateUserMock(...args),
      signOut: (...args: unknown[]) => signOutMock(...args),
      resetPasswordForEmail: (...args: unknown[]) => resetPasswordMock(...args),
    },
  },
  getAccessToken: async () => null,
}));

const authedUser = {
  email: "user@example.com",
  user_metadata: { full_name: "Айгерим Нурланова" },
  app_metadata: { provider: "email" },
  created_at: "2026-01-15T10:00:00Z",
} as unknown as User;

function authAs(user: User | null) {
  mockUseAuth.mockReturnValue({
    session: user ? { user } : null,
    user,
    loading: false,
    signOut: signOutMock,
  });
}

function renderApp(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<p>Страница входа</p>} />
        <Route path="/" element={<p>Лендинг</p>} />
        <Route
          path="/dashboard"
          element={
            <RequireAuth>
              <DashboardLayout />
            </RequireAuth>
          }
        >
          <Route index element={<OverviewPage />} />
          <Route path="billing" element={<BillingPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
  updateUserMock.mockReset().mockResolvedValue({ data: {}, error: null });
  signOutMock.mockReset().mockResolvedValue({ error: null });
  resetPasswordMock.mockReset().mockResolvedValue({ data: {}, error: null });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify({ detail: "Not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
});

afterEach(() => {
  cleanup();
});

describe("Защита маршрутов", () => {
  it("гость с /dashboard перенаправляется на /login", async () => {
    authAs(null);
    renderApp("/dashboard");
    expect(await screen.findByText("Страница входа")).toBeInTheDocument();
  });

  it("авторизованный пользователь видит Dashboard", async () => {
    authAs(authedUser);
    renderApp("/dashboard");
    expect(await screen.findByText(/Здравствуйте, Айгерим Нурланова/)).toBeInTheDocument();
  });
});

describe("Sidebar", () => {
  it("подсвечивает активный маршрут", async () => {
    authAs(authedUser);
    renderApp("/dashboard/billing");
    const link = await screen.findByRole("link", { name: "Тариф и лимиты" });
    expect(link).toHaveAttribute("aria-current", "page");
  });

  it("мобильное меню открывается и закрывается по Escape", async () => {
    authAs(authedUser);
    renderApp("/dashboard");
    await screen.findByText(/Здравствуйте/);
    await userEvent.click(screen.getByRole("button", { name: "Открыть меню" }));
    const aside = document.querySelector("aside");
    expect(aside?.className).toContain("translate-x-0");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => {
      expect(document.querySelector("aside")?.className).toContain("-translate-x-full");
    });
  });

  it("Ctrl+K открывает поиск и переводит в найденный раздел", async () => {
    authAs(authedUser);
    renderApp("/dashboard");
    await screen.findByText(/Здравствуйте/);
    await userEvent.keyboard("{Control>}k{/Control}");
    const dialog = screen.getByRole("dialog", { name: "Поиск по кабинету" });
    await userEvent.type(within(dialog).getByPlaceholderText("Найти раздел или действие..."), "тариф");
    await userEvent.click(within(dialog).getByRole("link", { name: /Тариф и лимиты/ }));
    expect(await screen.findByLabelText("Тариф Plus")).toBeInTheDocument();
  });
});

describe("Профиль", () => {
  it("загружается из Supabase metadata", async () => {
    authAs(authedUser);
    renderApp("/dashboard/settings");
    expect(await screen.findByDisplayValue("Айгерим Нурланова")).toBeInTheDocument();
    expect(screen.getByDisplayValue("user@example.com")).toBeInTheDocument();
  });

  it("сохраняется через updateUser", async () => {
    authAs(authedUser);
    renderApp("/dashboard/settings");
    const name = await screen.findByDisplayValue("Айгерим Нурланова");
    await userEvent.clear(name);
    await userEvent.type(name, "Айгерим Н.");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));
    await waitFor(() => {
      expect(updateUserMock).toHaveBeenCalledWith({
        data: expect.objectContaining({ full_name: "Айгерим Н." }),
      });
    });
    expect(await screen.findByText("Профиль сохранён.")).toBeInTheDocument();
  });

  it("ошибка сохранения отображается безопасным текстом", async () => {
    updateUserMock.mockResolvedValue({ data: null, error: { message: "db exploded: secret" } });
    authAs(authedUser);
    renderApp("/dashboard/settings");
    const name = await screen.findByDisplayValue("Айгерим Нурланова");
    await userEvent.type(name, "!");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("secret");
    expect(alert.textContent).not.toContain("exploded");
  });
});

describe("Выход", () => {
  it("завершает сессию и ведёт на лендинг", async () => {
    vi.stubGlobal("confirm", () => true);
    authAs(authedUser);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderApp("/dashboard");
    await screen.findByText(/Здравствуйте/);
    const buttons = screen.getAllByRole("button", { name: "Выйти" });
    await userEvent.click(buttons[0]);
    await waitFor(() => {
      expect(signOutMock).toHaveBeenCalled();
    });
    expect(await screen.findByText("Лендинг")).toBeInTheDocument();
    confirmSpy.mockRestore();
  });
});

describe("Пустые состояния и тарифы", () => {
  it("overview без данных показывает empty state, а не фейк", async () => {
    authAs(authedUser);
    renderApp("/dashboard");
    expect(await screen.findByText("Пока тихо")).toBeInTheDocument();
    expect(screen.getByText("Дедлайнов нет")).toBeInTheDocument();
  });

  it("тарифы Plus/Pro/Ultra честно показывают, что оплата не настроена", async () => {
    authAs(authedUser);
    renderApp("/dashboard/billing");
    expect(await screen.findByLabelText("Тариф Plus")).toBeInTheDocument();
    expect(screen.getByLabelText("Тариф Pro")).toBeInTheDocument();
    expect(screen.getByLabelText("Тариф Ultra")).toBeInTheDocument();
    for (const btn of await screen.findAllByRole("button", { name: "Оплата не настроена" })) {
      expect(btn).toBeDisabled();
    }
    expect(screen.getByText(/Если кнопка неактивна, онлайн-оплата пока недоступна/)).toBeInTheDocument();
  });
});
