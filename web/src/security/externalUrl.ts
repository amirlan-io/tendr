/**
 * Проверка внешних URL для каталога лотов.
 *
 * Требования безопасности:
 * - использовать `new URL()`;
 * - разрешать только схему https:;
 * - разрешать только точные доверенные hostname (строгое равенство, без includes());
 * - отклонять URL с userinfo (username/password);
 * - отклонять нестандартный порт;
 * - отклонять javascript:, data:, file: и всё, что не https:.
 */

const TRUSTED_HOSTS: ReadonlySet<string> = new Set([
  "goszakup.gov.kz",
  "zakup.gov.kz",
]);

export function getTrustedHosts(): string[] {
  return [...TRUSTED_HOSTS];
}

/**
 * Возвращает нормализованный безопасный URL или null, если URL опасен.
 * Никогда не бросает исключений.
 */
export function getSafeExternalUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const candidate = raw.trim();
  if (!candidate) return null;

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return null;
  }

  // Только https. Это же отклоняет javascript:, data:, file:, http:.
  if (parsed.protocol !== "https:") return null;

  // Точное совпадение hostname (без поддоменных трюков вида evil-goszakup.gov.kz).
  // URL.hostname уже нормализован в нижний регистр.
  if (!TRUSTED_HOSTS.has(parsed.hostname)) return null;

  // Запрещаем userinfo (https://user:pass@host/ — фишинг).
  if (parsed.username !== "" || parsed.password !== "") return null;

  // Запрещаем нестандартный порт (явный или подразумеваемый).
  if (parsed.port !== "") return null;

  return parsed.toString();
}

export function isSafeExternalUrl(raw: string | null | undefined): boolean {
  return getSafeExternalUrl(raw) !== null;
}

/**
 * Общая проверка произвольных https-ссылок (товары магазинов, live-URL
 * и записи ИИ-агента, чьи домены заранее неизвестны).
 *
 * Гарантии слабее строгого allowlist:
 * - только схема https: (отклоняет javascript:, data:, file:, http:);
 * - без userinfo;
 * - нестандартные порты допускаются (нужны для live-URL агента).
 *
 * Для ссылок на госзакупки используйте строгий getSafeExternalUrl().
 */
export function getSafeHttpsUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const candidate = raw.trim();
  if (!candidate) return null;

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return null;
  }

  if (parsed.protocol !== "https:") return null;
  if (parsed.username !== "" || parsed.password !== "") return null;

  return parsed.toString();
}

export function isSafeHttpsUrl(raw: string | null | undefined): boolean {
  return getSafeHttpsUrl(raw) !== null;
}
