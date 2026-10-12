import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";
import { LayoutOrEmbed } from "../dashboard/Embedded";
import { useT } from "../i18n";
import { api, ApiError, downloadBlob } from "../clientId";
import { trackDocumentDownload } from "../dashboard/dashboard.data";
import { getSafeHttpsUrl } from "../security/externalUrl";

type Workspace = {
  id: number;
  name: string;
  organization: string | null;
  region: string | null;
  role: string;
  tz_drafts_count: number;
  created_at: string;
};

type Draft = {
  id: number;
  version: number;
  title: string;
  author_id: number;
  legal_compliance: string;
  red_flags_count: number;
  warnings_count: number;
  version_note: string | null;
  created_at: string;
};

type TzData = {
  title: string;
  description: string;
  technical_specification: string | Record<string, unknown>;
  category: string;
  procurement_method: string;
  estimated_budget_kzt: number | null;
  deadline: string | null;
  delivery_address: string | null;
  delivery_days: number | null;
  qualification_requirements: string[];
  documents_required: string[];
  evaluation_criteria: Record<string, unknown>;
  red_flags: string[];
  warnings: string[];
  legal_compliance: string;
  compliance_notes: string;
};

type ProductItem = {
  name: string;
  price_kzt: number | null;
  price_text: string;
  url: string;
  store: string;
  rating: number | null;
  reviews_count: number | null;
  match_score: number;
  match_reason: string;
  concerns: string[];
  // === Browser-Use поля ===
  browser_verified_price?: number | null;
  browser_verified_at?: string | null;
  browser_session_id?: string | null;
  browser_recording_url?: string | null;
};

type ProductSearchResult = {
  lot_id: string;
  query: string;
  products: ProductItem[];
  search_queries: string[];
  summary: string;
  // === Метрики Browser-Use ===
  browser_actions_count?: number;
  browser_total_cost_usd?: number;
  browser_total_duration_sec?: number;
};

type BrowserActionType = null | "verify_price" | "extract_contacts" | "book";

const METHOD_LABELS: Record<string, string> = {
  tender: "Открытый конкурс",
  auction: "Электронный аукцион",
  request_quotes: "Запрос ценовых",
  single_source: "Из одного источника",
  other: "Иной",
};

const COMPLIANCE_COLORS: Record<string, string> = {
  ok: "#10b981",
  review: "#f59e0b",
  violation: "#ef4444",
};

const COMPLIANCE_LABELS: Record<string, string> = {
  ok: "Соответствует",
  review: "Требует проверки",
  violation: "Есть нарушения",
};

export function B2GPage({ embedded = false }: { embedded?: boolean } = {}) {
  const t = useT();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWs, setSelectedWs] = useState<Workspace | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selectedDraft, setSelectedDraft] = useState<TzData | null>(null);
  const [view, setView] = useState<
    "list" | "create" | "view" | "ws" | "products"
  >("list");
  const [needDesc, setNeedDesc] = useState("");
  const [category, setCategory] = useState("товары");
  const [versionNote, setVersionNote] = useState("");
  const [productSearch, setProductSearch] =
    useState<ProductSearchResult | null>(null);
  const [productLoading, setProductLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Загрузка workspace'ов
  const loadWorkspaces = async () => {
    try {
      const r = await api<{ items: Workspace[] }>("/api/b2g/workspaces");
      setWorkspaces(r.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Произошла ошибка. Попробуйте снова.");
    }
  };

  useEffect(() => {
    loadWorkspaces();
  }, []);

  // Создание workspace
  const createWorkspace = async (data: {
    name: string;
    organization: string;
    organization_bin: string;
    region: string;
  }) => {
    setLoading(true);
    setError(null);
    try {
      await api("/api/b2g/workspaces", {
        method: "POST",
        body: JSON.stringify(data),
      });
      await loadWorkspaces();
      setView("list");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Произошла ошибка. Попробуйте снова.");
    } finally {
      setLoading(false);
    }
  };

  // Выбор workspace
  const selectWorkspace = async (ws: Workspace) => {
    setSelectedWs(ws);
    setSelectedDraft(null);
    setView("ws");
    try {
      const r = await api<{ items: Draft[] }>(
        `/api/b2g/workspaces/${ws.id}/drafts`,
      );
      setDrafts(r.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Произошла ошибка. Попробуйте снова.");
    }
  };

  // Генерация нового ТЗ
  const generateTz = async () => {
    if (!selectedWs) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api<{ version: number; tz_data: TzData }>(
        `/api/b2g/workspaces/${selectedWs.id}/generate`,
        {
          method: "POST",
          body: JSON.stringify({
            need_description: needDesc,
            category,
            version_note: versionNote || null,
          }),
        },
      );
      // Перезагрузить список
      const draftsR = await api<{ items: Draft[] }>(
        `/api/b2g/workspaces/${selectedWs.id}/drafts`,
      );
      setDrafts(draftsR.items);
      setView("ws");
      // Открыть новый
      const newDraft = draftsR.items.find((d) => d.version === r.version);
      if (newDraft) {
        openDraftVersion(selectedWs.id, newDraft.version);
      } else {
        // fallback: открываем последний
        const last = draftsR.items[0];
        if (last) openDraftVersion(selectedWs.id, last.version);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Произошла ошибка. Попробуйте снова.");
    } finally {
      setLoading(false);
    }
  };

  // Открыть версию
  const openDraftVersion = async (wsId: number, version: number) => {
    try {
      const r = await api<{
        id: number;
        tz_data: TzData;
        version_note: string | null;
      }>(`/api/b2g/workspaces/${wsId}/drafts/${version}`);
      // Прикрепляем id черновика к самому tz_data для связи версии
      (r.tz_data as unknown as { _id: number })._id = r.id;
      setSelectedDraft(r.tz_data);
      setView("view");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Произошла ошибка. Попробуйте снова.");
    }
  };

  // Поиск товаров через Tavily (опционально + Browser-Use)
  const [browserAction, setBrowserAction] = useState<BrowserActionType>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyProgress, setVerifyProgress] = useState<{
    current: number;
    total: number;
  } | null>(null);

  const searchProducts = async (withBrowser: BrowserActionType = null) => {
    if (!selectedDraft) return;
    if (withBrowser) setVerifying(true);
    setProductLoading(true);
    setError(null);
    try {
      // Формируем запрос на основе ТЗ
      const spec = selectedDraft.technical_specification;
      const specText =
        typeof spec === "string"
          ? spec.slice(0, 500)
          : JSON.stringify(spec).slice(0, 500);
      const query = `${selectedDraft.title}. ${specText}`;
      const r = await api<ProductSearchResult>("/api/products/search", {
        method: "POST",
        body: JSON.stringify({
          query,
          budget_kzt: selectedDraft.estimated_budget_kzt
            ? selectedDraft.estimated_budget_kzt /
              (selectedDraft.delivery_days || 1)
            : null,
          additional_info: specText,
          browser_action: withBrowser || undefined,
          browser_model: "gpt-5.4-mini",
        }),
      });
      setProductSearch(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Произошла ошибка. Попробуйте снова.");
    } finally {
      setProductLoading(false);
      setVerifying(false);
      setVerifyProgress(null);
    }
  };

  // Скачать DOCX (endpoint существует в backend: /api/b2g/.../download).
  // Единый helper downloadBlob: безопасные ошибки, отложенный revokeObjectURL.
  const downloadDocx = (version: number) => {
    if (!selectedWs) return;
    setError(null);
    const filename = `tz_v${version}.docx`;
    downloadBlob(
      `/api/b2g/workspaces/${selectedWs.id}/drafts/${version}/download`,
      filename,
    )
      .then(() => {
        trackDocumentDownload({
          id: `b2g-docx-${selectedWs.id}-v${version}`,
          kind: "report",
          filename,
          lotId: `b2g-${selectedWs.id}`,
          lotTitle: selectedWs.name,
          createdAt: new Date().toISOString(),
        });
      })
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : "Не удалось скачать файл. Попробуйте позже."),
      );
  };

  // Главный рендер
  return (
    <LayoutOrEmbed embedded={embedded}>
      <div className="page-container py-12 sm:py-16">
        <div className="mx-auto max-w-5xl">
        <div className="mb-10 flex items-end justify-between gap-6">
          <div>
            <div className="section-kicker">Подготовка документов</div>
            <h1 className="text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">
              Технические задания
            </h1>
            <p className="mt-4 max-w-2xl leading-7 text-[var(--text-muted)]">Организуйте закупки по проектам, создавайте версии ТЗ и храните рабочие документы в одном месте.</p>
          </div>
          {view !== "list" && (
            <button
              onClick={() => {
                setView("list");
                setSelectedWs(null);
                setSelectedDraft(null);
              }}
              className="text-sm text-[var(--text-muted)] hover:text-[var(--text)]"
            >
              ← К списку
            </button>
          )}
        </div>

        {error && (
          <div
            role="alert"
            className="mb-4 p-3 rounded-lg text-sm"
            style={{
              backgroundColor: "var(--bg-elevated)",
              borderLeft: "3px solid #ef4444",
              color: "#ef4444",
            }}
          >
            {error}
          </div>
        )}

        {view === "list" && (
          <WorkspaceList
            workspaces={workspaces}
            onCreate={createWorkspace}
            onSelect={selectWorkspace}
            loading={loading}
          />
        )}

        {view === "ws" && selectedWs && (
          <WorkspaceView
            workspace={selectedWs}
            drafts={drafts}
            onNewVersion={() => {
              setView("create");
              setNeedDesc("");
              setVersionNote("");
            }}
            onOpenVersion={(v) => openDraftVersion(selectedWs.id, v)}
            onDownload={downloadDocx}
          />
        )}

        {view === "create" && selectedWs && (
          <CreateTzView
            workspace={selectedWs}
            needDesc={needDesc}
            setNeedDesc={setNeedDesc}
            category={category}
            setCategory={setCategory}
            versionNote={versionNote}
            setVersionNote={setVersionNote}
            onSubmit={generateTz}
            loading={loading}
          />
        )}

        {view === "view" && selectedDraft && selectedWs && (
          <TzView
            workspace={selectedWs}
            tz={selectedDraft}
            version={
              drafts.find(
                (d) =>
                  (d as unknown as { _tz_id?: number })._tz_id ===
                  (selectedDraft as unknown as { _id?: number })._id,
              )?.version ||
              drafts[0]?.version ||
              1
            }
            onDownload={() => {
              const draftMatch = drafts.find(
                (d) =>
                  (d as unknown as { _tz_id?: number })._tz_id ===
                  (selectedDraft as unknown as { _id?: number })._id,
              );
              if (draftMatch) downloadDocx(draftMatch.version);
            }}
            onDownloadPdf={() => {
              const draftMatch =
                drafts.find(
                  (d) =>
                    (d as unknown as { _tz_id?: number })._tz_id ===
                    (selectedDraft as unknown as { _id?: number })._id,
                ) ??
                drafts[0] ??
                null;
              const v = draftMatch?.version ?? 1;
              setError(null);
              const filename = `tz_v${v}.pdf`;
              downloadBlob(
                `/api/b2g/workspaces/${selectedWs.id}/drafts/${v}/download-pdf`,
                filename,
              )
                .then(() => {
                  trackDocumentDownload({
                    id: `b2g-pdf-${selectedWs.id}-v${v}`,
                    kind: "report",
                    filename,
                    lotId: `b2g-${selectedWs.id}`,
                    lotTitle: selectedWs.name,
                    createdAt: new Date().toISOString(),
                  });
                })
                .catch((e: unknown) =>
                  setError(e instanceof ApiError ? e.message : "Не удалось скачать файл. Попробуйте позже."),
                );
            }}
            onNewVersion={() => {
              setView("create");
              setNeedDesc("");
              setVersionNote("");
            }}
            onSearchProducts={() => {
              void searchProducts();
              setView("products");
            }}
          />
        )}

        {view === "products" && (
          <ProductSearchView
            result={productSearch}
            loading={productLoading}
            verifying={verifying}
            browserAction={browserAction}
            onBack={() => setView("view")}
            onSearchAgain={() => void searchProducts(null)}
            onVerifyWithBrowser={(action) => {
              setBrowserAction(action);
              void searchProducts(action);
            }}
          />
        )}
        </div>
      </div>
    </LayoutOrEmbed>
  );
}

// ───── Sub-views ─────

function WorkspaceList({
  workspaces,
  onCreate,
  onSelect,
  loading,
}: {
  workspaces: Workspace[];
  onCreate: (d: {
    name: string;
    organization: string;
    organization_bin: string;
    region: string;
  }) => void;
  onSelect: (ws: Workspace) => void;
  loading: boolean;
}) {
  const [name, setName] = useState("");
  const [org, setOrg] = useState("");
  const [bin, setBin] = useState("");
  const [region, setRegion] = useState("");
  const [showForm, setShowForm] = useState(false);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    onCreate({ name, organization: org, organization_bin: bin, region });
    setName("");
    setOrg("");
    setBin("");
    setRegion("");
  };

  return (
    <div>
      <div className="mb-5 flex items-center justify-between gap-4">
        <div><h2 className="text-xl font-semibold">Мои проекты</h2><p className="mt-1 text-sm text-[var(--text-muted)]">Отдельный проект для каждой закупки или организации.</p></div>
        <button
          onClick={() => setShowForm(!showForm)}
          className={showForm ? "button-secondary" : "button-primary"}
        >
          {showForm ? "Отмена" : "Новый проект"}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={submit}
          className="mb-6 space-y-3 rounded-3xl border p-6"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
          }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Название (например, Школа №5 Шымкент)"
            required
            className="w-full px-3 py-2 rounded-md border bg-[var(--bg)] text-[var(--text)]"
            style={{ borderColor: "var(--border-strong)" }}
          />
          <input
            value={org}
            onChange={(e) => setOrg(e.target.value)}
            placeholder="Название организации (КГУ Школа-гимназия №5)"
            className="w-full px-3 py-2 rounded-md border bg-[var(--bg)] text-[var(--text)]"
            style={{ borderColor: "var(--border-strong)" }}
          />
          <input
            value={bin}
            onChange={(e) => setBin(e.target.value)}
            placeholder="БИН (12 цифр)"
            className="w-full px-3 py-2 rounded-md border bg-[var(--bg)] text-[var(--text)]"
            style={{ borderColor: "var(--border-strong)" }}
          />
          <input
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            placeholder="Регион (Алматы, Шымкент, Астана...)"
            className="w-full px-3 py-2 rounded-md border bg-[var(--bg)] text-[var(--text)]"
            style={{ borderColor: "var(--border-strong)" }}
          />
          <button
            type="submit"
            disabled={loading || !name}
            className="px-4 py-2 rounded-md text-white disabled:opacity-50"
            style={{ backgroundColor: "var(--accent)" }}
          >
            {loading ? "Создание..." : "Создать"}
          </button>
        </form>
      )}

      {workspaces.length === 0 ? (
        <div
          className="rounded-[28px] border border-dashed p-10 text-center"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
          }}
        >
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-400/20 bg-emerald-400/[0.07] text-emerald-300">01</div>
          <h3 className="mt-5 text-lg font-semibold text-[var(--text)]">Создайте первый проект</h3>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">Укажите организацию и регион, а затем добавьте описание закупки для подготовки технического задания.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {workspaces.map((ws) => (
            <button
              key={ws.id}
              onClick={() => onSelect(ws)}
              className="rounded-lg border p-4 text-left transition hover:border-[var(--accent)]"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="font-medium mb-1">{ws.name}</div>
              {ws.organization && (
                <div className="text-xs text-[var(--text-muted)] mb-1">
                  {ws.organization}
                </div>
              )}
              {ws.region && (
                <div className="text-xs text-[var(--text-subtle)] mb-2">
                  {ws.region}
                </div>
              )}
              <div className="text-xs text-[var(--text-subtle)]">
                {ws.tz_drafts_count} черновик(ов) ·{" "}
                {ws.role === "owner" ? "owner" : "member"}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function WorkspaceView({
  workspace,
  drafts,
  onNewVersion,
  onOpenVersion,
  onDownload,
}: {
  workspace: Workspace;
  drafts: Draft[];
  onNewVersion: () => void;
  onOpenVersion: (v: number) => void;
  onDownload: (v: number) => void;
}) {
  return (
    <div>
      <div
        className="rounded-lg border p-5 mb-4"
        style={{
          backgroundColor: "var(--bg-elevated)",
          borderColor: "var(--border)",
        }}
      >
        <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-1">
          Workspace
        </div>
        <div className="text-xl font-semibold">{workspace.name}</div>
        {workspace.organization && (
          <div className="text-sm text-[var(--text-muted)] mt-1">
            {workspace.organization}
          </div>
        )}
        {workspace.region && (
          <div className="text-xs text-[var(--text-subtle)] mt-1">
            {workspace.region}
          </div>
        )}
      </div>

      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">Версии ТЗ ({drafts.length})</h2>
        <button
          onClick={onNewVersion}
          className="px-3 py-1.5 rounded-md text-sm text-white"
          style={{ backgroundColor: "var(--accent)" }}
        >
          + Новая версия
        </button>
      </div>

      {drafts.length === 0 ? (
        <div
          className="rounded-lg border p-8 text-center text-[var(--text-muted)]"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
          }}
        >
          Нет версий. Создайте первую.
        </div>
      ) : (
        <div className="space-y-2">
          {drafts.map((d) => (
            <div
              key={d.id}
              className="rounded-lg border p-3 flex items-center gap-3"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div
                className="text-2xl font-bold tabular-nums"
                style={{ color: "var(--accent)" }}
              >
                v{d.version}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">
                  {d.title || "(без названия)"}
                </div>
                {d.version_note && (
                  <div className="text-xs text-[var(--text-muted)] truncate mt-0.5">
                    💬 {d.version_note}
                  </div>
                )}
                <div className="text-xs text-[var(--text-subtle)] mt-0.5">
                  {new Date(d.created_at).toLocaleString("ru-RU")}
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span
                  className="px-2 py-0.5 rounded font-medium"
                  style={{
                    backgroundColor: `${COMPLIANCE_COLORS[d.legal_compliance]}20`,
                    color: COMPLIANCE_COLORS[d.legal_compliance],
                  }}
                >
                  {COMPLIANCE_LABELS[d.legal_compliance]}
                </span>
                {d.red_flags_count > 0 && (
                  <span className="text-[var(--text-muted)]">
                    ⚠ {d.red_flags_count}
                  </span>
                )}
                {d.warnings_count > 0 && (
                  <span className="text-[var(--text-muted)]">
                    ! {d.warnings_count}
                  </span>
                )}
              </div>
              <div className="flex gap-1">
                <button
                  onClick={() => onOpenVersion(d.version)}
                  className="px-2 py-1 text-xs rounded-md border transition"
                  style={{
                    borderColor: "var(--border-strong)",
                    color: "var(--text)",
                  }}
                >
                  Открыть
                </button>
                <button
                  onClick={() => onDownload(d.version)}
                  className="px-2 py-1 text-xs rounded-md transition"
                  style={{
                    backgroundColor: "var(--accent-glow)",
                    color: "var(--accent)",
                  }}
                >
                  ⬇ DOCX
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateTzView({
  workspace,
  needDesc,
  setNeedDesc,
  category,
  setCategory,
  versionNote,
  setVersionNote,
  onSubmit,
  loading,
}: {
  workspace: Workspace;
  needDesc: string;
  setNeedDesc: (v: string) => void;
  category: string;
  setCategory: (v: string) => void;
  versionNote: string;
  setVersionNote: (v: string) => void;
  onSubmit: () => void;
  loading: boolean;
}) {
  return (
    <div
      className="rounded-lg border p-6"
      style={{
        backgroundColor: "var(--bg-elevated)",
        borderColor: "var(--border)",
      }}
    >
      <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-1">
        Новая версия для
      </div>
      <div className="text-lg font-semibold mb-4">{workspace.name}</div>

      <label className="block text-sm font-medium mb-1">
        Что нужно закупить
      </label>
      <textarea
        value={needDesc}
        onChange={(e) => setNeedDesc(e.target.value)}
        placeholder="Например: Нужно закупить 30 ученических парт для нового крыла школы. Парты регулируемые по высоте, цвет бук, для детей 7-10 лет. Доставка в Шымкент, ул. Абая 15, за 30 дней. Бюджет около 3 млн."
        rows={6}
        required
        className="w-full px-3 py-2 rounded-md border bg-[var(--bg)] text-[var(--text)] mb-4"
        style={{ borderColor: "var(--border-strong)" }}
      />

      <label className="block text-sm font-medium mb-1">Категория</label>
      <select
        value={category}
        onChange={(e) => setCategory(e.target.value)}
        className="w-full px-3 py-2 rounded-md border bg-[var(--bg)] text-[var(--text)] mb-4"
        style={{ borderColor: "var(--border-strong)" }}
      >
        <option value="товары">Товары</option>
        <option value="услуги">Услуги</option>
        <option value="работы">Работы</option>
      </select>

      <label className="block text-sm font-medium mb-1">
        Комментарий к версии (необязательно)
      </label>
      <input
        value={versionNote}
        onChange={(e) => setVersionNote(e.target.value)}
        placeholder="Например: С учётом замечаний бухгалтера"
        className="w-full px-3 py-2 rounded-md border bg-[var(--bg)] text-[var(--text)] mb-4"
        style={{ borderColor: "var(--border-strong)" }}
      />

      <button
        onClick={onSubmit}
        disabled={loading || !needDesc}
        className="w-full px-4 py-3 rounded-md text-white font-medium disabled:opacity-50"
        style={{ backgroundColor: "var(--accent)" }}
      >
        {loading ? "Генерация (30-60 сек)..." : "Сгенерировать ТЗ"}
      </button>
    </div>
  );
}

function TzView({
  workspace,
  tz,
  version,
  onDownload,
  onDownloadPdf,
  onNewVersion,
  onSearchProducts,
}: {
  workspace: Workspace;
  tz: TzData;
  version: number;
  onDownload: () => void;
  onDownloadPdf: () => void;
  onNewVersion: () => void;
  onSearchProducts: () => void;
}) {
  return (
    <div className="space-y-4">
      {/* Шапка */}
      <div
        className="rounded-lg border p-5"
        style={{
          backgroundColor: "var(--bg-elevated)",
          borderColor: "var(--border)",
        }}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <h2 className="text-xl font-semibold tracking-tight">{tz.title}</h2>
            {workspace.organization && (
              <div className="text-sm text-[var(--text-muted)] mt-1">
                {workspace.organization}
              </div>
            )}
            <div className="flex flex-wrap gap-2 mt-2 text-xs">
              {tz.category && (
                <span className="px-2 py-0.5 rounded bg-[var(--border)]">
                  {tz.category}
                </span>
              )}
              {tz.procurement_method && (
                <span className="px-2 py-0.5 rounded bg-[var(--border)]">
                  {METHOD_LABELS[tz.procurement_method] ||
                    tz.procurement_method}
                </span>
              )}
              {tz.estimated_budget_kzt && (
                <span className="px-2 py-0.5 rounded bg-[var(--border)] tabular-nums">
                  ≈ {tz.estimated_budget_kzt.toLocaleString()} ₸
                </span>
              )}
              <span
                className="px-2 py-0.5 rounded font-medium"
                style={{
                  backgroundColor: `${COMPLIANCE_COLORS[tz.legal_compliance]}20`,
                  color: COMPLIANCE_COLORS[tz.legal_compliance],
                }}
              >
                {COMPLIANCE_LABELS[tz.legal_compliance]}
              </span>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <button
              onClick={onSearchProducts}
              className="px-3 py-1.5 rounded-md text-sm font-medium"
              style={{
                backgroundColor: "var(--accent-glow)",
                color: "var(--accent)",
                border: "1px solid var(--accent)",
              }}
            >
              🔍 Найти товары
            </button>
            <button
              onClick={onDownload}
              className="px-3 py-1.5 rounded-md text-sm text-white"
              style={{ backgroundColor: "var(--accent)" }}
            >
              ⬇ DOCX
            </button>
            <button
              onClick={onDownloadPdf}
              className="px-3 py-1.5 rounded-md text-sm border"
              style={{
                borderColor: "var(--border-strong)",
                color: "var(--text)",
              }}
            >
              ⬇ PDF
            </button>
            <button
              onClick={onNewVersion}
              className="px-3 py-1.5 rounded-md text-sm border"
              style={{
                borderColor: "var(--border-strong)",
                color: "var(--text)",
              }}
            >
              + Версия
            </button>
          </div>
        </div>
      </div>

      {/* Compliance notes */}
      {tz.compliance_notes && (
        <div
          className="rounded-lg border p-4"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
            borderLeftWidth: "3px",
            borderLeftColor: COMPLIANCE_COLORS[tz.legal_compliance],
          }}
        >
          <div className="text-xs font-medium uppercase tracking-wider text-[var(--text-muted)] mb-1">
            Замечание по закону
          </div>
          <div className="text-sm">{tz.compliance_notes}</div>
        </div>
      )}

      {/* Description */}
      {tz.description && (
        <Section title="Описание">
          <p className="text-sm text-[var(--text-muted)] whitespace-pre-wrap">
            {tz.description}
          </p>
        </Section>
      )}

      {/* Tech spec */}
      {tz.technical_specification && (
        <Section title="Техническая спецификация">
          {typeof tz.technical_specification === "string" ? (
            <pre className="text-xs whitespace-pre-wrap text-[var(--text-muted)] font-mono">
              {tz.technical_specification}
            </pre>
          ) : (
            <pre className="text-xs whitespace-pre-wrap text-[var(--text-muted)] font-mono">
              {JSON.stringify(tz.technical_specification, null, 2)}
            </pre>
          )}
        </Section>
      )}

      {/* Requirements + Documents */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {tz.qualification_requirements?.length > 0 && (
          <Section title="Квалификационные требования">
            <ul className="text-sm space-y-1">
              {tz.qualification_requirements.map((r, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-[var(--text-muted)]">•</span>
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}
        {tz.documents_required?.length > 0 && (
          <Section title="Документы">
            <ul className="text-sm space-y-1">
              {tz.documents_required.map((d, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-[var(--text-muted)]">•</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>

      {/* Red flags */}
      {tz.red_flags?.length > 0 && (
        <Section title="⚠ Возможные нарушения">
          <ul className="text-sm space-y-1.5">
            {tz.red_flags.map((f, i) => (
              <li
                key={i}
                className="flex gap-2 p-2 rounded"
                style={{ backgroundColor: "rgba(239, 68, 68, 0.08)" }}
              >
                <span style={{ color: "#ef4444" }}>!</span>
                <span className="text-[var(--text-muted)]">{f}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Warnings */}
      {tz.warnings?.length > 0 && (
        <Section title="Рекомендации">
          <ul className="text-sm space-y-1.5">
            {tz.warnings.map((w, i) => (
              <li
                key={i}
                className="flex gap-2 p-2 rounded"
                style={{ backgroundColor: "rgba(245, 158, 11, 0.08)" }}
              >
                <span style={{ color: "#f59e0b" }}>!</span>
                <span className="text-[var(--text-muted)]">{w}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-lg border p-4"
      style={{
        backgroundColor: "var(--bg-elevated)",
        borderColor: "var(--border)",
      }}
    >
      <div className="text-xs font-medium uppercase tracking-wider text-[var(--text-muted)] mb-2">
        {title}
      </div>
      {children}
    </div>
  );
}

// ───── ProductSearchView (поиск товаров через Tavily + опционально Browser-Use) ─────

function ProductSearchView({
  result,
  loading,
  verifying,
  onBack,
  onSearchAgain,
  onVerifyWithBrowser,
  browserAction,
}: {
  result: ProductSearchResult | null;
  loading: boolean;
  verifying: boolean;
  onBack: () => void;
  onSearchAgain: () => void;
  onVerifyWithBrowser: (action: "verify_price" | "extract_contacts") => void;
  browserAction: BrowserActionType;
}) {
  const hasBrowserResults =
    (result?.browser_actions_count ?? 0) > 0 ||
    result?.products.some((p) => p.browser_session_id);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <button
          onClick={onBack}
          className="text-sm text-[var(--text-muted)] hover:text-[var(--text)]"
        >
          ← Назад к ТЗ
        </button>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={onSearchAgain}
            disabled={loading || verifying}
            className="px-3 py-1.5 rounded-md text-sm border transition disabled:opacity-50"
            style={{
              borderColor: "var(--border-strong)",
              color: "var(--text)",
            }}
          >
            {loading ? "⏳ Ищу..." : "↻ Tavily"}
          </button>
          <button
            onClick={() => onVerifyWithBrowser("verify_price")}
            disabled={
              loading || verifying || !result || result.products.length === 0
            }
            className="px-3 py-1.5 rounded-md text-sm font-medium transition disabled:opacity-50"
            style={{
              backgroundColor: "var(--accent)",
              color: "white",
            }}
            title="ИИ-агент зайдёт на сайт и проверит реальную цену"
          >
            {verifying && browserAction === "verify_price"
              ? "⏳ Проверяю цены..."
              : "🤖 Проверить цены на сайтах"}
          </button>
          <button
            onClick={() => onVerifyWithBrowser("extract_contacts")}
            disabled={
              loading || verifying || !result || result.products.length === 0
            }
            className="px-3 py-1.5 rounded-md text-sm border transition disabled:opacity-50"
            style={{
              borderColor: "var(--border-strong)",
              color: "var(--text)",
            }}
            title="Достать контакты поставщика (email, телефон, БИН)"
          >
            {verifying && browserAction === "extract_contacts"
              ? "⏳ Ищу контакты..."
              : "📞 Контакты"}
          </button>
        </div>
      </div>

      <div
        className="rounded-lg border p-5"
        style={{
          backgroundColor: "var(--bg-elevated)",
          borderColor: "var(--border)",
        }}
      >
        <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-1">
          Поиск товаров
        </div>
        <div className="text-lg font-semibold mb-2">
          {result?.query || "Загрузка..."}
        </div>
        {result && result.search_queries.length > 0 && (
          <div className="text-xs text-[var(--text-muted)]">
            Поисковые запросы:{" "}
            {result.search_queries.map((q, i) => (
              <span
                key={i}
                className="inline-block px-2 py-0.5 rounded mr-1"
                style={{ backgroundColor: "var(--border)" }}
              >
                {q}
              </span>
            ))}
          </div>
        )}

        {/* Метрики Browser-Use */}
        {hasBrowserResults && (
          <div
            className="mt-3 pt-3 text-xs flex flex-wrap gap-3"
            style={{
              borderTop: "1px solid var(--border)",
              color: "var(--text-muted)",
            }}
          >
            <span>
              🤖 Проверено браузером:{" "}
              <b style={{ color: "var(--text)" }}>
                {result?.browser_actions_count ?? 0}
              </b>{" "}
              товаров
            </span>
            <span>
              💰 Стоимость:{" "}
              <b style={{ color: "var(--text)" }}>
                ${(result?.browser_total_cost_usd ?? 0).toFixed(3)}
              </b>
            </span>
            <span>
              ⏱ Время:{" "}
              <b style={{ color: "var(--text)" }}>
                {Math.round(result?.browser_total_duration_sec ?? 0)}s
              </b>
            </span>
          </div>
        )}
      </div>

      {loading && <ProductSearchSkeleton />}

      {!loading && result && (
        <>
          {result.summary && (
            <div
              className="rounded-lg p-4 text-sm"
              style={{
                backgroundColor: "var(--bg-elevated)",
                border: "1px solid var(--border)",
                borderLeftWidth: "3px",
                borderLeftColor: "var(--accent)",
              }}
            >
              {result.summary}
            </div>
          )}

          {result.products.length === 0 ? (
            <div
              className="rounded-lg p-8 text-center text-[var(--text-muted)]"
              style={{
                backgroundColor: "var(--bg-elevated)",
                border: "1px solid var(--border)",
              }}
            >
              Ничего не найдено. Попробуйте изменить запрос.
            </div>
          ) : (
            <div className="space-y-3">
              {result.products.map((p, i) => (
                <ProductCard key={i} product={p} rank={i + 1} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ProductCard({
  product,
  rank,
}: {
  product: ProductItem;
  rank: number;
}) {
  const scoreColor =
    product.match_score >= 80
      ? "#10b981"
      : product.match_score >= 60
        ? "#f59e0b"
        : "#ef4444";

  const hasBrowserPrice =
    product.browser_verified_price != null &&
    product.browser_verified_price !== product.price_kzt;
  // Ссылки из поиска товаров — произвольные домены магазинов, поэтому
  // проверяем их общей https-проверкой (без allowlist) + rel noopener noreferrer.
  // javascript:, data:, file:, http: и userinfo отклоняются.
  const safeProductUrl = getSafeHttpsUrl(product.url);
  const safeRecordingUrl = getSafeHttpsUrl(product.browser_recording_url);
  const browserPriceLower =
    hasBrowserPrice &&
    (product.browser_verified_price ?? 0) < (product.price_kzt ?? Infinity);

  return (
    <div
      className="rounded-lg border p-4 transition hover:border-[var(--accent)]"
      style={{
        backgroundColor: "var(--bg-elevated)",
        borderColor: "var(--border)",
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
          style={{ backgroundColor: `${scoreColor}20`, color: scoreColor }}
        >
          {rank}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2 mb-1">
            {safeProductUrl ? (
              <a
                href={safeProductUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium hover:underline"
                style={{ color: "var(--accent)" }}
              >
                {product.name}
              </a>
            ) : (
              <span className="font-medium" style={{ color: "var(--accent)" }}>
                {product.name}
              </span>
            )}
            <div className="text-right flex-shrink-0">
              {product.price_kzt && (
                <div
                  className={`text-lg font-bold tabular-nums whitespace-nowrap ${
                    hasBrowserPrice ? "line-through opacity-60" : ""
                  }`}
                  style={{ color: scoreColor }}
                >
                  {product.price_kzt.toLocaleString()} ₸
                </div>
              )}
              {hasBrowserPrice && (
                <div
                  className="text-lg font-bold tabular-nums whitespace-nowrap"
                  style={{ color: browserPriceLower ? "#10b981" : "#ef4444" }}
                  title={`Проверено ИИ в браузере${product.browser_verified_at ? " " + new Date(product.browser_verified_at).toLocaleString("ru-RU") : ""}`}
                >
                  {product.browser_verified_price?.toLocaleString()} ₸
                  <span className="ml-1 text-xs">🤖</span>
                </div>
              )}
            </div>
          </div>

          <div className="flex flex-wrap gap-3 text-xs text-[var(--text-muted)] mb-2">
            {product.store && <span>🏪 {product.store}</span>}
            {product.rating && <span>⭐ {product.rating.toFixed(1)}</span>}
            {product.reviews_count && (
              <span>({product.reviews_count} отзывов)</span>
            )}
            {product.browser_session_id && (
              <span
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor: "var(--border)",
                  color: "var(--text)",
                }}
                title={`Session: ${product.browser_session_id}`}
              >
                🤖 Проверено
              </span>
            )}
          </div>

          {product.match_reason && (
            <p className="text-sm text-[var(--text-muted)] mb-2">
              ✓ {product.match_reason}
            </p>
          )}

          {product.concerns.length > 0 && (
            <div className="text-xs">
              <div className="text-[var(--text-muted)] font-medium mb-1">
                ⚠ Обратить внимание:
              </div>
              <ul className="space-y-0.5">
                {product.concerns.map((c, i) => (
                  <li
                    key={i}
                    className="text-[var(--text-muted)] pl-3"
                    style={{ borderLeft: "2px solid #f59e0b" }}
                  >
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <div
              className="text-xs px-2 py-0.5 rounded font-medium"
              style={{ backgroundColor: `${scoreColor}20`, color: scoreColor }}
            >
              Match: {product.match_score}/100
            </div>
            {safeProductUrl && (
              <a
                href={safeProductUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs hover:underline"
                style={{ color: "var(--text-muted)" }}
              >
                Открыть →
              </a>
            )}
            {safeRecordingUrl && (
              <a
                href={safeRecordingUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs hover:underline"
                style={{ color: "var(--accent)" }}
                title="Видео запись сессии ИИ-агента (1 час)"
              >
                🎥 Видео
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ProductSearchSkeleton() {
  return (
    <div className="space-y-3">
      <style>{`
        @keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
        .shimmer {
          background: linear-gradient(90deg, var(--border) 0%, var(--bg-elevated) 50%, var(--border) 100%);
          background-size: 200% 100%;
          animation: shimmer 1.5s infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .spinner { animation: spin 1s linear infinite; }
      `}</style>

      <div
        className="rounded-lg p-4"
        style={{
          backgroundColor: "var(--bg-elevated)",
          border: "1px solid var(--border)",
        }}
      >
        <div className="flex items-center gap-3 mb-3">
          <div
            className="w-5 h-5 rounded-full spinner"
            style={{
              border: "2px solid var(--border)",
              borderTopColor: "var(--accent)",
            }}
          />
          <div className="text-sm font-medium">
            AI ищет товары в интернет-магазинах...
          </div>
        </div>
        <div className="text-xs text-[var(--text-muted)] mb-3">
          Это может занять 30-90 секунд. Генерируем поисковые запросы, ищем
          через Tavily, фильтруем результаты через LLM.
        </div>
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="shimmer rounded h-20"
              style={{ opacity: 0.7 - i * 0.15 }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
