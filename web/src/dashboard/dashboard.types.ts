export type TariffId = "trial" | "plus" | "pro" | "ultra";

export type Tariff = {
  id: TariffId;
  name: string;
  priceKzt: number | null;
  monthlyCredits: number | null;
  burstCredits: number | null;
  features: string[];
};

export type QuotaInfo = {
  limit: number;
  used: number;
  isPilot: boolean;
};

export type SavedLot = {
  id: number;
  title: string;
  organizer?: string;
  amountKzt?: number | null;
  region?: string;
  deadlineDate?: string | null;
  sourceUrl?: string | null;
  /** Номер объявления на площадке — нужен для перехода на оригинал. */
  sourceId?: string | null;
  savedAt: string;
};

export type PreparedDocument = {
  id: string;
  kind: "complaint" | "report";
  filename: string;
  lotId: string;
  lotTitle: string;
  createdAt: string;
};

export type ActivityKind = "analysis" | "lot" | "document";

export type ActivityItem = {
  id: string;
  kind: ActivityKind;
  title: string;
  subtitle: string;
  status: string;
  createdAt: string;
  to: string;
  /** Ссылка на оригинал объявления: даёт доступ к источнику из списка. */
  sourceUrl?: string | null;
  lotId?: string | null;
};

export type DeadlineItem = {
  id: string;
  title: string;
  customer: string;
  deadlineDate: string;
  daysLeft: number;
  urgency: "overdue" | "urgent" | "soon" | "normal";
  to: string;
  sourceUrl?: string | null;
  lotId?: string | null;
};

export type ProfileForm = {
  fullName: string;
  companyName: string;
  position: string;
  phone: string;
  city: string;
};

export type NavItem = {
  to: string;
  label: string;
  description: string;
  icon:
    | "home"
    | "spark"
    | "lots"
    | "history"
    | "docs"
    | "briefcase"
    | "billing"
    | "suppliers"
    | "settings";
};
