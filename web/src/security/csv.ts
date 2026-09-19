/**
 * Защита от CSV Injection при экспорте каталога.
 *
 * Значения, начинающиеся с = + - @ (а также с пробела/таба перед ними —
 * Excel игнорирует ведущие пробелы), оборачиваем префиксом `'`,
 * чтобы Excel трактовал ячейку как текст, а не как формулу.
 */

const DANGEROUS_START = new Set(["=", "+", "-", "@"]);

export function escapeCsvCell(value: unknown): string {
  const text = (value ?? "").toString();
  const trimmedStart = text.trimStart();
  const first = trimmedStart.charAt(0);
  const needsEscape = first !== "" && DANGEROUS_START.has(first);
  const body = needsEscape ? `'${text}` : text;
  // Стандартное CSV-экранирование кавычек + обёртка в кавычки.
  return `"${body.replace(/"/g, '""')}"`;
}
