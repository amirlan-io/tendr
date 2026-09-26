/**
 * Хранилище административного ключа.
 *
 * Безопасность:
 * - ключ хранится ТОЛЬКО в sessionStorage (вкладка закрылась — ключ исчез);
 * - ключ НИКОГДА не сохраняется в localStorage;
 * - ключ никогда не выводится в console.log и не попадает в тексты ошибок;
 * - при 401/403 сессия очищается и снова показывается форма входа.
 */

const ADMIN_KEY_STORAGE = "tendr_admin_key";

function session(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function getAdminKey(): string | null {
  const s = session();
  if (!s) return null;
  try {
    const v = s.getItem(ADMIN_KEY_STORAGE);
    if (!v || !v.trim()) return null;
    return v;
  } catch {
    return null;
  }
}

export function setAdminKey(key: string): void {
  const s = session();
  if (!s) return;
  const v = key.trim();
  if (!v) return;
  try {
    s.setItem(ADMIN_KEY_STORAGE, v);
  } catch {
    /* sessionStorage может быть недоступен — игнорируем */
  }
}

export function clearAdminSession(): void {
  const s = session();
  if (!s) return;
  try {
    s.removeItem(ADMIN_KEY_STORAGE);
  } catch {
    /* игнорируем */
  }
}

export function hasAdminKey(): boolean {
  return getAdminKey() !== null;
}

/** true, если по этому статусу нужно разлогинить админа (показать форму входа). */
export function isAdminAuthError(status: number | undefined): boolean {
  return status === 401 || status === 403;
}
