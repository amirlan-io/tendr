/**
 * Типы для агента поиска поставщиков и approval-потока.
 * Соответствуют схемам backend: /api/suppliers/*, /api/approvals, /api/outreach/*.
 */

/** Статус соответствия поставщика отдельному пункту ТЗ. */
export type MatchStatus = "fits" | "partial" | "no" | "unknown";

/** Одно требование ТЗ, отправленное в поиск. */
export interface RequirementInput {
  code: string;
  title: string;
  description?: string;
  is_mandatory?: boolean;
}

/** Сверка одного пункта ТЗ с найденным поставщиком. */
export interface RequirementMatch {
  code: string;
  title: string;
  status: MatchStatus;
  comment: string;
  source_url: string;
}

export interface SupplierCard {
  url: string;
  price_kzt: number | null;
  in_stock: boolean | null;
  city: string;
  delivery_days: number | null;
  email: string;
  phone: string;
  certificates: string[];
  warranty: string;
  sources: Record<string, string>;
  is_middleman: boolean;
}

export type CandidateStatus = "pending" | "approved" | "rejected";

/** Карточка поставщика в шорт-листе. */
export interface SupplierCandidate {
  id: number;
  lot_id: string;
  supplier: string;
  domain: string | null;
  title: string;
  status: CandidateStatus;
  score: number;
  card: SupplierCard;
  requirement_matches: RequirementMatch[];
  warnings: string[];
}

export interface SupplierSearchResponse {
  lot_id: string;
  candidates: SupplierCandidate[];
  queries: string[];
  summary: string;
  blocked_filtered: number;
  costs_usd: { llm: number; tavily: number; browser: number };
}

export interface ShortlistResponse {
  lot_id: string;
  candidates: SupplierCandidate[];
}

/**
 * Требования ТЗ по лоту — вход для агента.
 *
 * `has_analysis: false` означает, что разбора ТЗ ещё не было. В этом случае
 * агент запускать бессмысленно: он сверял бы поставщиков с пустым списком.
 */
export interface LotRequirements {
  lot_id: string;
  title: string;
  customer: string;
  budget_kzt: number | null;
  requirements: Array<{ code: string; title: string; is_mandatory?: boolean }>;
  has_analysis: boolean;
  message: string;
}

/** Тип исходящего действия: письмо или звонок. */
export type OutreachKind = "email" | "call";

export type ApprovalStatus = "pending" | "approved" | "rejected" | "executed" | "failed";

export interface CallPlan {
  goal: string;
  questions: string[];
  red_lines: string[];
  exit_script: string;
  introduction: string;
  price_outcome?: string | null;
  /** Флаг стоп-слов присутствует в обоих вариантах черновика. */
  has_stop_word?: boolean | null;
}

export interface EmailDraft {
  subject: string;
  body: string;
  ok: boolean;
  blocked_phrase?: string | null;
  has_stop_word?: boolean | null;
}

export interface Approval {
  id: number;
  kind: OutreachKind;
  status: ApprovalStatus;
  draft_text: string;
  plan: CallPlan | Record<string, never>;
  decision_note: string | null;
  candidate_id: number | null;
  created_at: string | null;
  decided_at: string | null;
  supplier?: string;
  lot_id?: string;
  recipient?: { email: string; phone: string };
}

/** Результат решения по цене — агент не может принять цену сам. */
export type PriceAction = "accept" | "counter_once" | "decline";

export interface DraftResponse {
  approval_id: number;
  kind: OutreachKind;
  status: ApprovalStatus;
  price_action: PriceAction;
  draft: EmailDraft | CallPlan;
}

export interface PricePolicy {
  tolerance_pct: number;
  counter_limit_pct: number;
  counter_script: string;
}

/** Профиль компании — источник персонализации агента. */
export interface CompanyProfile {
  categories: string[];
  regions: string[];
  capabilities: string;
  min_check_kzt: number | null;
  budget_max_kzt: number | null;
  work_email: string;
  work_phone: string;
  contact_name: string;
  outreach_mode: OutreachMode;
}

export interface TenderInterests {
  categories: string[];
  regions: string[];
  keywords: string[];
  min_budget_kzt: number | null;
  max_budget_kzt: number | null;
  quiz_completed: boolean;
}

export interface TenderFitScore {
  lot_id: string;
  title: string;
  score: number;
  reasons: string[];
  confidence: string;
  is_urgent: boolean;
  deadline_date: string | null;
  amount_kzt: number | null;
  customer: string;
}

export interface TenderScoreResponse {
  items: TenderFitScore[];
  profile_complete: boolean;
  profile_path: string;
}

/** Режим отправки: manual — только черновик, review — с проверкой, trusted — авто. */
export type OutreachMode = "manual" | "review" | "trusted";

export interface SupplierLists {
  allowlist: Array<{ supplier: string; domain: string | null; note: string | null }>;
  blocklist: Array<{ supplier: string; domain: string | null; reason: string | null }>;
}

/** Рекомендация «подобрано для вас» с объяснением «почему». */
export interface RecommendedTender {
  lot_id: string;
  title: string;
  score: number;
  reasons: string[];
  is_urgent: boolean;
  deadline_date: string | null;
  amount_kzt: number | null;
  customer: string;
  confidence: string;
}

export interface RecommendedResponse {
  items: RecommendedTender[];
  total: number;
  cold_start: boolean;
  message: string;
}

export interface CostSummary {
  llm_usd: number;
  tavily_usd: number;
  browser_usd: number;
  call_usd: number;
  total_usd: number;
}

export interface OutreachCapabilities {
  email: { available: boolean; provider: string | null };
  call: { available: boolean; provider: string | null };
  requires_approval: boolean;
  manual_fallback: boolean;
}

/** Человекочитаемые подписи статусов сверки (F2: объяснение первично). */
export const MATCH_STATUS_LABEL: Record<MatchStatus, string> = {
  fits: "Подходит",
  partial: "Подходит частично",
  no: "Не подходит",
  unknown: "Нет данных",
};

/** Цветовые классы по статусу — единые для всего кабинета. */
export const MATCH_STATUS_CLASS: Record<MatchStatus, string> = {
  fits: "bg-emerald-400/10 text-emerald-300 border-emerald-400/20",
  partial: "bg-amber-400/10 text-amber-300 border-amber-400/20",
  no: "bg-red-400/10 text-red-300 border-red-400/20",
  unknown: "bg-white/[0.04] text-white/45 border-white/10",
};

export function formatKzt(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("ru-RU")} ₸`;
}
