import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";
import { LayoutOrEmbed } from "../dashboard/Embedded";
import { useT } from "../i18n";
import { api, ApiError, downloadBlob, isQuotaExceededError } from "../clientId";
import { pushHistory } from "../historyStore";
import { trackDocumentDownload } from "../dashboard/dashboard.data";
import { resolveLotSourceUrl } from "../dashboard/components/LotSourceLink";

type Requirement = {
  code: string;
  title: string;
  description: string;
  is_mandatory: boolean;
  source_quote?: string;
};

type CustomerScore = {
  customer: string;
  trust_score: number;
  trust_label: string;
  total_lots: number;
  avg_risk?: string;
  source: string;
};

type MarginEstimate = {
  category: string;
  estimated_margin_pct: number;
  confidence: string;
};

type LotAnalysis = {
  lot_id: string;
  title: string;
  customer: string;
  method: string;
  deadline?: string;
  budget_kzt?: number;
  source_url?: string | null;
  requirements: Requirement[];
  documents_required: string[];
  summary: string;
  red_flags: string[];
  customer_score?: CustomerScore | null;
  margin_estimate?: MarginEstimate | null;
  recommendation?: string;
};

type LegalItem = {
  rule_id: string;
  rule_title: string;
  status: string;
  severity: string;
  description: string;
  law_reference?: string;
  recommendation?: string;
};

type ComplaintDraft = string | Record<string, string>;

type AnalysisResponse = {
  lot: LotAnalysis;
  legal?: {
    items: LegalItem[];
    overall_risk: string;
    summary: string;
    complaint_draft?: ComplaintDraft;
  };
  incomplete?: boolean;
  incomplete_reason?: string;
  created_at?: string;
};

const MAX_FILE_BYTES = 20 * 1024 * 1024;
const ALLOWED_EXTS = [".pdf", ".docx", ".txt", ".csv", ".xls", ".xlsx"] as const;

function getFileExt(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

function validateFileClientSide(f: File): string | null {
  const ext = getFileExt(f.name);
  if (!(ALLOWED_EXTS as readonly string[]).includes(ext)) {
    return "Неподдерживаемый тип файла. Разрешены: PDF, DOCX, TXT, CSV, XLS, XLSX.";
  }
  if (f.size > MAX_FILE_BYTES) {
    return "Файл слишком большой. Максимальный размер — 20 МБ. Уменьшите файл и попробуйте снова.";
  }
  if (f.size === 0) {
    return "Файл пустой. Выберите другой файл.";
  }
  return null;
}

export function AnalyzePage({ embedded = false }: { embedded?: boolean } = {}) {
  const t = useT();
  const [searchParams] = useSearchParams();
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState(false);
  const [autoTitle, setAutoTitle] = useState<string>("");
  const [lastRequest, setLastRequest] = useState<
    { kind: "url"; url: string } | { kind: "file"; name: string } | null
  >(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const lastFileRef = useRef<File | null>(null);

  // Автозапуск анализа, если в URL есть ?lot_url=...
  // Срабатывает когда пользователь нажимает "🤖 AI-анализ" в каталоге лотов.
  useEffect(() => {
    const lotUrl = searchParams.get("lot_url");
    const lotTitle = searchParams.get("lot_title");
    if (lotUrl && !loading && !result) {
      setUrl(lotUrl);
      if (lotTitle) setAutoTitle(lotTitle);
      // Авто-сабмит через 100мс (чтобы state обновился)
      const t = setTimeout(() => {
        const fakeEvent = { preventDefault: () => {} } as React.FormEvent;
        // Не вызываем submit() — формируем запрос напрямую чтобы не было race condition
        (async () => {
          setError(null);
          setResult(null);
          setQuota(false);
          setLoading(true);
          try {
            const resp = await api<AnalysisResponse>(
              "/api/lots/analyze",
              {
                method: "POST",
                body: JSON.stringify({ url: lotUrl }),
              }
            );
            setResult(resp);
            if (resp?.lot?.lot_id) {
              pushHistory({
                lot_id: resp.lot.lot_id,
                title: lotTitle || resp.lot.title || lotUrl,
                url: lotUrl,
                customer: resp.lot.customer || "",
                method: resp.lot.method || "",
                n_requirements: resp.lot.requirements?.length || 0,
                n_red_flags: resp.lot.red_flags?.length || 0,
                overall_risk: resp.legal?.overall_risk,
                created_at: new Date().toISOString(),
              });
            }
          } catch (e: unknown) {
            // Квота — только по стабильному коду QUOTA_EXCEEDED.
            // Показываем только безопасное сообщение, без сырого Error/JSON backend.
            if (isQuotaExceededError(e)) {
              setQuota(true);
            } else {
              setError(e instanceof ApiError ? e.message : "Ошибка анализа. Попробуйте снова.");
            }
          } finally {
            setLoading(false);
          }
        })();
      }, 100);
      return () => clearTimeout(t);
    }
  }, [searchParams]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    setError(null);
    setResult(null);
    setQuota(false);
    // Клиентская валидация файла до отправки (backend-лимиты не меняем).
    if (file) {
      const fileProblem = validateFileClientSide(file);
      if (fileProblem) {
        if (file.size > MAX_FILE_BYTES) {
          setError("Файл слишком большой. Максимальный размер — 20 МБ. Уменьшите файл и попробуйте снова.");
        } else {
          setError(fileProblem);
        }
        return;
      }
      lastFileRef.current = file;
      setLastRequest({ kind: "file", name: file.name });
    } else if (url.trim()) {
      setLastRequest({ kind: "url", url: url.trim() });
    }
    setLoading(true);
    let ok = false;
    try {
      let resp: AnalysisResponse;
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        resp = await api<AnalysisResponse>("/api/lots/analyze-upload", {
          method: "POST",
          body: fd,
        });
      } else if (url.trim()) {
        resp = await api<AnalysisResponse>("/api/lots/analyze", {
          method: "POST",
          body: JSON.stringify({
            url: url.trim(),
          }),
        });
      } else {
        throw new Error(t("analyze.empty"));
      }

      setResult(resp);
      setLastRequest(null);
      lastFileRef.current = null;
      ok = true;

      if (!resp.incomplete) {
        pushHistory({
          lot_id: resp.lot.lot_id,
          title: resp.lot.title,
          customer: resp.lot.customer,
          method: resp.lot.method,
          overall_risk: resp.legal?.overall_risk,
          n_requirements: resp.lot.requirements?.length || 0,
          n_red_flags: resp.lot.red_flags?.length || 0,
          created_at: new Date().toISOString(),
        });
      }
    } catch (e: unknown) {
      // Безопасные сообщения из ApiError; сырой backend-JSON пользователю не показываем.
      // Квота — только по стабильному коду QUOTA_EXCEEDED, не по тексту.
      if (isQuotaExceededError(e)) {
        setQuota(true);
      } else {
        setError(e instanceof ApiError ? e.message : "Произошла ошибка. Попробуйте снова.");
      }
    } finally {
      setLoading(false);
      // Файл очищаем только при успехе — чтобы работала кнопка «повторить».
      if (ok) {
        setFile(null);
        if (fileInput.current) fileInput.current.value = "";
      }
    }
  }

  function retry() {
    // Повтор последнего запроса без потери контекста.
    if (loading) return;
    if (lastRequest?.kind === "file" && lastFileRef.current) {
      setFile(lastFileRef.current);
    }
    if (lastRequest?.kind === "url") {
      setUrl(lastRequest.url);
    }
    setError(null);
    setQuota(false);
    // Даём state обновиться и повторяем submit.
    setTimeout(() => {
      const fake = { preventDefault: () => {} } as React.FormEvent;
      void submit(fake);
    }, 0);
  }

  function reset() {
    setResult(null);
    setError(null);
    setQuota(false);
    setUrl("");
    setFile(null);
    setLastRequest(null);
    lastFileRef.current = null;
  }

  function downloadDocx(kind: "complaint" | "report") {
    if (!result) return;
    const lotId = result.lot.lot_id;
    // Backend принимает только числовой lot_id (path-параметр int):
    // для файловых анализов ("raw"/"manual") скачивание недоступно.
    if (!/^\d+$/.test(lotId.trim())) {
      setError("Скачивание недоступно для этого анализа: нет числового ID лота.");
      return;
    }
    const stamp = new Date().toISOString().slice(0, 10);
    const filename =
      kind === "complaint"
        ? `zhaloba_${lotId}_${stamp}.docx`
        : `otchet_${lotId}_${stamp}.docx`;
    setError(null);
    void downloadBlob(`/api/lots/${lotId}/download?kind=${kind}`, filename)
      .then(() => {
        // Фиксируем только реально скачанный файл.
        trackDocumentDownload({
          id: `${kind}-${lotId}-${stamp}`,
          kind,
          filename,
          lotId,
          lotTitle: result.lot.title,
          createdAt: new Date().toISOString(),
        });
      })
      .catch((e: unknown) =>
        setError(
          e instanceof ApiError
            ? e.message
            : "Не удалось скачать файл. Попробуйте позже.",
        ),
      );
  }

  return (
    <LayoutOrEmbed embedded={embedded}>
      <div className="page-container py-12 sm:py-16">
        <div className="mx-auto max-w-5xl">
        <Link
          to="/"
          className="text-sm text-[var(--text-muted)] transition hover:text-[var(--text)]"
        >
          {t("common.back")}
        </Link>
        <div className="mt-8 max-w-2xl">
          <p className="section-kicker">AI-анализ закупки</p>
          <h1 className="text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">Разберите лот перед участием</h1>
          <p className="mt-5 text-lg leading-8 text-[var(--text-muted)]">Добавьте ссылку, ID лота или документацию. Tendr соберёт требования, риски и следующий шаг в одном отчёте.</p>
        </div>

        {autoTitle && (
          <div className="mt-8 rounded-2xl border border-emerald-400/20 bg-emerald-400/[0.06] px-5 py-4 text-sm">
            <div className="mb-1 font-medium text-emerald-300">
              Лот выбран из каталога
            </div>
            <div className="text-[var(--text-muted)]">
              <b>{autoTitle}</b>
            </div>
            <div className="text-xs text-slate-500 mt-1">{url}</div>
          </div>
        )}

        {loading && (
          <div
            role="status"
            aria-busy="true"
            aria-label="Идёт AI-анализ"
            className="mt-8 rounded-2xl border border-emerald-400/20 bg-emerald-400/[0.06] px-5 py-4 text-sm"
          >  <div className="mb-3 font-medium text-emerald-300">
              Анализируем документацию
            </div>
            <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2 overflow-hidden">
              <div
                className="h-full animate-pulse bg-emerald-400"
                style={{ width: "60%" }}
              />
            </div>
            <div className="mt-2 text-xs text-[var(--text-muted)]">
              Собираем требования и проверяем возможные риски. Это может занять до полутора минут.
            </div>
          </div>
        )}

        <form onSubmit={submit} className="mt-10 rounded-[28px] border border-white/[0.09] bg-[#0c1215]/90 p-5 shadow-[0_24px_80px_-40px_rgba(0,0,0,.9)] sm:p-7">
          <label htmlFor="lot-reference" className="mb-3 block text-sm font-medium">Ссылка или ID лота</label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              id="lot-reference"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t("analyze.placeholder")}
              aria-label={t("analyze.title")}
              className="min-h-14 flex-1 rounded-xl border border-white/10 bg-black/20 px-4 text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-emerald-400/50 focus:outline-none focus:ring-4 focus:ring-emerald-400/10"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || (!url.trim() && !file)}
              className="button-primary min-w-40 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? t("analyze.submitting") : t("analyze.submit")}
            </button>
          </div>
          <div className="my-5 flex items-center gap-4 text-xs uppercase tracking-[0.14em] text-[var(--text-subtle)]"><span className="h-px flex-1 bg-white/[0.07]" /><span>или загрузите документацию</span><span className="h-px flex-1 bg-white/[0.07]" /></div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx,.txt,.csv,.xls,.xlsx"
              aria-label={t("analyze.file.label")}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="sr-only"
              disabled={loading}
            />
            <button type="button" onClick={() => fileInput.current?.click()} disabled={loading} className="button-secondary min-w-44">Выбрать файл</button>
            {file ? (
              <div className="flex min-w-0 flex-1 items-center justify-between gap-3 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.06] px-4 py-3 text-sm">
                <div className="min-w-0"><p className="truncate font-medium text-emerald-100">{file.name}</p><p className="mt-0.5 text-xs text-[var(--text-muted)]">{(file.size / 1024 / 1024).toFixed(2)} МБ</p></div>
                <button type="button" aria-label="Убрать выбранный файл" onClick={() => { setFile(null); if (fileInput.current) fileInput.current.value = ""; }} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-lg text-[var(--text-muted)] hover:bg-white/10 hover:text-white">×</button>
              </div>
            ) : <p className="text-sm text-[var(--text-muted)]">PDF, DOCX, TXT, CSV или Excel · до 20 МБ</p>}
          </div>
        </form>

        {quota && (
          <div
            className="px-4 py-3 rounded-lg border mb-4"
            style={{
              backgroundColor: "var(--bg-elevated)",
              borderColor: "var(--border)",
              borderLeftWidth: "3px",
              borderLeftColor: "#f59e0b",
            }}
          >
            <div className="font-semibold mb-1" style={{ color: "#f59e0b" }}>
              {t("analyze.quota.title")}
            </div>
            <div className="text-sm text-[var(--text-muted)]">
              {t("analyze.quota.text")}
            </div>
            <button
              type="button"
              onClick={retry}
              disabled={loading}
              className="mt-2 px-4 py-1.5 rounded-lg text-sm font-medium border transition disabled:opacity-50"
            >
              ↻ Попробовать снова
            </button>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="px-4 py-3 rounded-lg border mb-4"
            style={{
              backgroundColor: "var(--bg-elevated)",
              borderColor: "var(--border)",
              borderLeftWidth: "3px",
              borderLeftColor: "#ef4444",
            }}
          >
            <div className="font-semibold mb-1" style={{ color: "#ef4444" }}>
              {t("analyze.error.title")}
            </div>
            <div className="text-sm text-[var(--text-muted)] whitespace-pre-wrap">
              {error}
            </div>
            <button
              type="button"
              onClick={retry}
              disabled={loading}
              className="mt-2 px-4 py-1.5 rounded-lg text-sm font-medium border transition disabled:opacity-50"
            >
              ↻ Попробовать снова
            </button>
          </div>
        )}

        {result?.incomplete && (
          <div
            className="px-4 py-4 rounded-lg border mb-4"
            style={{
              backgroundColor: "var(--bg-elevated)",
              borderColor: "var(--border)",
              borderLeftWidth: "3px",
              borderLeftColor: "#f59e0b",
            }}
          >
            <div className="font-semibold mb-2" style={{ color: "#f59e0b" }}>
              ⚠ {t("analyze.incomplete.title")}
            </div>
            <div className="text-sm mb-1 text-[var(--text-muted)]">
              <span className="font-medium text-[var(--text)]">
                {t("analyze.incomplete.reason_label")}
              </span>{" "}
              {result.incomplete_reason}
            </div>
            <div className="text-sm mt-2 text-[var(--text-muted)]">
              {t("analyze.incomplete.help")}
            </div>
          </div>
        )}

        {result && !result.incomplete && (
          <ResultView
            result={result}
            onReset={reset}
            onDownload={downloadDocx}
          />
        )}
        </div>
      </div>
    </LayoutOrEmbed>
  );
}

function ResultView({
  result,
  onReset,
  onDownload,
}: {
  result: AnalysisResponse;
  onReset: () => void;
  onDownload: (kind: "complaint" | "report") => void;
}) {
  const t = useT();
  const lot = result.lot;
  const legal = result.legal;
  // Ссылка приходит с backend и проходит строгий allowlist: недоверенный
  // хост или http:// приведёт к null. Если её нет, строим из lot_id —
  // иначе кнопка пропадала бы на загрузках, где source_url пуст.
  const lotSourceUrl = resolveLotSourceUrl(lot.source_url, lot.lot_id);
  const draft = legal?.complaint_draft;
  const draftDict =
    typeof draft === "object" && draft !== null
      ? (draft as Record<string, string>)
      : null;
  const hasComplaint =
    !!draft && (draftDict !== null ? Object.keys(draftDict).length > 0 : true);

  return (
    <div className="space-y-6">
      <section
        className="rounded-lg border p-6"
        style={{
          backgroundColor: "var(--bg-elevated)",
          borderColor: "var(--border)",
          borderLeftWidth: "3px",
          borderLeftColor:
            legal?.overall_risk === "high"
              ? "#ef4444"
              : legal?.overall_risk === "medium"
                ? "#f59e0b"
                : "#10b981",
        }}
      >
        <h2 className="text-xl font-semibold mb-2 tracking-tight">
          {lot.title}
        </h2>
        <div className="text-sm text-[var(--text-muted)] mb-3">
          {lot.customer}
          {lot.budget_kzt ? ` · ${lot.budget_kzt.toLocaleString()} ₸` : ""}
          {lot.deadline
            ? ` · ${t("analyze.summary.deadline")} ${lot.deadline}`
            : ""}
        </div>
        {lotSourceUrl && (
          <a
            href={lotSourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mb-3 inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium transition hover:border-white/25 hover:bg-white/[0.04]"
            style={{ color: "var(--accent)" }}
          >
            Открыть лот на Госзакупках ↗
          </a>
        )}
        {lot.summary && (
          <p className="text-[var(--text-muted)] leading-relaxed">
            {lot.summary}
          </p>
        )}
        {legal && (
          <div className="mt-4 inline-flex items-center gap-2 text-xs">
            <span className="text-[var(--text-muted)] uppercase tracking-wider font-medium">
              {t("analyze.summary.risk")}
            </span>
            <span
              className="px-2.5 py-1 rounded-md font-medium"
              style={{
                backgroundColor:
                  legal.overall_risk === "high"
                    ? "rgba(239, 68, 68, 0.1)"
                    : legal.overall_risk === "medium"
                      ? "rgba(245, 158, 11, 0.1)"
                      : "rgba(16, 185, 129, 0.1)",
                color:
                  legal.overall_risk === "high"
                    ? "#ef4444"
                    : legal.overall_risk === "medium"
                      ? "#f59e0b"
                      : "#10b981",
              }}
            >
              {legal.overall_risk}
            </span>
          </div>
        )}
      </section>

      {/* Рекомендация AI + скоринг заказчика + маржинальность */}
      {(lot.recommendation || lot.customer_score || lot.margin_estimate) && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Рекомендация */}
          {lot.recommendation && (
            <div
              className="rounded-lg border p-4"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="text-xs font-medium text-[var(--text-muted)] mb-1 uppercase tracking-wider">
                {t("analyze.recommendation.title")}
              </div>
              <div
                className="text-lg font-semibold flex items-center gap-2"
                style={{
                  color:
                    lot.recommendation === "participate"
                      ? "#10b981"
                      : lot.recommendation === "skip"
                        ? "#ef4444"
                        : "#f59e0b",
                }}
              >
                <span>
                  {lot.recommendation === "participate"
                    ? "✓"
                    : lot.recommendation === "skip"
                      ? "✕"
                      : "!"}
                </span>
                {t(`analyze.recommendation.${lot.recommendation}`)}
              </div>
            </div>
          )}

          {/* Скоринг заказчика */}
          {lot.customer_score && (
            <div
              className="rounded-lg border p-4"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="text-xs font-medium text-[var(--text-muted)] mb-2 uppercase tracking-wider">
                {t("analyze.score.title")}
              </div>
              <div className="flex items-baseline gap-2 mb-1">
                <span
                  className="text-2xl font-bold"
                  style={{
                    color:
                      lot.customer_score.trust_score >= 60
                        ? "#10b981"
                        : lot.customer_score.trust_score >= 40
                          ? "#f59e0b"
                          : "#ef4444",
                  }}
                >
                  {lot.customer_score.trust_score.toFixed(0)}
                </span>
                <span className="text-xs text-[var(--text-subtle)]">/ 100</span>
              </div>
              <div className="text-sm text-[var(--text-muted)] mb-1">
                {t(
                  `analyze.score.trust_label.${lot.customer_score.trust_label}`,
                )}
              </div>
              {lot.customer_score.total_lots > 0 && (
                <div className="text-xs text-[var(--text-subtle)]">
                  {t("analyze.score.lots_analyzed")}{" "}
                  {lot.customer_score.total_lots}
                </div>
              )}
            </div>
          )}

          {/* Маржинальность */}
          {lot.margin_estimate && (
            <div
              className="rounded-lg border p-4"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="text-xs font-medium text-[var(--text-muted)] mb-2 uppercase tracking-wider">
                {t("analyze.margin.title")}
              </div>
              <div
                className="text-2xl font-bold mb-1"
                style={{ color: "#10b981" }}
              >
                {lot.margin_estimate.estimated_margin_pct.toFixed(0)}%
              </div>
              <div className="text-xs text-[var(--text-muted)]">
                {t("analyze.margin.category")} {lot.margin_estimate.category}
              </div>
              <div className="text-xs text-[var(--text-subtle)]">
                {t(
                  "analyze.margin.confidence." + lot.margin_estimate.confidence,
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {lot.red_flags?.length > 0 && (
        <section
          className="rounded-lg border p-6"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
            borderLeftWidth: "3px",
            borderLeftColor: "#f59e0b",
          }}
        >
          <h3 className="font-semibold mb-3 flex items-center gap-2">
            <span style={{ color: "#f59e0b" }}>⚠</span>
            {t("analyze.flags.title")}{" "}
            <span className="text-[var(--text-muted)] font-normal text-sm">
              {lot.red_flags.length}
            </span>
          </h3>
          <ul className="space-y-2 text-sm text-[var(--text-muted)]">
            {lot.red_flags.map((f, i) => (
              <li key={i} className="flex gap-2">
                <span style={{ color: "#f59e0b" }}>•</span>
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {lot.requirements?.length > 0 && (
        <section className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-6">
          <h3 className="font-bold mb-3">
            📋 {t("analyze.requirements.title")} ({lot.requirements.length})
          </h3>
          <ul className="space-y-3">
            {lot.requirements.map((r, i) => (
              <li key={i} className="border-l-4 border-brand pl-3">
                <div className="font-medium">
                  {r.title}
                  {r.is_mandatory && (
                    <span className="ml-2 text-xs text-red-600">
                      {t("analyze.requirements.mandatory")}
                    </span>
                  )}
                </div>
                <div className="text-sm text-slate-600 dark:text-slate-300">
                  {r.description}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {lot.documents_required?.length > 0 && (
        <section className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-6">
          <h3 className="font-bold mb-2">
            📑 {t("analyze.docs.title")} ({lot.documents_required.length})
          </h3>
          <ul className="list-disc pl-5 space-y-1 text-sm">
            {lot.documents_required.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </section>
      )}

      {legal && legal.items?.length > 0 && (
        <section
          className="rounded-lg border p-6"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
            borderLeftWidth: "3px",
            borderLeftColor: "#ef4444",
          }}
        >
          <h3 className="font-semibold mb-3 flex items-center gap-2">
            <span style={{ color: "#ef4444" }}>⚖</span>
            {t("analyze.violations.title")}{" "}
            <span className="text-[var(--text-muted)] font-normal text-sm">
              {legal.items.length}
            </span>
          </h3>
          <ul className="space-y-2 text-sm">
            {legal.items.map((it, i) => (
              <li key={i} className="flex gap-2">
                <span
                  className={
                    it.status === "violation"
                      ? "text-red-600"
                      : it.status === "risk"
                        ? "text-amber-600"
                        : "text-green-600"
                  }
                >
                  {it.status === "violation"
                    ? "✗"
                    : it.status === "risk"
                      ? "!"
                      : "✓"}
                </span>
                <div>
                  <div className="font-medium">{it.rule_title}</div>
                  <div className="text-slate-600">{it.description}</div>
                  {it.law_reference && (
                    <div className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
                      📖 {it.law_reference}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {hasComplaint && (
        <section className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-6">
          <h3 className="font-bold mb-3">📝 {t("analyze.complaint.title")}</h3>
          {draftDict ? (
            <div className="space-y-3 text-sm">
              {(
                [
                  "шапка",
                  "обстоятельства",
                  "нарушенные_нормы",
                  "просьба",
                ] as const
              ).map((k) =>
                draftDict[k] ? (
                  <div key={k}>
                    <div className="font-semibold text-[var(--text)]">{k}:</div>
                    <div className="text-slate-600 dark:text-slate-300 whitespace-pre-wrap">
                      {draftDict[k]}
                    </div>
                  </div>
                ) : null,
              )}
            </div>
          ) : (
            <div className="text-sm text-slate-600 dark:text-slate-300 whitespace-pre-wrap">
              {draft as string}
            </div>
          )}
        </section>
      )}

      <div className="flex gap-3 flex-wrap pt-2">
        <button
          onClick={() => onDownload("report")}
          className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-5 py-2.5 font-medium text-white transition hover:bg-emerald-400"
        >
          <span>⬇</span> Скачать отчёт DOCX
        </button>
        {hasComplaint && (
          <button
            onClick={() => onDownload("complaint")}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border-strong)] px-5 py-2.5 font-medium transition hover:bg-[var(--accent-glow)]"
          >
            <span>⬇</span> Скачать жалобу DOCX
          </button>
        )}
        <button
          onClick={onReset}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-medium transition"
          style={{ color: "var(--text-muted)" }}
        >
          <span>↻</span>
          {t("analyze.another")}
        </button>
      </div>
    </div>
  );
}
