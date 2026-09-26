import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Layout } from "../Layout";
import { supabase } from "../supabase";

export function AuthCallbackPage() {
  const navigate = useNavigate();
  const [isRecovery, setIsRecovery] = useState(() =>
    /(?:[?#&])type=recovery(?:&|$)/.test(window.location.href),
  );
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!supabase) return;
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") setIsRecovery(true);
    });
    const timeout = isRecovery
      ? undefined
      : window.setTimeout(() => navigate("/", { replace: true }), 1200);
    return () => {
      if (timeout) window.clearTimeout(timeout);
      data.subscription.unsubscribe();
    };
  }, [isRecovery, navigate]);

  const updatePassword = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (!supabase) {
      setError("Авторизация не настроена.");
      return;
    }
    if (password.length < 8) {
      setError("Пароль должен содержать не менее 8 символов.");
      return;
    }
    if (password !== confirmation) {
      setError("Пароли не совпадают.");
      return;
    }
    setBusy(true);
    const { error: authError } = await supabase.auth.updateUser({ password });
    setBusy(false);
    if (authError) {
      setError("Не удалось изменить пароль. Запросите новую ссылку.");
      return;
    }
    navigate("/", { replace: true });
  };

  if (isRecovery) {
    return (
      <Layout>
        <div className="mx-auto flex min-h-[70vh] max-w-md items-center px-6">
          <form
            onSubmit={updatePassword}
            className="w-full rounded-3xl border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-8 shadow-2xl"
          >
            <h1 className="text-2xl font-semibold">Новый пароль</h1>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              Придумайте новый пароль длиной не менее 8 символов.
            </p>
            {error && (
              <div className="mt-5 rounded-xl bg-red-500/10 p-3 text-sm text-red-500">
                {error}
              </div>
            )}
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Новый пароль"
              className="mt-6 w-full rounded-xl border border-[var(--border-strong)] bg-[var(--bg)] px-4 py-3 outline-none focus:border-emerald-500"
              required
              minLength={8}
            />
            <input
              type="password"
              autoComplete="new-password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              placeholder="Повторите пароль"
              className="mt-3 w-full rounded-xl border border-[var(--border-strong)] bg-[var(--bg)] px-4 py-3 outline-none focus:border-emerald-500"
              required
              minLength={8}
            />
            <button
              type="submit"
              disabled={busy}
              className="mt-5 w-full rounded-xl bg-emerald-500 px-4 py-3 font-semibold text-white disabled:opacity-50"
            >
              {busy ? "Сохраняем…" : "Сохранить пароль"}
            </button>
          </form>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="mx-auto flex min-h-[60vh] max-w-xl items-center justify-center px-6 text-center">
        <div>
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-emerald-500/25 border-t-emerald-500" />
          <h1 className="mt-5 text-2xl font-semibold">Подтверждаем вход</h1>
          <p className="mt-2 text-sm text-[var(--text-muted)]">Сейчас вы вернётесь в Tendr.</p>
        </div>
      </div>
    </Layout>
  );
}
