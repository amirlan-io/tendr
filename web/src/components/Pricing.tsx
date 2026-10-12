import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { SpotlightCard } from "./ui/spotlight-card";

const plans = [
  {
    index: "01", name: "Plus", price: "10 000", credits: "150", window: "20", glowHue: 166,
    label: "СТАРТ",
    description: "Для ИП и небольших команд, которые начинают работать с закупками системно.",
    features: ["Поиск лотов по ключевым словам и регионам", "Краткий AI-разбор условий", "Чек-лист документов для подачи", "До 3 поисковых профилей*"],
  },
  {
    index: "02", name: "Pro", price: "25 000", credits: "400", window: "60", featured: true, glowHue: 154,
    label: "ДЛЯ РЕГУЛЯРНОЙ РАБОТЫ",
    description: "Для компаний, которые ведут несколько закупок и хотят быстрее принимать решения.",
    features: ["Всё из тарифа Plus", "Глубокая проверка условий и рисков", "Черновики документов", "История анализов и проектов", "До 10 поисковых профилей*"],
  },
  {
    index: "03", name: "Ultra", price: "56 000", credits: "1 200", window: "150", glowHue: 46,
    label: "МАКСИМУМ",
    description: "Для высокой нагрузки, больших пакетов документов и командной работы.",
    features: ["Всё из тарифа Pro", "Увеличенные AI-лимиты", "Пакетный разбор документов*", "Командное рабочее пространство*", "До 30 поисковых профилей*"],
  },
];

export function Pricing() {
  const { user } = useAuth();
  const startUrl = user ? "/analyze" : "/login?mode=register";

  return (
    <section id="pricing" className="section-block scroll-mt-28" aria-labelledby="pricing-title">
      <div className="editorial-heading">
        <div><span>04 / ТАРИФЫ</span><h2 id="pricing-title">Выберите свой<br />рабочий темп</h2></div>
        <div><p className="leading-7 text-[var(--text-muted)]">Прозрачные лимиты без автоматических доплат. Стоимость задачи видна до запуска.</p><span className="mt-4 inline-block rounded-full border border-[#d6bb63]/20 bg-[#d6bb63]/[0.05] px-3 py-1.5 text-[10px] tracking-[.1em] text-[#d6bb63]">ПРЕДВАРИТЕЛЬНЫЕ УСЛОВИЯ</span></div>
      </div>

      <div className="pricing-v2">
        {plans.map((plan) => (
          <SpotlightCard key={plan.name} glowHue={plan.glowHue} className={plan.featured ? "featured" : ""}>
            <div className="pricing-topline"><span>{plan.index}</span>{plan.featured && <b>ПОПУЛЯРНЫЙ</b>}</div>
            <div className="pricing-plan-head">
              <span>{plan.label}</span>
              <h3>{plan.name}</h3>
              <p>{plan.description}</p>
            </div>
            <div className="pricing-price"><strong>{plan.price}</strong><span>₸ / месяц</span></div>
            <Link className="pricing-action" to={startUrl}>{user ? "Перейти к анализу" : "Начать"}<span>↗</span></Link>

            <div className="pricing-limits" aria-label={`Лимиты тарифа ${plan.name}`}>
              <div><span>в месяц</span><b>{plan.credits}</b><small>кредитов</small></div>
              <div><span>каждые 5 часов</span><b>{plan.window}</b><small>кредитов</small></div>
            </div>

            <div className="pricing-includes">
              <span>В ТАРИФ ВХОДИТ</span>
              <ul>{plan.features.map((feature) => <li key={feature}><i aria-hidden="true">✓</i>{feature}</li>)}</ul>
            </div>
          </SpotlightCard>
        ))}
      </div>
      <div className="pricing-note"><span>*</span><p>Отмеченные возможности находятся в разработке. Оплата подписок пока недоступна; цены и лимиты могут измениться до запуска.</p><Link to={startUrl}>Начать с пробного анализа →</Link></div>
    </section>
  );
}
