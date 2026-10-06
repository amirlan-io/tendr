import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  Bookmark,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  CheckCircle2,
  Clock3,
  FileText,
  MapPin,
  Package,
  Sparkles,
  Wrench,
} from "lucide-react";
import { api, ApiError } from "../clientId";
import { LayoutOrEmbed } from "../dashboard/Embedded";
import { isLotSaved, removeSavedLot, saveLot } from "../dashboard/dashboard.data";
import { getSafeExternalUrl } from "../security/externalUrl";
import type { Lot } from "./Lots";

function money(value?: number | null): string {
  if (value === null || value === undefined) return "Не указана";
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₸`;
}

function dateTime(value?: string | null): string {
  if (!value) return "Не указана";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function DetailRow({ label, value, accent = false }: { label: string; value: React.ReactNode; accent?: boolean }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/[0.065] px-4 py-3.5 last:border-b-0">
      <dt className="text-xs text-white/35">{label}</dt>
      <dd className={`max-w-[70%] text-right text-sm ${accent ? "font-semibold text-emerald-300" : "text-white/75"}`}>{value}</dd>
    </div>
  );
}

export function LotDetailsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { lotId } = useParams();
  const [lot, setLot] = useState<Lot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void api<Lot>(`/api/lots/${encodeURIComponent(lotId || "")}`)
      .then((data) => {
        if (cancelled) return;
        setLot(data);
        setSaved(isLotSaved(data.id));
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof ApiError ? reason.message : "Не удалось загрузить лот.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [lotId]);

  const toggleSaved = () => {
    if (!lot) return;
    if (saved) {
      removeSavedLot(lot.id);
      setSaved(false);
      return;
    }
    saveLot({
      id: lot.id,
      title: lot.title,
      organizer: lot.organizer,
      amountKzt: lot.amount_kzt ?? null,
      region: lot.region,
      deadlineDate: lot.deadline_date ?? null,
      sourceUrl: getSafeExternalUrl(lot.source_url),
      sourceId: lot.source_id,
      savedAt: new Date().toISOString(),
    });
    setSaved(true);
  };

  const backPath = embedded ? "/dashboard/lots" : "/lots";
  const analyzePath = embedded ? "/dashboard/analyze" : "/analyze";

  if (loading) {
    return <LayoutOrEmbed embedded={embedded} plainBackground><div className="mx-auto max-w-6xl space-y-4"><div className="h-12 w-32 animate-pulse rounded-xl bg-white/[0.04]" /><div className="h-72 animate-pulse rounded-2xl border border-white/[0.07] bg-white/[0.025]" /></div></LayoutOrEmbed>;
  }

  if (error || !lot) {
    return <LayoutOrEmbed embedded={embedded} plainBackground><div className="mx-auto max-w-3xl rounded-2xl border border-red-400/20 bg-red-400/[0.05] p-6"><p role="alert" className="text-sm text-red-200">{error || "Лот не найден."}</p><Link to={backPath} className="mt-4 inline-flex items-center gap-2 text-sm text-white/60 hover:text-white"><ArrowLeft size={15} /> Вернуться к поиску</Link></div></LayoutOrEmbed>;
  }

  const sourceUrl = getSafeExternalUrl(lot.source_url);
  const category = (lot.category || "Лот").toLowerCase();
  const Icon = category === "работа" ? Wrench : category === "услуга" ? BriefcaseBusiness : Package;

  return (
    <LayoutOrEmbed embedded={embedded} plainBackground>
      <div className="mx-auto max-w-6xl pb-12">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link to={backPath} className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/[0.08] px-3.5 text-xs font-medium text-white/55 transition hover:bg-white/[0.04] hover:text-white"><ArrowLeft size={15} /> Назад к лотам</Link>
          <div className="flex items-center gap-2">
            <button type="button" onClick={toggleSaved} className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/[0.08] px-3.5 text-xs font-medium text-white/55 transition hover:bg-white/[0.04] hover:text-white"><Bookmark size={15} className={saved ? "fill-emerald-300 text-emerald-300" : ""} /> {saved ? "Сохранён" : "Сохранить"}</button>
            {sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/[0.08] px-3.5 text-xs font-medium text-white/70 transition hover:bg-white/[0.04] hover:text-white">Первоисточник <ArrowUpRight size={14} /></a>}
          </div>
        </div>

        <header className="mt-5 rounded-2xl border border-white/[0.075] bg-[#111112] p-5 sm:p-7">
          <div className="flex items-start gap-4">
            <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.035] text-white/55"><Icon size={23} /></span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <span className="rounded-full border border-white/[0.09] px-2.5 py-1 text-white/48">{lot.category || "Без категории"}</span>
                <span className="rounded-full border border-white/[0.09] px-2.5 py-1 text-white/48">{lot.status}</span>
                <span className="font-mono text-white/30">№ {lot.source_id}</span>
              </div>
              <h1 className="mt-4 max-w-4xl text-2xl font-semibold leading-tight tracking-[-.025em] text-white sm:text-3xl">{lot.title}</h1>
              {lot.description && lot.description !== lot.title && <p className="mt-3 max-w-4xl text-sm leading-6 text-white/45">{lot.description}</p>}
            </div>
          </div>
          <div className="mt-6 flex flex-wrap items-end justify-between gap-5 border-t border-white/[0.07] pt-5">
            <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-white/40">
              {lot.region && <span className="inline-flex items-center gap-1.5"><MapPin size={14} /> {lot.region}</span>}
              {lot.deadline_date && <span className={`inline-flex items-center gap-1.5 ${lot.is_urgent ? "text-amber-300" : ""}`}><Clock3 size={14} /> Приём до {dateTime(lot.deadline_date)}</span>}
            </div>
            <div className="text-right"><p className="text-[10px] uppercase tracking-[.14em] text-white/25">Сумма лота</p><p className="mt-1 text-2xl font-semibold tabular-nums text-white">{money(lot.amount_kzt)}</p></div>
          </div>
        </header>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <section className="overflow-hidden rounded-2xl border border-white/[0.075] bg-[#111112]">
            <div className="flex items-center gap-2 border-b border-white/[0.07] px-4 py-4"><Building2 size={16} className="text-emerald-300" /><h2 className="text-sm font-semibold text-white/80">Заказчик и условия</h2></div>
            <dl>
              <DetailRow label="Заказчик" value={lot.organizer || "Не указан"} />
              <DetailRow label="БИН заказчика" value={lot.organizer_bin || "Не указан"} />
              <DetailRow label="Регион" value={lot.region || "Не указан"} />
              <DetailRow label="Место поставки" value={lot.delivery_address || "Не указано"} />
              <DetailRow label="Способ закупки" value={lot.procurement_method || "Не указан"} />
              <DetailRow label="Площадка" value={lot.platform || "Госзакупки РК"} />
            </dl>
          </section>

          <section className="overflow-hidden rounded-2xl border border-white/[0.075] bg-[#111112]">
            <div className="flex items-center gap-2 border-b border-white/[0.07] px-4 py-4"><FileText size={16} className="text-emerald-300" /><h2 className="text-sm font-semibold text-white/80">Финансы и сроки</h2></div>
            <dl>
              <DetailRow label="Общая сумма" value={money(lot.amount_kzt)} accent />
              <DetailRow label="Цена за единицу" value={money(lot.price_per_unit)} />
              <DetailRow label="Дата публикации" value={<span className="inline-flex items-center gap-1.5"><CalendarDays size={13} /> {dateTime(lot.publish_date)}</span>} />
              <DetailRow label="Окончание приёма" value={dateTime(lot.deadline_date)} />
              <DetailRow label="Осталось" value={lot.deadline_time_str || (lot.days_until_deadline ? `${lot.days_until_deadline} дн.` : "Не указано")} />
              <DetailRow label="Статус" value={<span className="inline-flex items-center gap-1.5"><CheckCircle2 size={13} /> {lot.status}</span>} />
            </dl>
          </section>
        </div>

        <section className="mt-4 rounded-2xl border border-white/[0.075] bg-[#111112] p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div><p className="text-[10px] font-semibold uppercase tracking-[.16em] text-emerald-300/70">Информация о закупке</p><h2 className="mt-2 text-lg font-semibold text-white">Описание лота</h2></div>
            <Link to={`${analyzePath}?lot_url=${encodeURIComponent(lot.source_url || lot.source_id)}&lot_title=${encodeURIComponent(lot.title)}`} className="inline-flex h-10 items-center gap-2 rounded-xl bg-emerald-400 px-4 text-xs font-semibold text-[#04130c] transition hover:bg-emerald-300"><Sparkles size={15} /> Быстрый разбор</Link>
          </div>
          <p className="mt-5 whitespace-pre-wrap text-sm leading-7 text-white/48">{lot.description || "Подробное описание отсутствует в карточке реестра. Откройте первоисточник или запустите быстрый разбор документации."}</p>
          {lot.ai_summary && <div className="mt-5 rounded-xl border border-emerald-400/15 bg-emerald-400/[0.045] p-4"><p className="text-[10px] font-semibold uppercase tracking-[.14em] text-emerald-300/70">AI-резюме</p><p className="mt-2 text-sm leading-6 text-white/60">{lot.ai_summary}</p></div>}
          {lot.ai_red_flags?.length ? <div className="mt-4 rounded-xl border border-amber-400/15 bg-amber-400/[0.04] p-4"><p className="text-xs font-semibold text-amber-200/80">На что обратить внимание</p><ul className="mt-2 space-y-1.5 text-xs leading-5 text-white/50">{lot.ai_red_flags.map((flag) => <li key={flag}>• {flag}</li>)}</ul></div> : null}
        </section>
      </div>
    </LayoutOrEmbed>
  );
}
