import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import {
  ArrowDownUp,
  Bookmark,
  BriefcaseBusiness,
  Building2,
  ChevronDown,
  Clock3,
  Download,
  MapPin,
  Package,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { LayoutOrEmbed } from "../dashboard/Embedded";
import { api, ApiError, getOrCreateClientId } from "../clientId";
import { escapeCsvCell } from "../security/csv";
import { getSafeExternalUrl } from "../security/externalUrl";
import { LotSourceIconButton } from "../dashboard/components/LotSourceLink";
import { isLotSaved, removeSavedLot, saveLot } from "../dashboard/dashboard.data";

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
  organizer_bin?: string;
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
  next_cursor?: number | null;
  has_more?: boolean;
  total_is_exact?: boolean;
  fetched_at?: string;
  last_updated_at?: string;
  scope?: "active" | "published" | "offers" | "archive" | "all";
};

type SortMode = "amount_desc" | "amount_asc" | "deadline";
type StatusMode = "active" | "published" | "offers" | "archive";

const CACHE_TTL_MS = 5 * 60 * 1000;
// v5 invalidates empty V2-search results cached before global V3 search.
const CACHE_PREFIX = "lots_cache:v6:";
const PRICE_MAX = 49_500_000_000;
const PRICE_STEP = 50_000_000;
const LOT_TYPES = [
  { value: "товар", label: "Товар", icon: Package },
  { value: "услуга", label: "Услуга", icon: BriefcaseBusiness },
  { value: "работа", label: "Работа", icon: Wrench },
] as const;
const REGIONS = [
  ["10", "область Абай"], ["11", "Акмолинская область"],
  ["15", "Актюбинская область"], ["19", "Алматинская область"],
  ["23", "Атырауская область"], ["27", "Западно-Казахстанская область"],
  ["31", "Жамбылская область"], ["33", "область Жетысу"],
  ["35", "Карагандинская область"], ["39", "Костанайская область"],
  ["43", "Кызылординская область"], ["47", "Мангистауская область"],
  ["55", "Павлодарская область"], ["59", "Северо-Казахстанская область"],
  ["61", "Туркестанская область"], ["62", "область Улытау"],
  ["63", "Восточно-Казахстанская область"], ["71", "Астана"],
  ["75", "Алматы"], ["79", "Шымкент"],
] as const;
const PROCUREMENT_METHODS = [
  ["3", "Запрос ценовых предложений"],
  ["6", "Из одного источника по несостоявшимся закупкам"],
] as const;
const PRICE_LABELS = [0, PRICE_MAX * 0.25, PRICE_MAX * 0.5, PRICE_MAX * 0.75, PRICE_MAX];

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
    localStorage.setItem(CACHE_PREFIX + key, JSON.stringify({ ts: Date.now(), data }));
  } catch {
    // localStorage может быть переполнен.
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
  status: string;
  procurement_method_ids: number[];
  published_from?: string;
  cursor?: number;
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
    req.status,
    req.procurement_method_ids.join(","),
    req.published_from,
    req.cursor,
    req.limit,
  ].join("|");
}

function formatCompactKzt(value: number): string {
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млрд ₸`;
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн ₸`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} тыс. ₸`;
  }
  return `${value.toLocaleString("ru-RU")} ₸`;
}

function formatFullKzt(value?: number): string {
  if (value === undefined || value === null) return "Сумма не указана";
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₸`;
}

function formatPriceTick(value: number, index: number): string {
  if (value === 0) return "0";
  const amount = (value / 1_000_000_000).toLocaleString("ru-RU", {
    maximumFractionDigits: 1,
  });
  return index === PRICE_LABELS.length - 1 ? `${amount} млрд ₸` : amount;
}

export function LotsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const initialSearchStarted = useRef(false);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [query, setQuery] = useState("");
  const [region, setRegion] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState<StatusMode>("active");
  const [procurementMethod, setProcurementMethod] = useState("");
  const [publicationDays, setPublicationDays] = useState("30");
  const [customerBin, setCustomerBin] = useState("");
  const [priceRange, setPriceRange] = useState<[number, number]>([0, PRICE_MAX]);
  const [onlyUrgent, setOnlyUrgent] = useState(false);
  const [withAi, setWithAi] = useState(false);
  const [sort, setSort] = useState<SortMode>("amount_desc");
  const [currentCursor, setCurrentCursor] = useState<number | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<number | null>>([]);
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

  const search = async (cursor: number | null = null, resetPagination = false) => {
    setLoading(true);
    setError(null);
    const publishedFrom = publicationDays
      ? new Date(Date.now() - Number(publicationDays) * 86_400_000)
          .toISOString()
          .slice(0, 10)
      : undefined;
    const requestBody = {
      query,
      region,
      category,
      status,
      procurement_method_ids: procurementMethod ? [Number(procurementMethod)] : [],
      published_from: publishedFrom,
      customer_bin: customerBin,
      min_amount_kzt: priceRange[0],
      max_amount_kzt: priceRange[1] >= PRICE_MAX ? 0 : priceRange[1],
      only_urgent: onlyUrgent,
      with_ai: withAi,
      ai_limit: withAi ? 3 : 0,
      cursor: cursor ?? undefined,
      limit: 20,
    };
    if (resetPagination) setCursorHistory([]);
    setCurrentCursor(cursor);
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
      if (!data.is_mock) setCachedSearch(cacheKey, data);
    } catch (requestError: unknown) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "Ошибка поиска. Попробуйте снова.",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (embedded && !initialSearchStarted.current) {
      initialSearchStarted.current = true;
      void search();
    }
    // Первый запрос в dashboard выполняется один раз.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embedded]);

  const sortedLots = useMemo(() => {
    if (!result) return [];
    return [...result.lots].sort((a, b) => {
      if (sort === "amount_asc") return (a.amount_kzt || 0) - (b.amount_kzt || 0);
      if (sort === "deadline") {
        const aDate = a.deadline_date
          ? new Date(a.deadline_date).getTime()
          : Number.MAX_SAFE_INTEGER;
        const bDate = b.deadline_date
          ? new Date(b.deadline_date).getTime()
          : Number.MAX_SAFE_INTEGER;
        return aDate - bDate;
      }
      return (b.amount_kzt || 0) - (a.amount_kzt || 0);
    });
  }, [result, sort]);

  const resetFilters = () => {
    setQuery("");
    setRegion("");
    setCategory("");
    setStatus("active");
    setProcurementMethod("");
    setPublicationDays("30");
    setCustomerBin("");
    setPriceRange([0, PRICE_MAX]);
    setOnlyUrgent(false);
    setWithAi(false);
    setCurrentCursor(null);
    setCursorHistory([]);
  };

  const goToNextPage = () => {
    const nextCursor = result?.next_cursor;
    if (!nextCursor) return;
    setCursorHistory((history) => [...history, currentCursor]);
    void search(nextCursor);
  };

  const goToPreviousPage = () => {
    if (!cursorHistory.length) return;
    const previousCursor = cursorHistory[cursorHistory.length - 1] ?? null;
    setCursorHistory((history) => history.slice(0, -1));
    void search(previousCursor);
  };

  const clearCache = () => {
    Object.keys(localStorage)
      .filter((key) => key.startsWith(CACHE_PREFIX))
      .forEach((key) => localStorage.removeItem(key));
    setFromCache(false);
    setResult(null);
  };

  const exportCSV = () => {
    if (!result?.lots.length) return;
    const headers = [
      "source_id",
      "title",
      "amount_kzt",
      "region",
      "deadline_date",
      "organizer_bin",
      "source_url",
    ];
    const rows = result.lots.map((lot) =>
      headers
        .map((header) =>
          escapeCsvCell((lot as unknown as Record<string, unknown>)[header]),
        )
        .join(","),
    );
    const blob = new Blob(["\ufeff" + [headers.join(","), ...rows].join("\n")], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `lots_${Date.now()}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const submitPartnership = async () => {
    if (!partnershipLot) return;
    setPartnershipStatus(null);
    try {
      await api(`/api/lots/${partnershipLot.id}/partnership`, {
        method: "POST",
        body: JSON.stringify({
          role: partnershipRole,
          contact: partnershipContact || undefined,
          message: partnershipMessage || undefined,
        }),
        headers: { "X-Client-Id": getOrCreateClientId() },
      });
      setPartnershipStatus({
        type: "success",
        text: "Заявка отправлена. Организатор сможет связаться с вами.",
      });
      setPartnershipContact("");
      setPartnershipMessage("");
    } catch (requestError: unknown) {
      setPartnershipStatus({
        type: "error",
        text:
          requestError instanceof ApiError
            ? requestError.message
            : "Ошибка отправки. Попробуйте снова.",
      });
    }
  };

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = { товар: 0, услуга: 0, работа: 0 };
    result?.lots.forEach((lot) => {
      if (lot.category && lot.category in counts) counts[lot.category] += 1;
    });
    return counts;
  }, [result]);

  return (
    <LayoutOrEmbed embedded={embedded}>
      <div
        className={
          embedded
            ? "-mx-4 -mt-7 min-h-[calc(100vh-64px)] sm:-mx-7 sm:-mt-9"
            : "page-container py-8 sm:py-12"
        }
      >
        <section className="overflow-hidden border border-white/[0.075] bg-[#0a0a0b] shadow-[0_32px_100px_-55px_rgba(0,0,0,.95)] sm:rounded-[18px]">
          <div className="grid min-h-[760px] lg:grid-cols-[286px_minmax(0,1fr)]">
            <aside className="border-b border-white/[0.065] bg-[#111112] lg:border-b-0 lg:border-r">
              <div className="flex h-[68px] items-center justify-between border-b border-white/[0.08] px-5">
                <div className="flex items-center gap-2 text-sm font-semibold text-white">
                  <SlidersHorizontal className="h-4 w-4 text-white/55" />
                  Фильтры
                </div>
                <button
                  type="button"
                  onClick={resetFilters}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.09] px-2.5 py-1.5 text-xs text-white/45 transition hover:border-white/20 hover:text-white"
                >
                  <RotateCcw className="h-3 w-3" />
                  Сбросить
                </button>
              </div>

              <div className="space-y-6 p-5">
                <div>
                  <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.17em] text-white/35">
                    Тип лота
                  </p>
                  <div className="space-y-1.5">
                    {LOT_TYPES.map((type) => {
                      const checked = category === type.value;
                      const TypeIcon = type.icon;
                      return (
                        <label
                          key={type.value}
                          className={`flex cursor-pointer items-center gap-3 rounded-xl px-2.5 py-2.5 text-sm transition ${
                            checked
                              ? "bg-white/[0.07] text-white"
                              : "text-white/58 hover:bg-white/[0.035] hover:text-white"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => setCategory(checked ? "" : type.value)}
                            className="h-4 w-4 rounded border-white/20 bg-black/20 accent-white"
                          />
                          <TypeIcon className="h-4 w-4" strokeWidth={1.7} />
                          <span className="flex-1">{type.label}</span>
                          <span className="font-mono text-[11px] text-white/34">
                            {typeCounts[type.value] || "—"}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </div>

                <div className="space-y-1 border-y border-white/[0.07] py-3">
                  <FilterDisclosure title="Статус">
                    <div className="space-y-1 px-2 pb-2">
                      {([
                        ["active", "Актуальные"],
                        ["published", "Приём заявок"],
                        ["offers", "Приём ценовых предложений"],
                        ["archive", "Архив"],
                      ] as const).map(([value, label]) => (
                        <label key={value} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-white/55 hover:bg-white/[0.035] hover:text-white">
                          <input
                            type="radio"
                            name="lot-status"
                            value={value}
                            checked={status === value}
                            onChange={() => setStatus(value)}
                            className="accent-white"
                          />
                          {label}
                        </label>
                      ))}
                    </div>
                  </FilterDisclosure>
                  <FilterDisclosure title="Метод закупки">
                    <div className="px-2 pb-2">
                      <select
                        value={procurementMethod}
                        onChange={(event) => setProcurementMethod(event.target.value)}
                        aria-label="Метод закупки"
                        className="h-9 w-full rounded-lg border border-white/[0.09] bg-[#171718] px-2 text-xs text-white/70 outline-none"
                      >
                        <option value="">Все методы</option>
                        {PROCUREMENT_METHODS.map(([value, label]) => (
                          <option key={value} value={value}>{label}</option>
                        ))}
                      </select>
                    </div>
                  </FilterDisclosure>
                  <FilterDisclosure title="Регионы">
                    <div className="px-2 pb-2">
                      <select
                        value={region}
                        onChange={(event) => setRegion(event.target.value)}
                        aria-label="Регион поставки"
                        className="h-9 w-full rounded-lg border border-white/[0.09] bg-[#171718] px-2 text-xs text-white/70 outline-none"
                      >
                        <option value="">Все регионы</option>
                        {REGIONS.map(([value, label]) => (
                          <option key={value} value={value}>{label}</option>
                        ))}
                      </select>
                    </div>
                  </FilterDisclosure>
                </div>

                <div>
                  <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.17em] text-white/35">
                    Дата публикации
                  </label>
                  <select
                    value={publicationDays}
                    onChange={(event) => setPublicationDays(event.target.value)}
                    aria-label="Дата публикации"
                    className="h-10 w-full rounded-xl border border-white/[0.09] bg-[#171718] px-3 text-xs text-white/70 outline-none"
                  >
                    <option value="7">За последние 7 дней</option>
                    <option value="30">За последние 30 дней</option>
                    <option value="90">За последние 90 дней</option>
                    <option value="365">За последний год</option>
                    <option value="">За всё время</option>
                  </select>
                </div>

                <PriceRangeSlider value={priceRange} onChange={setPriceRange} />

                <div>
                  <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.17em] text-white/35">
                    БИН заказчика
                  </label>
                  <input
                    value={customerBin}
                    onChange={(event) => setCustomerBin(event.target.value.replace(/\D/g, ""))}
                    maxLength={12}
                    placeholder="12 цифр"
                    className="h-10 w-full rounded-xl border border-white/[0.09] bg-black/20 px-3 font-mono text-xs text-white outline-none transition placeholder:text-white/20 focus:border-white/25 focus:ring-4 focus:ring-white/[0.035]"
                  />
                </div>

                <div className="space-y-3">
                  <ToggleFilter
                    checked={onlyUrgent}
                    onChange={setOnlyUrgent}
                    label="Только срочные"
                  />
                  <ToggleFilter
                    checked={withAi}
                    onChange={setWithAi}
                    label="Предварительный AI-анализ"
                  />
                </div>

                <button
                  type="button"
                  onClick={() => void search(null, true)}
                  disabled={loading}
                  className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#f2f2f2] text-sm font-semibold text-[#111112] shadow-[0_12px_28px_-18px_rgba(255,255,255,.5)] transition hover:bg-white disabled:cursor-wait disabled:opacity-50"
                >
                  <Search className="h-4 w-4" />
                  {loading ? "Ищем лоты…" : "Найти лоты"}
                </button>
              </div>
            </aside>

            <div className="min-w-0 bg-[#0d0d0e]">
              <div className="flex min-h-[68px] flex-col gap-3 border-b border-white/[0.08] px-4 py-3 sm:flex-row sm:items-center sm:px-6">
                <div className="relative min-w-0 flex-1 sm:max-w-[520px]">
                  <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void search();
                    }}
                    placeholder="Поиск по названию или точному номеру лота"
                    aria-label="Ключевые слова поиска"
                    className="h-11 w-full rounded-xl border border-white/[0.09] bg-[#151516] pl-10 pr-4 text-sm text-white outline-none transition placeholder:text-white/33 focus:border-white/25 focus:ring-4 focus:ring-white/[0.035]"
                  />
                </div>
                <div className="relative sm:ml-auto">
                  <ArrowDownUp className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/36" />
                  <select
                    value={sort}
                    onChange={(event) => setSort(event.target.value as SortMode)}
                    className="h-11 min-w-48 appearance-none rounded-xl border border-white/[0.09] bg-[#151516] pl-10 pr-9 text-sm text-white/75 outline-none focus:border-white/25"
                  >
                    <option value="amount_desc">Сначала крупные</option>
                    <option value="amount_asc">Сначала небольшие</option>
                    <option value="deadline">По ближайшему сроку</option>
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/35" />
                </div>
              </div>

              <div className="p-4 sm:p-6">
                <div className="mb-4 flex flex-wrap items-center gap-3">
                  <span className="inline-flex items-center gap-2 rounded-full border border-white/[0.09] bg-white/[0.035] px-3 py-1.5 text-xs text-white/55">
                    <span className="h-1.5 w-1.5 rounded-full bg-white/65" />
                    Госзакупки РК · официальный API
                  </span>
                  <span className="text-sm text-white/42">
                    {result?.total_is_exact === false ? "Показано" : "Найдено"}: {" "}
                    <b className="font-semibold text-white/80">{result?.total ?? 0}</b> лотов
                  </span>
                  {(result?.last_updated_at || result?.fetched_at) && (
                    <span className="text-[11px] text-white/30">
                      {result.last_updated_at ? "Реестр обновлён" : "Проверено"} {new Date((result.last_updated_at || result.fetched_at) as string).toLocaleString("ru-RU", {
                        day: "2-digit",
                        month: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  )}
                  {fromCache && (
                    <button
                      type="button"
                      onClick={clearCache}
                      className="rounded-md bg-blue-400/10 px-2 py-1 text-[11px] text-blue-300"
                    >
                      из кеша · обновить
                    </button>
                  )}
                  {result && result.total > 0 && (
                    <button
                      type="button"
                      onClick={exportCSV}
                      className="ml-auto inline-flex items-center gap-2 rounded-lg border border-white/[0.09] px-3 py-2 text-xs text-white/50 transition hover:text-white"
                    >
                      <Download className="h-3.5 w-3.5" />
                      CSV
                    </button>
                  )}
                </div>

                {result?.is_mock && (
                  <div className="mb-4 rounded-xl border border-amber-400/25 bg-amber-400/[0.08] p-3 text-sm text-amber-200">
                    <b>Демо-режим — это не реальные лоты.</b> GOSZAKUP_API_TOKEN отсутствует на сервере.
                  </div>
                )}

                {error && (
                  <div role="alert" className="mb-4 rounded-xl border border-red-400/25 bg-red-400/[0.08] p-3 text-sm text-red-200">
                    {error}
                  </div>
                )}

                {loading ? (
                  <div className="space-y-3">
                    {Array.from({ length: 5 }).map((_, index) => (
                      <div key={index} className="h-[150px] animate-pulse rounded-2xl border border-white/[0.07] bg-white/[0.025]" />
                    ))}
                  </div>
                ) : sortedLots.length > 0 ? (
                  <div>
                    <div className="space-y-3">
                      {sortedLots.map((lot) => (
                        <LotResultCard
                          key={lot.id}
                          lot={lot}
                          analyzeBase={embedded ? "/dashboard" : ""}
                          onPartnership={() => setPartnershipLot(lot)}
                        />
                      ))}
                    </div>
                    {(cursorHistory.length > 0 || result?.has_more) && (
                      <div className="mt-5 flex items-center justify-between border-t border-white/[0.07] pt-5">
                        <button
                          type="button"
                          onClick={goToPreviousPage}
                          disabled={!cursorHistory.length || loading}
                          className="h-10 rounded-xl border border-white/[0.1] px-4 text-sm text-white/60 transition hover:border-white/20 hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
                        >
                          ← Назад
                        </button>
                        <span className="text-xs text-white/32">Страница {cursorHistory.length + 1}</span>
                        <button
                          type="button"
                          onClick={goToNextPage}
                          disabled={!result?.has_more || !result?.next_cursor || loading}
                          className="h-10 rounded-xl bg-white px-4 text-sm font-semibold text-black transition hover:bg-white/90 disabled:cursor-not-allowed disabled:opacity-30"
                        >
                          Дальше →
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex min-h-[460px] flex-col items-center justify-center rounded-2xl border border-dashed border-white/[0.09] bg-white/[0.015] px-6 text-center">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/[0.09] bg-white/[0.03]">
                      <Search className="h-5 w-5 text-white/50" />
                    </div>
                    <h2 className="mt-4 text-lg font-semibold text-white">
                      {result ? "Лоты не найдены" : "Найдите подходящие закупки"}
                    </h2>
                    <p className="mt-2 max-w-sm text-sm leading-6 text-white/38">
                      Настройте тип, сумму и другие параметры. Здесь появятся реальные лоты из официального реестра.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>
      </div>

      {partnershipLot && (
        <PartnershipDialog
          lot={partnershipLot}
          role={partnershipRole}
          contact={partnershipContact}
          message={partnershipMessage}
          status={partnershipStatus}
          onRoleChange={setPartnershipRole}
          onContactChange={setPartnershipContact}
          onMessageChange={setPartnershipMessage}
          onClose={() => {
            setPartnershipLot(null);
            setPartnershipStatus(null);
          }}
          onSubmit={() => void submitPartnership()}
        />
      )}
    </LayoutOrEmbed>
  );
}

function FilterDisclosure({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group rounded-lg">
      <summary className="flex cursor-pointer list-none items-center justify-between rounded-lg px-2 py-2.5 text-sm text-white/58 transition hover:bg-white/[0.03] hover:text-white">
        {title}
        <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
      </summary>
      {children}
    </details>
  );
}

function ToggleFilter({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 text-xs text-white/52">
      <span>{label}</span>
      <span className={`relative h-5 w-9 rounded-full border transition ${checked ? "border-white/70 bg-white" : "border-white/10 bg-white/10"}`}>
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          className="sr-only"
        />
        <span className={`absolute top-0.5 h-3.5 w-3.5 rounded-full shadow transition-transform ${checked ? "translate-x-[18px] bg-[#111112]" : "translate-x-0.5 bg-white/70"}`} />
      </span>
    </label>
  );
}

function PriceRangeSlider({
  value,
  onChange,
}: {
  value: [number, number];
  onChange: (value: [number, number]) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [preview, setPreview] = useState<number | null>(null);
  const [low, high] = value;
  const lowPct = (low / PRICE_MAX) * 100;
  const highPct = (high / PRICE_MAX) * 100;
  const updateLow = (next: number) => onChange([Math.min(next, high - PRICE_STEP), high]);
  const updateHigh = (next: number) => onChange([low, Math.max(next, low + PRICE_STEP)]);
  const previewPct = preview === null ? null : (preview / PRICE_MAX) * 100;
  const isFullRange = low === 0 && high === PRICE_MAX;

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = rootRef.current?.getBoundingClientRect();
    if (!rect) return;
    const rawValue = ((event.clientX - rect.left) / rect.width) * PRICE_MAX;
    const roundedValue = Math.round(rawValue / PRICE_STEP) * PRICE_STEP;
    setPreview(Math.max(0, Math.min(PRICE_MAX, roundedValue)));
  };

  let ghostLeft = 0;
  let ghostWidth = 0;
  if (previewPct !== null && previewPct < lowPct) {
    ghostLeft = previewPct;
    ghostWidth = lowPct - previewPct;
  } else if (previewPct !== null && previewPct > highPct) {
    ghostLeft = highPct;
    ghostWidth = previewPct - highPct;
  }

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center justify-between gap-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.17em] text-white/35">Сумма лота</p>
          <button
            type="button"
            onClick={() => onChange([0, PRICE_MAX])}
            disabled={isFullRange}
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-white/[0.1] bg-white/[0.025] px-2.5 text-[11px] text-white/45 transition hover:border-white/20 hover:bg-white/[0.05] hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
          >
            <X className="h-3 w-3" />
            Очистить
          </button>
        </div>
        <p className="mt-1.5 whitespace-nowrap text-lg font-semibold tabular-nums tracking-[-0.025em] text-white">
          {formatCompactKzt(low)} <span className="px-1 text-white/28">—</span> {formatCompactKzt(high)}
        </p>
      </div>

      <div
        ref={rootRef}
        className="relative h-6 w-full touch-none"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setPreview(null)}
      >
        <div className="absolute left-0 right-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-white/[0.11]" />
        <div
          className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-white/80 shadow-[0_0_16px_rgba(255,255,255,.08)]"
          style={{ left: `${lowPct}%`, right: `${100 - highPct}%` }}
        />
        {ghostWidth > 0 && (
          <div
            className="pointer-events-none absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-white/20 transition-[left,width] duration-75"
            style={{ left: `${ghostLeft}%`, width: `${ghostWidth}%` }}
          />
        )}
        <span
          aria-hidden
          className="pointer-events-none absolute top-1/2 z-[5] h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white/85 bg-[#0d0d0e] shadow-[0_0_0_3px_rgba(255,255,255,.06),0_4px_14px_rgba(0,0,0,.55)]"
          style={{ left: `${lowPct}%` }}
        />
        <span
          aria-hidden
          className="pointer-events-none absolute top-1/2 z-[5] h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white/85 bg-[#0d0d0e] shadow-[0_0_0_3px_rgba(255,255,255,.06),0_4px_14px_rgba(0,0,0,.55)]"
          style={{ left: `${highPct}%` }}
        />
        <input
          type="range"
          min={0}
          max={PRICE_MAX}
          step={PRICE_STEP}
          value={low}
          onChange={(event) => updateLow(Number(event.target.value))}
          aria-label="Минимальная сумма лота"
          className="lot-range-input lot-range-input-low"
        />
        <input
          type="range"
          min={0}
          max={PRICE_MAX}
          step={PRICE_STEP}
          value={high}
          onChange={(event) => updateHigh(Number(event.target.value))}
          aria-label="Максимальная сумма лота"
          className="lot-range-input lot-range-input-high"
        />
      </div>

      <div className="flex select-none justify-between text-[10px] font-medium tabular-nums text-white/32">
        {PRICE_LABELS.map((label, index) => (
          <span key={label}>{formatPriceTick(label, index)}</span>
        ))}
      </div>
    </div>
  );
}

function LotResultCard({
  lot,
  analyzeBase,
  onPartnership,
}: {
  lot: Lot;
  analyzeBase: string;
  onPartnership: () => void;
}) {
  const safeSourceUrl = getSafeExternalUrl(lot.source_url);
  const [saved, setSaved] = useState(() => isLotSaved(lot.id));
  const normalizedCategory = (lot.category || "").toLowerCase();
  const Icon = normalizedCategory === "работа" ? Wrench : normalizedCategory === "услуга" ? BriefcaseBusiness : Package;
  const accentClasses = "border-white/[0.09] bg-white/[0.035] text-white/60";

  const toggleSaved = () => {
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
      sourceUrl: safeSourceUrl,
      sourceId: lot.source_id,
      savedAt: new Date().toISOString(),
    });
    setSaved(true);
  };

  return (
    <article className="group relative grid gap-4 rounded-xl border border-white/[0.075] bg-[#121213]/90 p-4 transition duration-200 hover:-translate-y-0.5 hover:border-white/[0.14] hover:bg-[#151516] sm:grid-cols-[52px_minmax(0,1fr)_auto] sm:p-5">
      <div className={`flex h-12 w-12 items-center justify-center rounded-xl border ${accentClasses}`}>
        <Icon className="h-5 w-5" strokeWidth={1.8} />
      </div>

      <div className="min-w-0">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {lot.category && (
            <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${accentClasses}`}>
              {lot.category[0].toUpperCase() + lot.category.slice(1)}
            </span>
          )}
          {lot.procurement_method && (
            <span className="max-w-[260px] truncate rounded-full border border-white/[0.1] px-2.5 py-1 text-[11px] text-white/46">
              {lot.procurement_method}
            </span>
          )}
          <span className="rounded-full border border-white/[0.08] px-2.5 py-1 text-[11px] text-white/34">
            {lot.status}
          </span>
        </div>

        <h2 className="text-base font-semibold leading-6 text-white sm:text-lg">{lot.title}</h2>
        {lot.description && lot.description !== lot.title && (
          <p className="mt-1 line-clamp-1 text-xs text-white/36">{lot.description}</p>
        )}

        <div className="mt-3 flex min-w-0 items-center gap-2 text-xs text-white/43">
          <Building2 className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{lot.organizer || `БИН ${lot.organizer_bin || "не указан"}`}</span>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-white/38">
          <span className="inline-flex items-center gap-1.5 font-mono text-white/48">
            № {lot.source_id}
          </span>
          {lot.region && (
            <span className="inline-flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5" /> {lot.region}
            </span>
          )}
          {lot.deadline_date && (
            <span className={`inline-flex items-center gap-1.5 ${lot.is_urgent ? "text-amber-300" : ""}`}>
              <Clock3 className="h-3.5 w-3.5" />
              до {new Date(lot.deadline_date).toLocaleDateString("ru-RU")}
            </span>
          )}
        </div>
      </div>

      <div className="flex items-end justify-between gap-4 sm:min-w-[180px] sm:flex-col sm:items-end">
        <div className="flex gap-1.5 sm:order-none">
          <Link
            to={`${analyzeBase}/analyze?lot_url=${encodeURIComponent(lot.source_url || "")}&lot_title=${encodeURIComponent(lot.title)}`}
            aria-label={`AI-анализ лота ${lot.source_id}`}
            title="AI-анализ"
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.09] text-white/42 transition hover:border-white/20 hover:bg-white/[0.05] hover:text-white"
          >
            <Sparkles className="h-3.5 w-3.5" />
          </Link>
          <button
            type="button"
            onClick={toggleSaved}
            aria-pressed={saved}
            title={saved ? "Убрать из сохранённых" : "Сохранить"}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.09] text-white/42 transition hover:border-white/20 hover:bg-white/[0.05] hover:text-white"
          >
            <Bookmark className={`h-3.5 w-3.5 ${saved ? "fill-white text-white" : ""}`} />
          </button>
          <button
            type="button"
            onClick={onPartnership}
            aria-label={`Сотрудничество по лоту ${lot.source_id}`}
            title="Сотрудничество"
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.09] text-white/42 transition hover:border-white/20 hover:bg-white/[0.05] hover:text-white"
          >
            <BriefcaseBusiness className="h-3.5 w-3.5" />
          </button>
          {safeSourceUrl && (
            <LotSourceIconButton sourceUrl={safeSourceUrl} lotId={lot.source_id} />
          )}
        </div>

        <div className="text-right">
          <div className="whitespace-nowrap text-xl font-semibold tabular-nums text-white sm:text-2xl">
            {lot.amount_kzt !== undefined && lot.amount_kzt !== null
              ? formatCompactKzt(lot.amount_kzt)
              : "—"}
          </div>
          {lot.amount_kzt !== undefined && lot.amount_kzt !== null && lot.amount_kzt >= 1_000_000 && (
            <div className="mt-1 text-[10px] tabular-nums text-white/28">{formatFullKzt(lot.amount_kzt)}</div>
          )}
        </div>
      </div>
    </article>
  );
}

function PartnershipDialog({
  lot,
  role,
  contact,
  message,
  status,
  onRoleChange,
  onContactChange,
  onMessageChange,
  onClose,
  onSubmit,
}: {
  lot: Lot;
  role: "supplier" | "investor" | "applicant" | "partner";
  contact: string;
  message: string;
  status: { type: "success" | "error"; text: string } | null;
  onRoleChange: (role: "supplier" | "investor" | "applicant" | "partner") => void;
  onContactChange: (value: string) => void;
  onMessageChange: (value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm" onMouseDown={(event) => event.currentTarget === event.target && onClose()}>
      <div className="w-full max-w-md space-y-4 rounded-xl border border-white/[0.09] bg-[#151516] p-6 shadow-2xl">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-white/45">Сотрудничество</p>
          <h3 className="mt-2 text-lg font-semibold text-white">Предложение по лоту</h3>
          <p className="mt-1 line-clamp-2 text-sm text-white/42">{lot.title}</p>
        </div>
        <select value={role} onChange={(event) => onRoleChange(event.target.value as typeof role)} className="h-11 w-full rounded-xl border border-white/10 bg-black/20 px-3 text-sm text-white">
          <option value="supplier">Могу поставить товар или услугу</option>
          <option value="investor">Могу профинансировать</option>
          <option value="applicant">Хочу подать заявку</option>
          <option value="partner">Готов к сотрудничеству</option>
        </select>
        <input value={contact} onChange={(event) => onContactChange(event.target.value)} placeholder="Email или телефон" className="h-11 w-full rounded-xl border border-white/10 bg-black/20 px-3 text-sm text-white outline-none" />
        <textarea value={message} onChange={(event) => onMessageChange(event.target.value)} rows={3} placeholder="Кратко опишите предложение" className="w-full rounded-xl border border-white/10 bg-black/20 p-3 text-sm text-white outline-none" />
        {status && <div className={`rounded-xl border p-3 text-sm ${status.type === "success" ? "border-emerald-400/25 bg-emerald-400/[0.08] text-emerald-200" : "border-red-400/25 bg-red-400/[0.08] text-red-200"}`}>{status.text}</div>}
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="h-11 flex-1 rounded-xl border border-white/10 text-sm text-white/55">Отмена</button>
          <button type="button" onClick={onSubmit} className="h-11 flex-1 rounded-xl bg-[#f2f2f2] text-sm font-semibold text-[#111112] transition hover:bg-white">Отправить</button>
        </div>
      </div>
    </div>
  );
}
