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
 *
 * Список хостов покрывает все поддомены, которые реально отдаёт goszakup:
 * парсер формирует ссылки на `v3bl.goszakup.gov.kz`, а не на корневой домен.
 * Без `v3bl` в allowlist ссылки на оригинал лота молча отбрасывались и
 * кнопка перехода не рендерилась вовсе.
 */

const TRUSTED_HOSTS: ReadonlySet<string> = new Set([
  "goszakup.gov.kz",
  "www.goszakup.gov.kz",
  "zakup.gov.kz",
  "www.zakup.gov.kz",
  // Реальные поддомены госзакупок: v3bl — публичный портал объявлений,
  // ows — API-хост. Ссылки на ows пользователю не полезны, но он
  // возвращается редиректом с v3bl, поэтому должен проходить ту же проверку.
  "v3bl.goszakup.gov.kz",
  "ows.goszakup.gov.kz",
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

/**
 * Ссылка на объявление goszakup по его ID.
 *
 * Зеркалит backend-парсер (GoszakupParser.parse_reference): принимается
 * только числовой ID из 6+ цифр, опционально с суффиксом лота
 * (`17726443-1`). Всё остальное — не лот, поэтому null.
 *
 * Нужен там, где известен только ID (песочница, ввод руками), а ссылки
 * от API ещё нет.
 */
export function buildGoszakupUrl(lotId: string | null | undefined): string | null {
  if (!lotId) return null;
  const candidate = lotId.trim();
  if (!/^\d{6,}(-\d+)?$/.test(candidate)) return null;
  return `https://goszakup.gov.kz/ru/announce/index/${candidate}`;
}
