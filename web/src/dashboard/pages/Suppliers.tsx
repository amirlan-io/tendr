/**
 * Страница «Поиск поставщиков» (/dashboard/suppliers).
 *
 * Реализует этапы 2–4 ТЗ:
 *  1. Поиск поставщиков по лоту (F1);
 *  2. Шорт-лист со сверкой по пунктам ТЗ (F2–F3);
 *  3. Черновик письма / план звонка → пользователь решает (F3–F4).
 *
 * Отправка писем и звонков с этой страницы НЕ выполняется: её делает
 * /api/outresh только после одобрения. Поэтому здесь только подготовка
 * и решение — так соблюдается правило «без approval ноль исходящих».
 */

import { useCallback, useEffect, useState } from "react";
import {
  createDraft,
  decideApproval,
  explainBlock,
  fetchLotRequirements,
  fetchShortlist,
  friendlyError,
  searchSuppliers,
  sendSupplierFeedback,
} from "../suppliers.api";
import type {
  Approval,
  CallPlan,
  DraftResponse,
  EmailDraft,
  LotRequirements,
  SupplierCandidate,
} from "../suppliers.types";
import { SupplierCandidateCard } from "../components/SupplierCandidateCard";
import { LotSourceLink } from "../components/LotSourceLink";
import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";

function isCallPlan(value: DraftResponse["draft"]): value is CallPlan {
  return "introduction" in value || "questions" in value;
}

function isEmailDraft(value: DraftResponse["draft"]): value is EmailDraft {
  return "body" in value;
}

export function SuppliersPage() {
  const [lotId, setLotId] = useState("");
  const [candidates, setCandidates] = useState<SupplierCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [draft, setDraft] = useState<DraftResponse | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [lotInfo, setLotInfo] = useState<LotRequirements | null>(null);

  useEffect(() => {
    const lot = new URLSearchParams(window.location.search).get("lot_id");
    if (lot) setLotId(lot);
  }, []);

  const runSearch = useCallback(async () => {
    const id = lotId.trim();
    if (!id) {
      setError("Укажите ID лота: он находится в адресе страницы закупки.");
      return;
    }
    setLoading(true);
    setError(null);
    setNotice(null);

    // Требования берём с сервера: без разбора ТЗ агенту нечего сверять.
    let requirements: LotRequirements | null = null;
    try {
      requirements = await fetchLotRequirements(id);
    } catch (e) {
      setError(explainBlock(e));
      setLoading(false);
      return;
    }

    if (!requirements.has_analysis || requirements.requirements.length === 0) {
      setNotice(
        requirements.message ||
          "Для этого лота ещё нет разбора ТЗ. Запустите AI-анализ, чтобы агент искал поставщиков по вашим требованиям.",
      );
      setLotInfo(null);
      setLoading(false);
      return;
    }

    try {
      const res = await searchSuppliers(id, requirements.requirements, {
        budgetKzt: requirements.budget_kzt,
      });
      setLotInfo(requirements);
      setCandidates(res.candidates);
      if (res.candidates.length === 0) {
        setNotice(
          res.queries.length > 0
            ? "По этим требованиям ничего не нашлось. Попробуйте другой лот или дополните ТЗ."
            : "Поисковые запросы не сформировались — попробуйте позже.",
        );
      } else if (res.blocked_filtered > 0) {
        setNotice(`Скрыто поставщиков из стоп-листа: ${res.blocked_filtered}.`);
      }
    } catch (e) {
      setError(explainBlock(e));
      // Fallback: показать ранее сохранённый шорт-лист, если он есть.
      try {
        const saved = await fetchShortlist(id);
        if (saved.candidates.length > 0) {
          setLotInfo(requirements);
          setCandidates(saved.candidates);
          setNotice("Показаны ранее найденные поставщики — новый поиск не удался.");
        }
      } catch {
        /* тихо — основная ошибка уже показана */
      }
    } finally {
      setLoading(false);
    }
  }, [lotId]);

  const onFeedback = async (candidate: SupplierCandidate, fits: boolean) => {
    setBusyId(candidate.id);
    try {
      await sendSupplierFeedback(candidate.id, fits);
      setCandidates((prev) =>
        prev.map((c) => (c.id === candidate.id ? { ...c, status: fits ? "approved" : "rejected" } : c)),
      );
      setNotice(fits ? "Отмечено как подходящее." : "Отмечено как не подходящее.");
    } catch (e) {
      setError(explainBlock(e));
    } finally {
      setBusyId(null);
    }
  };

  const onDraft = async (candidate: SupplierCandidate) => {
    setBusyId(candidate.id);
    setError(null);
    setNotice(null);
    try {
      const res = await createDraft(candidate.id, "email");
      setDraft(res);
      setApproval({
        id: res.approval_id,
        kind: res.kind,
        status: res.status,
        draft_text: isEmailDraft(res.draft) ? res.draft.body : "",
        plan: isCallPlan(res.draft) ? res.draft : {},
        decision_note: null,
        candidate_id: candidate.id,
        created_at: new Date().toISOString(),
        decided_at: null,
        supplier: candidate.supplier,
        lot_id: candidate.lot_id,
      });
    } catch (e) {
      setError(explainBlock(e));
    } finally {
      setBusyId(null);
    }
  };

  const onDecision = async (decision: "approved" | "rejected") => {
    if (!approval) return;
    setBusyId(approval.candidate_id ?? -1);
    setError(null);
    try {
      const updated = await decideApproval(approval.id, decision);
      setApproval(updated);
      setNotice(
        decision === "approved"
          ? "Одобрено. Отправка письма — отдельное действие."
          : "Отклонено, поставщику ничего не отправлено.",
      );
    } catch (e) {
      setError(explainBlock(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <p className="text-xs uppercase tracking-[0.18em] text-emerald-400/80">Поиск поставщиков</p>
        <h1 className="mt-2 text-2xl font-medium tracking-tight text-white sm:text-3xl">
          Кто поставит под этот лот
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-white/45">
          Агент найдёт компании по требованиям ТЗ и покажет сверку по каждому пункту.
          Письма и звонки возможны только после вашего одобрения.
        </p>
      </header>

      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          void runSearch();
        }}
      >
        <input
          value={lotId}
          onChange={(e) => setLotId(e.target.value)}
          placeholder="ID лота, например 17699886"
          aria-label="ID лота"
          className="flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-white placeholder:text-white/25 outline-none focus:border-emerald-400/40"
        />
        <LotSourceLink
          lotId={lotId.trim()}
          className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-white/10 px-4 text-sm text-white/70 transition hover:border-white/25 hover:text-white"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-xl bg-emerald-400 px-5 py-2.5 text-sm font-semibold text-[#03110b] transition hover:bg-emerald-300 disabled:opacity-50"
        >
          {loading ? "Ищем поставщиков…" : "Найти поставщиков"}
        </button>
      </form>

      {error && (
        <p role="alert" className="rounded-xl border border-red-400/25 bg-red-400/[0.07] px-4 py-3 text-sm text-red-200">
          {error}
        </p>
      )}
      {notice && (
        <p className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-white/60">
          {notice}
        </p>
      )}

      {lotInfo && (
              <section className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs text-white/40">Требования ТЗ, по которым ищем:</p>
                    <p className="mt-1 text-sm font-medium text-white/80">{lotInfo.title || `Лот ${lotInfo.lot_id}`}</p>
                    {lotInfo.customer && (
                      <p className="mt-0.5 text-xs text-white/35">{lotInfo.customer}</p>
                    )}
                  </div>
                  <LotSourceLink lotId={lotInfo.lot_id} />
                </div>
                <ul className="mt-3 flex flex-wrap gap-1.5">
                  {lotInfo.requirements.slice(0, 8).map((r) => (
                    <li
                      key={r.code || r.title}
                      className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 text-[11px] text-white/55"
                    >
                      {r.title.length > 60 ? `${r.title.slice(0, 60)}…` : r.title}
                    </li>
                  ))}
                  {lotInfo.requirements.length > 8 && (
                    <li className="px-2 py-1 text-[11px] text-white/35">
                      +{lotInfo.requirements.length - 8} ещё
                    </li>
                  )}
                </ul>
              </section>
            )}

            {loading && (
        <div className="space-y-3">
          <p className="text-xs text-white/40">Поиск и сверка занимают до 2–3 минут…</p>
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      )}

      {!loading && candidates.length === 0 && !notice && (
        <EmptyState
          title="Поиск ещё не запускался"
          text="Введите ID лота и нажмите «Найти поставщиков». Лучше сначала выполнить AI-анализ — тогда агент знает требования ТЗ."
        />
      )}

      {candidates.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-white/70">
            Найдено поставщиков: <span className="text-white/40">{candidates.length}</span>
          </h2>
          {candidates.map((c) => (
            <SupplierCandidateCard
              key={c.id}
              candidate={c}
              busy={busyId === c.id}
              onFeedback={(fits) => void onFeedback(c, fits)}
              onDraft={() => void onDraft(c)}
            />
          ))}
        </section>
      )}

      {draft && approval && (
        <DraftReview
          approval={approval}
          draft={draft}
          busy={busyId === (approval.candidate_id ?? -1)}
          onDecision={onDecision}
          onClose={() => {
            setDraft(null);
            setApproval(null);
          }}
        />
      )}
    </div>
  );
}

function DraftReview({
  approval,
  draft,
  busy,
  onDecision,
  onClose,
}: {
  approval: Approval;
  draft: DraftResponse;
  busy: boolean;
  onDecision: (decision: "approved" | "rejected") => void;
  onClose: () => void;
}) {
  const decided = approval.status !== "pending";
  const priceLabel =
    draft.price_action === "accept"
      ? "Цена в допуске — можно соглашаться"
      : draft.price_action === "counter_once"
        ? "Цена выше допуска: допустима одна встречная попытка"
        : "Цена за пределом: отказ без обязательств";

  return (
    <section
      role="dialog"
      aria-label="Проверка черновика"
      className="space-y-4 rounded-2xl border border-emerald-400/20 bg-[#0a1115]/95 p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-medium text-white/90">Черновик письма</h2>
          <p className="mt-1 text-xs text-white/40">{approval.supplier}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Закрыть черновик"
          className="rounded-lg px-2 py-1 text-xs text-white/40 transition hover:bg-white/[0.05] hover:text-white"
        >
          Закрыть
        </button>
      </div>

      <p className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-white/60">
        {priceLabel}
      </p>

      {isEmailDraft(draft.draft) && (
        <div className="space-y-2">
          <p className="text-xs text-white/40">Тема: {draft.draft.subject}</p>
          <p className="whitespace-pre-wrap rounded-lg border border-white/[0.07] bg-black/20 p-4 text-sm leading-6 text-white/75">
            {draft.draft.body || "Черновик пуст — агент не смог подготовить текст."}
          </p>
        </div>
      )}

      {draft.draft.has_stop_word === true && (
        <p className="text-xs text-amber-200/80">
          В тексте есть слова, требующие внимания (договор/оплата). Проверьте вручную.
        </p>
      )}

      {decided ? (
        <p className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white/60">
          {approval.status === "approved"
            ? "Одобрено. Письмо можно отправить отдельным действием."
            : "Отклонено — отправка невозможна."}
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onDecision("approved")}
            disabled={busy}
            className="rounded-lg bg-emerald-400 px-4 py-2 text-sm font-semibold text-[#03110b] transition hover:bg-emerald-300 disabled:opacity-50"
          >
            Одобрить
          </button>
          <button
            type="button"
            onClick={() => onDecision("rejected")}
            disabled={busy}
            className="rounded-lg border border-white/12 px-4 py-2 text-sm text-white/60 transition hover:bg-white/[0.05] disabled:opacity-50"
          >
            Отклонить
          </button>
          <p className="w-full text-[11px] leading-4 text-white/35">
            Агент не соглашается на цену, не подписывает договор и не платит — такие инструменты
            у него отсутствуют технически.
          </p>
        </div>
      )}
    </section>
  );
}

export { friendlyError };