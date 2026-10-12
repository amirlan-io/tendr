import { FormEvent, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Layout } from "../Layout";
import { useAuth } from "../auth/AuthContext";
import { isSupabaseConfigured, supabase } from "../supabase";

type Mode = "login" | "register" | "reset";

function friendlyAuthError(message: string): string {
  const normalized = message.toLowerCase();
  if (normalized.includes("invalid login credentials")) {
    return "Неверная почта или пароль.";
  }
  if (normalized.includes("email not confirmed")) {
    return "Подтвердите почту по ссылке из письма.";
  }
  if (normalized.includes("already registered")) {
    return "Аккаунт с такой почтой уже существует.";
  }
  if (normalized.includes("rate limit")) {
    return "Слишком много попыток. Попробуйте немного позже.";
  }
  if (normalized.includes("provider is not enabled") || normalized.includes("unsupported provider")) {
    return "Вход через Google ещё не включён в настройках Supabase.";
  }
  return "Не удалось выполнить вход. Проверьте данные и попробуйте снова.";
}

export function AuthPage() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedMode = searchParams.get("mode");
  const mode: Mode = requestedMode === "register" || requestedMode === "reset" ? requestedMode : "login";
  const setMode = (next: Mode) => {
    setSearchParams(next === "login" ? {} : { mode: next });
    setError("");
    setNotice("");
    setPassword("");
    setShowPassword(false);
  };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [oauthBusy, setOauthBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  if (!loading && user) return <Navigate to="/dashboard" replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");

    if (!supabase) {
      setError("Supabase ещё не подключён. Добавьте настройки в web/.env.");
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setError("Введите корректный адрес электронной почты.");
      return;
    }
    if (mode !== "reset" && password.length < 8) {
      setError("Пароль должен содержать не менее 8 символов.");
      return;
    }

    setBusy(true);
    try {
      if (mode === "login") {
        const { error: authError } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        });
        if (authError) throw authError;
        navigate("/dashboard", { replace: true });
      } else if (mode === "register") {
        const { data, error: authError } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: {
            emailRedirectTo: `${window.location.origin}/auth/callback`,
          },
        });
        if (authError) throw authError;
        if (data.session) {
          navigate("/dashboard", { replace: true });
        } else {
          setNotice("Мы отправили письмо. Откройте его и подтвердите регистрацию.");
        }
      } else {
        const { error: authError } = await supabase.auth.resetPasswordForEmail(
          email.trim(),
          { redirectTo: `${window.location.origin}/auth/callback` },
        );
        if (authError) throw authError;
        setNotice("Ссылка для восстановления пароля отправлена на почту.");
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "";
      setError(friendlyAuthError(message));
    } finally {
      setBusy(false);
    }
  };

  const continueWithGoogle = async () => {
    setError("");
    setNotice("");
    if (!supabase) {
      setError("Supabase ещё не подключён. Добавьте настройки в web/.env.");
      return;
    }

    setOauthBusy(true);
    const { error: authError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
        queryParams: {
          prompt: "select_account",
        },
      },
    });
    if (authError) {
      setError(friendlyAuthError(authError.message));
      setOauthBusy(false);
    }
  };

  const title =
    mode === "login"
      ? "С возвращением"
      : mode === "register"
        ? "Создайте аккаунт"
        : "Восстановление доступа";
  const subtitle =
    mode === "login"
      ? "Войдите, чтобы хранить историю и управлять тарифом."
      : mode === "register"
        ? "Один аккаунт для анализа закупок и совместной работы."
        : "Мы отправим безопасную ссылку на вашу почту.";

  return (
    <Layout>
      <section className="relative min-h-[calc(100vh-8rem)] overflow-hidden px-5 py-12 sm:py-20">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute left-[8%] top-12 h-64 w-64 rounded-full bg-emerald-500/10 blur-3xl" />
          <div className="absolute bottom-10 right-[8%] h-72 w-72 rounded-full bg-cyan-500/10 blur-3xl" />
          <div className="auth-grid absolute inset-0 opacity-40" />
        </div>

        <div className="relative mx-auto grid max-w-5xl items-center gap-10 lg:grid-cols-[1.05fr_.95fr]">
          <div className="hidden lg:block">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-500">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              Защищённый кабинет Tendr
            </div>
            <h1 className="max-w-xl text-5xl font-semibold leading-[1.08] tracking-tight">
              Закупки становятся понятнее, когда всё хранится в одном месте.
            </h1>
            <p className="mt-6 max-w-lg text-lg leading-8 text-[var(--text-muted)]">
              Входите по электронной почте — без Telegram. История анализов,
              квота и будущие тарифы будут привязаны к вашему аккаунту.
            </p>
            <div className="mt-9 grid max-w-lg grid-cols-3 gap-3">
              {[
                ["01", "Безопасный вход"],
                ["02", "История лотов"],
                ["03", "Единый тариф"],
              ].map(([number, label]) => (
                <div
                  key={number}
                  className="rounded-2xl border border-[var(--border)] bg-[var(--bg-elevated)]/70 p-4 backdrop-blur"
                >
                  <div className="text-xs font-semibold text-emerald-500">{number}</div>
                  <div className="mt-2 text-sm font-medium">{label}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[28px] border border-[var(--border-strong)] bg-[var(--bg-elevated)]/90 p-6 shadow-2xl shadow-emerald-950/10 backdrop-blur-xl sm:p-9">
            <div className="mb-8">
              <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-emerald-600 font-bold text-white shadow-lg shadow-emerald-500/20">
                T
              </div>
              <h2 className="text-3xl font-semibold tracking-tight">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">{subtitle}</p>
            </div>

            {!isSupabaseConfigured && (
              <div className="mb-5 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-600 dark:text-amber-300">
                Авторизация ещё не настроена. Заполните VITE_SUPABASE_URL и
                VITE_SUPABASE_PUBLISHABLE_KEY в web/.env.
              </div>
            )}
            {error && (
              <div role="alert" className="mb-5 rounded-xl border border-red-500/25 bg-red-500/10 p-3 text-sm text-red-500">
                {error}
              </div>
            )}
            {notice && (
              <div className="mb-5 rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-3 text-sm text-emerald-600 dark:text-emerald-300">
                {notice}
              </div>
            )}

            {mode !== "reset" && (
              <>
                <button
                  type="button"
                  onClick={() => void continueWithGoogle()}
                  disabled={busy || oauthBusy || !isSupabaseConfigured}
                  className="flex w-full items-center justify-center gap-3 rounded-xl border border-[var(--border-strong)] bg-[var(--bg)] px-4 py-3 font-medium transition hover:border-emerald-500/35 hover:bg-emerald-500/[0.04] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <GoogleIcon />
                  {oauthBusy ? "Открываем Google…" : "Продолжить с Google"}
                </button>
                <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-[.12em] text-[var(--text-subtle)]">
                  <span className="h-px flex-1 bg-[var(--border)]" />
                  или по почте
                  <span className="h-px flex-1 bg-[var(--border)]" />
                </div>
              </>
            )}

            <form onSubmit={submit} className="space-y-4">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium">Электронная почта</span>
                <input
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="name@company.kz"
                  className="w-full rounded-xl border border-[var(--border-strong)] bg-[var(--bg)] px-4 py-3 outline-none transition focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10"
                  required
                />
              </label>

              {mode !== "reset" && (
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium">Пароль</span>
                  <div className="relative">
                    <input
                      type={showPassword ? "text" : "password"}
                      autoComplete={mode === "login" ? "current-password" : "new-password"}
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="Минимум 8 символов"
                      className="w-full rounded-xl border border-[var(--border-strong)] bg-[var(--bg)] px-4 py-3 pr-20 outline-none transition focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10"
                      minLength={8}
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((value) => !value)}
                      className="absolute inset-y-0 right-3 text-xs font-medium text-[var(--text-muted)] hover:text-[var(--text)]"
                    >
                      {showPassword ? "Скрыть" : "Показать"}
                    </button>
                  </div>
                </label>
              )}

              <button
                type="submit"
                disabled={busy || oauthBusy || !isSupabaseConfigured}
                className="mt-2 flex w-full items-center justify-center rounded-xl bg-gradient-to-r from-emerald-500 to-emerald-600 px-4 py-3 font-semibold text-white shadow-lg shadow-emerald-500/20 transition hover:-translate-y-0.5 hover:shadow-xl disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
              >
                {busy
                  ? "Подождите…"
                  : mode === "login"
                    ? "Войти"
                    : mode === "register"
                      ? "Создать аккаунт"
                      : "Отправить ссылку"}
              </button>
            </form>

            <div className="mt-6 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-sm">
              {mode === "login" ? (
                <>
                  <button onClick={() => setMode("register")} className="font-medium text-emerald-500 hover:text-emerald-400">
                    Создать аккаунт
                  </button>
                  <button onClick={() => setMode("reset")} className="text-[var(--text-muted)] hover:text-[var(--text)]">
                    Забыли пароль?
                  </button>
                </>
              ) : (
                <button onClick={() => setMode("login")} className="font-medium text-emerald-500 hover:text-emerald-400">
                  Вернуться ко входу
                </button>
              )}
            </div>
          </div>
        </div>
      </section>
    </Layout>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M21.6 12.2c0-.7-.1-1.4-.2-2.1H12v4h5.4a4.6 4.6 0 0 1-2 3v2.6h3.3c1.9-1.8 2.9-4.4 2.9-7.5Z" />
      <path fill="#34A853" d="M12 22c2.7 0 5-.9 6.7-2.3l-3.3-2.6c-.9.6-2.1 1-3.4 1a5.9 5.9 0 0 1-5.6-4.1H3v2.7A10.1 10.1 0 0 0 12 22Z" />
      <path fill="#FBBC05" d="M6.4 14a6 6 0 0 1 0-3.9V7.4H3a10.1 10.1 0 0 0 0 9.3L6.4 14Z" />
      <path fill="#EA4335" d="M12 6a5.5 5.5 0 0 1 3.9 1.5l2.9-2.8A9.7 9.7 0 0 0 12 2a10.1 10.1 0 0 0-9 5.4l3.4 2.7A5.9 5.9 0 0 1 12 6Z" />
    </svg>
  );
}
