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
import { getOrCreateClientId } from "./clientId";
import { applyTheme, getTheme } from "./theme";
import { AuthProvider } from "./auth/AuthContext";
import { AuthPage } from "./pages/Auth";
import { AuthCallbackPage } from "./pages/AuthCallback";

// Сразу создаём client_id при загрузке.
// Контролируемая ошибка (нет Web Crypto) не должна ронять старт приложения.
try {
  getOrCreateClientId();
} catch {
  /* первый API-запрос вернёт понятную ошибку */
}
// Применяем тему до рендера, чтобы избежать flash
applyTheme(getTheme());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/analyze" element={<AnalyzePage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/b2g" element={<B2GPage />} />
          <Route path="/lots" element={<LotsPage />} />
          <Route path="/login" element={<AuthPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>,
);
