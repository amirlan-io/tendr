import { Link } from "react-router-dom";

type Props = {
  tariffName: string;
  limit: number | null;
  used: number;
  remaining: number | null;
  renewsAt: string | null;
};

/** Карточка текущего тарифа с прогрессом использования кредитов. */
export function UsageCard({ tariffName, limit, used, remaining, renewsAt }: Props) {
  const pct =
    limit !== null && limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <section
      aria-label="Текущий тариф"
      className="relative overflow-hidden rounded-[24px] border border-emerald-400/15 bg-emerald-400/[0.045] p-6"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -right-12 -top-16 h-44 w-44 rounded-full bg-emerald-400/10 blur-3xl"
      />
      <p className="relative text-[9px] font-semibold uppercase tracking-[.16em] text-emerald-300">
        Текущий тариф
      </p>
      <div className="relative mt-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-medium text-white">{tariffName}</h2>
          <p className="mt-2 text-xs leading-5 text-white/35">
            {limit !== null ? (
              <>
                Использовано {used} из {limit} кредитов
                {remaining !== null && <> · осталось {remaining}</>}
              </>
            ) : (
              <>Использовано кредитов: {used}</>
            )}
          </p>
          {renewsAt && (
            <p className="mt-1 text-[11px] text-white/25">Обновление: {renewsAt}</p>
          )}
        </div>
        <Link
          to="/dashboard/billing"
          className="shrink-0 rounded-lg px-2 py-1 text-xs font-medium text-emerald-300 hover:text-emerald-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
        >
          Тарифы
        </Link>
      </div>
      <div
        className="relative mt-5 h-2 overflow-hidden rounded-full bg-white/[0.07]"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label="Использование кредитов"
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-emerald-300 transition-[width] duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </section>
  );
}
