import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Building2,
  Check,
  ChevronRight,
  LockKeyhole,
  LogOut,
  UserRound,
} from "lucide-react";
import { supabase } from "../../supabase";
import { useAuth } from "../../auth/AuthContext";
import { useProfile } from "../hooks/useProfile";
import { CompanyTenderProfile } from "../components/CompanyTenderProfile";

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
  const [section, setSection] = useState<"profile" | "company" | "security">("profile");

  const provider =
    (user?.app_metadata as Record<string, unknown> | undefined)?.["provider"];
  const providerLabel = provider === "google" ? "Google" : "Email";
  const createdAt = user?.created_at
    ? new Date(user.created_at).toLocaleDateString("ru-RU")
    : "—";
  const initials = ((form.fullName.trim()[0] || email?.[0] || "T") as string).toUpperCase();
  const filledProfileFields = [form.fullName, form.companyName, form.position, form.phone, form.city]
    .filter((value) => value.trim()).length;
  const profileProgress = Math.round((filledProfileFields / 5) * 100);

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

  const navigation = [
    { id: "profile" as const, label: "Личные данные", hint: "Имя, контакты и компания", icon: UserRound },
    { id: "company" as const, label: "Подбор лотов", hint: "Что и где вы поставляете", icon: Building2 },
    { id: "security" as const, label: "Вход и безопасность", hint: "Пароль и активный аккаунт", icon: LockKeyhole },
  ];

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[.2em] text-white/30">Настройки</p>
          <h1 className="mt-2 text-3xl font-medium tracking-[-.045em] text-white">Ваш кабинет</h1>
          <p className="mt-2 text-sm text-white/35">Управляйте профилем и настройте персональный подбор закупок.</p>
        </div>
        <div className="flex items-center gap-3 rounded-2xl border border-white/[0.07] bg-white/[0.025] px-3 py-2.5">
          <span aria-hidden className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-400 text-sm font-bold text-[#04120c]">{initials}</span>
          <div className="min-w-0 pr-2">
            <p className="max-w-[220px] truncate text-sm font-medium text-white/85">{form.fullName || "Пользователь Tendr"}</p>
            <p className="max-w-[220px] truncate text-[11px] text-white/30">{email}</p>
          </div>
        </div>
      </div>

      <div className="mt-7 overflow-hidden rounded-2xl border border-white/[0.075] bg-[#101011] lg:grid lg:min-h-[570px] lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="border-b border-white/[0.07] bg-[#0c0c0d] p-3 lg:border-b-0 lg:border-r lg:p-4">
          <div className="flex gap-2 overflow-x-auto lg:block lg:space-y-1.5">
            {navigation.map((item) => {
              const Icon = item.icon;
              const active = section === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSection(item.id)}
                  aria-pressed={active}
                  className={`group flex min-w-[205px] items-center gap-3 rounded-xl px-3 py-3 text-left transition lg:w-full lg:min-w-0 ${active ? "bg-white/[0.07] text-white" : "text-white/45 hover:bg-white/[0.035] hover:text-white/75"}`}
                >
                  <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${active ? "border-emerald-400/25 bg-emerald-400/[0.1] text-emerald-300" : "border-white/[0.07] bg-white/[0.025] text-white/35"}`}><Icon size={16} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium">{item.label}</span>
                    <span className="mt-0.5 hidden truncate text-[10px] text-white/25 lg:block">{item.hint}</span>
                  </span>
                  <ChevronRight size={14} className={`hidden lg:block ${active ? "text-emerald-300" : "text-white/15"}`} />
                </button>
              );
            })}
          </div>

          <div className="mt-5 hidden rounded-xl border border-white/[0.06] bg-white/[0.018] p-4 lg:block">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-white/35">Профиль заполнен</span>
              <span className="font-semibold text-white/70">{profileProgress}%</span>
            </div>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full bg-emerald-400 transition-all" style={{ width: `${profileProgress}%` }} /></div>
            <p className="mt-3 text-[10px] leading-4 text-white/25">Полный профиль помогает точнее оценивать подходящие лоты.</p>
          </div>
        </aside>

        <main className="p-5 sm:p-7 lg:p-9">
          {section === "profile" && (
            <section aria-label="Профиль" className="max-w-3xl">
              <div className="border-b border-white/[0.07] pb-5">
                <h2 className="text-xl font-medium text-white">Личные данные</h2>
                <p className="mt-1.5 text-xs leading-5 text-white/32">Эта информация используется внутри вашего рабочего кабинета.</p>
              </div>
              <form className="mt-6 grid gap-x-5 gap-y-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); void save(); }}>
                <Field id="profile-name" label="Имя и фамилия"><input id="profile-name" value={form.fullName} onChange={(e) => set({ fullName: e.target.value })} placeholder="Айгерим Нурланова" autoComplete="name" className={INPUT_CLASS} /></Field>
                <Field id="profile-position" label="Должность"><input id="profile-position" value={form.position} onChange={(e) => set({ position: e.target.value })} placeholder="Менеджер по закупкам" autoComplete="organization-title" className={INPUT_CLASS} /></Field>
                <Field id="profile-company" label="Название компании"><input id="profile-company" value={form.companyName} onChange={(e) => set({ companyName: e.target.value })} placeholder="ТОО «Пример»" autoComplete="organization" className={INPUT_CLASS} /></Field>
                <Field id="profile-city" label="Город"><input id="profile-city" value={form.city} onChange={(e) => set({ city: e.target.value })} placeholder="Алматы" autoComplete="address-level2" className={INPUT_CLASS} /></Field>
                <Field id="profile-phone" label="Телефон"><input id="profile-phone" value={form.phone} onChange={(e) => set({ phone: e.target.value })} placeholder="+7 700 000 00 00" autoComplete="tel" inputMode="tel" className={INPUT_CLASS} /></Field>
                <Field id="profile-email" label="Email"><input id="profile-email" value={email ?? ""} readOnly aria-readonly autoComplete="email" className={`${INPUT_CLASS} cursor-not-allowed opacity-55`} /></Field>
              </form>
              {error && <p role="alert" className="mt-4 rounded-xl border border-red-400/20 bg-red-400/[0.06] px-4 py-3 text-xs text-red-300">{error}</p>}
              {savedOk && <p role="status" className="mt-4 flex items-center gap-2 text-xs text-emerald-300"><Check size={14} /> Профиль сохранён.</p>}
              <div className="mt-7 flex flex-wrap gap-3 border-t border-white/[0.07] pt-5">
                <button type="button" onClick={() => void save()} disabled={saving || !dirty} className="inline-flex min-h-11 items-center justify-center rounded-xl bg-emerald-400 px-5 text-sm font-semibold text-[#03110b] transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-40">{saving ? "Сохранение…" : "Сохранить изменения"}</button>
                <button type="button" onClick={reset} disabled={saving || !dirty} className="inline-flex min-h-11 items-center justify-center rounded-xl border border-white/[0.08] px-5 text-sm font-medium text-white/55 transition hover:bg-white/[0.035] hover:text-white disabled:cursor-not-allowed disabled:opacity-40">Отменить</button>
              </div>
            </section>
          )}

          {section === "company" && <CompanyTenderProfile embedded />}

          {section === "security" && (
            <section aria-label="Безопасность" className="max-w-3xl">
              <div className="border-b border-white/[0.07] pb-5">
                <h2 className="text-xl font-medium text-white">Вход и безопасность</h2>
                <p className="mt-1.5 text-xs leading-5 text-white/32">Управление способом входа и текущей сессией.</p>
              </div>
              <div className="mt-6 divide-y divide-white/[0.07] rounded-xl border border-white/[0.07]">
                <div className="flex items-center justify-between gap-4 px-4 py-4"><div><p className="text-sm text-white/75">Способ входа</p><p className="mt-1 text-[11px] text-white/28">Основной способ авторизации</p></div><span className="rounded-lg bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-white/65">{providerLabel}</span></div>
                <div className="flex items-center justify-between gap-4 px-4 py-4"><div><p className="text-sm text-white/75">Аккаунт создан</p><p className="mt-1 text-[11px] text-white/28">Дата первой регистрации</p></div><span className="text-xs font-medium text-white/55">{createdAt}</span></div>
                <div className="flex flex-wrap items-center justify-between gap-4 px-4 py-4"><div><p className="text-sm text-white/75">Пароль</p><p className="mt-1 text-[11px] text-white/28">Мы никогда не отображаем его в интерфейсе</p></div><button type="button" onClick={() => void sendReset()} disabled={resetSending || provider === "google"} title={provider === "google" ? "Для входа через Google смена пароля не требуется" : undefined} className="rounded-lg border border-white/[0.09] px-3.5 py-2 text-xs font-medium text-white/60 transition hover:bg-white/[0.04] hover:text-white disabled:cursor-not-allowed disabled:opacity-35">{resetSending ? "Отправка…" : "Восстановить пароль"}</button></div>
              </div>
              {resetSent && <p role="status" className="mt-4 text-xs text-emerald-300">Письмо отправлено на {email}.</p>}
              {resetError && <p role="alert" className="mt-4 text-xs text-red-300">{resetError}</p>}
              <div className="mt-8 rounded-xl border border-red-400/10 bg-red-400/[0.025] p-4">
                <p className="text-sm font-medium text-white/70">Завершить текущую сессию</p>
                <p className="mt-1 text-[11px] text-white/30">Для продолжения работы потребуется войти снова.</p>
                <button type="button" onClick={() => void logout()} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-red-400/15 px-4 py-2.5 text-xs font-medium text-red-300 transition hover:bg-red-400/[0.07]"><LogOut size={14} /> Выйти из аккаунта</button>
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
