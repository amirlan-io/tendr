import { TARIFFS } from "../dashboard.data";
import { UsageCard } from "../components/UsageCard";
import { Skeleton } from "../components/Skeleton";
import { useQuota } from "../hooks/useDashboardData";
import type { Tariff } from "../dashboard.types";

function TariffCard({ tariff, current }: { tariff: Tariff; current: boolean }) {
  return (
    <article
      aria-label={`Тариф ${tariff.name}`}
      className={`relative flex flex-col rounded-xl border p-6 transition hover:border-white/[0.16] ${
        current
          ? "border-emerald-400/25 bg-[#121413]/90 shadow-[inset_0_1px_0_rgba(52,211,153,.18)]"
          : "border-white/[0.075] bg-[#121213]/90"
      }`}
    >
      {current && (
        <span className="absolute right-5 top-5 rounded-full border border-emerald-400/25 bg-emerald-400/[0.08] px-2.5 py-1 text-[10px] font-medium text-emerald-300">
          Текущий
        </span>
      )}
      <h2 className="text-xl font-medium text-white">{tariff.name}</h2>
      <p className="mt-2 text-2xl font-light text-white">
        {tariff.priceKzt !== null ? `${tariff.priceKzt.toLocaleString("ru-RU")} ₸` : "—"}
        <span className="ml-1 text-xs font-normal text-white/30">/ месяц</span>
      </p>
      <ul className="mt-5 flex-1 space-y-2.5">
        {tariff.features.map((feature) => (
          <li key={feature} className="flex gap-2.5 text-[13px] leading-5 text-white/55">
            <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-emerald-400" />
            {feature}
          </li>
        ))}
      </ul>
      <button
        type="button"
        disabled
        aria-disabled
        title="Оплата тарифов будет доступна после запуска"
        className="mt-6 inline-flex min-h-11 w-full cursor-not-allowed items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.02] px-5 text-sm font-medium text-white/30"
      >
        Выбрать {tariff.name}
      </button>
    </article>
  );
}

export function BillingPage() {
  const { quota, loading } = useQuota();
  const remaining = quota ? Math.max(0, quota.limit - quota.used) : null;

  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[.2em] text-white/35">
        Оплата
      </p>
      <h1 className="mt-3 text-3xl font-medium tracking-[-.045em] text-white">
        Тариф и лимиты
      </h1>
      <p className="mt-3 max-w-xl text-sm leading-6 text-white/42">
        Кредиты тратятся на AI-анализ закупок и подготовку документов.
        Оплата тарифов будет доступна после запуска — сейчас все кнопки покупки отключены.
      </p>

      <div className="mt-8 grid gap-4 xl:grid-cols-[.9fr_1.1fr]">
        {loading ? (
          <Skeleton lines={2} />
        ) : (
          <UsageCard
            tariffName={quota?.isPilot ? "Пилот" : "Пробный"}
            limit={quota?.limit ?? null}
            used={quota?.used ?? 0}
            remaining={remaining}
            renewsAt={null}
          />
        )}
        <section
          aria-label="Использование лимита"
          className="rounded-xl border border-white/[0.075] bg-[#121213]/90 p-6"
        >
          <h2 className="text-base font-medium text-white">Как считаются лимиты</h2>
          <dl className="mt-4 space-y-3 text-[13px]">
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Месячный лимит</dt>
              <dd className="font-medium text-white/80">{quota ? `${quota.limit} кредитов` : "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Использовано</dt>
              <dd className="font-medium text-white/80">{quota ? `${quota.used} кредитов` : "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Осталось</dt>
              <dd className="font-medium text-emerald-300">{remaining !== null ? `${remaining} кредитов` : "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Лимит на 5 часов</dt>
              <dd className="font-medium text-white/80">зависит от тарифа</dd>
            </div>
          </dl>
          {!quota && !loading && (
            <p role="status" className="mt-4 text-xs text-white/30">
              Сервер лимитов недоступен — показаны тарифы без персональных данных.
            </p>
          )}
        </section>
      </div>

      <h2 className="mt-10 text-xl font-medium text-white">Сравнение тарифов</h2>
      <div className="mt-5 grid gap-4 md:grid-cols-3">
        {TARIFFS.map((tariff) => (
          <TariffCard key={tariff.id} tariff={tariff} current={false} />
        ))}
      </div>
      <p className="mt-6 text-xs leading-5 text-white/30">
        Данные банковских карт не собираются. Кнопки покупки останутся
        неактивными до запуска приёма оплаты.
      </p>
    </div>
  );
}
