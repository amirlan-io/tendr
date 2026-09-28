import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { DashboardSidebar } from "./DashboardSidebar";
import { DashboardHeader } from "./DashboardHeader";
import { DashboardMobileNav } from "./DashboardMobileNav";
import { EmbedProvider } from "./Embedded";
import { DASHBOARD_NAV } from "./dashboard.data";

function displayNameOf(email: string | null, metaName: unknown): string {
  if (typeof metaName === "string" && metaName.trim()) return metaName.trim();
  if (email) return email.split("@")[0];
  return "пользователь";
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length > 1) return (parts[0][0] + parts[1][0]).toUpperCase();
  return (name.trim()[0] || "T").toUpperCase();
}

export function DashboardLayout() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const email = user?.email ?? null;
  const metaName = (user?.user_metadata as Record<string, unknown> | undefined)?.["full_name"];
  const displayName = displayNameOf(email, metaName);
  const initials = initialsOf(displayName);
  const tariffLabel = user ? "Пробный доступ" : "";

  const active = DASHBOARD_NAV.find(
    (item) =>
      item.to !== "/dashboard" && location.pathname.startsWith(item.to),
  );
  const currentLabel = active?.label ?? "Обзор";

  // Закрытие drawer по Escape.
  useEffect(() => {
    if (!mobileOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  const confirmSignOut = async () => {
    if (!window.confirm("Выйти из личного кабинета?")) return;
    await signOut();
    navigate("/", { replace: true });
  };

  return (
    <div className="relative min-h-screen overflow-x-clip bg-[#060b0e] text-[#f3f6f5]">
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_75%_5%,rgba(16,185,129,.07),transparent_28%),radial-gradient(circle_at_8%_92%,rgba(37,99,235,.05),transparent_32%)]"
      />
      <DashboardSidebar
        email={email}
        displayName={displayName}
        initials={initials}
        tariffLabel={tariffLabel}
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
        onSignOut={() => void confirmSignOut()}
      />
      <div
        className={`relative min-h-screen transition-[padding] duration-300 ${
          collapsed ? "lg:pl-[84px]" : "lg:pl-[268px]"
        }`}
      >
        <DashboardHeader
          title={currentLabel}
          breadcrumb={["Tendr", currentLabel]}
          initials={initials}
          onOpenMobile={() => setMobileOpen(true)}
          onToggleCollapse={() => setCollapsed((v) => !v)}
          collapsed={collapsed}
        />
        <main className="mx-auto w-full max-w-[1440px] px-4 pb-24 pt-7 sm:px-7 sm:pb-12 sm:pt-9">
          <EmbedProvider>
            <Outlet />
          </EmbedProvider>
        </main>
      </div>
      <DashboardMobileNav />
    </div>
  );
}
