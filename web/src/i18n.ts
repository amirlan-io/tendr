/**
 * Простая i18n: ru/kk, без зависимостей.
 * Язык хранится в localStorage("tendr_lang").
 */

export type Lang = "ru" | "kk";

const STORAGE_KEY = "tendr_lang";

export function getLang(): Lang {
  if (typeof window === "undefined") return "ru";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "kk" || stored === "ru") return stored;
  // Авто-определение по языку браузера
  const browser = window.navigator.language.toLowerCase();
  if (browser.startsWith("kk")) return "kk";
  return "ru";
}

export function setLang(lang: Lang): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, lang);
  // Сообщаем всем слушателям
  window.dispatchEvent(new CustomEvent("tendr:lang", { detail: lang }));
}

type Dict = Record<string, string>;

const RU: Dict = {
  // Home
  "home.h1": "AI-ассистент для участия МСБ в госзакупках Казахстана",
  "home.subtitle":
    "Tendr автоматически анализирует техническое задание лота, проверяет соответствие Закону РК «О государственных закупках» и помогает подготовить пакет документов. С 3–7 дней рутины — до 1–2 часов.",
  "home.feature1.title": "Чек-лист требований",
  "home.feature1.text":
    "По ТЗ лота — список всех требований с цитатами из документа.",
  "home.feature2.title": "Юридическая проверка",
  "home.feature2.text":
    "Соответствие Закону РК, поиск «красных флагов» и дискриминационных пунктов.",
  "home.feature3.title": "Черновик жалобы",
  "home.feature3.text":
    "Если закупка нарушает закон — сгенерируем жалобу в Счётный комитет.",
  "home.cta": "Попробовать на демо-лоте →",
  "home.nav.analyze": "Анализ лота",
  "home.nav.bot": "Telegram-бот",
  "home.nav.history": "История",

  // Analyze
  "analyze.title": "Анализ лота",
  "analyze.help":
    "Вставьте ссылку с goszakup.gov.kz или ID лота, либо загрузите файл с ТЗ (PDF/DOCX/TXT)",
  "analyze.placeholder": "https://goszakup.gov.kz/ru/announce/show/1234567",
  "analyze.submit": "Анализировать",
  "analyze.submitting": "Анализ…",
  "analyze.file.label": "или загрузите файл:",
  "analyze.file.choose": "Выберите PDF/DOCX/TXT",
  "analyze.error.title": "Ошибка",
  "analyze.incomplete.title": "Недостаточно данных по лоту",
  "analyze.incomplete.reason_label": "Причина:",
  "analyze.incomplete.help":
    "Откройте лот на goszakup.gov.kz, скопируйте текст ТЗ и пришлите сюда сообщением или загрузите PDF/DOCX файл.",
  "analyze.summary.title": "Сводка",
  "analyze.summary.budget": "Бюджет:",
  "analyze.summary.deadline": "до",
  "analyze.summary.risk": "Юр. риск:",
  "analyze.flags.title": "Красные флаги",
  "analyze.requirements.title": "Требования",
  "analyze.requirements.mandatory": "обязательно",
  "analyze.docs.title": "Нужные документы",
  "analyze.violations.title": "Выявленные нарушения",
  "analyze.complaint.title": "Черновик жалобы в Счётный комитет",
  "analyze.complaint.download": "📥 Скачать жалобу (DOCX)",
  "analyze.report.download": "📥 Скачать полный отчёт (DOCX)",
  "analyze.another": "Проверить ещё один лот",
  "analyze.empty": "Введите ID или загрузите файл, чтобы начать.",
  "analyze.quota.title": "Лимит исчерпан",
  "analyze.quota.text":
    "Вы использовали все бесплатные проверки в этом месяце. Скоро будет доступна платная подписка.",

  // History
  "history.title": "История проверок",
  "history.empty":
    "Пока нет ни одной проверки. Запустите первую на странице «Анализ лота».",
  "history.risk.low": "низкий",
  "history.risk.medium": "средний",
  "history.risk.high": "высокий",
  "history.risk.needs_review": "на проверке",
  "history.clear": "Очистить историю",

  // Recommendation / Score / Margin
  "analyze.recommendation.title": "🤖 Рекомендация",
  "analyze.recommendation.participate": "Участвовать",
  "analyze.recommendation.review": "Изучить внимательнее",
  "analyze.recommendation.skip": "Лучше пропустить",
  "analyze.score.title": "🏛 Заказчик",
  "analyze.score.trust_label.trusted": "Надёжный",
  "analyze.score.trust_label.neutral": "Нейтральный",
  "analyze.score.trust_label.risky": "Рискованный",
  "analyze.score.trust_label.avoid": "Лучше избегать",
  "analyze.score.trust_label.unknown": "Неизвестно",
  "analyze.score.trust_label.no_data": "Нет данных",
  "analyze.score.lots_analyzed": "Лотов проанализировано:",
  "analyze.score.avg_risk": "Средний риск:",
  "analyze.margin.title": "💰 Маржа",
  "analyze.margin.category": "Категория:",
  "analyze.margin.estimated": "Ожидаемая маржа:",
  "analyze.margin.confidence.low": "низкая",
  "analyze.margin.confidence.medium": "средняя",
  "analyze.margin.confidence.high": "высокая",

  // Common
  "common.lang.ru": "Русский",
  "common.lang.kk": "Қазақша",
  "common.back": "← Назад",
  "common.brand": "Tendr",
  "common.powered_by": "AI-ассистент для МСБ РК",
};

const KK: Dict = {
  "home.h1":
    "ҚР мемлекеттік сатып алуларына қатысуға арналған ШОБ-қа AI-көмекшісі",
  "home.subtitle":
    "Tendr лоттың техникалық тапсырмасын автоматты түрде талдайды, ҚР «Мемлекеттік сатып алулар туралы» Заңына сәйкестігін тексереді және құжаттар пакетін дайындауға көмектеседі. 3-7 күндік жұмысты 1-2 сағатқа дейін қысқартады.",
  "home.feature1.title": "Талаптар тізімі",
  "home.feature1.text":
    "Лот ТЗ бойынша — құжаттан дәйексөздері бар талаптар тізімі.",
  "home.feature2.title": "Заңи тексеру",
  "home.feature2.text":
    "ҚР Заңына сәйкестік, «қызыл жалаушалар» мен кемсітушілік тармақтарды іздеу.",
  "home.feature3.title": "Шағым жобасы",
  "home.feature3.text":
    "Егер сатып алу заңды бұзса — Есеп комитетіне шағым жобасын дайындаймыз.",
  "home.cta": "Демо-лотта қолданып көру →",
  "home.nav.analyze": "Лот талдау",
  "home.nav.bot": "Telegram-бот",
  "home.nav.history": "Тарих",

  "analyze.title": "Лот талдау",
  "analyze.help":
    "goszakup.gov.kz сайтынан сілтеме немесе лот ID енгізіңіз, не ТЗ файлын (PDF/DOCX/TXT) жүктеңіз",
  "analyze.placeholder": "https://goszakup.gov.kz/kk/announce/show/1234567",
  "analyze.submit": "Талдау",
  "analyze.submitting": "Талдау…",
  "analyze.file.label": "не файл жүктеңіз:",
  "analyze.file.choose": "PDF/DOCX/TXT таңдау",
  "analyze.error.title": "Қате",
  "analyze.incomplete.title": "Лот бойынша деректер жеткіліксіз",
  "analyze.incomplete.reason_label": "Себебі:",
  "analyze.incomplete.help":
    "goszakup.gov.kz сайтында лотты ашып, ТЗ мәтінін көшіріп жіберіңіз немесе PDF/DOCX файлын жүктеңіз.",
  "analyze.summary.title": "Қысқаша",
  "analyze.summary.budget": "Бюджет:",
  "analyze.summary.deadline": "дейін",
  "analyze.summary.risk": "Заңи тәуекел:",
  "analyze.flags.title": "Қызыл жалаушалар",
  "analyze.requirements.title": "Талаптар",
  "analyze.requirements.mandatory": "міндетті",
  "analyze.docs.title": "Қажетті құжаттар",
  "analyze.violations.title": "Анықталған бұзушылықтар",
  "analyze.complaint.title": "Есеп комитетіне шағым жобасы",
  "analyze.complaint.download": "📥 Шағымды жүктеу (DOCX)",
  "analyze.report.download": "📥 Толық есепті жүктеу (DOCX)",
  "analyze.another": "Тағы бір лотты тексеру",
  "analyze.empty": "Бастау үшін ID енгізіңіз немесе файл жүктеңіз.",
  "analyze.quota.title": "Лимит таусылды",
  "analyze.quota.text":
    "Сіз биылғы айда тегін тексерулердің барлығын пайдаландыңыз. Жақында ақылы жазылу қол жетімді болады.",

  "history.title": "Тексерулер тарихы",
  "history.empty":
    "Әзірге ешбір тексеру жоқ. «Лот талдау» бетінде алғашқысын бастаңыз.",
  "history.risk.low": "төмен",
  "history.risk.medium": "орташа",
  "history.risk.high": "жоғары",
  "history.risk.needs_review": "тексеруде",
  "history.clear": "Тарихты тазалау",

  "analyze.recommendation.title": "🤖 AI ұсынысы",
  "analyze.recommendation.participate": "✅ Қатысу",
  "analyze.recommendation.review": "⚠️ Мұқият зерттеу",
  "analyze.recommendation.skip": "❌ Өткізіп жіберген жөн",
  "analyze.score.title": "🏛 Тапсырыс беруші скорингі",
  "analyze.score.trust_label.trusted": "Сенімді",
  "analyze.score.trust_label.neutral": "Бейтарап",
  "analyze.score.trust_label.risky": "Тәуекелді",
  "analyze.score.trust_label.avoid": "Айналып өткен жөн",
  "analyze.score.trust_label.unknown": "Белгісіз",
  "analyze.score.trust_label.no_data": "Деректер жоқ",
  "analyze.score.lots_analyzed": "Талданған лоттар:",
  "analyze.score.avg_risk": "Орташа тәуекел:",
  "analyze.margin.title": "💰 Маржа бағасы",
  "analyze.margin.category": "Санат:",
  "analyze.margin.estimated": "Күтілетін маржа:",
  "analyze.margin.confidence.low": "төмен",
  "analyze.margin.confidence.medium": "орташа",
  "analyze.margin.confidence.high": "жоғары",

  "common.lang.ru": "Русский",
  "common.lang.kk": "Қазақша",
  "common.back": "← Артқа",
  "common.brand": "Tendr",
  "common.powered_by": "ҚР ШОБ-қа арналған AI-көмекшісі",
};

const DICTS: Record<Lang, Dict> = { ru: RU, kk: KK };

export function t(key: string, lang: Lang = getLang()): string {
  return DICTS[lang]?.[key] ?? DICTS.ru[key] ?? key;
}

/**
 * React-хук для подписки на смену языка.
 */
import { useEffect, useState } from "react";

export function useLang(): [Lang, (l: Lang) => void] {
  const [lang, setLangState] = useState<Lang>(getLang());
  useEffect(() => {
    const onChange = (e: Event) => {
      const ce = e as CustomEvent<Lang>;
      if (ce.detail === "ru" || ce.detail === "kk") setLangState(ce.detail);
    };
    window.addEventListener("tendr:lang", onChange);
    return () => window.removeEventListener("tendr:lang", onChange);
  }, []);
  return [lang, setLang];
}

export function useT(): (key: string) => string {
  const [lang] = useLang();
  return (key: string) => t(key, lang);
}
