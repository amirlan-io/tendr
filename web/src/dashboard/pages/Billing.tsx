import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TARIFFS } from "../dashboard.data";
import { UsageCard } from "../components/UsageCard";
import { Skeleton } from "../components/Skeleton";
import { useQuota } from "../hooks/useDashboardData";
import type { Tariff } from "../dashboard.types";
import { api, ApiError } from "../../clientId";

function TariffCard({ tariff, current, available, busy, onSelect }: { tariff: Tariff; current: boolean; available: boolean; busy: boolean; onSelect: () => void }) {
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
        disabled={current || !available || busy}
        onClick={onSelect}
        title={!available ? "Платёжный провайдер ещё не настроен" : undefined}
        className="mt-6 inline-flex min-h-11 w-full items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/[0.08] px-5 text-sm font-medium text-emerald-200 transition hover:bg-emerald-400/[0.14] disabled:cursor-not-allowed disabled:border-white/[0.08] disabled:bg-white/[0.02] disabled:text-white/30"
      >
        {current ? "Текущий тариф" : busy ? "Открываем оплату…" : available ? `Выбрать ${tariff.name}` : "Оплата не настроена"}
      </button>
    </article>
  );
}

export function BillingPage() {
  const { quota, loading } = useQuota();
  const [searchParams] = useSearchParams();
  const [availablePlans, setAvailablePlans] = useState<Set<string>>(new Set());
  const [billingLoading, setBillingLoading] = useState(true);
  const [checkoutPlan, setCheckoutPlan] = useState<string | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);
  const remaining = quota ? quota.remainingInWindow : null;
  const currentPlanName = quota
    ? ({ free: "Пробный", pilot: "Пилот", plus: "Plus", pro: "Pro", ultra: "Ultra" }[quota.plan] ?? quota.plan)
    : "Пробный";

  useEffect(() => {
    api<{ plans: Array<{ id: string; checkout_available: boolean }> }>("/api/account/billing/plans")
      .then((response) => setAvailablePlans(new Set(response.plans.filter((plan) => plan.checkout_available).map((plan) => plan.id))))
      .catch(() => setAvailablePlans(new Set()))
      .finally(() => setBillingLoading(false));
  }, []);

  async function checkout(plan: string) {
    setBillingError(null);
    setCheckoutPlan(plan);
    try {
      const response = await api<{ checkout_url: string }>("/api/account/billing/checkout", {
        method: "POST",
        body: JSON.stringify({ plan }),
      });
      window.location.assign(response.checkout_url);
    } catch (error) {
      setBillingError(error instanceof ApiError ? error.message : "Не удалось открыть оплату. Попробуйте позже.");
      setCheckoutPlan(null);
    }
  }

  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[.2em] text-white/35">
        Оплата
      </p>
      <h1 className="mt-3 text-3xl font-medium tracking-[-.045em] text-white">
        Тариф и лимиты
      </h1>
      <p className="mt-3 max-w-xl text-sm leading-6 text-white/42">
        В тарифе один лимит AI-анализов на пять часов, без месячного ограничения.
        Окно начинается с первого запуска и затем полностью обновляется. Неудачный анализ не расходует лимит.
        AI-чат, глубокий поиск и подготовка AI-черновика используют по одному запуску; пакетный разбор — по одному на лот.
      </p>

      {searchParams.get("payment") === "success" && (
        <p role="status" className="mt-5 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.07] px-4 py-3 text-sm text-emerald-200">Оплата принята. Тариф активируется после подтверждения платёжной системой.</p>
      )}
      {searchParams.get("payment") === "cancelled" && (
        <p role="status" className="mt-5 rounded-xl border border-amber-400/20 bg-amber-400/[0.07] px-4 py-3 text-sm text-amber-200">Оплата отменена, тариф не изменился.</p>
      )}
      {billingError && <p role="alert" className="mt-5 rounded-xl border border-red-400/20 bg-red-400/[0.07] px-4 py-3 text-sm text-red-200">{billingError}</p>}

      <div className="mt-8 grid gap-4 xl:grid-cols-[.9fr_1.1fr]">
        {loading ? (
          <Skeleton lines={2} />
        ) : (
          <UsageCard
            tariffName={currentPlanName}
            limit={quota?.limit ?? null}
            used={quota?.used ?? 0}
            remaining={remaining}
            renewsAt={quota?.windowResetsAt ?? null}
          />
        )}
        <section
          aria-label="Использование лимита"
          className="rounded-xl border border-white/[0.075] bg-[#121213]/90 p-6"
        >
          <h2 className="text-base font-medium text-white">Как считаются лимиты</h2>
          <dl className="mt-4 space-y-3 text-[13px]">
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">AI-анализы за 5 часов</dt>
              <dd className="font-medium text-white/80">{quota ? `${quota.limit} анализов` : "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Использовано</dt>
              <dd className="font-medium text-white/80">{quota ? `${quota.used} анализов` : "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Осталось</dt>
              <dd className="font-medium text-emerald-300">{remaining !== null ? `${remaining} анализов` : "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Выполняются сейчас</dt>
              <dd className="font-medium text-white/80">{quota ? quota.reserved : "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Доступно сейчас</dt>
              <dd className="font-medium text-emerald-300">{quota ? `${quota.remainingInWindow} анализов` : "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/40">Обновление всего лимита</dt>
              <dd className="font-medium text-white/80">{quota?.windowResetsAt ? new Date(quota.windowResetsAt).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) : "после использования"}</dd>
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
          <TariffCard
            key={tariff.id}
            tariff={tariff}
            current={quota?.plan === tariff.id}
            available={!billingLoading && availablePlans.has(tariff.id)}
            busy={checkoutPlan === tariff.id}
            onSelect={() => void checkout(tariff.id)}
          />
        ))}
      </div>
      <p className="mt-6 text-xs leading-5 text-white/30">
        Данные банковских карт Tendr не получает: оплата проходит на защищённой странице Stripe. Тариф активируется только после подписанного подтверждения платежа. Если кнопка неактивна, онлайн-оплата пока недоступна.
      </p>
    </div>
  );
}
