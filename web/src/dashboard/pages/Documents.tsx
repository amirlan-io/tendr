import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, downloadBlob } from "../../clientId";
import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";
import { removeDocument } from "../dashboard.data";
import { useHistoryList, useLocalCabinet } from "../hooks/useDashboardData";
import { DashboardIcon } from "../DashboardIcon";

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function isNumericId(lotId: string): boolean {
  return /^\d+$/.test(lotId.trim());
}

export function DocumentsPage() {
  const { items: history, loading } = useHistoryList();
  const { documents, refresh } = useLocalCabinet();
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Скачивание доступно только для анализов с числовым ID лота:
  // backend-эндпоинт GET /api/lots/{lot_id}/download принимает только int.
  const downloadable = history.filter((i) => isNumericId(i.lot_id));

  const download = async (lotId: string, kind: "complaint" | "report", filename: string) => {
    setDownloading(`${kind}-${lotId}`);
    setError(null);
    try {
      await downloadBlob(`/api/lots/${lotId}/download?kind=${kind}`, filename);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось скачать файл. Попробуйте позже.");
    } finally {
      setDownloading(null);
    }
  };

  const remove = (id: string) => {
    if (!window.confirm("Убрать документ из списка? Файл уже скачан и останется у вас.")) return;
    removeDocument(id);
    refresh();
  };

  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[.2em] text-white/35">
        Файлы
      </p>
      <h1 className="mt-3 text-3xl font-medium tracking-[-.045em] text-white">Документы</h1>
      <p className="mt-3 max-w-xl text-sm leading-6 text-white/42">
        Жалобы и отчёты по вашим анализам. Кнопка скачивания есть только там,
        где файл действительно существует на сервере.
      </p>

      {error && (
        <p role="alert" className="mt-6 rounded-xl border border-red-400/20 bg-red-400/[0.06] px-4 py-3 text-xs text-red-300">
          {error}
        </p>
      )}

      <section aria-label="Скачанные документы" className="mt-8 overflow-hidden rounded-xl border border-white/[0.075] bg-[#121213]/90">
        <div className="border-b border-white/[0.07] px-5 py-5 sm:px-6">
          <p className="text-sm font-medium text-white">Подготовленные документы</p>
          <p className="mt-1 text-xs text-white/30">Файлы, которые вы уже скачали</p>
        </div>
        {documents.length === 0 ? (
          <EmptyState
            title="Документы появятся после анализа закупки"
            text="Проведите анализ, скачайте жалобу или отчёт — и он сохранится в этом списке."
            actionTo="/dashboard/analyze"
            actionLabel="Перейти к анализу"
          />
        ) : (
          <ul className="divide-y divide-white/[0.06]">
            {documents.map((doc) => (
              <li key={doc.id} className="flex items-center gap-3 px-5 py-4 sm:px-6">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/[0.04] text-white/50">
                  <DashboardIcon name="docs" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-white/80">{doc.filename}</p>
                  <p className="mt-1 truncate text-[11px] text-white/25">
                    {doc.kind === "complaint" ? "Жалоба" : "Отчёт"} · {doc.lotTitle} · {formatDateTime(doc.createdAt)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => remove(doc.id)}
                  aria-label={`Убрать ${doc.filename} из списка`}
                  className="rounded-lg px-2 py-1 text-xs text-white/30 hover:text-red-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
                >
                  Убрать
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Доступно для скачивания" className="mt-4 overflow-hidden rounded-xl border border-white/[0.075] bg-[#121213]/90">
        <div className="border-b border-white/[0.07] px-5 py-5 sm:px-6">
          <p className="text-sm font-medium text-white">Доступно из анализов</p>
          <p className="mt-1 text-xs text-white/30">Отчёты формируются сервером по данным анализа</p>
        </div>
        {loading ? (
          <div className="p-6">
            <Skeleton lines={2} />
          </div>
        ) : downloadable.length === 0 ? (
          <p className="px-6 py-8 text-center text-sm text-white/30">
            Нет анализов, для которых сервер может сформировать документ.
          </p>
        ) : (
          <ul className="divide-y divide-white/[0.06]">
            {downloadable.map((item) => {
              const busy = downloading !== null;
              return (
                <li key={`${item.lot_id}-${item.created_at}`} className="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_auto] sm:items-center sm:px-6">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-white/80">
                      {item.title || `Лот № ${item.lot_id}`}
                    </p>
                    <p className="mt-1 truncate text-[11px] text-white/25">
                      {item.customer || "Заказчик не указан"} · {formatDateTime(item.created_at)}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void download(item.lot_id, "report", `otchet_${item.lot_id}.docx`)}
                      className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.025] px-4 text-xs font-medium text-white/70 transition hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <DashboardIcon name="download" />
                      {downloading === `report-${item.lot_id}` ? "Скачивание…" : "Отчёт"}
                    </button>
                    <Link
                      to="/dashboard/analyze"
                      className="inline-flex min-h-11 items-center rounded-xl px-3 text-xs font-medium text-emerald-300 hover:text-emerald-200"
                    >
                      Открыть анализ
                    </Link>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
