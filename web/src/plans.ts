import catalog from "../../backend/app/core/plans.json";

export type PaidPlanId = keyof typeof catalog;
export const PAID_PLANS = Object.entries(catalog).map(([id, plan]) => ({
  id: id as PaidPlanId,
  name: plan.name,
  priceKzt: plan.amount_kzt,
  windowLimit: plan.window_limit,
  label: plan.label,
  description: plan.description,
  features: plan.features,
  capabilities: plan.capabilities,
}));
export function planName(id: string): string {
  return PAID_PLANS.find((plan) => plan.id === id)?.name ?? ({ free: "Пробный", pilot: "Пилот", monthly: "Pro" }[id] ?? id);
}
