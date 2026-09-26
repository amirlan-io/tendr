import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";
import { useT } from "../i18n";
import { api, downloadFile, getOrCreateClientId } from "../clientId";

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

const HISTORY_KEY = "tendr_history";

type HistoryItem = {
  lot_id: string;
  title: string;
  customer: string;
  method: string;
  overall_risk?: string;
  n_requirements: number;
  n_red_flags: number;
  url?: string;
  created_at: string;
};

function loadHistory(): HistoryItem[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(HISTORY_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveHistory(items: HistoryItem[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 20)));
}

function pushHistory(item: HistoryItem) {
  const items = loadHistory().filter((i) => i.lot_id !== item.lot_id);
  items.unshift(item);
  saveHistory(items);
}

export function AnalyzePage() {
  const t = useT();
  const [searchParams] = useSearchParams();
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState(false);
  const [autoTitle, setAutoTitle] = useState<string>("");
  const fileInput = useRef<HTMLInputElement>(null);

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
            const cid = getOrCreateClientId();
            const resp = await api<AnalysisResponse>(
              "/api/lots/analyze",
              {
                method: "POST",
                body: JSON.stringify({ url: lotUrl }),
                headers: { "X-Client-Id": cid },
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
          } catch (e: any) {
            setError(
              e?.response?.data?.detail || e?.message || "Ошибка анализа"
            );
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
    setError(null);
    setResult(null);
    setQuota(false);
    setLoading(true);
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
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (
        msg.toLowerCase().includes("limit") ||
        msg.toLowerCase().includes("лимит")
      ) {
        setQuota(true);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function reset() {
    setResult(null);
    setError(null);
    setQuota(false);
    setUrl("");
    setFile(null);
  }

  function downloadDocx(kind: "complaint" | "report") {
    if (!result) return;
    const lotId = result.lot.lot_id;
    const stamp = new Date().toISOString().slice(0, 10);
    const filename =
      kind === "complaint"
        ? `zhaloba_${lotId}_${stamp}.docx`
        : `otchet_${lotId}_${stamp}.docx`;
    void downloadFile(`/api/lots/${lotId}/download?kind=${kind}`, filename)
      .catch((e) => alert(String(e)));
  }

  return (
    <Layout>
      <div className="max-w-4xl mx-auto px-6 py-8">
        <Link
          to="/"
          className="text-sm text-[var(--text-muted)] hover:underline"
        >
          {t("common.back")}
        </Link>
        <h1 className="text-2xl font-bold mt-2 mb-2">{t("analyze.title")}</h1>
        <p className="text-[var(--text-muted)] mb-6">{t("analyze.help")}</p>

        {autoTitle && (
          <div className="mb-4 px-4 py-3 rounded-lg border border-blue-300 bg-blue-50 dark:bg-blue-900/30 text-sm">
            <div className="font-medium text-blue-700 dark:text-blue-300 mb-1">
              🤖 Автоматический анализ из каталога
            </div>
            <div className="text-[var(--text-muted)]">
              <b>{autoTitle}</b>
            </div>
            <div className="text-xs text-slate-500 mt-1">{url}</div>
          </div>
        )}

        {loading && (
          <div className="mb-4 px-4 py-3 rounded-lg border border-blue-300 bg-blue-50 dark:bg-blue-900/30 text-sm">
            <div className="font-medium text-blue-700 dark:text-blue-300 mb-2">
              ⏳ Идёт AI-анализ (30-90 сек)...
            </div>
            <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2 overflow-hidden">
              <div
                className="bg-blue-600 h-full animate-pulse"
                style={{ width: "60%" }}
              />
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Documenter анализирует ТЗ + Legal проверяет соответствие Закону РК
            </div>
          </div>
        )}

        <form onSubmit={submit} className="space-y-3 mb-6">
          <div className="flex gap-2">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t("analyze.placeholder")}
              className="flex-1 px-4 py-2 border border-[var(--border-strong)] bg-[var(--bg-elevated)] text-[var(--text)] placeholder:text-[var(--text-subtle)] rounded-lg focus:outline-none focus:ring-2 focus:ring-brand"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || (!url.trim() && !file)}
              className="bg-[var(--accent)] text-white px-6 py-2.5 rounded-lg font-medium hover:bg-brand-dark transition disabled:opacity-50"
            >
              {loading ? t("analyze.submitting") : t("analyze.submit")}
            </button>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-500 dark:text-slate-400">
              {t("analyze.file.label")}
            </span>
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx,.txt"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="text-sm text-slate-600 dark:text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:bg-slate-100 dark:file:bg-slate-700 file:text-slate-700 dark:file:text-slate-200 hover:file:bg-slate-200 dark:hover:file:bg-slate-600"
              disabled={loading}
            />
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
          </div>
        )}

        {error && (
          <div
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
            onDownload={downloadDocx}
            onReset={reset}
          />
        )}
      </div>
    </Layout>
  );
}

function ResultView({
  result,
  onDownload,
  onReset,
}: {
  result: AnalysisResponse;
  onDownload: (k: "complaint" | "report") => void;
  onReset: () => void;
}) {
  const t = useT();
  const lot = result.lot;
  const legal = result.legal;
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
        {hasComplaint && (
          <button
            onClick={() => onDownload("complaint")}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-medium text-white transition"
            style={{
              background: "#0e7c7b",
              boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
            }}
          >
            <span>📥</span>
            {t("analyze.complaint.download")}
          </button>
        )}
        <button
          onClick={() => onDownload("report")}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-medium border transition"
          style={{
            background: "var(--bg-elevated)",
            borderColor: "var(--border-strong)",
            color: "var(--text)",
          }}
        >
          <span>📄</span>
          {t("analyze.report.download")}
        </button>
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
