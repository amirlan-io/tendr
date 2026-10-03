/**
 * Песочница агента поставщиков.
 *
 * Даёт увидеть не только результат, но и ход работы агента: какие
 * запросы он пробовал, что нашёл до фильтров, сколько потратил.
 * Именно этого не хватало при проверке на моках — часть решений
 * (квота на каждый пункт ТЗ, разбор телефонов) оказалась неверной
 * только на живых данных.
 *
 * Песочница ничего не отправляет наружу: агент только читает страницы.
 */

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../clientId";

type MatchStatus = "fits" | "partial" | "no" | "unknown";

interface SandboxCandidate {
  supplier: string;
  domain: string;
  title: string;
  url: string;
  score: number;
  domain_kind: string;
  price_kzt: number | null;
  city: string;
  email: string;
  phone: string;
  requirement_matches: Array<{
    code: string;
    title: string;
    status: MatchStatus;
    comment: string;
    source_url: string;
  }>;
  warnings: string[];
}

interface SandboxResult {
  lot_id: string;
  requirements: Array<{ code: string; title: string; mandatory: boolean }>;
  trace: {
    queries: string[];
    direct_queries: string[];
    found_before_filters: number;
    blocked_filtered: number;
    pages_read: number;
    personalization: string;
    filters_applied: Record<string, unknown>;
  };
  costs: { llm_usd: number; tavily_usd: number; browser_usd: number; total_usd: number };
  duration_sec: number;
  total: number;
  candidates: SandboxCandidate[];
}

const STATUS_LABEL: Record<MatchStatus, string> = {
  fits: "Подходит",
  partial: "Частично",
  no: "Не подходит",
  unknown: "Нет данных",
};

const STATUS_CLASS: Record<MatchStatus, string> = {
  fits: "bg-emerald-400/10 text-emerald-300 border-emerald-400/20",
  partial: "bg-amber-400/10 text-amber-300 border-amber-400/20",
  no: "bg-red-400/10 text-red-300 border-red-400/20",
  unknown: "bg-white/[0.04] text-white/45 border-white/10",
};

export function SandboxPage() {
  const [lotId, setLotId] = useState("");
  const [variants, setVariants] = useState(2);
  const [onlyDirect, setOnlyDirect] = useState(false);
  const [onlyContacts, setOnlyContacts] = useState(false);
  const [useProfile, setUseProfile] = useState(true);
  const [readPages, setReadPages] = useState(false);
  const [result, setResult] = useState<SandboxResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const lot = new URLSearchParams(window.location.search).get("lot_id");
    if (lot) setLotId(lot);
  }, []);

  const run = useCallback(async () => {
    if (!lotId.trim()) {
      setError("Укажите ID лота.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await api<SandboxResult>("/api/sandbox/suppliers", {
        method: "POST",
        body: JSON.stringify({
          lot_id: lotId.trim(),
          query_variants: variants,
          limit: 15,
          only_direct: onlyDirect,
          only_with_contacts: onlyContacts,
          use_company_profile: useProfile,
          enrich_browser: readPages,
          save_results: false,
        }),
      });
      setResult(data);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(
          e.status === 400
            ? "Сначала выполните AI-анализ лота: песочнице нужны требования ТЗ."
            : e.message,
        );
      } else {
        setError("Не удалось выполнить прогон. Попробуйте позже.");
      }
    } finally {
      setLoading(false);
    }
  }, [lotId, variants, onlyDirect, onlyContacts, useProfile, readPages]);

  return (
    <div className="space-y-6">
      <header>
        <p className="text-xs uppercase tracking-[0.18em] text-emerald-400/80">Песочница</p>
        <h1 className="mt-2 text-2xl font-medium tracking-tight text-white">
          Проверка агента на реальном лоте
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-white/45">
          Прогоняет полный конвейер поиска поставщиков на реальных данных goszakup и
          показывает ход работы: какие запросы пробовались, что нашлось до фильтров и
          сколько это стоило. Ничего не отправляется поставщикам.
        </p>
      </header>

      <section className="space-y-4 rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={lotId}
            onChange={(e) => setLotId(e.target.value)}
            placeholder="ID лота, например 17726443"
            aria-label="ID лота"
            className="flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-white outline-none placeholder:text-white/25 focus:border-emerald-400/40"
          />
          <button
            type="button"
            onClick={() => void run()}
            disabled={loading}
            className="rounded-xl bg-emerald-400 px-5 py-2.5 text-sm font-semibold text-[#03110b] transition hover:bg-emerald-300 disabled:opacity-50"
          >
            {loading ? "Агент работает…" : "Запустить"}
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs text-white/45">
            Вариантов запроса на пункт
            <select
              value={variants}
              onChange={(e) => setVariants(Number(e.target.value))}
              className="mt-1 w-full rounded-lg border border-white/10 bg-[#0a1115] px-3 py-2 text-sm text-white"
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <Toggle label="Только прямые поставщики" checked={onlyDirect} onChange={setOnlyDirect} />
          <Toggle label="Только с контактами" checked={onlyContacts} onChange={setOnlyContacts} />
          <Toggle label="Учитывать профиль компании" checked={useProfile} onChange={setUseProfile} />
        </div>
        <Toggle label="Читать страницы поставщиков (медленнее, но находит цены и телефоны)" checked={readPages} onChange={setReadPages} />
      </section>

      {error && (
        <p role="alert" className="rounded-xl border border-red-400/25 bg-red-400/[0.07] px-4 py-3 text-sm text-red-200">
          {error}
        </p>
      )}

      {loading && (
        <div className="space-y-2" role="status" aria-busy="true">
          <p className="text-xs text-white/40">Поиск, чтение страниц и сверка занимают 1–2 минуты…</p>
          <div className="h-24 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.03]" />
          <div className="h-24 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.03]" />
        </div>
      )}

      {result && <SandboxOutput result={result} />}
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 self-end rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5 text-xs text-white/60">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function SandboxOutput({ result }: { result: SandboxResult }) {
  const { trace, costs } = result;
  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-white/[0.08] bg-[#0a1115]/90 p-5">
        <h2 className="text-sm font-medium text-white/80">Ход работы агента</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Запросов пробовано" value={String(trace.queries.length + trace.direct_queries.length)} />
          <Stat label="Найдено до фильтров" value={String(trace.found_before_filters)} />
          <Stat label="Прочитано страниц" value={String(trace.pages_read)} />
          <Stat label="Прошло фильтры" value={String(result.total)} />
        </div>
        <div className="mt-4 grid gap-4 text-xs lg:grid-cols-2">
          <div>
            <p className="mb-1.5 text-white/35">Поисковые запросы:</p>
            <ul className="space-y-1">
              {trace.queries.map((q) => (
                <li key={q} className="rounded-md border border-white/[0.07] bg-white/[0.02] px-2.5 py-1.5 text-white/60">
                  {q}
                </li>
              ))}
              {trace.queries.length === 0 && <li className="text-white/30">не сформированы</li>}
            </ul>
          </div>
          <div>
            <p className="mb-1.5 text-white/35">Стоимость прогона</p>
            <dl className="space-y-1 text-white/55">
              <Row label="LLM" value={`$${costs.llm_usd.toFixed(4)}`} />
              <Row label="Tavily" value={`$${costs.tavily_usd.toFixed(4)}`} />
              <Row label="Browser Use" value={`$${costs.browser_usd.toFixed(4)}`} />
              <Row label="Итого" value={`$${costs.total_usd.toFixed(4)}`} strong />
              <Row label="Время" value={`${result.duration_sec} с`} />
            </dl>
            {trace.personalization && (
              <p className="mt-3 rounded-lg border border-white/[0.07] bg-white/[0.02] px-2.5 py-2 text-white/45">
                Персонализация: {trace.personalization.split("\n").slice(1).join(" · ").slice(0, 160)}
              </p>
            )}
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-white/80">
          Кандидаты ({result.total})
        </h2>
        {result.candidates.length === 0 && (
          <p className="rounded-xl border border-white/[0.08] bg-white/[0.02] px-4 py-6 text-center text-sm text-white/35">
            Под фильтры ничего не подошло. Ослабьте условия или отключите чтение страниц.
          </p>
        )}
        {result.candidates.map((c) => (
          <article key={`${c.domain}-${c.url}`} className="rounded-2xl border border-white/[0.08] bg-[#0a1115]/90 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate text-base font-medium text-white/90">{c.supplier}</h3>
                <p className="mt-1 text-xs text-white/35">
                  {c.domain_kind === "direct" ? "сайт компании" : c.domain_kind} · {c.domain}
                </p>
              </div>
              <div className="font-mono text-2xl font-light text-white/80">
                {c.score}
                <span className="text-sm text-white/30">/100</span>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-3 text-xs text-white/45">
              {c.price_kzt ? <span>Цена: {c.price_kzt.toLocaleString("ru-RU")} ₸</span> : <span className="text-white/25">Цена не найдена</span>}
              {c.city && <span>Город: {c.city}</span>}
              {c.email && <span>✉ {c.email}</span>}
              {c.phone && <span>☎ {c.phone}</span>}
            </div>

            <ul className="mt-3 space-y-1.5">
              {c.requirement_matches.map((m) => (
                <li key={`${m.code}-${m.title}`} className="flex items-start gap-2 text-xs">
                  <span className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[10px] ${STATUS_CLASS[m.status]}`}>
                    {STATUS_LABEL[m.status]}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-white/65">{m.title}</span>
                    {m.comment && <span className="mt-0.5 block text-white/35">{m.comment}</span>}
                  </span>
                </li>
              ))}
            </ul>

            {c.warnings.length > 0 && (
              <ul className="mt-3 space-y-1 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] p-3">
                {c.warnings.map((w) => (
                  <li key={w} className="text-xs text-amber-200/75">{w}</li>
                ))}
              </ul>
            )}

            {c.url && (
              <a href={c.url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-xs text-emerald-300/80 hover:underline">
                Открыть страницу
              </a>
            )}
          </article>
        ))}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
      <div className="text-[10px] uppercase tracking-wider text-white/30">{label}</div>
      <div className="mt-1 font-mono text-xl text-white/85">{value}</div>
    </div>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-white/40">{label}</dt>
      <dd className={strong ? "font-medium text-white/85" : "text-white/60"}>{value}</dd>
    </div>
  );
}
