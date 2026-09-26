/**
 * BrowserActionPanel — UI для запуска browser-use задач.
 *
 * Используется в B2G (заполнение заявок на zakupki.kz) и в Discovery
 * (сбор данных с сайтов поставщиков).
 *
 * Workflow:
 * 1. Пользователь описывает задачу на русском
 * 2. Выбирает модель (gpt-5.4-mini / claude-sonnet-4.6)
 * 3. Включает human-in-loop если нужно (получит live_url)
 * 4. Запускает → получает session_id
 * 5. Смотрит recording или live_url
 */
import { useEffect, useState } from "react";
import { api, ApiError } from "../clientId";
import { getSafeHttpsUrl } from "../security/externalUrl";

type Model = {
  id: string;
  name: string;
  tier: string;
  cost_per_task_estimate_usd: string;
  best_for: string;
};

type TaskResult = {
  session_id: string;
  status: string;
  output: any;
  cost_usd: number;
  duration_sec: number;
  recording_url: string | null;
  step_count: number;
  live_url: string | null;
};

type Props = {
  /** Предустановленная задача (например из контекста B2G) */
  defaultTask?: string;
  /** Заголовок панели */
  title?: string;
  /** Показывать ли выбор доменов */
  showDomainSelector?: boolean;
  /** Домены по умолчанию */
  defaultDomains?: string[];
};

const PRESETS = [
  {
    label: "🔍 Найти цены на kaspi.kz",
    task: "Зайди на https://kaspi.kz и найди товар «{ТОВАР}». Собери первые 5 результатов с ценами и рейтингами. Верни JSON со списком {name, price, rating, url}.",
    domains: ["kaspi.kz"],
  },
  {
    label: "📋 Заполнить заявку на goszakup",
    task: "Зайди на https://goszakup.gov.kz, войди в раздел «Подача заявки» и заполни форму данными: {ДАННЫЕ}. НЕ нажимай кнопку «Отправить». Сделай скриншот заполненной формы.",
    domains: ["goszakup.gov.kz"],
  },
  {
    label: "🏢 Найти контакты поставщика",
    task: "Зайди на сайт {URL_ПОСТАВЩИКА}, найди раздел «Контакты» или «О нас», собери email, телефон, ИИН/БИН. Верни как JSON.",
    domains: [],
  },
  {
    label: "💰 Сравнить цены в 3 магазинах",
    task: "Сравни цену на «{ТОВАР}» в kaspi.kz, sulpak.kz и technodom.kz. Для каждого магазина собери: название, цену, наличие, рейтинг. Верни таблицу.",
    domains: ["kaspi.kz", "sulpak.kz", "technodom.kz"],
  },
];

export function BrowserActionPanel({
  defaultTask = "",
  title = "🤖 Browser Agent",
  showDomainSelector = true,
  defaultDomains = [],
}: Props) {
  const [models, setModels] = useState<Model[]>([]);
  const [task, setTask] = useState(defaultTask);
  const [model, setModel] = useState("gpt-5.4-mini");
  const [humanInLoop, setHumanInLoop] = useState(false);
  const [domains, setDomains] = useState(defaultDomains.join(", "));
  const [recording, setRecording] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<TaskResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [presetIdx, setPresetIdx] = useState<number | null>(null);

  useEffect(() => {
    api<{ models: Model[] }>("/api/browser/models")
      .then((r) => {
        setModels(r.models || []);
      })
      .catch(() => {});
  }, []);

  const applyPreset = (idx: number) => {
    const p = PRESETS[idx];
    setTask(p.task);
    setDomains(p.domains.join(", "));
    setPresetIdx(idx);
  };

  const submit = async () => {
    if (!task.trim()) {
      setError("Опиши задачу");
      return;
    }
    setSubmitting(true);
    setError(null);
    setResult(null);

    const allowedDomains = domains
      .split(",")
      .map((d) => d.trim())
      .filter(Boolean);

    try {
      const r = await api<TaskResult>("/api/browser/run", {
        method: "POST",
        body: JSON.stringify({
          task,
          model,
          human_in_loop: humanInLoop,
          allowed_domains: allowedDomains.length ? allowedDomains : null,
          enable_recording: recording,
          max_duration_min: 15,
          proxy_country: "kz",
        }),
      });
      setResult(r);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Ошибка. Попробуйте снова.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-6 space-y-4">
      <h2 className="text-xl font-semibold">{title}</h2>

      <div>
        <label className="text-sm text-slate-500">Готовые шаблоны</label>
        <div className="flex flex-wrap gap-2 mt-2">
          {PRESETS.map((p, i) => (
            <button
              key={i}
              onClick={() => applyPreset(i)}
              className={`px-3 py-1 text-sm rounded border ${
                presetIdx === i
                  ? "bg-blue-500 text-white border-blue-500"
                  : "bg-slate-100 dark:bg-slate-700 border-slate-300"
              }`}
              type="button"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="text-sm text-slate-500" htmlFor="browser-task">
          Задача для агента
        </label>
        <textarea
          id="browser-task"
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="Опиши что должен сделать агент. Например: 'Зайди на kaspi.kz, найди ноутбук Lenovo IdeaPad, собери 5 лучших предложений с ценами.'"
          className="w-full mt-1 p-3 border rounded dark:bg-slate-700 dark:border-slate-600"
          rows={4}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="text-sm text-slate-500">Модель</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full mt-1 p-2 border rounded dark:bg-slate-700 dark:border-slate-600"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} — {m.cost_per_task_estimate_usd}
              </option>
            ))}
            {!models.length && (
              <option value="gpt-5.4-mini">GPT-5.4 mini (~$0.10-0.20)</option>
            )}
          </select>
          <p className="text-xs text-slate-400 mt-1">
            {models.find((m) => m.id === model)?.best_for}
          </p>
        </div>

        {showDomainSelector && (
          <div>
            <label className="text-sm text-slate-500">
              Домены (через запятую)
            </label>
            <input
              value={domains}
              onChange={(e) => setDomains(e.target.value)}
              placeholder="kaspi.kz, goszakup.gov.kz"
              className="w-full mt-1 p-2 border rounded dark:bg-slate-700 dark:border-slate-600"
            />
            <p className="text-xs text-slate-400 mt-1">
              Пусто = любые. Заполни для безопасности.
            </p>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={humanInLoop}
            onChange={(e) => setHumanInLoop(e.target.checked)}
          />
          <span className="text-sm">
            👤 Human-in-the-loop (получишь live_url для контроля)
          </span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={recording}
            onChange={(e) => setRecording(e.target.checked)}
          />
          <span className="text-sm">🎥 Записать видео</span>
        </label>
      </div>

      <button
        onClick={submit}
        disabled={submitting}
        className="w-full py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-400 text-white rounded font-medium"
      >
        {submitting ? "⏳ Агент работает..." : "🚀 Запустить агента"}
      </button>

      {error && (
        <div
          role="alert"
          className="bg-red-50 dark:bg-red-900/30 border border-red-300 text-red-700 dark:text-red-300 p-3 rounded"
        >
          ❌ {error}
        </div>
      )}

      {result && <AgentResult result={result} />}
    </div>
  );
}

function AgentResult({ result }: { result: TaskResult }) {
  // live_url и recording_url приходят от backend-агента (домены заранее
  // неизвестны), поэтому проверяем их общей https-проверкой:
  // javascript:, data:, file:, http: и userinfo отклоняются.
  const safeLiveUrl = getSafeHttpsUrl(result.live_url);
  const safeRecordingUrl = getSafeHttpsUrl(result.recording_url);

  return (
    <div className="bg-green-50 dark:bg-green-900/30 border border-green-300 p-4 rounded space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-mono text-slate-600">
          session: {result.session_id.slice(0, 16)}...
        </span>
        <span className="px-2 py-0.5 bg-green-200 dark:bg-green-700 rounded text-xs">
          {result.status}
        </span>
        <span>⏱ {result.duration_sec.toFixed(1)}s</span>
        <span>💰 ${result.cost_usd.toFixed(4)}</span>
        <span>📊 {result.step_count} шагов</span>
      </div>

      {safeLiveUrl && (
        <div>
          <p className="text-sm font-medium">👁 Открой live-браузер:</p>
          <a
            href={safeLiveUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline text-sm break-all"
          >
            {safeLiveUrl}
          </a>
        </div>
      )}

      {safeRecordingUrl && (
        <div>
          <p className="text-sm font-medium">🎥 Видео записи:</p>
          <a
            href={safeRecordingUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline text-sm break-all"
          >
            {safeRecordingUrl}
          </a>
          <p className="text-xs text-amber-600">
            ⚠️ Ссылка живёт 1 час, скачай сейчас
          </p>
        </div>
      )}

      {result.output && (
        <div>
          <p className="text-sm font-medium">📤 Результат:</p>
          <pre className="bg-slate-100 dark:bg-slate-900 p-3 rounded text-xs overflow-auto max-h-96">
            {typeof result.output === "string"
              ? result.output
              : JSON.stringify(result.output, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
