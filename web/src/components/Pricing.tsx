import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

// Proposed commercial terms only. Entitlements must be enforced by the backend
// after verified payment; these cards never activate a subscription.
const plans = [
  {
    name: "Плюс", price: 10000, monthlyCredits: 150, windowCredits: 20,
    audience: "Найти свой тендер",
    description: "Для ИП и малого бизнеса: меньше ручного поиска, больше подходящих закупок.",
    highlights: ["Поиск по словам, категории, сумме и региону", "Краткий разбор условий и сроков", "Чек-лист документов для участия"],
    planned: ["До 3 сохранённых поисковых профилей", "Уведомления в Telegram и календарь сроков"],
    featured: false,
  },
  {
    name: "Про", price: 25000, monthlyCredits: 400, windowCredits: 60,
    audience: "Оценить риски и подготовиться",
    description: "Для компаний, бухгалтеров и специалистов, которые регулярно участвуют в закупках.",
    highlights: ["Все возможности «Плюс»", "Глубокий разбор ТЗ и спорных требований", "Черновики заявок и сопроводительных документов"],
    planned: ["До 10 поисковых профилей", "Сравнение лотов и история результатов торгов", "Сведения о заказчиках со ссылками на источники"],
    featured: true,
  },
  {
    name: "Ультра", price: 56000, monthlyCredits: 1200, windowCredits: 150,
    audience: "Вести несколько закупок с AI",
    description: "Для высокой нагрузки: больше анализов, документов и помощи на каждом этапе подготовки.",
    highlights: ["Все возможности «Про»", "В 3 раза больше месячных AI-кредитов", "Больше глубоких разборов и черновиков документов"],
    planned: ["До 30 поисковых профилей", "Рабочие папки и план действий по закупкам", "Пакетный разбор документов с подтверждением стоимости"],
    featured: false,
  },
];

const formatNumber = (value: number) => new Intl.NumberFormat("ru-RU").format(value);

export function Pricing() {
  const { user } = useAuth();
  const startUrl = user ? "/analyze" : "/login?mode=register";

  return (
    <section id="pricing" aria-labelledby="pricing-title" className="scroll-mt-32 max-w-6xl mx-auto px-6 py-20">
      <div className="mx-auto max-w-2xl text-center mb-12">
        <p className="text-xs uppercase tracking-widest text-emerald-400 mb-3">Тарифы Tendr</p>
        <h2 id="pricing-title" className="text-3xl md:text-4xl font-bold tracking-tight">Ваш помощник в закупках.<br />В вашем рабочем ритме.</h2>
        <p className="mt-5 leading-7 text-[var(--text-muted)]">От первого лота до ежедневной работы с тендерами. Выберите объём помощи, который нужен вашему бизнесу.</p>
        <p className="mt-5 inline-block rounded-full border border-amber-400/20 bg-amber-400/5 px-4 py-2 text-xs text-amber-200">Планируемые тарифы · подписки готовятся к запуску</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-3 items-stretch">
        {plans.map((plan) => (
          <article key={plan.name} aria-labelledby={`plan-${plan.name}`} className={`relative flex flex-col rounded-3xl border p-7 xl:p-8 ${plan.featured ? "border-emerald-400/60 bg-[#10221d] shadow-[0_0_50px_-20px_rgba(16,185,129,0.35)]" : "border-[var(--border-strong)] bg-[var(--bg-elevated)]"}`}>
            <div className="flex items-center justify-between gap-3">
              <h3 id={`plan-${plan.name}`} className="text-2xl font-semibold tracking-tight">{plan.name}</h3>
              {plan.featured && <span className="rounded-full bg-emerald-400/10 px-3 py-1 text-[11px] font-medium text-emerald-300">Для бизнеса</span>}
            </div>
            <p className="mt-2 text-sm text-emerald-400">{plan.audience}</p>
            <p className="mt-4 min-h-[4.5rem] text-sm leading-6 text-[var(--text-muted)]">{plan.description}</p>
            <div className="mt-6 flex items-baseline gap-2">
              <span className="text-4xl font-semibold tracking-tight tabular-nums">{formatNumber(plan.price)} ₸</span>
              <span className="text-sm text-[var(--text-muted)]">/ месяц</span>
            </div>
            <dl className="my-7 space-y-3 rounded-2xl border border-white/5 bg-black/20 p-4 text-sm">
              <div className="flex justify-between gap-3"><dt className="text-[var(--text-muted)]">Кредитов в месяц</dt><dd className="font-semibold tabular-nums">{formatNumber(plan.monthlyCredits)}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-[var(--text-muted)]">На каждые 5 часов</dt><dd className="font-semibold tabular-nums">{plan.windowCredits}</dd></div>
            </dl>
            <ul className="space-y-3 text-sm leading-6 flex-1">
              {[...plan.highlights, "3 режима AI: быстрый, стандартный, глубокий"].map((feature) => (
                <li key={feature} className="flex items-start gap-3"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" aria-hidden="true" /><span>{feature}</span></li>
              ))}
            </ul>
            <div className="mt-6 border-t border-white/10 pt-5">
              <p className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--text-muted)]">Планируем добавить</p>
              <ul className="space-y-2 text-xs leading-6 text-[var(--text-muted)]">
                {plan.planned.map((feature) => <li key={feature}>{feature}</li>)}
              </ul>
            </div>
            <p className="mt-6 text-xs leading-5 text-[var(--text-muted)]">До {plan.monthlyCredits / 5} стандартных разборов в месяц, если тратить все кредиты только на них.</p>
            <div className="mt-7 rounded-xl border border-white/10 py-3 text-center text-sm text-[var(--text-muted)]">Подключение скоро</div>
          </article>
        ))}
      </div>

      <p className="mt-5 text-center text-xs leading-6 text-[var(--text-muted)]">Предварительные цены и лимиты. Оплата пока недоступна. Состав подписок, режимы AI и кредитные лимиты готовятся к запуску.</p>

      <div className="mt-10 grid gap-8 rounded-3xl border border-[var(--border)] bg-[var(--bg-elevated)] p-7 md:grid-cols-[1fr_1.2fr] md:p-8">
        <div>
          <h3 className="text-xl font-semibold">Понятный расход — без сюрпризов</h3>
          <p className="mt-3 text-sm leading-7 text-[var(--text-muted)]">Кредит — единица работы ассистента. Перед запуском задачи будет видна её стоимость. Чем сложнее разбор, тем больше требуется кредитов.</p>
        </div>
        <dl className="space-y-3 text-sm">
          {[
            ["Короткий ответ или уточнение", "1 кредит"],
            ["Поиск лотов по одному запросу", "2 кредита"],
            ["Стандартный разбор одного лота", "5 кредитов"],
            ["Черновик одного документа", "5 кредитов"],
            ["Глубокий разбор одного лота", "10 кредитов"],
          ].map(([task, cost]) => (
            <div key={task} className="flex justify-between gap-5 border-b border-white/5 pb-3 last:border-0"><dt className="text-[var(--text-muted)]">{task}</dt><dd className="shrink-0 font-medium">{cost}</dd></div>
          ))}
        </dl>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2 text-sm text-[var(--text-muted)]">
        <details className="rounded-2xl border border-[var(--border)] bg-[var(--bg-elevated)] p-5">
          <summary className="cursor-pointer font-medium text-[var(--text)]">В «Ультра» входит живой специалист?</summary>
          <p className="mt-3 leading-7">Нет. Это помощь AI, а не услуги тендерного юриста или персонального менеджера. Ассистент помогает готовиться, но не подаёт заявки за вас и не гарантирует победу. Решения и отправка документов остаются за вами.</p>
        </details>
        <details className="rounded-2xl border border-[var(--border)] bg-[var(--bg-elevated)] p-5">
          <summary className="cursor-pointer font-medium text-[var(--text)]">Будут уведомления в WhatsApp?</summary>
          <p className="mt-3 leading-7">Это отдельная планируемая интеграция. Сначала готовим мониторинг и уведомления в Telegram. Поддержку WhatsApp и условия её использования объявим после подключения сервиса.</p>
        </details>
        <details className="rounded-2xl border border-[var(--border)] bg-[var(--bg-elevated)] p-5">
          <summary className="cursor-pointer font-medium text-[var(--text)]">Как будут работать 5 часов?</summary>
          <p className="mt-3 leading-7">Окно начинается с первой платной AI-задачи и длится 5 часов. Затем этот лимит обновляется. Месячный остаток при этом не пополняется: для задачи должно хватать обоих лимитов. Это ограничение расхода, а не времени нахождения на сайте.</p>
        </details>
        <details className="rounded-2xl border border-[var(--border)] bg-[var(--bg-elevated)] p-5">
          <summary className="cursor-pointer font-medium text-[var(--text)]">Что произойдёт, если лимит закончится?</summary>
          <p className="mt-3 leading-7">Новые AI-задачи приостановятся до обновления соответствующего лимита. Просмотр уже сохранённых результатов останется доступен. Автоматических доплат не будет.</p>
        </details>
      </div>

      <div className="mt-8 flex flex-col items-start justify-between gap-5 rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-6 sm:flex-row sm:items-center">
        <div><h3 className="font-semibold">Пока выбираете — познакомьтесь с Tendr</h3><p className="mt-1 text-sm text-[var(--text-muted)]">Начните с доступного пробного анализа.</p></div>
        <Link to={startUrl} className="shrink-0 rounded-lg bg-emerald-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-emerald-400">{user ? "Перейти к анализу" : "Начать бесплатно"}</Link>
      </div>
    </section>
  );
}
