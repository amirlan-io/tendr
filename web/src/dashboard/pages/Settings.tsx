import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "../../supabase";
import { useAuth } from "../../auth/AuthContext";
import { useProfile } from "../hooks/useProfile";

const INPUT_CLASS =
  "mt-1.5 h-11 w-full rounded-xl border border-white/[0.08] bg-white/[0.025] px-3.5 text-sm text-white outline-none transition placeholder:text-white/25 hover:border-white/[0.14] focus:border-emerald-400/40 focus:outline-none";
const LABEL_CLASS = "block text-xs font-medium text-white/45";

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className={LABEL_CLASS}>
        {label}
      </label>
      {children}
    </div>
  );
}

export function SettingsPage() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const { form, set, reset, save, dirty, saving, error, savedOk, email } = useProfile();
  const [resetSent, setResetSent] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetSending, setResetSending] = useState(false);

  const provider =
    (user?.app_metadata as Record<string, unknown> | undefined)?.["provider"];
  const providerLabel = provider === "google" ? "Google" : "Email";
  const createdAt = user?.created_at
    ? new Date(user.created_at).toLocaleDateString("ru-RU")
    : "—";
  const initials = ((form.fullName.trim()[0] || email?.[0] || "T") as string).toUpperCase();

  const sendReset = async () => {
    if (!email || !supabase) return;
    if (!window.confirm("Отправить письмо для восстановления пароля на ваш email?")) return;
    setResetSending(true);
    setResetError(null);
    try {
      const { error: err } = await supabase.auth.resetPasswordForEmail(email);
      if (err) setResetError("Не удалось отправить письмо. Попробуйте позже.");
      else setResetSent(true);
    } catch {
      setResetError("Не удалось отправить письмо. Попробуйте позже.");
    } finally {
      setResetSending(false);
    }
  };

  const logout = async () => {
    if (!window.confirm("Выйти из личного кабинета?")) return;
    await signOut();
    navigate("/", { replace: true });
  };

  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[.2em] text-white/35">
        Аккаунт
      </p>
      <h1 className="mt-3 text-3xl font-medium tracking-[-.045em] text-white">
        Профиль и настройки
      </h1>

      <div className="mt-8 grid items-start gap-4 xl:grid-cols-[1.2fr_.8fr]">
        <section
          aria-label="Профиль"
          className="rounded-xl border border-white/[0.075] bg-[#121213]/90 p-6"
        >
          <div className="flex items-center gap-4">
            <span
              aria-hidden
              className="flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-400/20 bg-emerald-400/[0.08] text-base font-semibold text-emerald-300"
            >
              {initials}
            </span>
            <div>
              <h2 className="text-base font-medium text-white">Профиль</h2>
              <p className="mt-1 text-xs text-white/30">
                Данные восстанавливаются после перезагрузки из аккаунта.
              </p>
            </div>
          </div>

          <form
            className="mt-6 grid gap-4 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <Field id="profile-name" label="Имя и фамилия">
              <input
                id="profile-name"
                value={form.fullName}
                onChange={(e) => set({ fullName: e.target.value })}
                placeholder="Айгерим Нурланова"
                autoComplete="name"
                className={INPUT_CLASS}
              />
            </Field>
            <Field id="profile-company" label="Название компании">
              <input
                id="profile-company"
                value={form.companyName}
                onChange={(e) => set({ companyName: e.target.value })}
                placeholder="ТОО «Пример»"
                autoComplete="organization"
                className={INPUT_CLASS}
              />
            </Field>
            <Field id="profile-position" label="Должность">
              <input
                id="profile-position"
                value={form.position}
                onChange={(e) => set({ position: e.target.value })}
                placeholder="Менеджер по закупкам"
                autoComplete="organization-title"
                className={INPUT_CLASS}
              />
            </Field>
            <Field id="profile-phone" label="Телефон">
              <input
                id="profile-phone"
                value={form.phone}
                onChange={(e) => set({ phone: e.target.value })}
                placeholder="+7 700 000 00 00"
                autoComplete="tel"
                inputMode="tel"
                className={INPUT_CLASS}
              />
            </Field>
            <Field id="profile-city" label="Город">
              <input
                id="profile-city"
                value={form.city}
                onChange={(e) => set({ city: e.target.value })}
                placeholder="Алматы"
                autoComplete="address-level2"
                className={INPUT_CLASS}
              />
            </Field>
            <Field id="profile-email" label="Email (только чтение)">
              <input
                id="profile-email"
                value={email ?? ""}
                readOnly
                aria-readonly
                autoComplete="email"
                className={`${INPUT_CLASS} cursor-not-allowed opacity-60`}
              />
            </Field>
          </form>

          {error && (
            <p role="alert" className="mt-4 rounded-xl border border-red-400/20 bg-red-400/[0.06] px-4 py-3 text-xs text-red-300">
              {error}
            </p>
          )}
          {savedOk && (
            <p role="status" className="mt-4 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.06] px-4 py-3 text-xs text-emerald-300">
              Профиль сохранён.
            </p>
          )}

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving || !dirty}
              className="inline-flex min-h-11 items-center justify-center rounded-xl bg-emerald-400 px-5 text-sm font-semibold text-[#03110b] transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saving ? "Сохранение…" : "Сохранить изменения"}
            </button>
            <button
              type="button"
              onClick={reset}
              disabled={saving || !dirty}
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.025] px-5 text-sm font-medium text-white/70 transition hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              Отменить
            </button>
          </div>
        </section>

        <section
          aria-label="Безопасность"
          className="rounded-xl border border-white/[0.075] bg-[#121213]/90 p-6"
        >
          <h2 className="text-base font-medium text-white">Безопасность</h2>
          <dl className="mt-4 space-y-3 text-[13px]">
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Способ входа</dt>
              <dd className="font-medium text-white/80">{providerLabel}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Аккаунт создан</dt>
              <dd className="font-medium text-white/80">{createdAt}</dd>
            </div>
          </dl>
          <p className="mt-4 text-[11px] leading-5 text-white/30">
            Пароль никогда не отображается в интерфейсе.
          </p>

          <div className="mt-5 grid gap-2.5">
            <button
              type="button"
              onClick={() => void sendReset()}
              disabled={resetSending || provider === "google"}
              title={provider === "google" ? "Для входа через Google смена пароля не требуется" : undefined}
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.025] px-5 text-sm font-medium text-white/70 transition hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              {resetSending ? "Отправка…" : "Восстановить пароль"}
            </button>
            {resetSent && (
              <p role="status" className="text-xs text-emerald-300">
                Письмо отправлено на {email}.
              </p>
            )}
            {resetError && (
              <p role="alert" className="text-xs text-red-300">
                {resetError}
              </p>
            )}
            <button
              type="button"
              onClick={() => void logout()}
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-red-400/15 bg-red-400/[0.04] px-5 text-sm font-medium text-red-300 transition hover:bg-red-400/[0.08]"
            >
              Выйти из аккаунта
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
