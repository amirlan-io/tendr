import { useEffect, useState } from "react";
import { Building2, CheckCircle2 } from "lucide-react";
import {
  fetchCompanyProfile,
  fetchTenderInterests,
  friendlyError,
  updateCompanyProfile,
  updateTenderInterests,
} from "../suppliers.api";

const INPUT =
  "mt-1.5 h-11 w-full rounded-xl border border-white/[0.08] bg-white/[0.025] px-3.5 text-sm text-white outline-none transition placeholder:text-white/25 hover:border-white/[0.14] focus:border-emerald-400/40";
const LABEL = "block text-xs font-medium text-white/45";

type FormState = {
  categories: string;
  regions: string;
  keywords: string;
  capabilities: string;
  minBudget: string;
  maxBudget: string;
};

const EMPTY_FORM: FormState = {
  categories: "",
  regions: "",
  keywords: "",
  capabilities: "",
  minBudget: "",
  maxBudget: "",
};

function splitList(value: string): string[] {
  return [...new Set(value.split(/[,;\n]/).map((item) => item.trim()).filter(Boolean))].slice(0, 20);
}

function numberOrNull(value: string): number | null {
  const normalized = value.replace(/\s/g, "").replace(",", ".");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function CompanyTenderProfile({ embedded = false }: { embedded?: boolean } = {}) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([fetchCompanyProfile(), fetchTenderInterests()])
      .then(([profile, interests]) => {
        if (cancelled) return;
        setForm({
          categories: (profile.categories.length ? profile.categories : interests.categories).join(", "),
          regions: (profile.regions.length ? profile.regions : interests.regions).join(", "),
          keywords: interests.keywords.join(", "),
          capabilities: profile.capabilities,
          minBudget: String(interests.min_budget_kzt ?? profile.min_check_kzt ?? ""),
          maxBudget: String(interests.max_budget_kzt ?? profile.budget_max_kzt ?? ""),
        });
      })
      .catch((reason) => {
        if (!cancelled) setError(friendlyError(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const update = (patch: Partial<FormState>) => {
    setSaved(false);
    setForm((current) => ({ ...current, ...patch }));
  };

  const save = async () => {
    const categories = splitList(form.categories);
    const regions = splitList(form.regions);
    const keywords = splitList(form.keywords);
    const minBudget = numberOrNull(form.minBudget);
    const maxBudget = numberOrNull(form.maxBudget);
    if (minBudget !== null && maxBudget !== null && minBudget > maxBudget) {
      setError("Минимальная сумма не может быть больше максимальной.");
      return;
    }
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await Promise.all([
        updateCompanyProfile({
          categories,
          regions,
          capabilities: form.capabilities.trim(),
          min_check_kzt: minBudget,
          budget_max_kzt: maxBudget,
        }),
        updateTenderInterests({
          categories,
          regions,
          keywords,
          min_budget_kzt: minBudget,
          max_budget_kzt: maxBudget,
          quiz_completed: true,
        }),
      ]);
      setSaved(true);
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      aria-label="Профиль компании для подбора лотов"
      className={embedded ? "p-0" : "mt-4 rounded-xl border border-white/[0.075] bg-[#121213]/90 p-6"}
    >
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-300">
          <Building2 size={18} />
        </span>
        <div>
          <h2 className="text-base font-medium text-white">Профиль компании для подбора лотов</h2>
          <p className="mt-1 max-w-2xl text-xs leading-5 text-white/35">
            По этим данным Tendr рассчитывает совпадение, объясняет причины и поднимает подходящие закупки выше.
          </p>
        </div>
      </div>

      {loading ? (
        <div className="mt-6 h-36 animate-pulse rounded-xl bg-white/[0.025]" />
      ) : (
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <label className={LABEL}>
            Что поставляете
            <input value={form.categories} onChange={(e) => update({ categories: e.target.value })} placeholder="фильтры, мебель, разработка сайтов" className={INPUT} />
            <span className="mt-1.5 block text-[10px] font-normal text-white/25">Разделяйте значения запятыми.</span>
          </label>
          <label className={LABEL}>
            Регионы работы
            <input value={form.regions} onChange={(e) => update({ regions: e.target.value })} placeholder="Астана, Алматы, Акмолинская область" className={INPUT} />
          </label>
          <label className={LABEL}>
            Ключевые слова
            <input value={form.keywords} onChange={(e) => update({ keywords: e.target.value })} placeholder="топливный фильтр, веб-сайт, обслуживание" className={INPUT} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className={LABEL}>
              Лот от, ₸
              <input value={form.minBudget} onChange={(e) => update({ minBudget: e.target.value.replace(/[^\d.,\s]/g, "") })} inputMode="decimal" placeholder="100 000" className={INPUT} />
            </label>
            <label className={LABEL}>
              Лот до, ₸
              <input value={form.maxBudget} onChange={(e) => update({ maxBudget: e.target.value.replace(/[^\d.,\s]/g, "") })} inputMode="decimal" placeholder="50 000 000" className={INPUT} />
            </label>
          </div>
          <label className={`${LABEL} sm:col-span-2`}>
            Возможности и опыт
            <textarea value={form.capabilities} onChange={(e) => update({ capabilities: e.target.value })} maxLength={4000} rows={4} placeholder="Опишите оборудование, лицензии, опыт, мощности и ограничения компании." className={`${INPUT} h-auto min-h-28 py-3 leading-6`} />
          </label>
        </div>
      )}

      {error && <p aria-live="polite" className="mt-4 rounded-xl border border-red-400/20 bg-red-400/[0.06] px-4 py-3 text-xs text-red-300">{error}</p>}
      {saved && <p role="status" className="mt-4 flex items-center gap-2 text-xs text-emerald-300"><CheckCircle2 size={14} /> Профиль сохранён. Новая выдача получит персональную оценку.</p>}
      <button type="button" onClick={() => void save()} disabled={loading || saving} className="mt-5 inline-flex min-h-11 items-center justify-center rounded-xl bg-emerald-400 px-5 text-sm font-semibold text-[#03110b] transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-40">
        {saving ? "Сохраняем…" : "Сохранить профиль компании"}
      </button>
    </section>
  );
}
