import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "../../supabase";
import { useAuth } from "../../auth/AuthContext";
import type { ProfileForm } from "../dashboard.types";

const SAFE_ERROR = "Не удалось сохранить профиль. Попробуйте позже.";

function readMeta(user: { user_metadata?: Record<string, unknown> } | null): ProfileForm {
  const meta = user?.user_metadata ?? {};
  const pick = (key: string): string => {
    const v = meta[key];
    return typeof v === "string" ? v : "";
  };
  return {
    fullName: pick("full_name"),
    companyName: pick("company_name"),
    position: pick("position"),
    phone: pick("phone"),
    city: pick("city"),
  };
}

export function validateProfile(form: ProfileForm): string | null {
  if (form.fullName.trim().length > 120) return "Имя слишком длинное (максимум 120 символов).";
  if (form.companyName.trim().length > 160) return "Название компании слишком длинное.";
  if (form.position.trim().length > 120) return "Должность слишком длинная.";
  if (form.city.trim().length > 80) return "Название города слишком длинное.";
  const phone = form.phone.trim();
  if (phone && !/^[+\d][\d\s\-()]{5,24}$/.test(phone)) {
    return "Проверьте номер телефона: допускаются цифры, пробелы, +, скобки и дефис.";
  }
  return null;
}

export function useProfile() {
  const { user } = useAuth();
  const [form, setForm] = useState<ProfileForm>(() => readMeta(user));
  const [saved, setSaved] = useState<ProfileForm>(() => readMeta(user));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedOk, setSavedOk] = useState(false);
  const hydrated = useRef(false);

  // Подтягиваем metadata при появлении пользователя (refresh, OAuth-callback).
  useEffect(() => {
    if (hydrated.current || !user) return;
    const fresh = readMeta(user);
    if (fresh.fullName || fresh.companyName || fresh.phone || fresh.city || fresh.position) {
      setForm(fresh);
      setSaved(fresh);
    }
    hydrated.current = true;
  }, [user]);

  const dirty =
    form.fullName !== saved.fullName ||
    form.companyName !== saved.companyName ||
    form.position !== saved.position ||
    form.phone !== saved.phone ||
    form.city !== saved.city;

  const set = useCallback((patch: Partial<ProfileForm>) => {
    setForm((prev) => ({ ...prev, ...patch }));
    setSavedOk(false);
    setError(null);
  }, []);

  const reset = useCallback(() => {
    setForm(saved);
    setError(null);
    setSavedOk(false);
  }, [saved]);

  const save = useCallback(async (): Promise<boolean> => {
    const problem = validateProfile(form);
    if (problem) {
      setError(problem);
      return false;
    }
    if (!supabase) {
      setError(SAFE_ERROR);
      return false;
    }
    setSaving(true);
    setError(null);
    try {
      const { error: updateError } = await supabase.auth.updateUser({
        data: {
          full_name: form.fullName.trim(),
          company_name: form.companyName.trim(),
          position: form.position.trim(),
          phone: form.phone.trim(),
          city: form.city.trim(),
        },
      });
      if (updateError) {
        setError(SAFE_ERROR);
        return false;
      }
      setSaved(form);
      setSavedOk(true);
      return true;
    } catch {
      setError(SAFE_ERROR);
      return false;
    } finally {
      setSaving(false);
    }
  }, [form]);

  return { form, set, reset, save, dirty, saving, error, savedOk, email: user?.email ?? null };
}
