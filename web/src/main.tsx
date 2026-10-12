import React, { Suspense } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import "./index.css";
import { getOrCreateClientId } from "./clientId";
import { applyTheme } from "./theme";
import { AuthProvider } from "./auth/AuthContext";
import { AuthPage } from "./pages/Auth";
import { AuthCallbackPage } from "./pages/AuthCallback";
import { RequireAuth } from "./auth/RequireAuth";
import { installErrorReporting } from "./monitoring/errorReporter";

const HomePage = React.lazy(() => import("./pages/Home").then((m) => ({ default: m.HomePage })));
const AnalyzePage = React.lazy(() => import("./pages/Analyze").then((m) => ({ default: m.AnalyzePage })));
const HistoryPage = React.lazy(() => import("./pages/History").then((m) => ({ default: m.HistoryPage })));
const AdminPage = React.lazy(() => import("./pages/Admin").then((m) => ({ default: m.AdminPage })));
const B2GPage = React.lazy(() => import("./pages/B2G").then((m) => ({ default: m.B2GPage })));
const LotsPage = React.lazy(() => import("./pages/Lots").then((m) => ({ default: m.LotsPage })));
const LotDetailsPage = React.lazy(() => import("./pages/LotDetails").then((m) => ({ default: m.LotDetailsPage })));
const NotFoundPage = React.lazy(() => import("./pages/NotFound").then((m) => ({ default: m.NotFoundPage })));
const UiPreviewPage = React.lazy(() => import("./pages/UiPreview").then((m) => ({ default: m.UiPreviewPage })));
const DashboardLayout = React.lazy(() => import("./dashboard/DashboardLayout").then((m) => ({ default: m.DashboardLayout })));
const OverviewPage = React.lazy(() => import("./dashboard/pages/Overview").then((m) => ({ default: m.OverviewPage })));
const BillingPage = React.lazy(() => import("./dashboard/pages/Billing").then((m) => ({ default: m.BillingPage })));
const SettingsPage = React.lazy(() => import("./dashboard/pages/Settings").then((m) => ({ default: m.SettingsPage })));
const DocumentsPage = React.lazy(() => import("./dashboard/pages/Documents").then((m) => ({ default: m.DocumentsPage })));
const SuppliersPage = React.lazy(() => import("./dashboard/pages/Suppliers").then((m) => ({ default: m.SuppliersPage })));
const SandboxPage = React.lazy(() => import("./dashboard/pages/Sandbox").then((m) => ({ default: m.SandboxPage })));

function RouteFallback() {
  return <div role="status" className="flex min-h-screen items-center justify-center bg-[#0a0a0b] text-sm text-white/65">Загружаем раздел…</div>;
}

function LegacyLotRedirect() {
  const { lotId = "" } = useParams();
  return <Navigate replace to={`/dashboard/lots/${encodeURIComponent(lotId)}`} />;
}

// Сразу создаём client_id при загрузке.
// Контролируемая ошибка (нет Web Crypto) не должна ронять старт приложения.
try {
  getOrCreateClientId();
} catch {
  /* первый API-запрос вернёт понятную ошибку */
}
// Применяем тему до рендера, чтобы избежать flash
applyTheme("dark");

// Автосообщения об ошибках: необработанные JS-ошибки и отклонённые
// промисы уходят на backend и дальше владельцу в Telegram.
installErrorReporting(window.location.pathname);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          {/* Старые ссылки сохраняются, но приватные функции открываются только в кабинете. */}
          <Route path="/analyze" element={<RequireAuth><Navigate replace to="/dashboard/analyze" /></RequireAuth>} />
          <Route path="/history" element={<RequireAuth><Navigate replace to="/dashboard/history" /></RequireAuth>} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/b2g" element={<RequireAuth><Navigate replace to="/dashboard/b2g" /></RequireAuth>} />
          <Route path="/lots" element={<RequireAuth><Navigate replace to="/dashboard/lots" /></RequireAuth>} />
          <Route path="/lots/:lotId" element={<RequireAuth><LegacyLotRedirect /></RequireAuth>} />
          <Route path="/login" element={<AuthPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          {/* Песочница shadcn-компонентов для ручной проверки. */}
          <Route path="/ui-preview" element={<UiPreviewPage />} />
          {/* Личный кабинет: все маршруты внутри DashboardLayout под RequireAuth. */}
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <DashboardLayout />
              </RequireAuth>
            }
          >
            <Route index element={<OverviewPage />} />
            <Route path="analyze" element={<AnalyzePage embedded />} />
            <Route path="lots" element={<LotsPage embedded />} />
            <Route path="lots/:lotId" element={<LotDetailsPage embedded />} />
            <Route path="history" element={<HistoryPage embedded />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="suppliers" element={<SuppliersPage />} />
            <Route path="sandbox" element={<SandboxPage />} />
            <Route path="b2g" element={<B2GPage embedded />} />
            <Route path="billing" element={<BillingPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>,
);
