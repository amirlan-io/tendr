/**
 * API-слой агента поставщиков.
 *
 * Все запросы идут через общий `api()` из clientId, который сам добавляет
 * X-Client-Id и Bearer-токен Supabase. Никаких прямых fetch и никаких
 * заголовков X-Admin-Key: агент работает в кабинете пользователя, а не в админке.
 *
 * Пользователю наружу уходят только безопасные сообщения ApiError — сырой
 * detail бэкенда не показывается (это общее правило проекта).
 */

import { api, ApiError, toSafeApiMessage } from "../clientId";
import type {
  Approval,
  ApprovalStatus,
  CompanyProfile,
  CostSummary,
  DraftResponse,
  OutreachKind,
  PricePolicy,
  RecommendedResponse,
  ShortlistResponse,
  SupplierCandidate,
  SupplierLists,
  SupplierSearchResponse,
  LotRequirements,
  OutreachCapabilities,
} from "./suppliers.types";

/** Поиск поставщиков по лоту (F1+F2). Долгий запрос — 60–180 сек. */
export async function searchSuppliers(
  lotId: string,
  requirements: Array<{ code: string; title: string; description?: string; is_mandatory?: boolean }>,
  opts: { budgetKzt?: number | null; enrichBrowser?: boolean } = {},
): Promise<SupplierSearchResponse> {
  return api<SupplierSearchResponse>("/api/suppliers/search", {
    method: "POST",
    body: JSON.stringify({
      lot_id: lotId,
      requirements,
      budget_kzt: opts.budgetKzt ?? null,
      enrich_browser: opts.enrichBrowser ?? true,
    }),
  });
}

/** Шорт-лист без повторного поиска. */
export async function fetchShortlist(lotId: string): Promise<ShortlistResponse> {
  return api<ShortlistResponse>(`/api/suppliers/shortlist?lot_id=${encodeURIComponent(lotId)}`);
}

/**
 * Требования ТЗ по последнему анализу лота.
 *
 * Источник входа для агента. Берём с сервера, а не из состояния страницы:
 * пользователь может открыть раздел напрямую или после перезагрузки.
 */
export async function fetchLotRequirements(lotId: string): Promise<LotRequirements> {
  return api<LotRequirements>(
    `/api/suppliers/requirements?lot_id=${encodeURIComponent(lotId)}`,
  );
}

/** Одобрить/отклонить поставщика — сигнал для будущего скоринга. */
export async function sendSupplierFeedback(
  candidateId: number,
  fits: boolean,
): Promise<void> {
  await api("/api/suppliers/feedback", {
    method: "POST",
    body: JSON.stringify({ candidate_id: candidateId, verdict: fits ? "fits" : "not_fits" }),
  });
}

/** Подготовить черновик письма или план звонка. Ничего не отправляет. */
export async function createDraft(
  candidateId: number,
  kind: OutreachKind,
): Promise<DraftResponse> {
  return api<DraftResponse>("/api/suppliers/draft", {
    method: "POST",
    body: JSON.stringify({ candidate_id: candidateId, kind }),
  });
}

export async function decideApproval(
  approvalId: number,
  decision: "approved" | "rejected",
  note?: string,
  editedText?: string,
): Promise<Approval> {
  return api<Approval>("/api/approvals", {
    method: "POST",
    body: JSON.stringify({
      approval_id: approvalId,
      decision,
      note: note ?? null,
      edited_text: editedText ?? null,
    }),
  });
}

export async function fetchPendingApprovals(): Promise<{ items: Approval[]; total: number }> {
  return api<{ items: Approval[]; total: number }>("/api/approvals/pending");
}

/** Отправить письмо. Без одобрения бэкенд вернёт 403 — это ожидаемое поведение. */
export async function sendApprovedEmail(
  approvalId: number,
  subject: string,
): Promise<{ job_id: number; status: string; mode: string }> {
  return api<{ job_id: number; status: string; mode: string }>("/api/outreach/email", {
    method: "POST",
    body: JSON.stringify({ approval_id: approvalId, subject }),
  });
}

/** Инициировать звонок. Вне рабочего времени КЗ бэкенд вернёт 409. */
export async function placeApprovedCall(approvalId: number): Promise<{ job_id: number; status: string; mode: string }> {
  return api<{ job_id: number; status: string; mode: string }>("/api/outreach/call", {
    method: "POST",
    body: JSON.stringify({ approval_id: approvalId }),
  });
}

export async function fetchOutreachCapabilities(): Promise<OutreachCapabilities> {
  return api<OutreachCapabilities>("/api/outreach/capabilities");
}

export async function fetchPricePolicy(): Promise<PricePolicy> {
  return api<PricePolicy>("/api/suppliers/price-policy");
}

export async function updatePricePolicy(patch: Partial<PricePolicy>): Promise<PricePolicy> {
  return api<PricePolicy>("/api/suppliers/price-policy", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function fetchCompanyProfile(): Promise<CompanyProfile> {
  return api<CompanyProfile>("/api/suppliers/profile");
}

export async function updateCompanyProfile(patch: Partial<CompanyProfile>): Promise<CompanyProfile> {
  return api<CompanyProfile>("/api/suppliers/profile", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function fetchSupplierLists(): Promise<SupplierLists> {
  return api<SupplierLists>("/api/suppliers/lists");
}

export async function addToSupplierList(
  supplier: string,
  allow: boolean,
  reason?: string,
): Promise<void> {
  await api("/api/suppliers/lists", {
    method: "POST",
    body: JSON.stringify({ supplier, allow, reason: reason ?? null }),
  });
}

export async function removeFromSupplierList(supplier: string, allow: boolean): Promise<void> {
  await api(
    `/api/suppliers/lists?supplier=${encodeURIComponent(supplier)}&allow=${allow ? "true" : "false"}`,
    { method: "DELETE" },
  );
}

/** Подбор тендеров с объяснением «почему». */
export async function fetchRecommendedTenders(): Promise<RecommendedResponse> {
  return api<RecommendedResponse>("/api/tenders/recommended");
}

/** Фидбек «подходит / не подходит» по тендеру. */
export async function sendTenderFeedback(lotId: string, fits: boolean): Promise<void> {
  await api("/api/tenders/feedback", {
    method: "POST",
    body: JSON.stringify({ lot_id: lotId, verdict: fits ? "fits" : "not_fits" }),
  });
}

/** Расходы агента — для контроля себестоимости. */
export async function fetchCostSummary(): Promise<CostSummary> {
  return api<CostSummary>("/api/outreach/audit/costs");
}

/**
 * Безопасное сообщение для UI.
 * Отдельная обёртка, чтобы страницы не импортировали ApiError напрямую.
 */
export function friendlyError(e: unknown): string {
  return toSafeApiMessage(e, "Не удалось выполнить действие. Попробуйте позже.");
}

/** Человекочитаемый текст для частых блокировок (F4/F5/F6). */
export function explainBlock(error: unknown): string {
  if (!(error instanceof ApiError)) return friendlyError(error);
  switch (error.status) {
    case 403:
      return error.message || "Действие запрещено: нужно одобрение пользователя.";
    case 409:
      return error.message || "Сейчас это действие недоступно.";
    case 429:
      return "Достигнут дневной лимит. Попробуйте завтра.";
    case 503:
      return "Функция пока недоступна: не настроена на сервере.";
    default:
      return friendlyError(error);
  }
}

export type { ApprovalStatus, SupplierCandidate };
