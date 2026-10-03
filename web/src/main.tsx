import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import { HomePage } from "./pages/Home";
import { AnalyzePage } from "./pages/Analyze";
import { HistoryPage } from "./pages/History";
import { AdminPage } from "./pages/Admin";
import { B2GPage } from "./pages/B2G";
import { LotsPage } from "./pages/Lots";
import { NotFoundPage } from "./pages/NotFound";
import { UiPreviewPage } from "./pages/UiPreview";
import { getOrCreateClientId } from "./clientId";
import { applyTheme } from "./theme";
import { AuthProvider } from "./auth/AuthContext";
import { AuthPage } from "./pages/Auth";
import { AuthCallbackPage } from "./pages/AuthCallback";
import { RequireAuth } from "./auth/RequireAuth";
import { DashboardLayout } from "./dashboard/DashboardLayout";
import { OverviewPage } from "./dashboard/pages/Overview";
import { BillingPage } from "./dashboard/pages/Billing";
import { SettingsPage } from "./dashboard/pages/Settings";
import { DocumentsPage } from "./dashboard/pages/Documents";
import { SuppliersPage } from "./dashboard/pages/Suppliers";
import { installErrorReporting } from "./monitoring/errorReporter";

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
        <Routes>
          <Route path="/" element={<HomePage />} />
          {/* Standalone-маршруты сохранены: существующие ссылки не ломаются. */}
          <Route path="/analyze" element={<AnalyzePage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/b2g" element={<B2GPage />} />
          <Route path="/lots" element={<LotsPage />} />
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
            <Route path="history" element={<HistoryPage embedded />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="suppliers" element={<SuppliersPage />} />
            <Route path="b2g" element={<B2GPage embedded />} />
            <Route path="billing" element={<BillingPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>,
);
