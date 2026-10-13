import { PAID_PLANS } from "../plans";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { SpotlightCard } from "./ui/spotlight-card";

const plans = PAID_PLANS.map((plan, index) => ({ ...plan, index: `0${index + 1}`, featured: plan.id === "pro", glowHue: [166, 154, 46][index] }));

export function Pricing() {
  const { user } = useAuth();
  const startUrl = user ? "/analyze" : "/login?mode=register";

  return (
    <section id="pricing" className="section-block scroll-mt-28" aria-labelledby="pricing-title">
      <div className="editorial-heading">
        <div><span>04 / ТАРИФЫ</span><h2 id="pricing-title">Выберите свой<br />рабочий темп</h2></div>
        <div><p className="leading-7 text-[var(--text-muted)]">Один понятный лимит AI-анализов на пять часов. Выберите объём работы, который подходит вам.</p><span className="mt-4 inline-block rounded-full border border-[#d6bb63]/20 bg-[#d6bb63]/[0.05] px-3 py-1.5 text-[10px] tracking-[.1em] text-[#d6bb63]">ПОДПИСКА НА МЕСЯЦ</span></div>
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
            <div className="pricing-price"><strong>{plan.priceKzt.toLocaleString("ru-RU")}</strong><span>₸ / месяц</span></div>
            <Link className="pricing-action" to={startUrl}>{user ? "Перейти к анализу" : "Начать"}<span>↗</span></Link>

            <div className="pricing-limits" aria-label={`Лимиты тарифа ${plan.name}`}>
              <div><span>за 5 часов</span><b>{plan.windowLimit}</b><small>AI-анализов</small></div>
              <div><span>обновление лимита</span><b>5 ч</b><small>после первого запуска</small></div>
            </div>

            <div className="pricing-includes">
              <span>В ТАРИФ ВХОДИТ</span>
              <ul>{plan.features.map((feature) => <li key={feature}><i aria-hidden="true">✓</i>{feature}</li>)}</ul>
            </div>
          </SpotlightCard>
        ))}
      </div>
      <div className="pricing-note"><span>↻</span><p>Без месячного лимита анализов. Через пять часов после первого запуска доступный лимит полностью обновляется. Неудачные анализы не расходуют лимит. Каталог и сохранённые результаты доступны всегда.</p><Link to={startUrl}>Начать с пробного анализа →</Link></div>
    </section>
  );
}
