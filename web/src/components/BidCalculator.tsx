import { accountLocalStorage } from "../accountStorage";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Calculator, CheckCircle2, ShieldCheck } from "lucide-react";
import { loadWorkspaceState, saveWorkspaceState } from "../workspaceState";

export type BidInputs = {
  quantity: string;
  unitCost: string;
  logistics: string;
  labor: string;
  taxes: string;
  banking: string;
  overhead: string;
  riskReserve: string;
  minimumMargin: string;
  targetMargin: string;
  marketReference: string;
  specificationConfirmed: boolean;
  supplierPriceConfirmed: boolean;
  logisticsConfirmed: boolean;
  taxesConfirmed: boolean;
};

export type BidCalculation = {
  productCost: number;
  totalCost: number;
  breakEvenPrice: number;
  minimumSafePrice: number;
  targetPrice: number;
  recommendedPrice: number | null;
  expectedProfit: number | null;
  expectedMarginPct: number | null;
  viable: boolean;
};

const EMPTY_INPUTS: BidInputs = {
  quantity: "1",
  unitCost: "",
  logistics: "",
  labor: "",
  taxes: "",
  banking: "",
  overhead: "",
  riskReserve: "",
  minimumMargin: "5",
  targetMargin: "15",
  marketReference: "",
  specificationConfirmed: false,
  supplierPriceConfirmed: false,
  logisticsConfirmed: false,
  taxesConfirmed: false,
};

function numberValue(value: string): number {
  const parsed = Number(value.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function priceForMargin(cost: number, marginPct: number): number {
  const rate = Math.min(95, Math.max(0, marginPct)) / 100;
  return rate >= 1 ? cost : cost / (1 - rate);
}

export function calculateBid(inputs: BidInputs, budgetKzt: number): BidCalculation {
  const quantity = Math.max(1, Math.floor(numberValue(inputs.quantity) || 1));
  const productCost = numberValue(inputs.unitCost) * quantity;
  const totalCost = productCost + [
    inputs.logistics,
    inputs.labor,
    inputs.taxes,
    inputs.banking,
    inputs.overhead,
    inputs.riskReserve,
  ].reduce((sum, value) => sum + numberValue(value), 0);
  const minimumMargin = numberValue(inputs.minimumMargin);
  const targetMargin = Math.max(minimumMargin, numberValue(inputs.targetMargin));
  const minimumSafePrice = priceForMargin(totalCost, minimumMargin);
  const targetPrice = priceForMargin(totalCost, targetMargin);
  const marketReference = numberValue(inputs.marketReference);
  const officialCeiling = budgetKzt > 0 ? budgetKzt : Number.POSITIVE_INFINITY;
  const ceiling = marketReference > 0 ? Math.min(officialCeiling, marketReference) : officialCeiling;
  const viable = totalCost > 0 && ceiling >= minimumSafePrice;
  const recommendedPrice = viable ? Math.min(targetPrice, ceiling) : null;
  const expectedProfit = recommendedPrice === null ? null : recommendedPrice - totalCost;
  const expectedMarginPct = recommendedPrice && expectedProfit !== null
    ? expectedProfit / recommendedPrice * 100
    : null;

  return {
    productCost,
    totalCost,
    breakEvenPrice: totalCost,
    minimumSafePrice,
    targetPrice,
    recommendedPrice,
    expectedProfit,
    expectedMarginPct,
    viable,
  };
}

function money(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${Math.round(value).toLocaleString("ru-RU")} ₸`;
}

export function BidCalculator({
  lotId,
  lotTitle,
  budgetKzt,
}: {
  lotId: string;
  lotTitle: string;
  budgetKzt: number;
}) {
  const storageKey = `tendr_bid_calculation:v1:${lotId}`;
  const [inputs, setInputs] = useState<BidInputs>(EMPTY_INPUTS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let active = true;
    try {
      const saved = JSON.parse(accountLocalStorage.getItem(storageKey) || "null") as Partial<BidInputs> | null;
      setInputs(saved ? { ...EMPTY_INPUTS, ...saved } : EMPTY_INPUTS);
    } catch {
      setInputs(EMPTY_INPUTS);
    }
    void loadWorkspaceState<Partial<BidInputs>>(`bid-${lotId}`)
      .then((remote) => {
        if (active && remote) setInputs({ ...EMPTY_INPUTS, ...remote });
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setLoaded(true);
      });
    return () => {
      active = false;
    };
  }, [lotId, storageKey]);

  useEffect(() => {
    if (!loaded) return;
    accountLocalStorage.setItem(storageKey, JSON.stringify(inputs));
    const timer = window.setTimeout(() => {
      void saveWorkspaceState(`bid-${lotId}`, inputs).catch(() => undefined);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [inputs, loaded, lotId, storageKey]);

  const calculation = useMemo(() => calculateBid(inputs, budgetKzt), [inputs, budgetKzt]);
  const confirmations = [
    inputs.specificationConfirmed,
    inputs.supplierPriceConfirmed,
    inputs.logisticsConfirmed,
    inputs.taxesConfirmed,
  ];
  const confirmedCount = confirmations.filter(Boolean).length;
  const canCalculate = numberValue(inputs.unitCost) > 0 && numberValue(inputs.quantity) > 0;
  const status = !canCalculate
    ? "missing"
    : confirmedCount === confirmations.length
      ? "confirmed"
      : "preliminary";

  const updateText = (key: keyof BidInputs, value: string) => {
    setInputs((current) => ({
      ...current,
      [key]: value.replace(/[^0-9.,]/g, ""),
    }));
  };
  const updateFlag = (key: keyof BidInputs, value: boolean) => {
    setInputs((current) => ({ ...current, [key]: value }));
  };

  const moneyFields: Array<[keyof BidInputs, string, string]> = [
    ["unitCost", "Цена поставщика за единицу", "Например, 120000"],
    ["logistics", "Доставка и разгрузка", "Общая сумма"],
    ["labor", "Работы и монтаж", "Общая сумма"],
    ["taxes", "Налоги и обязательные платежи", "Проверяет бухгалтер"],
    ["banking", "Гарантии и банковские расходы", "Обеспечение и комиссии"],
    ["overhead", "Накладные и прочие расходы", "Склад, сотрудники, связь"],
    ["riskReserve", "Резерв риска", "Курс, гарантия, штрафы"],
    ["marketReference", "Публичный ценовой ориентир", "Необязательно"],
  ];

  return (
    <section className="mt-4 overflow-hidden rounded-2xl border border-white/[0.075] bg-[#111112]">
      <header className="border-b border-white/[0.07] p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[.17em] text-emerald-300/75">Расчёт заявки</p>
            <h2 className="mt-2 text-xl font-semibold text-white">Финансовая граница участия</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-white/42">{lotTitle}</p>
          </div>
          <div className="rounded-xl border border-white/[0.08] bg-black/20 px-4 py-3 text-right">
            <p className="text-[10px] uppercase tracking-wider text-white/30">Бюджет заказчика</p>
            <p className="mt-1 text-lg font-semibold text-white">{budgetKzt > 0 ? money(budgetKzt) : "Не указан"}</p>
          </div>
        </div>
      </header>

      <div className="grid gap-6 p-5 sm:p-6 xl:grid-cols-[1.25fr_.75fr]">
        <div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-white/45">
              Количество
              <input inputMode="numeric" value={inputs.quantity} onChange={(event) => updateText("quantity", event.target.value)} className="mt-1.5 h-11 w-full rounded-xl border border-white/[0.09] bg-black/20 px-3 text-sm text-white outline-none transition focus:border-emerald-400/40" />
            </label>
            <label className="text-xs text-white/45">
              Желаемая маржа, %
              <input inputMode="decimal" value={inputs.targetMargin} onChange={(event) => updateText("targetMargin", event.target.value)} className="mt-1.5 h-11 w-full rounded-xl border border-white/[0.09] bg-black/20 px-3 text-sm text-white outline-none transition focus:border-emerald-400/40" />
            </label>
            {moneyFields.map(([key, label, placeholder]) => (
              <label key={key} className="text-xs text-white/45">
                {label}, ₸
                <input inputMode="decimal" value={String(inputs[key])} onChange={(event) => updateText(key, event.target.value)} placeholder={placeholder} className="mt-1.5 h-11 w-full rounded-xl border border-white/[0.09] bg-black/20 px-3 text-sm text-white outline-none transition placeholder:text-white/18 focus:border-emerald-400/40" />
              </label>
            ))}
            <label className="text-xs text-white/45">
              Минимально допустимая маржа, %
              <input inputMode="decimal" value={inputs.minimumMargin} onChange={(event) => updateText("minimumMargin", event.target.value)} className="mt-1.5 h-11 w-full rounded-xl border border-white/[0.09] bg-black/20 px-3 text-sm text-white outline-none transition focus:border-emerald-400/40" />
            </label>
          </div>

          <div className="mt-5 rounded-xl border border-white/[0.07] bg-black/20 p-4">
            <p className="text-xs font-medium text-white/65">Подтверждение исходных данных</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {([
                ["specificationConfirmed", "ТЗ и количество проверены"],
                ["supplierPriceConfirmed", "Есть актуальное КП поставщика"],
                ["logisticsConfirmed", "Доставка рассчитана"],
                ["taxesConfirmed", "Налоги проверены бухгалтером"],
              ] as Array<[keyof BidInputs, string]>).map(([key, label]) => (
                <label key={key} className="flex cursor-pointer items-center gap-2 rounded-lg border border-white/[0.06] px-3 py-2.5 text-xs text-white/55">
                  <input type="checkbox" checked={Boolean(inputs[key])} onChange={(event) => updateFlag(key, event.target.checked)} className="accent-emerald-400" />
                  {label}
                </label>
              ))}
            </div>
          </div>
        </div>

        <aside className="space-y-3">
          <div className={`rounded-xl border p-4 ${status === "confirmed" ? "border-emerald-400/20 bg-emerald-400/[0.05]" : status === "preliminary" ? "border-amber-400/20 bg-amber-400/[0.05]" : "border-white/[0.08] bg-black/20"}`}>
            <div className="flex items-center gap-2">
              {status === "confirmed" ? <ShieldCheck size={17} className="text-emerald-300" /> : status === "preliminary" ? <AlertTriangle size={17} className="text-amber-300" /> : <Calculator size={17} className="text-white/40" />}
              <p className="text-sm font-medium text-white/80">{status === "confirmed" ? "Расчёт подтверждён" : status === "preliminary" ? "Предварительный расчёт" : "Введите себестоимость"}</p>
            </div>
            <p className="mt-2 text-xs leading-5 text-white/40">{status === "confirmed" ? "Все критичные исходные данные отмечены как проверенные." : status === "preliminary" ? `Подтверждено ${confirmedCount} из ${confirmations.length} групп данных.` : "Без цены поставщика точный результат невозможен."}</p>
          </div>

          <div className="divide-y divide-white/[0.06] overflow-hidden rounded-xl border border-white/[0.08] bg-black/20">
            <ResultRow label="Товар с учётом количества" value={money(calculation.productCost)} />
            <ResultRow label="Полная себестоимость" value={money(calculation.totalCost)} />
            <ResultRow label="Точка безубыточности" value={money(calculation.breakEvenPrice)} />
            <ResultRow label="Минимальная безопасная цена" value={money(calculation.minimumSafePrice)} />
            <ResultRow label="Целевая цена" value={money(calculation.targetPrice)} />
          </div>

          {canCalculate && (
            <div className={`rounded-xl border p-4 ${calculation.viable ? "border-emerald-400/20 bg-emerald-400/[0.055]" : "border-red-400/20 bg-red-400/[0.055]"}`}>
              <p className="text-[10px] font-semibold uppercase tracking-[.15em] text-white/35">Рекомендация</p>
              {calculation.viable ? (
                <>
                  <p className="mt-2 text-2xl font-semibold text-emerald-300">{money(calculation.recommendedPrice)}</p>
                  <p className="mt-2 text-xs leading-5 text-white/48">Ожидаемая прибыль: {money(calculation.expectedProfit)} · маржа {calculation.expectedMarginPct?.toFixed(1)}%.</p>
                </>
              ) : (
                <p className="mt-2 text-sm leading-6 text-red-200/80">Не участвовать с текущими расходами: бюджет или проверенный ценовой ориентир ниже минимальной безопасной цены.</p>
              )}
            </div>
          )}

          <p className="text-[11px] leading-5 text-white/25">Расчёт сохраняется в этом браузере. Публичный ценовой ориентир используйте только из проверяемого источника — закрытые ставки конкурентов недоступны.</p>
        </aside>
      </div>
    </section>
  );
}

function ResultRow({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-4 px-4 py-3 text-xs"><span className="text-white/38">{label}</span><strong className="text-right font-medium text-white/75">{value}</strong></div>;
}
