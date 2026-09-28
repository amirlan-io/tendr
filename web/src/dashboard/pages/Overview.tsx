import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { StatCard } from "../components/StatCard";
import { UsageCard } from "../components/UsageCard";
import { QuickActions } from "../components/QuickActions";
import { RecentActivity } from "../components/RecentActivity";
import { DeadlineList } from "../components/DeadlineList";
import { Skeleton } from "../components/Skeleton";
import { useHistoryList, useLocalCabinet, useQuota } from "../hooks/useDashboardData";
import type { ActivityItem, DeadlineItem } from "../dashboard.types";

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

function toDeadlines(savedLots: ReturnType<typeof useLocalCabinet>["savedLots"]): DeadlineItem[] {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const list: DeadlineItem[] = savedLots
    .filter((l) => l.deadlineDate)
    .map((l) => {
      const d = new Date(l.deadlineDate as string);
      const daysLeft = Math.ceil((d.getTime() - now.getTime()) / 86400000);
      const urgency: DeadlineItem["urgency"] =
        daysLeft < 0 ? "overdue" : daysLeft <= 3 ? "urgent" : daysLeft <= 7 ? "soon" : "normal";
      return {
        id: `lot-${l.id}`,
        title: l.title,
        customer: l.organizer || "Заказчик не указан",
        deadlineDate: d.toLocaleDateString("ru-RU"),
        daysLeft,
        urgency,
        to: "/dashboard/lots",
      };
    })
    .sort((a, b) => a.daysLeft - b.daysLeft)
    .slice(0, 5);
  return list;
}

export function OverviewPage() {
  const { user } = useAuth();
  const metaName = (user?.user_metadata as Record<string, unknown> | undefined)?.["full_name"];
  const displayName =
    (typeof metaName === "string" && metaName.trim()) ||
    user?.email?.split("@")[0] ||
    "пользователь";

  const { items: history, total, loading: historyLoading, offline } = useHistoryList();
  const { quota, loading: quotaLoading } = useQuota();
  const { savedLots, documents } = useLocalCabinet();

  const redFlags = history.reduce((sum, i) => sum + (i.n_red_flags || 0), 0);
  const requirements = history.reduce((sum, i) => sum + (i.n_requirements || 0), 0);
  const deadlines = toDeadlines(savedLots);

  const activity: ActivityItem[] = [
    ...history.slice(0, 4).map((i) => ({
      id: `a-${i.lot_id}-${i.created_at}`,
      kind: "analysis" as const,
      title: i.title || `Лот № ${i.lot_id}`,
      subtitle: `${i.customer || "Заказчик не указан"} · ${formatDate(i.created_at)}`,
      status: i.overall_risk === "high" ? "Высокий риск" : i.overall_risk === "medium" ? "Средний риск" : "Проверено",
      createdAt: formatDate(i.created_at),
      to: "/dashboard/history",
    })),
    ...savedLots.slice(0, 2).map((l) => ({
      id: `s-${l.id}`,
      kind: "lot" as const,
      title: l.title,
      subtitle: `${l.organizer || ""} · сохранён ${formatDate(l.savedAt)}`,
      status: "Сохранён",
      createdAt: formatDate(l.savedAt),
      to: "/dashboard/lots",
    })),
    ...documents.slice(0, 2).map((d) => ({
      id: `d-${d.id}`,
      kind: "document" as const,
      title: d.filename,
      subtitle: `${d.lotTitle} · ${formatDate(d.createdAt)}`,
      status: d.kind === "complaint" ? "Жалоба" : "Отчёт",
      createdAt: formatDate(d.createdAt),
      to: "/dashboard/documents",
    })),
  ].slice(0, 6);

  const analysesCount = total ?? history.length;
  const remaining = quota ? Math.max(0, quota.limit - quota.used) : null;

  return (
    <div>
      <div className="flex flex-col justify-between gap-6 xl:flex-row xl:items-end">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[.2em] text-emerald-400">
            Рабочий стол
          </p>
          <h1 className="mt-3 text-3xl font-medium tracking-[-.045em] text-white sm:text-[42px]">
            Здравствуйте, {displayName}
          </h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-white/42">
            Все важные действия по закупкам собраны в одном месте. Начните новый
            анализ или продолжите работу с сохранёнными лотами.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link to="/dashboard/analyze" className="button-primary">
            Проанализировать закупку
          </Link>
          <Link to="/dashboard/lots" className="button-secondary">
            Найти лоты
          </Link>
        </div>
      </div>

      {offline && (
        <p role="status" className="mt-6 rounded-xl border border-[#d6bb63]/20 bg-[#d6bb63]/[0.05] px-4 py-3 text-xs text-[#d6bb63]">
          Сервер истории недоступен — показана локальная копия с этого устройства.
        </p>
      )}

      <section className="mt-9 grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Статистика">
        {historyLoading && quotaLoading ? (
          <div className="sm:col-span-2 xl:col-span-5">
            <Skeleton lines={2} />
          </div>
        ) : (
          <>
            <StatCard label="Выполнено анализов" value={String(analysesCount).padStart(2, "0")} note="всего" accent="emerald" />
            <StatCard label="Сохранено закупок" value={String(savedLots.length).padStart(2, "0")} note="в кабинете" accent="blue" />
            <StatCard label="Документов подготовлено" value={String(documents.length).padStart(2, "0")} note="скачано" accent="blue" />
            <StatCard label="Активных дедлайнов" value={String(deadlines.length).padStart(2, "0")} note="отслеживается" accent="gold" />
            <StatCard
              label="AI-кредиты"
              value={remaining !== null ? String(remaining) : "—"}
              note={quota ? `осталось из ${quota.limit}` : "сервер недоступен"}
              accent="emerald"
            />
          </>
        )}
      </section>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.45fr_.75fr]">
        <div className="grid content-start gap-4">
          <RecentActivity items={activity} />
          <DeadlineList items={deadlines} />
        </div>
        <div className="grid content-start gap-4">
          <UsageCard
            tariffName={quota?.isPilot ? "Пилот" : "Пробный"}
            limit={quota?.limit ?? null}
            used={quota?.used ?? 0}
            remaining={remaining}
            renewsAt={null}
          />
          <QuickActions />
        </div>
      </div>

      {requirements > 0 && (
        <p className="mt-6 text-xs text-white/25">
          Всего найдено требований: {requirements} · отмечено рисков: {redFlags}
        </p>
      )}
    </div>
  );
}
