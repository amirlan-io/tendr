import { useState } from "react";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";
import { api, ApiError, getOrCreateClientId } from "../clientId";
import { getSafeExternalUrl } from "../security/externalUrl";
import { escapeCsvCell } from "../security/csv";

type Lot = {
  id: number;
  source: string;
  source_id: string;
  title: string;
  description?: string;
  category?: string;
  procurement_method?: string;
  platform?: string;
  amount_kzt?: number;
  region?: string;
  delivery_address?: string;
  publish_date?: string;
  deadline_date?: string;
  organizer?: string;
  status: string;
  source_url?: string;
  days_until_deadline?: number;
  is_urgent: boolean;
  deadline_time_str?: string;
  ai_summary?: string;
  ai_red_flags?: string[];
  ai_match_score?: number;
};

type SearchResult = {
  lots: Lot[];
  total: number;
  source: string;
  is_mock: boolean;
};

// Кеш результатов в localStorage (5 минут TTL)
const CACHE_TTL_MS = 5 * 60 * 1000;
const CACHE_PREFIX = "lots_cache:";

function getCachedSearch(key: string): SearchResult | null {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (Date.now() - parsed.ts > CACHE_TTL_MS) {
      localStorage.removeItem(CACHE_PREFIX + key);
      return null;
    }
    return parsed.data as SearchResult;
  } catch {
    return null;
  }
}

function setCachedSearch(key: string, data: SearchResult) {
  try {
    localStorage.setItem(
      CACHE_PREFIX + key,
      JSON.stringify({ ts: Date.now(), data })
    );
  } catch {
    // localStorage может быть переполнен
  }
}

function buildCacheKey(req: {
  query: string;
  region: string;
  category: string;
  customer_bin?: string;
  min_amount_kzt: number;
  max_amount_kzt: number;
  only_urgent: boolean;
  limit: number;
}): string {
  return [
    req.query,
    req.region,
    req.category,
    req.customer_bin,
    req.min_amount_kzt,
    req.max_amount_kzt,
    req.only_urgent ? 1 : 0,
    req.limit,
  ].join("|");
}

const REGIONS = [
  "",
  "г. Астана",
  "г. Алматы",
  "г. Шымкент",
  "Абайская область",
  "Акмолинская область",
  "Актюбинская область",
  "Алматинская область",
  "Атырауская область",
  "Восточно-Казахстанская область (ВКО)",
  "Жамбылская область",
  "Западно-Казахстанская область (ЗКО)",
  "Карагандинская область",
  "Костанайская область",
  "Кызылординская область",
  "Мангистауская область",
  "Павлодарская область",
  "Северо-Казахстанская область (СКО)",
  "Туркестанская область",
  "Улытауская область",
];

const CATEGORIES = ["", "товар", "работа", "услуга"];

export function LotsPage() {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [stats, setStats] = useState<any>(null);

  // Фильтры
  const [query, setQuery] = useState("");
  const [region, setRegion] = useState("");
  const [category, setCategory] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [onlyUrgent, setOnlyUrgent] = useState(false);
  const [customerBin, setCustomerBin] = useState("");
  const [withAi, setWithAi] = useState(false);

  // Партнёрство
  const [partnershipLot, setPartnershipLot] = useState<Lot | null>(null);
  const [partnershipRole, setPartnershipRole] = useState<
    "supplier" | "investor" | "applicant" | "partner"
  >("supplier");
  const [partnershipContact, setPartnershipContact] = useState("");
  const [partnershipMessage, setPartnershipMessage] = useState("");
  const [partnershipStatus, setPartnershipStatus] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const search = async () => {
    setLoading(true);
    setError(null);

    const requestBody = {
      query,
      region,
      category,
      customer_bin: customerBin,
      min_amount_kzt: minAmount ? Number(minAmount) : 0,
      max_amount_kzt: maxAmount ? Number(maxAmount) : 0,
      only_urgent: onlyUrgent,
      with_ai: withAi,
      ai_limit: withAi ? 3 : 0,
      limit: 50,
    };

    const cacheKey = buildCacheKey(requestBody);
    const cached = getCachedSearch(cacheKey);
    if (cached) {
      setResult(cached);
      setFromCache(true);
      setLoading(false);
      return;
    }
    setFromCache(false);

    try {
      const data = await api<SearchResult>("/api/lots/search", {
        method: "POST",
        body: JSON.stringify(requestBody),
      });
      setResult(data);
      setCachedSearch(cacheKey, data);

      api<any>("/api/lots/stats/overview")
        .then(setStats)
        .catch(() => {});
    } catch (e: unknown) {
      // Только безопасное сообщение — без сырого JSON backend.
      setError(e instanceof ApiError ? e.message : "Ошибка поиска. Попробуйте снова.");
    } finally {
      setLoading(false);
    }
  };

  const submitPartnership = async () => {
    if (!partnershipLot) return;
    setPartnershipStatus(null);
    try {
      const cid = getOrCreateClientId();
      await api(`/api/lots/${partnershipLot.id}/partnership`, {
        method: "POST",
        body: JSON.stringify({
          role: partnershipRole,
          contact: partnershipContact || undefined,
          message: partnershipMessage || undefined,
        }),
        headers: { "X-Client-Id": cid },
      });
      setPartnershipStatus({
        type: "success",
        text: "✅ Заявка отправлена! Организатор свяжется с вами.",
      });
      setPartnershipContact("");
      setPartnershipMessage("");
    } catch (e: unknown) {
      setPartnershipStatus({
        type: "error",
        text: e instanceof ApiError ? e.message : "Ошибка отправки. Попробуйте снова.",
      });
    }
  };

  const exportCSV = () => {
    if (!result || result.lots.length === 0) return;
    const headers = [
      "id",
      "title",
      "amount_kzt",
      "region",
      "deadline_date",
      "organizer_bin",
      "source_url",
    ];
    const rows = result.lots.map((l) =>
      headers.map((h) => escapeCsvCell((l as unknown as Record<string, unknown>)[h])).join(",")
    );
    const csv = [headers.join(","), ...rows].join("\n");
    const blob = new Blob(["\ufeff" + csv], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `lots_${Date.now()}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const clearCache = () => {
    Object.keys(localStorage)
      .filter((k) => k.startsWith(CACHE_PREFIX))
      .forEach((k) => localStorage.removeItem(k));
    setFromCache(false);
    setResult(null);
  };

  return (
    <Layout>
      <div className="page-container space-y-8 py-12 sm:py-16">
        <div>
          <p className="section-kicker">Каталог закупок</p>
          <h1 className="text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">Найдите подходящий лот</h1>
          <p className="mt-4 max-w-2xl text-lg leading-8 text-[var(--text-muted)]">
            Настройте критерии поиска и сравните актуальные закупки по региону, категории, сроку и бюджету.
          </p>
        </div>

        {stats && stats.total_lots > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-3">
              <div className="text-xs text-slate-500 uppercase">Всего лотов</div>
              <div className="text-xl font-bold mt-1">{stats.total_lots}</div>
            </div>
            <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-3">
              <div className="text-xs text-slate-500 uppercase">
                Активных на сумму
              </div>
              <div className="text-xl font-bold mt-1">
                {(stats.total_active_amount_kzt / 1_000_000).toFixed(1)} М ₸
              </div>
            </div>
            <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-3">
              <div className="text-xs text-slate-500 uppercase">Площадок</div>
              <div className="text-xl font-bold mt-1">
                {Object.keys(stats.by_platform || {}).length}
              </div>
            </div>
            <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-3">
              <div className="text-xs text-slate-500 uppercase">Статусов</div>
              <div className="text-xl font-bold mt-1">
                {Object.keys(stats.by_status || {}).length}
              </div>
            </div>
          </div>
        )}

        {result?.is_mock && (
          <div className="bg-amber-50 dark:bg-amber-900/30 border border-amber-300 text-amber-700 dark:text-amber-200 p-3 rounded text-sm">
            ⚠️ <b>Демо-режим — показаны тестовые данные, а не реальные лоты.</b>{" "}
            GOSZAKUP_API_TOKEN отсутствует на сервере. Реальные лоты появятся
            после настройки токена goszakup.gov.kz.
          </div>
        )}

        <div className="space-y-5 rounded-[28px] border border-white/[0.09] bg-[#0c1215]/90 p-5 shadow-[0_24px_80px_-40px_rgba(0,0,0,.9)] sm:p-7">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ключевые слова: мебель, компьютеры, лекарства…"
              aria-label="Ключевые слова поиска"
              className="min-h-12 rounded-xl border border-white/10 bg-black/20 px-4 focus:border-emerald-400/50 focus:outline-none focus:ring-4 focus:ring-emerald-400/10"
            />
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              aria-label="Регион"
              className="min-h-12 rounded-xl border border-white/10 bg-black/20 px-4"
            >
              {REGIONS.map((r) => (
                <option key={r} value={r}>
                  {r || "Все регионы"}
                </option>
              ))}
            </select>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              aria-label="Категория"
              className="min-h-12 rounded-xl border border-white/10 bg-black/20 px-4"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c
                    ? c[0].toUpperCase() + c.slice(1)
                    : "Все категории"}
                </option>
              ))}
            </select>
            <label className="flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-white/10 bg-black/20 px-4">
              <input
                type="checkbox"
                checked={onlyUrgent}
                onChange={(e) => setOnlyUrgent(e.target.checked)}
              />
              <span className="text-sm">
                Только срочные — менее 3 дней
              </span>
            </label>
            <label
              className="flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-white/10 bg-black/20 px-4"
              title="Запустить AI-анализ (Documenter+Legal) для топ-3 лотов. Занимает 1-2 минуты."
            >
              <input
                type="checkbox"
                checked={withAi}
                onChange={(e) => setWithAi(e.target.checked)}
              />
              <span className="text-sm">
                Добавить предварительный AI-анализ
              </span>
            </label>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <input
              type="text"
              value={customerBin}
              onChange={(e) => setCustomerBin(e.target.value)}
              placeholder="БИН заказчика — 12 цифр"
              maxLength={12}
              aria-label="БИН заказчика"
              className="min-h-12 rounded-xl border border-white/10 bg-black/20 px-4 font-mono text-sm"
            />
            <div className="text-xs text-slate-500 flex items-center px-2">
              Например:{" "}
              <code className="px-1 bg-slate-200 dark:bg-slate-700 rounded mx-1">
                020640001647
              </code>{" "}
              чтобы найти все лоты конкретного заказчика
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <input
              type="number"
              value={minAmount}
              onChange={(e) => setMinAmount(e.target.value)}
              placeholder="Мин. сумма (₸)"
              aria-label="Минимальная сумма"
              className="min-h-12 rounded-xl border border-white/10 bg-black/20 px-4"
            />
            <input
              type="number"
              value={maxAmount}
              onChange={(e) => setMaxAmount(e.target.value)}
              placeholder="Макс. сумма (₸)"
              aria-label="Максимальная сумма"
              className="min-h-12 rounded-xl border border-white/10 bg-black/20 px-4"
            />
            <button
              onClick={search}
              disabled={loading}
              className="button-primary disabled:opacity-40"
            >
              {loading ? "Идёт поиск..." : "Найти лоты"}
            </button>
          </div>

          {!result && !error && (
            <div className="text-xs leading-5 text-[var(--text-muted)]">
              Введите хотя бы один критерий — например, ключевое слово или БИН заказчика. Результаты сохраняются на 5 минут.
            </div>
          )}

          {fromCache && (
            <div className="text-xs text-blue-600 -mt-1 flex items-center gap-2">
              <span>⚡ Показаны кешированные данные (5 мин TTL)</span>
              <button
                onClick={clearCache}
                className="underline hover:text-red-600"
                type="button"
              >
                Очистить кеш
              </button>
            </div>
          )}
        </div>

        {error && (
          <div role="alert" className="bg-red-50 border border-red-300 text-red-700 p-3 rounded">
            ❌ {error}
          </div>
        )}

        {result && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-500">
                {result.is_mock ? (
                  <>Найдено демо-записей: <b>{result.total}</b> (не реальные лоты)</>
                ) : (
                  <>Найдено: <b>{result.total}</b> лотов</>
                )}
                {fromCache && (
                  <span className="ml-2 px-2 py-0.5 text-xs bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 rounded">
                    ⚡ из кеша
                  </span>
                )}
              </div>
              {result.total > 0 && (
                <button
                  onClick={exportCSV}
                  className="px-3 py-1.5 text-sm border rounded hover:bg-slate-50 dark:hover:bg-slate-700"
                >
                  📥 CSV
                </button>
              )}
            </div>
            {result.lots.map((lot) => (
              <LotCard
                key={lot.id}
                lot={lot}
                onPartnership={() => setPartnershipLot(lot)}
              />
            ))}
          </div>
        )}

        {partnershipLot && (
          <div
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
            onClick={() => setPartnershipLot(null)}
          >
            <div
              className="bg-white dark:bg-slate-800 rounded-lg max-w-md w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold">🤝 Стать партнёром</h3>
              <div className="text-sm text-slate-500">
                <b>{partnershipLot.title}</b>
                <br />
                {partnershipLot.amount_kzt?.toLocaleString()} ₸ •{" "}
                {partnershipLot.region}
              </div>

              <div>
                <label className="text-sm font-medium">Ваша роль</label>
                <select
                  value={partnershipRole}
                  onChange={(e) =>
                    setPartnershipRole(e.target.value as any)
                  }
                  className="w-full mt-1 p-2 border rounded dark:bg-slate-700"
                >
                  <option value="supplier">
                    🚚 Могу поставить товар/услугу
                  </option>
                  <option value="investor">💰 Могу профинансировать</option>
                  <option value="applicant">
                    📝 Хочу подать заявку от своего имени
                  </option>
                  <option value="partner">
                    🤝 Готов к любой форме сотрудничества
                  </option>
                </select>
              </div>

              <div>
                <label className="text-sm font-medium">
                  Контакт (email/телефон)
                </label>
                <input
                  value={partnershipContact}
                  onChange={(e) => setPartnershipContact(e.target.value)}
                  placeholder="+7 777 123 4567"
                  className="w-full mt-1 p-2 border rounded dark:bg-slate-700"
                />
              </div>

              <div>
                <label className="text-sm font-medium">
                  Сообщение (опционально)
                </label>
                <textarea
                  value={partnershipMessage}
                  onChange={(e) => setPartnershipMessage(e.target.value)}
                  rows={3}
                  placeholder="Опишите ваше предложение"
                  className="w-full mt-1 p-2 border rounded dark:bg-slate-700"
                />
              </div>

              {partnershipStatus && (
                <div
                  className={
                    "p-3 rounded text-sm " +
                    (partnershipStatus.type === "success"
                      ? "bg-green-50 text-green-700 border border-green-300"
                      : "bg-red-50 text-red-700 border border-red-300")
                  }
                >
                  {partnershipStatus.text}
                </div>
              )}

              <div className="flex gap-2">
                <button
                  onClick={() => setPartnershipLot(null)}
                  className="flex-1 px-3 py-2 border rounded"
                >
                  Отмена
                </button>
                <button
                  onClick={submitPartnership}
                  className="flex-1 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded"
                >
                  Отправить заявку
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}

function LotCard({
  lot,
  onPartnership,
}: {
  lot: Lot;
  onPartnership: () => void;
}) {
  const urgentColor = lot.is_urgent ? "border-red-500" : "border-slate-200";
  // Безопасная внешняя ссылка: только https на доверенные домены.
  // javascript:, data:, http:, поддоменные трюки и userinfo отклоняются.
  const safeSourceUrl = getSafeExternalUrl(lot.source_url);
  return (
    <div
      className={
        "bg-white dark:bg-slate-800 rounded-lg shadow p-4 border-l-4 " +
        urgentColor +
        " hover:shadow-md transition"
      }
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            {lot.is_urgent && (
              <span
                className="px-2 py-0.5 text-xs bg-red-100 text-red-700 rounded font-medium"
                title={
                  lot.deadline_time_str ||
                  `${lot.days_until_deadline} дней до дедлайна`
                }
              >
                {lot.days_until_deadline === 0
                  ? "🔥 сегодня"
                  : lot.days_until_deadline === 1
                    ? "⏰ завтра"
                    : `🔥 ${lot.days_until_deadline} дн`}
              </span>
            )}
            {lot.category && (
              <span className="px-2 py-0.5 text-xs bg-blue-100 text-blue-700 rounded">
                {lot.category}
              </span>
            )}
            {lot.procurement_method && (
              <span className="px-2 py-0.5 text-xs bg-slate-100 text-slate-700 rounded">
                {lot.procurement_method}
              </span>
            )}
          </div>
          <h3 className="font-medium mb-1">{lot.title}</h3>
          <div className="flex flex-wrap gap-3 text-xs text-slate-500">
            {lot.organizer && <span>🏛 {lot.organizer}</span>}
            {lot.region && <span>📍 {lot.region}</span>}
            {lot.deadline_date && (
              <span className="font-medium">
                📅 до{" "}
                {new Date(lot.deadline_date).toLocaleDateString("ru-RU")}
                {lot.deadline_time_str && lot.days_until_deadline === 0 && (
                  <span className="text-red-600 ml-1">
                    {lot.deadline_time_str}
                  </span>
                )}
              </span>
            )}
          </div>

          {(lot.ai_match_score !== undefined && lot.ai_match_score !== null) ||
          (lot.ai_red_flags && lot.ai_red_flags.length > 0) ? (
            <div className="mt-2 space-y-1">
              {lot.ai_match_score !== undefined &&
                lot.ai_match_score !== null && (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-500">
                      🤖 AI оценка:
                    </span>
                    <div className="flex-1 max-w-[200px] h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className={
                          "h-full " +
                          (lot.ai_match_score >= 70
                            ? "bg-green-500"
                            : lot.ai_match_score >= 50
                              ? "bg-yellow-500"
                              : "bg-red-500")
                        }
                        style={{ width: `${lot.ai_match_score}%` }}
                      />
                    </div>
                    <span className="text-xs font-medium">
                      {lot.ai_match_score}/100
                    </span>
                  </div>
                )}
              {lot.ai_red_flags && lot.ai_red_flags.length > 0 && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-slate-500 hover:text-slate-700">
                    ⚠️ {lot.ai_red_flags.length} предупреждеий
                  </summary>
                  <ul className="mt-1 space-y-0.5 pl-4">
                    {lot.ai_red_flags.map((f, i) => (
                      <li
                        key={i}
                        className="text-slate-600 dark:text-slate-400"
                      >
                        {f}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          ) : null}
        </div>
        {lot.amount_kzt !== null && lot.amount_kzt !== undefined && (
          <div className="text-right">
            <div className="text-2xl font-bold text-blue-600 whitespace-nowrap">
              {lot.amount_kzt.toLocaleString()} ₸
            </div>
            <div className="text-xs text-slate-500">{lot.status}</div>
          </div>
        )}
      </div>

      <div className="mt-3 flex gap-2 flex-wrap">
        {safeSourceUrl && (
          <a
            href={safeSourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 text-sm border rounded hover:bg-slate-50 dark:hover:bg-slate-700"
          >
            🔗 Источник
          </a>
        )}
        <Link
          to={`/analyze?lot_url=${encodeURIComponent(
            lot.source_url || ""
          )}&lot_title=${encodeURIComponent(lot.title)}`}
          className="px-3 py-1.5 text-sm border rounded hover:bg-slate-50 dark:hover:bg-slate-700"
        >
          🤖 AI-анализ
        </Link>
        <button
          onClick={onPartnership}
          className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded"
        >
          🤝 Стать партнёром
        </button>
      </div>
    </div>
  );
}
