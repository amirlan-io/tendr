import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";
import { Pricing } from "../components/Pricing";

type ProcessIconName = "document" | "search" | "shield" | "calendar";

const processStages: Array<{ icon: ProcessIconName; title: string; value: string; label: string }> = [
  { icon: "document", title: "Чтение документации", value: "PDF · DOCX · XLSX", label: "Файлы и ссылка на лот" },
  { icon: "search", title: "Извлечение требований", value: "14", label: "Требований найдено" },
  { icon: "shield", title: "Проверка рисков", value: "3", label: "Пункта требуют внимания" },
  { icon: "calendar", title: "Формирование плана", value: "4 дня", label: "Ориентир на подготовку" },
];

const processComparison = {
  without: [
    "Вручную читать документацию и приложения",
    "Собирать требования в заметках и таблицах",
    "Отдельно сверять сроки и список документов",
    "Рисковать пропустить важное условие",
    "Самостоятельно собирать план подготовки",
  ],
  withTendr: [
    "Краткое резюме закупки на одном экране",
    "Требования, собранные в понятный чек-лист",
    "Риски и спорные условия выделены отдельно",
    "Список документов и контрольные сроки",
    "Последовательный план следующих действий",
  ],
};

function Arrow() {
  return <span aria-hidden="true" className="transition-transform group-hover:translate-x-1">↗</span>;
}

function ProcessIcon({ name }: { name: ProcessIconName }) {
  if (name === "document") {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3.75h6.8L18 8v12.25H7z" /><path d="M13.5 4v4.5H18M9.5 12h6M9.5 15.5h6" /></svg>;
  }
  if (name === "search") {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.75" /><path d="m15 15 4.25 4.25" /></svg>;
  }
  if (name === "shield") {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5 19 6v5.25c0 4.3-2.75 7.45-7 9.25-4.25-1.8-7-4.95-7-9.25V6z" /><path d="m9 12 2 2 4-4" /></svg>;
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="6" width="16" height="14" rx="2" /><path d="M8 3.5V8M16 3.5V8M4 10h16M8 14h2M14 14h2" /></svg>;
}

function ComparisonBoard() {
  return (
    <div className="comparison-board">
      <article className="comparison-card comparison-manual">
        <div className="comparison-title"><span aria-hidden="true">×</span><div><small>Обычный процесс</small><h3>Без Tendr</h3></div></div>
        <ul>{processComparison.without.map((item) => <li key={item}><i aria-hidden="true" />{item}</li>)}</ul>
      </article>
      <article className="comparison-card comparison-tendr">
        <div className="comparison-title"><span aria-hidden="true">✓</span><div><small>Структурированный результат</small><h3>С Tendr</h3></div></div>
        <ul>{processComparison.withTendr.map((item) => <li key={item}><i aria-hidden="true">✓</i>{item}</li>)}</ul>
        <div className="comparison-mark" aria-hidden="true">↯</div>
      </article>
      <div className="comparison-note"><span>Важно</span><p>Tendr помогает анализировать информацию. Окончательное решение и отправка заявки остаются за пользователем.</p></div>
    </div>
  );
}

function Hero() {
  return (
    <section className="signal-hero">
      <div className="page-container relative">
        <div className="signal-copy">
          <div className="signal-badge"><span />Для ИП, поставщиков и тендерных специалистов</div>
          <h1>AI-помощник для участия<br />в <em>госзакупках Казахстана</em></h1>
          <p>Tendr помогает понять условия тендера до подачи заявки: находит требования и риски, собирает список документов и подсказывает, что делать дальше.</p>
          <div className="signal-actions">
            <Link to="/login?mode=register" className="button-primary group">Начать бесплатно <Arrow /></Link>
            <a href="#how-it-works" className="signal-text-link">Как это работает <span>↓</span></a>
          </div>
          <div className="hero-outcomes"><span>Проверка лота</span><span>Разбор документов</span><span>План действий</span></div>
        </div>
      </div>
    </section>
  );
}

function Process() {
  const [activeStage, setActiveStage] = useState(0);
  const [isProcessVisible, setProcessVisible] = useState(false);
  const processRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const stageTimers: number[] = [];

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setProcessVisible(true);
        setActiveStage(0);
        for (let index = 1; index < processStages.length; index += 1) {
          stageTimers.push(window.setTimeout(() => setActiveStage(index), index * 2500));
        }
        observer.disconnect();
      }
    }, { threshold: 0.35 });

    const section = processRef.current;
    if (section) observer.observe(section);

    return () => {
      stageTimers.forEach((timer) => window.clearTimeout(timer));
      observer.disconnect();
    };
  }, []);

  return (
    <section ref={processRef} id="how-it-works" className={`section-block process-reveal scroll-mt-28 ${isProcessVisible ? "is-visible" : ""}`}>
      <div className="process-heading"><span>01 / КАК РАБОТАЕТ</span><h2>Как работает <b>Tendr AI</b></h2><p>Добавьте ссылку на закупку или загрузите документацию — Tendr последовательно разберёт её и соберёт рабочую картину.</p></div>
      <div className="process-console">
        <div className="process-example-label">Пример результата</div>
        <div className="process-flow">
          <div className="process-track" aria-hidden="true">
            <i />
            <b />
          </div>
          {processStages.map((stage, index) => (
            <article
              key={stage.title}
              className={index === activeStage ? "is-active" : index < activeStage ? "is-complete" : ""}
              style={{ "--stage-index": index } as CSSProperties}
            >
              <div className="process-icon"><ProcessIcon name={stage.icon} /></div>
              <span className="process-status">{index < activeStage ? "Готово" : index === activeStage ? (activeStage === processStages.length - 1 ? "Завершено" : "В работе") : `0${index + 1}`}</span>
              <h3>{stage.title}</h3>
            </article>
          ))}
        </div>
        <div className="process-metrics">
          {processStages.map((stage, index) => (
            <div key={stage.label} className={index <= activeStage ? "is-revealed" : ""}>
              <strong>{stage.value}</strong><span>{stage.label}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Showcase() {
  return <section id="product" className="section-block scroll-mt-28">
    <div className="result-heading"><span>РЕЗУЛЬТАТ АНАЛИЗА</span><h2>Не длинный ответ AI,<br />а понятная рабочая картина</h2><p>После анализа вы видите, подходит ли закупка, какие условия нужно выполнить и что подготовить для участия.</p></div>
    <div className="mt-12"><ComparisonBoard /></div>
  </section>;
}

function Features() {
  return (
    <section id="features" className="section-block scroll-mt-28">
      <div className="editorial-heading"><div><span>02 / ВОЗМОЖНОСТИ</span><h2>Видеть больше.<br />Решать быстрее.</h2></div><p>Не набор AI-функций, а последовательный процесс, который помогает принять решение об участии.</p></div>
      <div className="bento-grid">
        <article className="bento-card bento-analysis">
          <div className="bento-copy">
            <div className="bento-label">АНАЛИЗ ДОКУМЕНТАЦИИ</div>
            <h3>Документ превращается<br />в понятный чек-лист</h3>
            <p>Tendr проходит по закупочной документации и собирает обязательные условия в одну структуру.</p>
          </div>
          <div className="analysis-visual" aria-hidden="true">
            <div className="document-shadow document-shadow-one" />
            <div className="document-shadow document-shadow-two" />
            <div className="document-sheet-live">
              <div className="document-file"><i>PDF</i><span>Техническая спецификация</span><b>24 стр.</b></div>
              <div className="document-preview-title"><span>Обязательные требования</span><em>12 дней</em><b>3 из 14</b></div>
              <div className="document-checklist">
                <div><i>01</i><span>Опыт аналогичных поставок</span><b>✓</b></div>
                <div><i>02</i><span>Гарантия от 12 месяцев</span><b>✓</b></div>
                <div><i>03</i><span>Поставка до 20 дней</span><b>!</b></div>
              </div>
              <div className="document-progress"><div><i /></div><span>Документ анализируется</span><b>72%</b></div>
              <div className="document-scanner" />
            </div>
          </div>
        </article>
        <article className="bento-card bento-risk-live">
          <div className="bento-label">ПРОВЕРКА РИСКОВ</div>
          <div className="risk-intelligence" aria-hidden="true">
            <div className="risk-intelligence-head">
              <div className="risk-count"><strong>03</strong><span>пункта<br />требуют внимания</span></div>
              <div className="risk-level"><small>Общий уровень риска</small><b><i />Средний</b></div>
            </div>
            <div className="risk-findings">
              <div className="risk-finding risk-high">
                <i>!</i><div><span>Срок поставки</span><small>Всего 5 рабочих дней</small></div><b>Высокий</b>
              </div>
              <div className="risk-finding risk-medium">
                <i>!</i><div><span>Условия договора</span><small>Неустойка 0,5% за каждый день</small></div><b>Средний</b>
              </div>
              <div className="risk-finding risk-review">
                <i>?</i><div><span>Подтверждающий документ</span><small>Нужно проверить наличие оригинала</small></div><b>Проверить</b>
              </div>
            </div>
            <div className="risk-scan-line" />
            <div className="risk-intelligence-foot"><span><i /> Анализ завершён</span><b>Пример результата</b></div>
          </div>
          <h3>Риски видны до подачи</h3>
          <p>Спорные пункты и ограничения отделены от обычного текста.</p>
        </article>
        <article className="bento-card bento-search-live">
          <div className="bento-label">УМНЫЙ ПОИСК</div>
          <h3>Подходящие лоты<br />приходят в один поток</h3>
          <p>Регион, категория, бюджет и срок уже собраны в карточке закупки.</p>
          <div className="lot-stream" aria-hidden="true">
            <div className="lot-search-bar"><i /><span>Офисная мебель</span><b>3 результата</b></div>
            <div className="lot-row lot-row-active"><span>Астана</span><strong>Офисные кресла</strong><b>18,4 млн ₸</b></div>
            <div className="lot-row"><span>Алматы</span><strong>Мебель для школ</strong><b>9,7 млн ₸</b></div>
            <div className="lot-row"><span>Караганда</span><strong>Комплект столов</strong><b>6,2 млн ₸</b></div>
          </div>
        </article>
        <article className="bento-card bento-workflow-live">
          <div className="bento-copy">
            <div className="bento-label">ЕДИНЫЙ РАБОЧИЙ ПРОЦЕСС</div>
            <h3>От найденного лота<br />до готовности к подаче</h3>
            <p>Анализы, документы и следующие действия остаются связаны в одном проекте.</p>
          </div>
          <div className="workflow-map" aria-hidden="true">
            <div className="workflow-map-head"><span>Готовность проекта</span><b>3 из 4 этапов</b></div>
            <div className="workflow-route"><i /></div>
            <div className="workflow-step step-one"><b>01</b><span>Лот найден</span><small>готово</small></div>
            <div className="workflow-step step-two"><b>02</b><span>Условия проверены</span><small>готово</small></div>
            <div className="workflow-step step-three"><b>03</b><span>Документы собраны</span><small>в работе</small></div>
            <div className="workflow-step step-four"><b>04</b><span>Подача заявки</span><small>следующий шаг</small></div>
          </div>
        </article>
      </div>
    </section>
  );
}

function Audience() {
  const items = [
    ["Поставщики", "Быстрее оценивать закупки и готовиться к участию."],
    ["Тендерные специалисты", "Сократить ручную проверку и вести больше заявок."],
    ["Заказчики", "Структурировать закупку и готовить технические задания."],
  ];
  return <section className="section-block"><div className="audience-v2"><div className="audience-intro"><span>03 / ДЛЯ КОГО</span><h2>Один продукт.<br />Три рабочих сценария.</h2></div><div className="audience-list">{items.map(([title, text], index) => <div key={title}><b>0{index + 1}</b><h3>{title}</h3><p>{text}</p><Link to={index === 2 ? "/b2g" : "/analyze"}>Открыть <Arrow /></Link></div>)}</div></div></section>;
}

function FinalCTA() {
  return <section className="page-container pb-24 pt-8 sm:pb-32"><div className="final-signal"><span>ГОТОВЫ ПОПРОБОВАТЬ?</span><h2>Начните с одной<br />реальной закупки.</h2><p>Создание аккаунта займёт меньше минуты. Банковская карта не нужна.</p><Link to="/login?mode=register" className="button-primary group">Создать аккаунт <Arrow /></Link></div></section>;
}

export function HomePage() {
  return <Layout><Hero /><Process /><Showcase /><Features /><Audience /><Pricing /><FinalCTA /></Layout>;
}
