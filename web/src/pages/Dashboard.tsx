import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { loadHistory, type HistoryItem } from "../historyStore";

type IconName = "home" | "spark" | "history" | "lots" | "docs" | "search" | "menu" | "close" | "logout" | "arrow";

const navigation: Array<{ to: string; label: string; description: string; icon: IconName }> = [
  { to: "/dashboard", label: "Обзор", description: "Рабочий стол", icon: "home" },
  { to: "/analyze", label: "Новый анализ", description: "Проверить закупку", icon: "spark" },
  { to: "/history", label: "Мои закупки", description: "История анализов", icon: "history" },
  { to: "/lots", label: "Поиск лотов", description: "Найти возможности", icon: "lots" },
  { to: "/b2g", label: "Документы", description: "Подготовка ТЗ", icon: "docs" },
];

export function DashboardPage() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [history] = useState<HistoryItem[]>(() => loadHistory());

  const displayName = user?.email?.split("@")[0] || "пользователь";
  const initial = (user?.email?.[0] || "T").toUpperCase();
  const redFlags = history.reduce((total, item) => total + (item.n_red_flags || 0), 0);
  const requirements = history.reduce((total, item) => total + (item.n_requirements || 0), 0);
  const recent = history.slice(0, 4);

  const searchResults = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return navigation;
    return navigation.filter((item) => `${item.label} ${item.description}`.toLowerCase().includes(normalized));
  }, [query]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
      if (event.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const logout = async () => {
    await signOut();
    navigate("/", { replace: true });
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#060b0e] text-[#f3f6f5]">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_75%_5%,rgba(16,185,129,.10),transparent_28%),radial-gradient(circle_at_8%_92%,rgba(37,99,235,.08),transparent_32%)]" />

      {sidebarOpen && <button aria-label="Закрыть меню" className="fixed inset-0 z-40 bg-black/65 backdrop-blur-sm lg:hidden" onClick={() => setSidebarOpen(false)} />}

      <aside className={`fixed inset-y-0 left-0 z-50 flex border-r border-white/[0.075] bg-[#080e12]/95 backdrop-blur-2xl transition-all duration-300 ${sidebarCollapsed ? "w-[84px]" : "w-[268px]"} ${sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}>
        <div className="flex min-w-0 flex-1 flex-col p-3">
          <div className={`flex h-14 items-center ${sidebarCollapsed ? "justify-center" : "justify-between px-2"}`}>
            <Link to="/dashboard" className="flex min-w-0 items-center gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-emerald-600 text-sm font-bold text-[#03100b] shadow-[0_10px_28px_-12px_rgba(16,185,129,.9)]">T</span>
              {!sidebarCollapsed && <span className="truncate text-[17px] font-semibold tracking-[-.03em]">Tendr</span>}
            </Link>
            {!sidebarCollapsed && <button aria-label="Закрыть меню" onClick={() => setSidebarOpen(false)} className="rounded-lg p-2 text-white/35 hover:bg-white/[0.05] hover:text-white lg:hidden"><Icon name="close" /></button>}
          </div>

          <div className={`mt-4 rounded-2xl border border-white/[0.07] bg-white/[0.025] ${sidebarCollapsed ? "p-2" : "p-3"}`}>
            <div className={`flex items-center ${sidebarCollapsed ? "justify-center" : "gap-3"}`}>
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/[0.08] text-xs font-semibold text-emerald-300">{initial}</span>
              {!sidebarCollapsed && <div className="min-w-0"><p className="truncate text-xs font-medium">{user?.email}</p><p className="mt-1 text-[10px] uppercase tracking-[.12em] text-white/30">Пробный доступ</p></div>}
            </div>
          </div>

          <nav className="mt-6 flex-1 space-y-1" aria-label="Навигация кабинета">
            {!sidebarCollapsed && <p className="mb-3 px-3 text-[9px] font-semibold uppercase tracking-[.18em] text-white/25">Рабочее пространство</p>}
            {navigation.map((item) => (
              <NavLink key={item.to} to={item.to} onClick={() => setSidebarOpen(false)} className={({ isActive }) => `group flex min-h-11 items-center rounded-xl border transition ${sidebarCollapsed ? "justify-center px-2" : "gap-3 px-3"} ${isActive ? "border-emerald-400/15 bg-emerald-400/[0.08] text-emerald-200" : "border-transparent text-white/48 hover:border-white/[0.06] hover:bg-white/[0.035] hover:text-white/85"}`}>
                <Icon name={item.icon} />
                {!sidebarCollapsed && <span className="text-[13px] font-medium">{item.label}</span>}
              </NavLink>
            ))}
          </nav>

          <div className="space-y-1 border-t border-white/[0.07] pt-3">
            <button onClick={() => void logout()} className={`flex min-h-11 w-full items-center rounded-xl border border-transparent text-white/40 transition hover:border-red-400/10 hover:bg-red-400/[0.05] hover:text-red-300 ${sidebarCollapsed ? "justify-center px-2" : "gap-3 px-3"}`}>
              <Icon name="logout" />{!sidebarCollapsed && <span className="text-[13px] font-medium">Выйти</span>}
            </button>
          </div>
        </div>
      </aside>

      <div className={`relative min-h-screen transition-[padding] duration-300 ${sidebarCollapsed ? "lg:pl-[84px]" : "lg:pl-[268px]"}`}>
        <header className="sticky top-0 z-30 flex h-[72px] items-center justify-between border-b border-white/[0.07] bg-[#060b0e]/80 px-4 backdrop-blur-xl sm:px-7">
          <div className="flex items-center gap-3">
            <button aria-label="Открыть меню" onClick={() => setSidebarOpen(true)} className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-2.5 text-white/60 hover:text-white lg:hidden"><Icon name="menu" /></button>
            <button aria-label={sidebarCollapsed ? "Развернуть меню" : "Свернуть меню"} onClick={() => setSidebarCollapsed((value) => !value)} className="hidden rounded-xl border border-white/[0.08] bg-white/[0.025] p-2.5 text-white/45 hover:text-white lg:block"><Icon name="menu" /></button>
            <div className="hidden items-center gap-2 text-xs sm:flex"><span className="text-white/30">Tendr</span><span className="text-white/15">/</span><span className="font-medium text-white/75">Обзор</span></div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => setSearchOpen(true)} className="hidden min-w-56 items-center justify-between rounded-xl border border-white/[0.08] bg-white/[0.025] px-3 py-2.5 text-xs text-white/30 transition hover:border-white/[0.13] hover:text-white/55 sm:flex"><span className="flex items-center gap-2"><Icon name="search" />Быстрый поиск</span><kbd className="rounded border border-white/[0.08] px-1.5 py-0.5 font-mono text-[9px]">Ctrl K</kbd></button>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/[0.07] text-xs font-semibold text-emerald-300">{initial}</div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1440px] px-4 py-7 sm:px-7 sm:py-9">
          <div className="flex flex-col justify-between gap-6 xl:flex-row xl:items-end">
            <div><p className="text-[10px] font-semibold uppercase tracking-[.2em] text-emerald-400">РАБОЧИЙ СТОЛ</p><h1 className="mt-3 text-3xl font-medium tracking-[-.045em] sm:text-[42px]">Здравствуйте, {displayName}</h1><p className="mt-3 max-w-xl text-sm leading-6 text-white/42">Все важные действия по закупкам собраны в одном месте. Начните новый анализ или продолжите работу с сохранёнными лотами.</p></div>
            <Link to="/analyze" className="inline-flex h-12 items-center justify-center gap-3 self-start rounded-xl bg-emerald-400 px-5 text-sm font-semibold text-[#03110b] shadow-[0_16px_36px_-18px_rgba(52,211,153,.8)] transition hover:-translate-y-0.5 hover:bg-emerald-300">Новый анализ <Icon name="arrow" /></Link>
          </div>

          <section className="mt-9 grid gap-3 sm:grid-cols-3" aria-label="Статистика">
            <Metric label="Проверено закупок" value={String(history.length).padStart(2, "0")} note="в этом браузере" accent="emerald" />
            <Metric label="Требований найдено" value={String(requirements).padStart(2, "0")} note="во всех анализах" accent="blue" />
            <Metric label="Рисков отмечено" value={String(redFlags).padStart(2, "0")} note={redFlags ? "требуют внимания" : "критичных нет"} accent="gold" />
          </section>

          <div className="mt-4 grid gap-4 xl:grid-cols-[1.45fr_.75fr]">
            <section className="overflow-hidden rounded-[24px] border border-white/[0.08] bg-[#0a1115]/90">
              <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-5 sm:px-6"><div><p className="text-sm font-medium">Последние закупки</p><p className="mt-1 text-xs text-white/30">Недавние результаты анализа</p></div><Link to="/history" className="text-xs font-medium text-emerald-300 hover:text-emerald-200">Вся история →</Link></div>
              {recent.length ? <div className="divide-y divide-white/[0.06]">{recent.map((item) => <RecentLot key={`${item.lot_id}-${item.created_at}`} item={item} />)}</div> : <div className="flex min-h-[290px] flex-col items-center justify-center px-6 text-center"><span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-400/15 bg-emerald-400/[0.06] text-emerald-300"><Icon name="spark" /></span><h2 className="mt-5 text-lg font-medium">Пока нет анализов</h2><p className="mt-2 max-w-sm text-sm leading-6 text-white/35">Добавьте ссылку на закупку или загрузите документацию — первый результат появится здесь.</p><Link to="/analyze" className="mt-5 text-sm font-medium text-emerald-300">Проверить первую закупку →</Link></div>}
            </section>

            <div className="grid gap-4">
              <section className="rounded-[24px] border border-white/[0.08] bg-[#0a1115]/90 p-6">
                <div className="flex items-start justify-between"><div><p className="text-[9px] font-semibold uppercase tracking-[.16em] text-[#d6bb63]">БЫСТРЫЙ СТАРТ</p><h2 className="mt-3 text-xl font-medium tracking-[-.025em]">Что сделать сейчас</h2></div><span className="font-mono text-xs text-white/20">01—03</span></div>
                <div className="mt-6 space-y-2.5"><QuickStep number="01" title="Найти подходящий лот" to="/lots" /><QuickStep number="02" title="Проверить условия и риски" to="/analyze" /><QuickStep number="03" title="Подготовить документы" to="/b2g" /></div>
              </section>
              <section className="relative overflow-hidden rounded-[24px] border border-emerald-400/15 bg-emerald-400/[0.045] p-6"><div className="pointer-events-none absolute -right-12 -top-16 h-44 w-44 rounded-full bg-emerald-400/10 blur-3xl" /><p className="relative text-[9px] font-semibold uppercase tracking-[.16em] text-emerald-300">ТЕКУЩИЙ ТАРИФ</p><div className="relative mt-4 flex items-end justify-between"><div><h2 className="text-2xl font-medium">Пробный</h2><p className="mt-2 text-xs leading-5 text-white/35">Познакомьтесь с основными возможностями Tendr.</p></div><Link to="/#pricing" className="shrink-0 text-xs font-medium text-emerald-300">Тарифы →</Link></div></section>
            </div>
          </div>
        </main>
      </div>

      {searchOpen && <div className="fixed inset-0 z-[70] flex items-start justify-center bg-black/70 px-4 pt-[14vh] backdrop-blur-md" onMouseDown={() => setSearchOpen(false)}><div className="w-full max-w-xl overflow-hidden rounded-2xl border border-white/[0.1] bg-[#0c1317] shadow-2xl" onMouseDown={(event) => event.stopPropagation()}><div className="flex items-center gap-3 border-b border-white/[0.08] px-4"><Icon name="search" /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Раздел или действие…" className="h-14 flex-1 border-0 !bg-transparent px-0 text-sm outline-none placeholder:text-white/25" /><button onClick={() => setSearchOpen(false)} className="rounded-lg border border-white/[0.08] px-2 py-1 font-mono text-[9px] text-white/35">ESC</button></div><div className="p-2">{searchResults.map((item) => <Link key={item.to} to={item.to} onClick={() => setSearchOpen(false)} className="flex items-center gap-3 rounded-xl px-3 py-3 text-white/60 transition hover:bg-white/[0.05] hover:text-white"><span className="text-emerald-300"><Icon name={item.icon} /></span><div><p className="text-sm font-medium">{item.label}</p><p className="mt-0.5 text-[11px] text-white/25">{item.description}</p></div></Link>)}{!searchResults.length && <p className="px-3 py-8 text-center text-sm text-white/30">Ничего не найдено</p>}</div></div></div>}
    </div>
  );
}

function Metric({ label, value, note, accent }: { label: string; value: string; note: string; accent: "emerald" | "blue" | "gold" }) {
  const colors = { emerald: "from-emerald-400/20 text-emerald-300", blue: "from-sky-400/20 text-sky-300", gold: "from-[#d6bb63]/20 text-[#d6bb63]" };
  return <article className="relative overflow-hidden rounded-[22px] border border-white/[0.08] bg-[#0a1115]/90 p-5"><div className={`pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r ${colors[accent]} to-transparent opacity-25`} /><p className="relative text-xs text-white/35">{label}</p><div className="relative mt-5 flex items-end justify-between"><strong className="font-mono text-3xl font-light tracking-[-.06em] text-white/90">{value}</strong><span className="pb-1 text-[10px] text-white/25">{note}</span></div></article>;
}

function RecentLot({ item }: { item: HistoryItem }) {
  const risk = item.overall_risk === "high" ? "Высокий риск" : item.overall_risk === "medium" ? "Средний риск" : "Проверено";
  const riskClass = item.overall_risk === "high" ? "text-red-300 bg-red-400/[0.07] border-red-400/15" : item.overall_risk === "medium" ? "text-[#d6bb63] bg-[#d6bb63]/[0.06] border-[#d6bb63]/15" : "text-emerald-300 bg-emerald-400/[0.06] border-emerald-400/15";
  return <div className="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_auto] sm:items-center sm:px-6"><div className="min-w-0"><p className="truncate text-sm font-medium text-white/80">{item.title || `Лот № ${item.lot_id}`}</p><p className="mt-1 truncate text-[11px] text-white/28">{item.customer || "Заказчик не указан"} · № {item.lot_id}</p></div><div className="flex items-center gap-3"><span className="text-[10px] text-white/25">{item.n_requirements} требований</span><span className={`rounded-full border px-2.5 py-1 text-[9px] ${riskClass}`}>{risk}</span></div></div>;
}

function QuickStep({ number, title, to }: { number: string; title: string; to: string }) {
  return <Link to={to} className="group flex items-center gap-3 rounded-xl border border-white/[0.065] bg-white/[0.018] p-3 transition hover:border-emerald-400/20 hover:bg-emerald-400/[0.035]"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.04] font-mono text-[9px] text-white/35 group-hover:bg-emerald-400/10 group-hover:text-emerald-300">{number}</span><span className="flex-1 text-xs font-medium text-white/60 group-hover:text-white/85">{title}</span><span className="text-white/20 group-hover:text-emerald-300">→</span></Link>;
}

function Icon({ name }: { name: IconName }) {
  const common = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  const paths: Record<IconName, ReactNode> = {
    home: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    spark: <><path d="m12 3 1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6L12 3Z" /><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" /></>,
    history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /><path d="M12 7v5l3 2" /></>,
    lots: <><path d="M4 7h16M4 12h16M4 17h10" /><circle cx="18" cy="17" r="2" /></>,
    docs: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    logout: <><path d="M10 17l5-5-5-5M15 12H3" /><path d="M15 4h5v16h-5" /></>,
    arrow: <><path d="M5 12h14M14 7l5 5-5 5" /></>,
  };
  return <svg {...common}>{paths[name]}</svg>;
}
