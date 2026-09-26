import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";

// ───── Анимация счётчика (count-up) ─────
function useCountUp(target: number, duration = 1500, start = false) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!start || target === 0) return;
    const startTime = Date.now();
    const id = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.floor(target * eased));
      if (progress >= 1) clearInterval(id);
    }, 16);
    return () => clearInterval(id);
  }, [target, duration, start]);
  return value;
}

function Counter({
  value,
  label,
  color,
}: {
  value: number;
  label: string;
  color: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [started, setStarted] = useState(false);
  const display = useCountUp(value, 1500, started);
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) setStarted(true);
      },
      { threshold: 0.3 },
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return (
    <div ref={ref} className="text-center">
      <div
        className="text-4xl md:text-5xl font-bold tracking-tightest mb-1 tabular-nums"
        style={{ color }}
      >
        {display}
      </div>
      <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider">
        {label}
      </div>
    </div>
  );
}

// ───── Reveal on scroll ─────
function useReveal() {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) setShown(true);
      },
      { threshold: 0.1 },
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return { ref, shown };
}

function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const { ref, shown } = useReveal();
  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: shown ? 1 : 0,
        transform: shown ? "translateY(0)" : "translateY(30px)",
        transition: `opacity 0.8s ease-out ${delay}ms, transform 0.8s ease-out ${delay}ms`,
      }}
    >
      {children}
    </div>
  );
}

// ───── Floating particles ─────
function FloatingDots() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="absolute rounded-full opacity-20"
          style={{
            width: `${20 + (i % 3) * 16}px`,
            height: `${20 + (i % 3) * 16}px`,
            top: `${10 + i * 14}%`,
            left: `${(i * 17) % 90}%`,
            backgroundColor: "var(--accent)",
            animation: `float-${i % 3} ${8 + i}s ease-in-out infinite`,
          }}
        />
      ))}
      <style>{`
        @keyframes float-0 { 0%, 100% { transform: translate(0, 0); } 50% { transform: translate(20px, -30px); } }
        @keyframes float-1 { 0%, 100% { transform: translate(0, 0); } 50% { transform: translate(-30px, 20px); } }
        @keyframes float-2 { 0%, 100% { transform: translate(0, 0); } 50% { transform: translate(15px, 25px); } }
      `}</style>
    </div>
  );
}

// ───── Hero с проблемой → решением ─────
function Hero() {
  return (
    <section className="relative overflow-hidden">
      <FloatingDots />
      <div
        className="absolute inset-0 opacity-30 pointer-events-none"
        style={{
          background:
            "radial-gradient(circle at 50% 0%, var(--accent-glow) 0%, transparent 60%)",
        }}
      />
      <div className="max-w-6xl mx-auto px-6 pt-20 pb-24 relative">
        <Reveal>
          <div
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full border text-xs text-[var(--text-muted)] mb-6"
            style={{ borderColor: "var(--border-strong)" }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full animate-pulse"
              style={{ background: "var(--accent)" }}
            />
            Грант «Тәуелсіздік ұрпақтары» 2026 · Пилот в Алматы
          </div>
        </Reveal>

        <Reveal delay={100}>
          <h1 className="text-5xl md:text-7xl font-bold tracking-tightest leading-[1.02] mb-6 max-w-4xl">
            Госзакупки без{" "}
            <span
              className="bg-clip-text text-transparent"
              style={{
                backgroundImage:
                  "linear-gradient(135deg, #10b981 0%, #34d399 50%, #6ee7b7 100%)",
              }}
            >
              головной боли
            </span>
            <br />
            <span className="text-[var(--text-muted)]">за 30 секунд.</span>
          </h1>
        </Reveal>

        <Reveal delay={200}>
          <p className="text-lg md:text-xl text-[var(--text-muted)] mb-10 max-w-2xl leading-relaxed">
            AI-ассистент для МСБ Казахстана. Анализирует техническое задание
            лота, проверяет соответствие Закону, находит нарушения, генерит
            черновик жалобы и заявку — за{" "}
            <span className="text-[var(--text)] font-semibold">
              30 секунд вместо 5 часов
            </span>
            .
          </p>
        </Reveal>

        <Reveal delay={300}>
          <div className="flex gap-3 flex-wrap mb-12">
            <Link
              to="/analyze"
              className="group inline-flex items-center gap-2 px-6 py-3.5 rounded-lg font-medium text-white transition"
              style={{
                background: "var(--accent)",
                boxShadow:
                  "0 0 0 1px rgba(16, 185, 129, 0.4), 0 8px 24px -6px rgba(16, 185, 129, 0.5)",
              }}
            >
              Попробовать бесплатно
              <span className="transition-transform group-hover:translate-x-1">
                →
              </span>
            </Link>
            <Link
              to="/b2g"
              className="inline-flex items-center gap-2 px-6 py-3.5 rounded-lg font-medium border transition"
              style={{
                background: "var(--bg-elevated)",
                borderColor: "var(--border-strong)",
                color: "var(--text)",
              }}
            >
              <span>📋</span>
              Помощь заказчикам
            </Link>
            <a
              href="https://t.me/TendrBot"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 px-6 py-3.5 rounded-lg font-medium border transition"
              style={{
                background: "var(--bg-elevated)",
                borderColor: "var(--border-strong)",
                color: "var(--text)",
              }}
            >
              <span>✈️</span>
              Telegram-бот
            </a>
          </div>
        </Reveal>

        <Reveal delay={400}>
          <div
            className="grid grid-cols-2 md:grid-cols-4 gap-px rounded-2xl overflow-hidden border"
            style={{
              borderColor: "var(--border)",
              background: "var(--border)",
            }}
          >
            <div className="p-6" style={{ background: "var(--bg-elevated)" }}>
              <Counter
                value={30}
                label="Секунд на анализ"
                color="var(--accent)"
              />
            </div>
            <div className="p-6" style={{ background: "var(--bg-elevated)" }}>
              <Counter value={4} label="AI-агента" color="var(--text)" />
            </div>
            <div className="p-6" style={{ background: "var(--bg-elevated)" }}>
              <Counter value={190} label="Чанков в RAG" color="#f59e0b" />
            </div>
            <div className="p-6" style={{ background: "var(--bg-elevated)" }}>
              <Counter value={3} label="Бесплатно в месяц" color="#10b981" />
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

// ───── 3-шаговый процесс ─────
function HowItWorks() {
  const steps = [
    {
      step: "01",
      icon: "🔗",
      title: "Введите ID или пришлите файл",
      text: "Скопируйте ID лота с goszakup.gov.kz или отправьте PDF/DOCX/Excel с ТЗ. Работает даже без токена.",
    },
    {
      step: "02",
      icon: "🤖",
      title: "4 AI-агента работают параллельно",
      text: "Documenter извлекает требования. Legal проверяет Закон РК (190 чанков RAG). Vision анализирует чертежи. B2G генерит ТЗ.",
    },
    {
      step: "03",
      icon: "📥",
      title: "Получите готовые документы",
      text: "Чек-лист требований, черновик жалобы в Счётный комитет со ссылками на статьи, заявка на участие — в DOCX за 1 секунду.",
    },
  ];
  return (
    <section className="max-w-6xl mx-auto px-6 py-20">
      <Reveal>
        <div className="text-center mb-12">
          <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2">
            Как это работает
          </div>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-3">
            Три шага от лота до готовой заявки
          </h2>
        </div>
      </Reveal>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {steps.map((s, i) => (
          <Reveal key={s.step} delay={i * 100}>
            <div
              className="rounded-2xl border p-6 h-full"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="flex items-baseline gap-3 mb-3">
                <div className="text-3xl" style={{ color: "var(--accent)" }}>
                  {s.icon}
                </div>
                <div className="text-xs text-[var(--text-subtle)] font-mono">
                  ШАГ {s.step}
                </div>
              </div>
              <h3 className="text-lg font-semibold mb-2 tracking-tight">
                {s.title}
              </h3>
              <p className="text-sm text-[var(--text-muted)] leading-relaxed">
                {s.text}
              </p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

// ───── Для кого (3 сегмента) ─────
function ForWho() {
  const segments = [
    {
      icon: "🏢",
      title: "Поставщикам МСБ",
      text: "Хотите участвовать в госзакупках, но нет юриста за 300К тг/мес? Получите анализ лота, проверку закона и черновик жалобы за 30 секунд.",
      cta: { to: "/analyze", label: "Проанализировать лот" },
    },
    {
      icon: "📋",
      title: "Заказчикам",
      text: "Нужно составить ТЗ для закупки, но нет юриста? Получите готовое техзадание с проверкой закона, прогнозом цены и DOCX/PDF экспортом.",
      cta: { to: "/b2g", label: "Сгенерировать ТЗ" },
    },
    {
      icon: "👔",
      title: "Тендерным специалистам",
      text: "Ведёте 10+ заявок в месяц? Автоматизируйте рутину: извлечение требований, проверка нарушений, генерация документов. Экономьте часы каждую неделю.",
      cta: { to: "/analyze", label: "Ускорить работу" },
    },
  ];
  return (
    <section className="max-w-6xl mx-auto px-6 py-20">
      <Reveal>
        <div className="text-center mb-12">
          <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2">
            Для кого
          </div>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-3">
            Помогаем всем сторонам рынка
          </h2>
        </div>
      </Reveal>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {segments.map((s, i) => (
          <Reveal key={s.title} delay={i * 100}>
            <Link
              to={s.cta.to}
              className="block rounded-2xl border p-6 h-full transition hover:border-[var(--accent)]"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="text-3xl mb-3">{s.icon}</div>
              <h3 className="text-lg font-semibold mb-2 tracking-tight">
                {s.title}
              </h3>
              <p className="text-sm text-[var(--text-muted)] leading-relaxed mb-3">
                {s.text}
              </p>
              <div
                className="text-sm font-medium"
                style={{ color: "var(--accent)" }}
              >
                {s.cta.label} →
              </div>
            </Link>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

// ───── 4 AI-агента (что внутри) ─────
function Agents() {
  const agents = [
    {
      icon: "📋",
      name: "Documenter",
      role: "Извлекает требования",
      desc: "Читает ТЗ (включая PDF с чертежами) и составляет чек-лист требований с цитатами.",
    },
    {
      icon: "⚖️",
      name: "Legal + RAG",
      role: "Проверяет по Закону РК",
      desc: "Ищет нарушения в требованиях закупки. 190 чанков Закона РК «О госзакупках» в векторной БД.",
    },
    {
      icon: "🔍",
      name: "Product Search",
      role: "Находит товары по ТЗ",
      desc: "AI-поиск в Kaspi, Sulpak, OLX, Vernal, OMNI PARTS. Извлекает характеристики, сравнивает цены.",
    },
    {
      icon: "📝",
      name: "B2G Agent",
      role: "Генерит ТЗ для заказчика",
      desc: "Помогает составить корректное ТЗ с прогнозом цены, без дискриминационных требований.",
    },
  ];
  return (
    <section className="max-w-6xl mx-auto px-6 py-20">
      <Reveal>
        <div className="text-center mb-12">
          <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2">
            Внутри
          </div>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-3">
            4 AI-агента работают вместе
          </h2>
          <p className="text-[var(--text-muted)] max-w-2xl mx-auto">
            Каждый агент — эксперт в своей области. LLM-failover между Mistral
            Large и qwen3-6 (казахстанская модель) — без зависимости от одного
            провайдера.
          </p>
        </div>
      </Reveal>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {agents.map((a, i) => (
          <Reveal key={a.name} delay={i * 100}>
            <div
              className="rounded-2xl border p-5"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="flex items-center gap-3 mb-2">
                <div className="text-2xl">{a.icon}</div>
                <div>
                  <div className="font-semibold">{a.name}</div>
                  <div
                    className="text-xs uppercase tracking-wider"
                    style={{ color: "var(--accent)" }}
                  >
                    {a.role}
                  </div>
                </div>
              </div>
              <p className="text-sm text-[var(--text-muted)]">{a.desc}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

// ───── Что нового (changelog) ─────
function Changelog() {
  const items = [
    {
      date: "Июль 2026",
      tag: "NEW",
      tagColor: "#10b981",
      title: "PDF с vision-анализом",
      text: "AI видит чертежи и фото в PDF-приложениях к ТЗ. Извлекает размеры, материалы, особенности конструкции.",
      link: null,
    },
    {
      date: "Июль 2026",
      tag: "NEW",
      tagColor: "#10b981",
      title: "AI-поиск товаров (Tavily)",
      text: "Находит реальные товары на Kaspi, Sulpak, OLX по характеристикам из ТЗ. match_score 50-95%.",
      link: { to: "/analyze", label: "Попробовать →" },
    },
    {
      date: "Июль 2026",
      tag: "NEW",
      tagColor: "#10b981",
      title: "B2G-агент — помощь заказчикам",
      text: "Workspace, версии ТЗ, multi-user, экспорт в DOCX/PDF. Заказчик получает готовое техзадание за минуту.",
      link: { to: "/b2g", label: "Попробовать →" },
    },
    {
      date: "Июль 2026",
      tag: "NEW",
      tagColor: "#10b981",
      title: "Генератор заявки (DOCX)",
      text: "Готовая заявка на участие в лоте за 1 секунду вместо 2-3 часов ручной работы.",
      link: null,
    },
    {
      date: "Июль 2026",
      tag: "NEW",
      tagColor: "#10b981",
      title: "Калькулятор цены + маржа",
      text: "Считает min/optimal/aggressive цену. Сравнивает с рынком. Рекомендует конкурентную стратегию.",
      link: null,
    },
    {
      date: "Июнь 2026",
      tag: "CORE",
      tagColor: "#3b82f6",
      title: "Documenter + Legal + RAG по Закону РК",
      text: "Основа продукта: 2 AI-агента, RAG-индекс по 190 чанкам Закона о госзакупках, failover Mistral → qwen3-6.",
      link: null,
    },
  ];
  return (
    <section className="max-w-6xl mx-auto px-6 py-20">
      <Reveal>
        <div className="text-center mb-12">
          <div
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full border text-xs text-[var(--text-muted)] mb-4"
            style={{ borderColor: "var(--border-strong)" }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full animate-pulse"
              style={{ background: "#10b981" }}
            />
            Активно развивается
          </div>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-3">
            Что нового
          </h2>
          <p className="text-[var(--text-muted)] max-w-2xl mx-auto">
            Самые свежие обновления Tendr
          </p>
        </div>
      </Reveal>
      <div className="space-y-3 max-w-3xl mx-auto">
        {items.map((item, i) => (
          <Reveal key={item.title} delay={i * 50}>
            <div
              className="rounded-xl border p-4"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="flex items-start gap-3">
                <div
                  className="px-2 py-0.5 rounded text-xs font-semibold whitespace-nowrap"
                  style={{
                    backgroundColor: `${item.tagColor}20`,
                    color: item.tagColor,
                  }}
                >
                  {item.tag}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="font-semibold">{item.title}</h3>
                    <div className="text-xs text-[var(--text-subtle)] whitespace-nowrap">
                      {item.date}
                    </div>
                  </div>
                  <p className="text-sm text-[var(--text-muted)] mt-1">
                    {item.text}
                  </p>
                  {item.link && (
                    <div className="mt-2">
                      <Link
                        to={item.link.to}
                        className="text-sm font-medium"
                        style={{ color: "var(--accent)" }}
                      >
                        {item.link.label}
                      </Link>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

// ───── Roadmap ─────
function Roadmap() {
  const items = [
    {
      quarter: "Q2 2026",
      title: "MVP",
      status: "done",
      desc: "Documenter, Legal, RAG, B2G, поиск товаров",
    },
    {
      quarter: "Q3 2026",
      title: "Pilot + Токен goszakup",
      status: "current",
      desc: "5 SMB, реальные метрики, парсер по API",
    },
    {
      quarter: "Q4 2026",
      title: "Kaspi Pay + Mobile",
      status: "planned",
      desc: "Подписки, Telegram Mini App, PWA",
    },
    {
      quarter: "2027",
      title: "B2G + ЕАЭС",
      status: "planned",
      desc: "Помощь заказчикам + экспорт в РФ/РБ",
    },
  ];
  return (
    <section className="max-w-6xl mx-auto px-6 py-20">
      <Reveal>
        <div className="text-center mb-12">
          <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2">
            Roadmap
          </div>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-3">
            Куда мы идём
          </h2>
        </div>
      </Reveal>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        {items.map((item, i) => (
          <Reveal key={item.title} delay={i * 100}>
            <div
              className="rounded-xl border p-4"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor:
                  item.status === "current" ? "var(--accent)" : "var(--border)",
                borderWidth: item.status === "current" ? "2px" : "1px",
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs font-mono text-[var(--text-muted)]">
                  {item.quarter}
                </div>
                <div
                  className="text-xs px-2 py-0.5 rounded"
                  style={{
                    backgroundColor:
                      item.status === "done"
                        ? "rgba(16, 185, 129, 0.15)"
                        : item.status === "current"
                          ? "rgba(245, 158, 11, 0.15)"
                          : "var(--border)",
                    color:
                      item.status === "done"
                        ? "#10b981"
                        : item.status === "current"
                          ? "#f59e0b"
                          : "var(--text-muted)",
                  }}
                >
                  {item.status === "done"
                    ? "✓ готово"
                    : item.status === "current"
                      ? "→ в работе"
                      : "планируется"}
                </div>
              </div>
              <div className="font-semibold mb-1">{item.title}</div>
              <div className="text-xs text-[var(--text-muted)]">
                {item.desc}
              </div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

// ───── CTA в конце ─────
function FinalCTA() {
  return (
    <section className="max-w-6xl mx-auto px-6 py-20">
      <Reveal>
        <div
          className="rounded-3xl p-12 md:p-16 border text-center relative overflow-hidden"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
          }}
        >
          <div
            className="absolute inset-0 opacity-30"
            style={{
              background:
                "radial-gradient(circle at 50% 50%, var(--accent-glow) 0%, transparent 70%)",
            }}
          />
          <div className="relative">
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-3">
              Попробуйте Tendr
            </h2>
            <p className="text-[var(--text-muted)] mb-8 max-w-xl mx-auto">
              Введите ID любого лота с goszakup.gov.kz — за 30 секунд получите
              полный анализ. Или пришлите файл с ТЗ в Telegram-бот.
            </p>
            <div className="flex gap-3 justify-center flex-wrap">
              <Link
                to="/analyze"
                className="inline-flex items-center gap-2 px-6 py-3.5 rounded-lg font-medium text-white"
                style={{ background: "var(--accent)" }}
              >
                Начать бесплатно →
              </Link>
              <Link
                to="/b2g"
                className="inline-flex items-center gap-2 px-6 py-3.5 rounded-lg font-medium border"
                style={{
                  background: "var(--bg)",
                  borderColor: "var(--border-strong)",
                  color: "var(--text)",
                }}
              >
                Генерировать ТЗ
              </Link>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}

// ───── Главная страница ─────
// Публичная страница НЕ обращается к /api/admin/stats: у неё нет X-Admin-Key,
// а после hardening admin endpoints вернут 401/403 и метрики показались бы нулями.
// Блок живых метрик убран до появления публичного endpoint статистики.
export function HomePage() {
  return (
    <Layout>
      <Hero />
      <ForWho />
      <HowItWorks />
      <Agents />
      <Changelog />
      <Roadmap />
      <FinalCTA />
    </Layout>
  );
}
