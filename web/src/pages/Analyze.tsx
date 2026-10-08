import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ChevronDown,
  ExternalLink,
  FileCheck2,
  MessageSquare,
  MoreHorizontal,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { LayoutOrEmbed } from "../dashboard/Embedded";
import { useT } from "../i18n";
import { api, ApiError, downloadBlob, isQuotaExceededError } from "../clientId";
import { pushHistory } from "../historyStore";
import { trackDocumentDownload } from "../dashboard/dashboard.data";
import {
  AssistantBubble,
  TendrChatComposer,
  UserBubble,
} from "../components/ui/tendr-ai-chat";
import { BidCalculator } from "../components/BidCalculator";
import { resolveLotSourceUrl } from "../dashboard/components/LotSourceLink";

type Requirement = {
  code?: string;
  title?: string;
  description?: string;
  is_mandatory?: boolean;
  name?: string;
  value?: string;
  is_critical?: boolean;
  category?: string;
  source_quote?: string;
  source_document?: string;
};

type SourceDocument = {
  name: string;
  document_type?: string;
  url: string;
  extracted: boolean;
  text_chars?: number;
  error?: string;
};

type CustomerScore = {
  customer: string;
  trust_score: number;
  trust_label: string;
  total_lots: number;
  avg_risk?: string;
  source: string;
  evidence_count?: number;
  disclaimer?: string;
};

type MarginEstimate = {
  category: string;
  estimated_margin_pct: number;
  confidence: string;
  assumptions?: string[];
  disclaimer?: string;
};

type LotAnalysis = {
  lot_id: string;
  title: string;
  customer: string;
  method: string;
  deadline?: string;
  budget_kzt?: number;
  amount_kzt?: number;
  technical_specification?: string;
  qualification_requirements?: string[];
  source_url?: string | null;
  requirements: Requirement[];
  documents_required: string[];
  source_documents?: SourceDocument[];
  summary: string;
  red_flags: string[];
  customer_score?: CustomerScore | null;
  margin_estimate?: MarginEstimate | null;
  recommendation?: string;
};

type LegalItem = {
  rule_id: string;
  rule_title: string;
  status: string;
  severity: string;
  description: string;
  law_reference?: string;
  recommendation?: string;
};

type ComplaintDraft = string | Record<string, string>;

type AnalysisResponse = {
  lot: LotAnalysis;
  legal?: {
    items: LegalItem[];
    overall_risk: string;
    summary: string;
    complaint_draft?: ComplaintDraft;
  };
  incomplete?: boolean;
  incomplete_reason?: string;
  created_at?: string;
};

type AnalysisJob = {
  id: string;
  kind: "url" | "upload";
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  stage: string;
  input_label: string;
  result?: AnalysisResponse | null;
  error_code?: string | null;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  analysisJobId?: string;
  actions?: Array<{ label: string; href: string }>;
};

type ChatSession = {
  id: string;
  title: string;
  updatedAt: string;
  messages: ChatMessage[];
};

const ACTIVE_JOB_KEY = "tendr_active_analysis_job:v1";
const LAST_JOB_KEY = "tendr_last_analysis_job:v1";
const CHAT_STORAGE_KEY = "tendr_ai_analyst_chat:v1";
const CHAT_SESSIONS_KEY = "tendr_ai_chat_sessions:v2";
const ACTIVE_CHAT_KEY = "tendr_ai_active_chat:v2";

const MAX_FILE_BYTES = 20 * 1024 * 1024;
const ALLOWED_EXTS = [".pdf", ".docx", ".txt", ".csv", ".xls", ".xlsx"] as const;

function getFileExt(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

function validateFileClientSide(f: File): string | null {
  const ext = getFileExt(f.name);
  if (!(ALLOWED_EXTS as readonly string[]).includes(ext)) {
    return "Неподдерживаемый тип файла. Разрешены: PDF, DOCX, TXT, CSV, XLS, XLSX.";
  }
  if (f.size > MAX_FILE_BYTES) {
    return "Файл слишком большой. Максимальный размер — 20 МБ. Уменьшите файл и попробуйте снова.";
  }
  if (f.size === 0) {
    return "Файл пустой. Выберите другой файл.";
  }
  return null;
}

function createLocalId(): string {
  const randomPart = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : Math.random().toString(16).slice(2);
  return `${Date.now()}-${randomPart}`;
}

function isChatMessage(item: unknown): item is ChatMessage {
  if (!item || typeof item !== "object") return false;
  const value = item as Partial<ChatMessage>;
  return (value.role === "user" || value.role === "assistant") && typeof value.content === "string";
}

function chatTitle(messages: ChatMessage[]): string {
  const firstUser = messages.find((message) => message.role === "user")?.content.trim();
  if (!firstUser) return "Новый чат";
  return firstUser.length > 42 ? `${firstUser.slice(0, 42).trim()}…` : firstUser;
}

function loadLegacyMessages(): ChatMessage[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isChatMessage).slice(-40);
  } catch {
    return [];
  }
}

function loadChatState(): { sessions: ChatSession[]; activeId: string } {
  try {
    const parsed = JSON.parse(localStorage.getItem(CHAT_SESSIONS_KEY) || "[]");
    if (Array.isArray(parsed)) {
      const sessions = parsed
        .filter((item): item is ChatSession => Boolean(
          item && typeof item.id === "string" && Array.isArray(item.messages),
        ))
        .map((item) => ({ ...item, messages: item.messages.filter(isChatMessage).slice(-40) }))
        .slice(0, 30);
      if (sessions.length) {
        const savedActive = localStorage.getItem(ACTIVE_CHAT_KEY);
        const activeId = sessions.some((item) => item.id === savedActive) ? savedActive! : sessions[0].id;
        return { sessions, activeId };
      }
    }
  } catch {
    // Повреждённую локальную историю заменяем новым диалогом.
  }
  const legacy = loadLegacyMessages();
  const session: ChatSession = {
    id: createLocalId(),
    title: chatTitle(legacy),
    updatedAt: new Date().toISOString(),
    messages: legacy,
  };
  return { sessions: [session], activeId: session.id };
}

function cleanAssistantText(value: string): string {
  return value
    .replace(/^[ \t]*#{1,6}[ \t]*/gm, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/^[ \t]*[-*][ \t]+/gm, "• ")
    .replace(/```|`/g, "")
    .replace(/\*/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function formatChatDate(value: string): string {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

function chatMessage(
  role: ChatMessage["role"],
  content: string,
  analysisJobId?: string,
  actions?: Array<{ label: string; href: string }>,
): ChatMessage {
  return {
    id: createLocalId(),
    role,
    content,
    analysisJobId,
    actions,
  };
}

function extractLotReference(message: string): string | null {
  const urlMatch = message.match(/https?:\/\/[^\s]+/i);
  if (urlMatch && /goszakup\.gov\.kz/i.test(urlMatch[0])) {
    return urlMatch[0].replace(/[),.;!?]+$/, "");
  }
  const idMatch = message.match(/(?:лот|закупк\w*|объявлен\w*)\s*(?:№|#|id\s*)?([0-9]{5,})/i);
  return idMatch?.[1] || (/^[0-9]{5,}$/.test(message.trim()) ? message.trim() : null);
}

function requirementTitle(requirement: Requirement): string {
  return requirement.title || requirement.name || requirement.code || "Требование";
}

function requirementDescription(requirement: Requirement): string {
  return requirement.description || requirement.value || "";
}

function requirementIsMandatory(requirement: Requirement): boolean {
  return requirement.is_mandatory ?? requirement.is_critical ?? false;
}

function TypewriterText({ text, active }: { text: string; active: boolean }) {
  const [visibleCharacters, setVisibleCharacters] = useState(active ? 0 : text.length);

  useEffect(() => {
    if (!active || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setVisibleCharacters(text.length);
      return;
    }
    setVisibleCharacters(0);
    const durationMs = Math.min(1800, Math.max(650, text.length * 10));
    const tickMs = 18;
    const charactersPerTick = Math.max(1, Math.ceil(text.length / (durationMs / tickMs)));
    const timer = window.setInterval(() => {
      setVisibleCharacters((current) => {
        const next = Math.min(text.length, current + charactersPerTick);
        if (next >= text.length) window.clearInterval(timer);
        return next;
      });
    }, tickMs);
    return () => window.clearInterval(timer);
  }, [active, text]);

  const typing = active && visibleCharacters < text.length;
  return (
    <>
      {text.slice(0, visibleCharacters)}
      {typing && <span aria-hidden="true" className="ml-0.5 inline-block h-[1em] w-px translate-y-0.5 animate-pulse bg-emerald-300/80" />}
    </>
  );
}

function AnalysisOrbit() {
  return (
    <span className="analysis-orbit" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  );
}

export function AnalyzePage({ embedded = false }: { embedded?: boolean } = {}) {
  const t = useT();
  const [searchParams] = useSearchParams();
  const requestedLotUrl = searchParams.get("lot_url");
  const initialChatState = useMemo(loadChatState, []);
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState(false);
  const [autoTitle, setAutoTitle] = useState<string>("");
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>(initialChatState.sessions);
  const [activeChatId, setActiveChatId] = useState(initialChatState.activeId);
  const [messages, setMessages] = useState<ChatMessage[]>(
    initialChatState.sessions.find((item) => item.id === initialChatState.activeId)?.messages || [],
  );
  const [chatBusy, setChatBusy] = useState(false);
  const [openChatMenuId, setOpenChatMenuId] = useState<string | null>(null);
  const [typingMessageId, setTypingMessageId] = useState<string | null>(null);
  const [restoreChecked, setRestoreChecked] = useState(false);
  const [lastRequest, setLastRequest] = useState<
    { kind: "url"; url: string } | { kind: "file"; name: string } | null
  >(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const lastFileRef = useRef<File | null>(null);
  const autoStartedRef = useRef(false);
  const completedJobsRef = useRef(new Set<string>());
  const conversationEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const now = new Date().toISOString();
    setChatSessions((current) => {
      const next = current.map((session) => session.id === activeChatId
        ? {
            ...session,
            title: chatTitle(messages),
            updatedAt: now,
            messages: messages.slice(-40),
          }
        : session);
      localStorage.setItem(CHAT_SESSIONS_KEY, JSON.stringify(next.slice(0, 30)));
      localStorage.setItem(ACTIVE_CHAT_KEY, activeChatId);
      return next;
    });
    if (typeof conversationEndRef.current?.scrollIntoView === "function") {
      conversationEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages, loading, chatBusy, result, activeChatId]);

  function applyCompletedJob(done: AnalysisJob, animateResponse = true) {
    if (!done.result) {
      setError("Результат анализа не найден. Запустите анализ ещё раз.");
      setLoading(false);
      return;
    }
    setResult(done.result);
    setLoading(false);
    setLastRequest(null);
    lastFileRef.current = null;
    localStorage.removeItem(ACTIVE_JOB_KEY);
    localStorage.setItem(LAST_JOB_KEY, done.id);
    if (!completedJobsRef.current.has(done.id) && done.result.lot?.lot_id) {
      completedJobsRef.current.add(done.id);
      const confirmedRequirements = done.result.lot.requirements?.length || 0;
      const readDocuments = done.result.lot.source_documents?.filter((document) => document.extracted).length || 0;
      const completedMessage = readDocuments
        ? `Готово — я прочитал официальные файлы Госзакупок (${readDocuments}) и нашёл ${confirmedRequirements} подтверждённых требований с цитатами. Полный разбор ниже.`
        : `Готово — я проверил официальную карточку лота и нашёл ${confirmedRequirements} подтверждённых требований. Полный разбор ниже.`;
      const responseMessage = chatMessage(
        "assistant",
        done.result?.incomplete
          ? "Я собрал доступные данные, но часть сведений не удалось подтвердить. Ниже показал, что найдено и что нужно перепроверить в первоисточнике."
          : completedMessage,
        done.id,
      );
      if (animateResponse) setTypingMessageId(responseMessage.id);
      setMessages((current) => current.some((message) => message.analysisJobId === done.id)
        ? current
        : [...current, responseMessage]);
      pushHistory({
        lot_id: done.result.lot.lot_id,
        title: done.result.lot.title || done.input_label,
        url: done.kind === "url" ? done.input_label : undefined,
        customer: done.result.lot.customer || "",
        method: done.result.lot.method || "",
        n_requirements: done.result.lot.requirements?.length || 0,
        n_red_flags: done.result.lot.red_flags?.length || 0,
        overall_risk: done.result.legal?.overall_risk,
        created_at: new Date().toISOString(),
      });
    }
  }

  // Восстанавливаем незавершённый анализ после обновления страницы.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const savedId = localStorage.getItem(ACTIVE_JOB_KEY);
        let restored = savedId
          ? await api<AnalysisJob>(`/api/lots/analysis-jobs/${savedId}`)
          : null;
        if (requestedLotUrl && restored?.input_label !== requestedLotUrl) {
          restored = null;
          localStorage.removeItem(ACTIVE_JOB_KEY);
        }
        if (!requestedLotUrl && !restored) {
          restored = await api<AnalysisJob | null>("/api/lots/analysis-jobs/active");
        }
        const lastId = localStorage.getItem(LAST_JOB_KEY);
        if (!requestedLotUrl && !restored && lastId) {
          restored = await api<AnalysisJob>(`/api/lots/analysis-jobs/${lastId}`);
        }
        if (
          restored?.status === "completed"
          && restored.result?.lot?.title?.toLowerCase().includes("не удалось проанализировать")
        ) {
          localStorage.removeItem(LAST_JOB_KEY);
          localStorage.removeItem(ACTIVE_JOB_KEY);
          restored = null;
        }
        if (cancelled || !restored) return;
        setJob(restored);
        if (restored.status === "completed") applyCompletedJob(restored, false);
        else if (restored.status === "failed") {
          localStorage.removeItem(ACTIVE_JOB_KEY);
          setError("Предыдущий анализ не завершился. Запустите его ещё раз.");
        } else {
          localStorage.setItem(ACTIVE_JOB_KEY, restored.id);
          setLoading(true);
        }
      } catch {
        localStorage.removeItem(ACTIVE_JOB_KEY);
      } finally {
        if (!cancelled) setRestoreChecked(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [requestedLotUrl]);

  // Сервер выполняет работу независимо от вкладки; UI только читает состояние.
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const fresh = await api<AnalysisJob>(`/api/lots/analysis-jobs/${job.id}`);
        if (cancelled) return;
        setJob(fresh);
        if (fresh.status === "completed") applyCompletedJob(fresh);
        if (fresh.status === "failed") {
          localStorage.removeItem(ACTIVE_JOB_KEY);
          setLoading(false);
          setError(
            fresh.error_code === "UPLOAD_EXPIRED"
              ? "Загруженный файл больше недоступен. Выберите файл ещё раз."
              : "Не удалось завершить анализ. Проверьте данные и повторите попытку.",
          );
        }
      } catch {
        // Краткий сетевой сбой не отменяет серверное задание.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job?.id, job?.status]);

  async function startAnalysis(input: { url?: string; file?: File }) {
    setError(null);
    setResult(null);
    setQuota(false);
    setLoading(true);
    try {
      let created: AnalysisJob;
      if (input.file) {
        const fd = new FormData();
        fd.append("file", input.file);
        created = await api<AnalysisJob>("/api/lots/analysis-jobs/upload", {
          method: "POST",
          body: fd,
        });
      } else {
        created = await api<AnalysisJob>("/api/lots/analysis-jobs", {
          method: "POST",
          body: JSON.stringify({ url: input.url }),
        });
      }
      localStorage.setItem(ACTIVE_JOB_KEY, created.id);
      setJob(created);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    } catch (e: unknown) {
      setLoading(false);
      if (isQuotaExceededError(e)) setQuota(true);
      else setError(e instanceof ApiError ? e.message : "Ошибка анализа. Попробуйте снова.");
    }
  }

  // Автозапуск анализа, если в URL есть ?lot_url=...
  // Срабатывает когда пользователь нажимает "🤖 AI-анализ" в каталоге лотов.
  useEffect(() => {
    const lotUrl = searchParams.get("lot_url");
    const lotTitle = searchParams.get("lot_title");
    if (restoreChecked && lotUrl && !loading && !result && !job && !autoStartedRef.current) {
      autoStartedRef.current = true;
      setUrl(lotUrl);
      if (lotTitle) setAutoTitle(lotTitle);
      setMessages((current) => [
        ...current,
        chatMessage("user", `Разбери этот лот и собери требования ТЗ: ${lotTitle || lotUrl}`),
      ]);
      void startAnalysis({ url: lotUrl });
    }
  }, [restoreChecked, searchParams, loading, result, job]);

  async function sendChatMessage(message: string) {
    const cleanMessage = message.trim();
    if (!cleanMessage || chatBusy) return;
    const history = messages.slice(-10).map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, chatMessage("user", cleanMessage)]);
    setUrl("");
    setError(null);
    setChatBusy(true);
    try {
      const response = await api<{
        answer: string;
        actions?: Array<{ label: string; href: string }>;
      }>("/api/lots/assistant/chat", {
        method: "POST",
        body: JSON.stringify({
          message: cleanMessage,
          job_id: job?.status === "completed" ? job.id : null,
          history,
        }),
      });
      const responseMessage = chatMessage("assistant", response.answer, undefined, response.actions);
      setTypingMessageId(responseMessage.id);
      setMessages((current) => [...current, responseMessage]);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "AI-чат временно недоступен. Попробуйте ещё раз.");
    } finally {
      setChatBusy(false);
    }
  }

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    if (loading || chatBusy) return;
    setError(null);
    setQuota(false);
    if (file) {
      const fileProblem = validateFileClientSide(file);
      if (fileProblem) {
        if (file.size > MAX_FILE_BYTES) {
          setError("Файл слишком большой. Максимальный размер — 20 МБ. Уменьшите файл и попробуйте снова.");
        } else {
          setError(fileProblem);
        }
        return;
      }
      lastFileRef.current = file;
      setLastRequest({ kind: "file", name: file.name });
      setMessages((current) => [
        ...current,
        chatMessage("user", url.trim() || `Разбери документацию «${file.name}» и собери требования ТЗ.`),
      ]);
      setUrl("");
      await startAnalysis({ file });
      return;
    }
    const message = url.trim();
    if (!message) {
      setError(t("analyze.empty"));
      return;
    }
    const reference = extractLotReference(message);
    if (reference) {
      setLastRequest({ kind: "url", url: reference });
      setMessages((current) => [...current, chatMessage("user", message)]);
      setUrl("");
      await startAnalysis({ url: reference });
      return;
    }
    await sendChatMessage(message);
  }

  function retry() {
    // Повтор последнего запроса без потери контекста.
    if (loading) return;
    setError(null);
    setQuota(false);
    setJob(null);
    localStorage.removeItem(ACTIVE_JOB_KEY);
    if (lastRequest?.kind === "file" && lastFileRef.current) {
      setFile(lastFileRef.current);
      void startAnalysis({ file: lastFileRef.current });
    } else if (lastRequest?.kind === "url") {
      setUrl(lastRequest.url);
      void startAnalysis({ url: lastRequest.url });
    }
  }

  function clearActiveAnalysis() {
    setResult(null);
    setError(null);
    setQuota(false);
    setUrl("");
    setFile(null);
    setLastRequest(null);
    lastFileRef.current = null;
    setJob(null);
    localStorage.removeItem(LAST_JOB_KEY);
    localStorage.removeItem(ACTIVE_JOB_KEY);
  }

  function reset() {
    if (loading || chatBusy) return;
    const newSession: ChatSession = {
      id: createLocalId(),
      title: "Новый чат",
      updatedAt: new Date().toISOString(),
      messages: [],
    };
    setChatSessions((current) => [newSession, ...current.filter((item) => item.messages.length)].slice(0, 30));
    setActiveChatId(newSession.id);
    setMessages([]);
    setTypingMessageId(null);
    setAutoTitle("");
    clearActiveAnalysis();
    localStorage.removeItem(CHAT_STORAGE_KEY);
  }

  async function openChat(session: ChatSession) {
    setOpenChatMenuId(null);
    if (session.id === activeChatId || loading || chatBusy) return;
    setActiveChatId(session.id);
    setMessages(session.messages);
    setTypingMessageId(null);
    setAutoTitle("");
    clearActiveAnalysis();
    const analysisJobId = [...session.messages]
      .reverse()
      .find((message) => message.analysisJobId)?.analysisJobId;
    if (!analysisJobId) return;
    try {
      const restored = await api<AnalysisJob>(`/api/lots/analysis-jobs/${analysisJobId}`);
      setJob(restored);
      if (restored.status === "completed" && restored.result) setResult(restored.result);
    } catch {
      // Текст старого диалога остаётся доступным, даже если серверный анализ удалён.
    }
  }

  function deleteChat(session: ChatSession) {
    if (loading || chatBusy) return;
    if (!window.confirm(`Удалить чат «${session.title}»? Это действие нельзя отменить.`)) return;

    setOpenChatMenuId(null);
    const remaining = chatSessions.filter((item) => item.id !== session.id);
    if (session.id !== activeChatId) {
      setChatSessions(remaining);
      localStorage.setItem(CHAT_SESSIONS_KEY, JSON.stringify(remaining));
      return;
    }

    const blank: ChatSession = {
      id: createLocalId(),
      title: "Новый чат",
      updatedAt: new Date().toISOString(),
      messages: [],
    };
    const next = [blank, ...remaining].slice(0, 30);
    setChatSessions(next);
    localStorage.setItem(CHAT_SESSIONS_KEY, JSON.stringify(next));
    localStorage.setItem(ACTIVE_CHAT_KEY, blank.id);
    setActiveChatId(blank.id);
    setMessages([]);
    setTypingMessageId(null);
    setAutoTitle("");
    clearActiveAnalysis();
  }

  function downloadDocx(kind: "complaint" | "report") {
    if (!result) return;
    const lotId = result.lot.lot_id;
    // Backend принимает только числовой lot_id (path-параметр int):
    // для файловых анализов ("raw"/"manual") скачивание недоступно.
    if (!/^\d+$/.test(lotId.trim())) {
      setError("Скачивание недоступно для этого анализа: нет числового ID лота.");
      return;
    }
    const stamp = new Date().toISOString().slice(0, 10);
    const filename =
      kind === "complaint"
        ? `zhaloba_${lotId}_${stamp}.docx`
        : `otchet_${lotId}_${stamp}.docx`;
    setError(null);
    void downloadBlob(`/api/lots/${lotId}/download?kind=${kind}`, filename)
      .then(() => {
        // Фиксируем только реально скачанный файл.
        trackDocumentDownload({
          id: `${kind}-${lotId}-${stamp}`,
          kind,
          filename,
          lotId,
          lotTitle: result.lot.title,
          createdAt: new Date().toISOString(),
        });
      })
      .catch((e: unknown) =>
        setError(
          e instanceof ApiError
            ? e.message
            : "Не удалось скачать файл. Попробуйте позже.",
        ),
      );
  }

  const resultNeedsReview = Boolean(
    result && (result.incomplete || !result.legal || result.legal.overall_risk === "needs_review"),
  );
  const sourceUrl = resolveLotSourceUrl(result?.lot.source_url, result?.lot.lot_id)
    ?? (job?.kind === "url" && /^https?:\/\//i.test(job.input_label) ? job.input_label : undefined);
  const jobProgress = Math.max(3, job?.progress ?? 3);
  const isVerifyingSources = loading && jobProgress >= 18 && jobProgress < 82;
  const loadingTitle = isVerifyingSources
    ? "Ещё немного — проверяем требования по источникам"
    : (job?.stage || "Запускаю анализ");
  const loadingNote = isVerifyingSources
    ? "Читаем официальные вложения и сверяем каждую цитату."
    : "Можно обновить страницу — задача сохранена на сервере.";

  return (
    <LayoutOrEmbed embedded={embedded} plainBackground>
      <div className={`${embedded ? "" : "page-container py-8 sm:py-10"} bg-[#070707]`}>
        <section className="relative mx-auto flex min-h-[calc(100vh-150px)] max-w-[1320px] flex-col overflow-hidden rounded-[28px] border border-white/[0.075] bg-[#090909] shadow-[0_30px_100px_-55px_rgba(0,0,0,1)]">
          <header className="relative flex items-center justify-between gap-4 border-b border-white/[0.065] px-5 py-4 sm:px-7">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-2xl border border-emerald-400/25 bg-emerald-400/[0.1] text-emerald-300"><Sparkles size={18} /></span>
              <div><h1 className="text-sm font-semibold text-white">AI‑чат Tendr</h1><p className="mt-0.5 text-[11px] text-white/35">Работает с реальными данными лота и вашим контекстом</p></div>
            </div>
            <button type="button" onClick={reset} disabled={loading || chatBusy} className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/[0.07] px-3 text-xs text-white/55 transition hover:bg-white/[0.05] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"><Plus size={14} /> <span className="hidden sm:inline">Новый чат</span></button>
          </header>

          <div className="flex min-h-0 flex-1">
            <aside className="hidden w-[245px] shrink-0 flex-col border-r border-white/[0.06] bg-[#0c0c0c] p-3 md:flex">
              <button type="button" onClick={reset} disabled={loading || chatBusy} className="flex h-10 items-center justify-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.035] text-xs font-medium text-white/70 transition hover:bg-white/[0.07] hover:text-white disabled:opacity-40"><Plus size={15} /> Новый чат</button>
              <p className="mb-2 mt-5 px-2 text-[10px] font-medium uppercase tracking-[.16em] text-white/25">История чатов</p>
              <div className="min-h-0 flex-1 space-y-1 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                {[...chatSessions]
                  .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
                  .map((session) => (
                    <div
                      key={session.id}
                      className={`group relative flex w-full items-start rounded-xl transition ${session.id === activeChatId ? "bg-white/[0.075] text-white" : "text-white/45 hover:bg-white/[0.04] hover:text-white/75"}`}
                    >
                      <button
                        type="button"
                        onClick={() => void openChat(session)}
                        className="flex min-w-0 flex-1 items-start gap-2.5 px-2.5 py-2.5 pr-9 text-left"
                      >
                        <MessageSquare size={14} className="mt-0.5 shrink-0 opacity-55" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-xs font-medium">{session.title}</span>
                          <span className="mt-1 block text-[10px] text-white/25">{formatChatDate(session.updatedAt)}</span>
                        </span>
                      </button>
                      <button
                        type="button"
                        aria-label={`Действия с чатом «${session.title}»`}
                        aria-expanded={openChatMenuId === session.id}
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenChatMenuId((current) => current === session.id ? null : session.id);
                        }}
                        className="absolute right-1.5 top-2 inline-flex h-7 w-7 items-center justify-center rounded-lg text-white/30 opacity-0 transition hover:bg-white/[0.08] hover:text-white/75 focus:opacity-100 group-hover:opacity-100"
                      >
                        <MoreHorizontal size={15} />
                      </button>
                      {openChatMenuId === session.id && (
                        <div className="absolute right-1.5 top-9 z-20 w-36 rounded-xl border border-white/[0.1] bg-[#171717] p-1 shadow-2xl">
                          <button
                            type="button"
                            onClick={() => deleteChat(session)}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs text-red-300/85 transition hover:bg-red-400/[0.09] hover:text-red-200"
                          >
                            <Trash2 size={14} /> Удалить чат
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
              </div>
              <p className="px-2 pb-1 pt-3 text-[10px] leading-4 text-white/20">Диалоги сохраняются в этом браузере.</p>
            </aside>

            <div className="flex min-w-0 flex-1 flex-col">
              <div className="relative flex-1 overflow-y-auto px-4 py-8 sm:px-8">
                <div className="mx-auto max-w-[900px] space-y-7">
                  {autoTitle && <div className="mx-auto w-fit rounded-full border border-emerald-400/15 bg-emerald-400/[0.06] px-3 py-1.5 text-xs text-emerald-200/75">Выбран из каталога: {autoTitle}</div>}
                  {messages.map((message) => message.role === "user" ? <UserBubble key={message.id}>{message.content}</UserBubble> : <AssistantBubble key={message.id}>
                    <div className="whitespace-pre-wrap text-sm leading-6 text-white/68"><TypewriterText text={cleanAssistantText(message.content)} active={message.id === typingMessageId} /></div>
                    {message.actions?.some((action) => /^\/dashboard(?:\/|$)/.test(action.href)) && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {message.actions
                          .filter((action) => /^\/dashboard(?:\/|$)/.test(action.href))
                          .slice(0, 2)
                          .map((action) => <Link key={action.href} to={action.href} className="inline-flex h-9 items-center rounded-xl border border-emerald-400/20 bg-emerald-400/[0.07] px-3 text-xs font-medium text-emerald-200/85 transition hover:bg-emerald-400/[0.12] hover:text-emerald-100">{action.label}</Link>)}
                      </div>
                    )}
                    {message.analysisJobId === job?.id && result ? <div className="mt-4"><AnalysisSnapshot result={result} needsReview={resultNeedsReview} sourceUrl={sourceUrl} onReset={reset} onDownload={downloadDocx} animate={message.id === typingMessageId} /></div> : null}
                  </AssistantBubble>)}

                  {loading && <AssistantBubble><div role="status" aria-busy="true" aria-label="Идёт AI-анализ" className="rounded-2xl border border-emerald-400/15 bg-emerald-400/[0.045] p-5"><div className="flex items-center justify-between gap-4"><div className="flex min-w-0 items-center gap-3">{isVerifyingSources ? <AnalysisOrbit /> : <Sparkles size={18} className="shrink-0 animate-pulse text-emerald-300/70" />}<div><p className="text-sm font-medium text-emerald-200">{loadingTitle}</p><p className="mt-1 text-xs text-white/35">{loadingNote}</p></div></div><span className="text-xs tabular-nums text-emerald-300">{jobProgress}%</span></div><div className="relative mt-4 h-1 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-emerald-300 transition-[width] duration-700" style={{ width: `${jobProgress}%` }} />{isVerifyingSources && <span className="analysis-progress-sheen" />}</div></div></AssistantBubble>}

                  {chatBusy && <AssistantBubble><div className="flex items-center gap-2 text-sm text-white/42"><span className="flex gap-1"><i className="h-1.5 w-1.5 animate-bounce rounded-full bg-emerald-300 [animation-delay:-.2s]" /><i className="h-1.5 w-1.5 animate-bounce rounded-full bg-emerald-300 [animation-delay:-.1s]" /><i className="h-1.5 w-1.5 animate-bounce rounded-full bg-emerald-300" /></span>Думаю…</div></AssistantBubble>}

                  {quota && <div role="alert" className="ml-11 rounded-xl border border-amber-400/15 bg-amber-400/[0.055] px-4 py-3 text-sm text-amber-100/75">{t("analyze.quota.text")} <button type="button" onClick={retry} className="ml-2 font-medium text-amber-300 hover:text-amber-200">Повторить</button></div>}
                  {error && <div role="alert" className="ml-11 rounded-xl border border-red-400/15 bg-red-400/[0.055] px-4 py-3 text-sm text-red-200/80">{error}</div>}
                  <div ref={conversationEndRef} />
                </div>
              </div>

              <footer className="relative border-t border-white/[0.055] bg-[#090909] px-4 py-4 sm:px-8 sm:py-5">
                <div className="mx-auto max-w-[900px]">
                  <form onSubmit={submit}>
                    <input ref={fileInput} type="file" accept=".pdf,.docx,.txt,.csv,.xls,.xlsx" aria-label={t("analyze.file.label")} onChange={(event) => setFile(event.target.files?.[0] || null)} className="sr-only" disabled={loading || chatBusy} />
                    <TendrChatComposer value={url} onChange={setUrl} onSubmit={() => void submit()} onAttach={() => fileInput.current?.click()} onRemoveFile={() => { setFile(null); if (fileInput.current) fileInput.current.value = ""; }} file={file} disabled={loading || chatBusy} />
                  </form>
                  <p className="mt-2 text-center text-[10px] text-white/22">AI может ошибаться. Важные требования сверяйте с документацией на Госзакупках.</p>
                </div>
              </footer>
            </div>
          </div>
        </section>
      </div>
    </LayoutOrEmbed>
  );
}

function AnalysisSnapshot({ result, needsReview, sourceUrl, onReset, onDownload, animate = false }: { result: AnalysisResponse; needsReview: boolean; sourceUrl?: string; onReset: () => void; onDownload: (kind: "complaint" | "report") => void; animate?: boolean }) {
  const lot = result.lot;
  const budget = lot.budget_kzt ?? lot.amount_kzt;
  const risk = result.legal?.overall_risk || "needs_review";
  const [fullOpen, setFullOpen] = useState(false);
  return (
    <div className={`overflow-hidden rounded-[22px] border border-white/[0.08] bg-[#111314] ${animate ? "analysis-result-card" : ""}`}>
      <div className="analysis-result-section border-b border-white/[0.06] p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0"><div className="mb-2 flex flex-wrap gap-2"><span className="rounded-full border border-emerald-400/20 bg-emerald-400/[0.07] px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider text-emerald-300">Лот {lot.lot_id}</span><span className={`rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider ${needsReview ? "border-amber-400/20 bg-amber-400/[0.06] text-amber-300" : "border-white/[0.08] text-white/40"}`}>{riskLabel(risk)}</span></div><h3 className="max-w-3xl text-xl font-medium leading-7 tracking-[-.025em] text-white">{lot.title}</h3><p className="mt-2 text-sm text-white/42">{lot.customer || "Заказчик не указан"}{lot.deadline ? ` · подача до ${lot.deadline}` : ""}</p></div>{budget ? <p className="shrink-0 text-lg font-medium text-white">{budget.toLocaleString("ru-RU")} ₸</p> : null}</div>
        {lot.summary && <p className="mt-4 max-w-3xl text-sm leading-6 text-white/55">{lot.summary}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-2.5">
          <button type="button" onClick={() => setFullOpen((current) => !current)} aria-expanded={fullOpen} className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.07] px-3 text-xs font-medium text-emerald-200/90 transition hover:bg-emerald-400/[0.12] hover:text-emerald-100">Открыть полный разбор и скачать документы <ChevronDown size={14} className={`transition-transform duration-300 ${fullOpen ? "rotate-180" : ""}`} /></button>
          {sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer" className="inline-flex min-h-9 items-center gap-1.5 px-2 text-xs text-emerald-300/65 transition hover:text-emerald-200">Первоисточник на Госзакупках <ExternalLink size={13} /></a>}
        </div>
      </div>
      <div className="analysis-result-section grid grid-cols-3 divide-x divide-white/[0.06] border-b border-white/[0.06]"><div className="p-4 sm:px-6"><p className="text-xl font-medium text-white">{lot.requirements?.length || 0}</p><p className="mt-1 text-[10px] uppercase tracking-wider text-white/28">требований</p></div><div className="p-4 sm:px-6"><p className="text-xl font-medium text-white">{lot.documents_required?.length || 0}</p><p className="mt-1 text-[10px] uppercase tracking-wider text-white/28">документов</p></div><div className="p-4 sm:px-6"><p className={`text-xl font-medium ${lot.red_flags?.length ? "text-amber-300" : "text-emerald-300"}`}>{lot.red_flags?.length || 0}</p><p className="mt-1 text-[10px] uppercase tracking-wider text-white/28">рисков</p></div></div>
      <div className="analysis-result-section grid gap-5 p-5 sm:p-6 lg:grid-cols-2">
        <div><p className="text-[10px] font-semibold uppercase tracking-[.18em] text-emerald-300/75">Что требуется</p><ul className="mt-3 space-y-3">{lot.requirements?.length ? lot.requirements.slice(0, 8).map((item, index) => <li key={`${item.code || item.name}-${index}`} className={`flex gap-2.5 text-sm leading-5 text-white/58 ${animate ? "analysis-result-line" : ""}`} style={animate ? { animationDelay: `${260 + index * 55}ms` } : undefined}><span className="mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-emerald-400/20 text-[8px] text-emerald-300">✓</span><span><span className="text-white/75">{requirementTitle(item)}</span>{requirementIsMandatory(item) ? <b className="ml-1 font-medium text-amber-300/75">обязательно</b> : null}{requirementDescription(item) ? <span className="mt-0.5 block text-xs text-white/40">{requirementDescription(item)}</span> : null}{item.source_quote ? <q className="mt-1 block text-[11px] text-emerald-200/45">{item.source_quote}</q> : null}</span></li>) : <li className="text-sm text-white/35">Подтверждённые требования не найдены.</li>}</ul></div>
        <div><p className="text-[10px] font-semibold uppercase tracking-[.18em] text-emerald-300/75">Документы</p><ul className="mt-3 space-y-2.5">{lot.documents_required?.length ? lot.documents_required.slice(0, 5).map((item, index) => <li key={`${item}-${index}`} className="flex gap-2.5 text-sm leading-5 text-white/58"><FileCheck2 size={14} className="mt-0.5 shrink-0 text-white/30" /><span>{item}</span></li>) : <li className="text-sm text-white/35">Список документов не найден.</li>}</ul></div>
      </div>
      {lot.source_documents?.length ? <div className="mx-5 mb-5 rounded-xl border border-white/[0.07] bg-black/20 px-4 py-3 sm:mx-6"><p className="text-[10px] font-semibold uppercase tracking-[.16em] text-white/35">Официальные источники</p><div className="mt-2 flex flex-wrap gap-2">{lot.source_documents.map((document) => <a key={`${document.url}-${document.name}`} href={document.url} target="_blank" rel="noreferrer" className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition ${document.extracted ? "border-emerald-400/20 text-emerald-200/70 hover:bg-emerald-400/[0.06]" : "border-amber-400/20 text-amber-200/70"}`}><FileCheck2 size={13} />{document.name}{document.extracted ? " · прочитан" : " · не прочитан"}<ExternalLink size={11} /></a>)}</div></div> : null}
      {needsReview && <div className="mx-5 mb-5 rounded-xl border border-amber-400/15 bg-amber-400/[0.05] px-4 py-3 text-xs leading-5 text-amber-100/65 sm:mx-6">Часть данных требует ручной проверки: {result.incomplete_reason || "не все сведения удалось однозначно подтвердить"}.</div>}
      <div className={`grid transition-[grid-template-rows,opacity] duration-500 ease-out ${fullOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`} aria-hidden={!fullOpen}><div className="overflow-hidden"><div className="border-t border-white/[0.05] bg-black/15 p-5 sm:p-6"><ResultView result={result} onReset={onReset} onDownload={onDownload} /></div></div></div>
    </div>
  );
}

function riskTone(risk?: string) {
  if (risk === "high") return { color: "#ef4444", background: "rgba(239, 68, 68, 0.1)" };
  if (risk === "medium") return { color: "#f59e0b", background: "rgba(245, 158, 11, 0.1)" };
  if (risk === "low") return { color: "#10b981", background: "rgba(16, 185, 129, 0.1)" };
  return { color: "#fbbf24", background: "rgba(251, 191, 36, 0.1)" };
}

function riskLabel(risk?: string) {
  if (risk === "high") return "Высокий";
  if (risk === "medium") return "Средний";
  if (risk === "low") return "Низкий";
  return "Не определён — нужна проверка";
}

function ResultView({
  result,
  onReset,
  onDownload,
}: {
  result: AnalysisResponse;
  onReset: () => void;
  onDownload: (kind: "complaint" | "report") => void;
}) {
  const t = useT();
  const lot = result.lot;
  const legal = result.legal;
  const overallRisk = legal?.overall_risk || "needs_review";
  const riskStyle = riskTone(overallRisk);
  const recommendation =
    result.incomplete || overallRisk === "needs_review" ? "review" : lot.recommendation;
  const lotBudget = lot.budget_kzt ?? lot.amount_kzt;
  // Ссылка приходит с backend и проходит строгий allowlist: недоверенный
  // хост или http:// приведёт к null. Если её нет, строим из lot_id —
  // иначе кнопка пропадала бы на загрузках, где source_url пуст.
  const lotSourceUrl = resolveLotSourceUrl(lot.source_url, lot.lot_id);
  const draft = legal?.complaint_draft;
  const draftDict =
    typeof draft === "object" && draft !== null
      ? (draft as Record<string, string>)
      : null;
  const hasComplaint =
    !!draft && (draftDict !== null ? Object.keys(draftDict).length > 0 : true);

  return (
    <div className="space-y-6">
      <section
        className="rounded-lg border p-6"
        style={{
          backgroundColor: "var(--bg-elevated)",
          borderColor: "var(--border)",
          borderLeftWidth: "3px",
          borderLeftColor: riskStyle.color,
        }}
      >
        <h2 className="text-xl font-semibold mb-2 tracking-tight">
          {lot.title}
        </h2>
        <div className="text-sm text-[var(--text-muted)] mb-3">
          {lot.customer}
          {lotBudget ? ` · ${lotBudget.toLocaleString()} ₸` : ""}
          {lot.deadline
            ? ` · ${t("analyze.summary.deadline")} ${lot.deadline}`
            : ""}
        </div>
        {lotSourceUrl && (
          <a
            href={lotSourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mb-3 inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium transition hover:border-white/25 hover:bg-white/[0.04]"
            style={{ color: "var(--accent)" }}
          >
            Открыть лот на Госзакупках ↗
          </a>
        )}
        {lot.summary && (
          <p className="text-[var(--text-muted)] leading-relaxed">
            {lot.summary}
          </p>
        )}
        {legal && (
          <div className="mt-4 inline-flex items-center gap-2 text-xs">
            <span className="text-[var(--text-muted)] uppercase tracking-wider font-medium">
              {t("analyze.summary.risk")}
            </span>
            <span
              className="px-2.5 py-1 rounded-md font-medium"
              style={{
                backgroundColor: riskStyle.background,
                color: riskStyle.color,
              }}
            >
              {riskLabel(legal.overall_risk)}
            </span>
          </div>
        )}
      </section>

      {/* Рекомендация AI + скоринг заказчика + маржинальность */}
      {(recommendation || lot.customer_score || lot.margin_estimate) && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Рекомендация */}
          {recommendation && (
            <div
              className="rounded-lg border p-4"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="text-xs font-medium text-[var(--text-muted)] mb-1 uppercase tracking-wider">
                {t("analyze.recommendation.title")}
              </div>
              <div
                className="text-lg font-semibold flex items-center gap-2"
                style={{
                  color:
                    recommendation === "participate"
                      ? "#10b981"
                      : recommendation === "skip"
                        ? "#ef4444"
                        : "#f59e0b",
                }}
              >
                <span>
                  {recommendation === "participate"
                    ? "✓"
                    : recommendation === "skip"
                      ? "✕"
                      : "!"}
                </span>
                {t(`analyze.recommendation.${recommendation}`)}
              </div>
            </div>
          )}

          {/* Скоринг заказчика */}
          {lot.customer_score && (
            <div
              className="rounded-lg border p-4"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="text-xs font-medium text-[var(--text-muted)] mb-2 uppercase tracking-wider">
                Оценка по внутренним анализам
              </div>
              <div className="flex items-baseline gap-2 mb-1">
                <span
                  className="text-2xl font-bold"
                  style={{
                    color:
                      lot.customer_score.trust_score >= 60
                        ? "#10b981"
                        : lot.customer_score.trust_score >= 40
                          ? "#f59e0b"
                          : "#ef4444",
                  }}
                >
                  {lot.customer_score.trust_score.toFixed(0)}
                </span>
                <span className="text-xs text-[var(--text-subtle)]">/ 100</span>
              </div>
              <div className="text-sm text-[var(--text-muted)] mb-1">
                {t(
                  `analyze.score.trust_label.${lot.customer_score.trust_label}`,
                )}
              </div>
              {lot.customer_score.total_lots > 0 && (
                <div className="text-xs text-[var(--text-subtle)]">
                  Основание: {lot.customer_score.evidence_count ?? lot.customer_score.total_lots} анализов Tendr
                </div>
              )}
              <p className="mt-2 text-xs leading-5 text-amber-300/80">
                {lot.customer_score.disclaimer || "Это приблизительная внутренняя оценка, а не проверенная надёжность заказчика."}
              </p>
            </div>
          )}

          {/* Маржинальность */}
          {lot.margin_estimate && (
            <div
              className="rounded-lg border p-4"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="text-xs font-medium text-[var(--text-muted)] mb-2 uppercase tracking-wider">
                Ориентир маржи по категории
              </div>
              <div
                className="text-2xl font-bold mb-1"
                style={{ color: "#fbbf24" }}
              >
                {lot.margin_estimate.estimated_margin_pct.toFixed(0)}%
              </div>
              <div className="text-xs text-[var(--text-muted)]">
                {t("analyze.margin.category")} {lot.margin_estimate.category}
              </div>
              <div className="text-xs text-[var(--text-subtle)]">
                {t(
                  "analyze.margin.confidence." + lot.margin_estimate.confidence,
                )}
              </div>
              <p className="mt-2 text-xs leading-5 text-amber-300/80">
                {lot.margin_estimate.disclaimer || "Это приблизительный ориентир, а не проверенная прибыль."}
              </p>
            </div>
          )}
        </div>
      )}

      {lotBudget && lotBudget > 0 && <BidCalculator budgetKzt={lotBudget} lotId={lot.lot_id} lotTitle={lot.title} />}

      {lot.red_flags?.length > 0 && (
        <section
          className="rounded-lg border p-6"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
            borderLeftWidth: "3px",
            borderLeftColor: "#f59e0b",
          }}
        >
          <h3 className="font-semibold mb-3 flex items-center gap-2">
            <span style={{ color: "#f59e0b" }}>⚠</span>
            {t("analyze.flags.title")}{" "}
            <span className="text-[var(--text-muted)] font-normal text-sm">
              {lot.red_flags.length}
            </span>
          </h3>
          <ul className="space-y-2 text-sm text-[var(--text-muted)]">
            {lot.red_flags.map((f, i) => (
              <li key={i} className="flex gap-2">
                <span style={{ color: "#f59e0b" }}>•</span>
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {lot.requirements?.length > 0 && (
        <section className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-6">
          <h3 className="font-bold mb-3">
            📋 {t("analyze.requirements.title")} ({lot.requirements.length})
          </h3>
          <ul className="space-y-3">
            {lot.requirements.map((r, i) => (
              <li key={i} className="border-l-4 border-brand pl-3">
                <div className="font-medium">
                  {requirementTitle(r)}
                  {requirementIsMandatory(r) && (
                    <span className="ml-2 text-xs text-red-600">
                      {t("analyze.requirements.mandatory")}
                    </span>
                  )}
                </div>
                <div className="text-sm text-slate-600 dark:text-slate-300">
                  {requirementDescription(r)}
                </div>
                {r.source_quote && <q className="mt-1 block text-xs text-emerald-700 dark:text-emerald-300/65">{r.source_quote}</q>}
                {r.source_document && <p className="mt-1 text-[11px] text-slate-500">Источник: {r.source_document}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {lot.documents_required?.length > 0 && (
        <section className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-6">
          <h3 className="font-bold mb-2">
            📑 {t("analyze.docs.title")} ({lot.documents_required.length})
          </h3>
          <ul className="list-disc pl-5 space-y-1 text-sm">
            {lot.documents_required.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </section>
      )}

      {legal && legal.items?.length > 0 && (
        <section
          className="rounded-lg border p-6"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
            borderLeftWidth: "3px",
            borderLeftColor: "#ef4444",
          }}
        >
          <h3 className="font-semibold mb-3 flex items-center gap-2">
            <span style={{ color: "#ef4444" }}>⚖</span>
            {t("analyze.violations.title")}{" "}
            <span className="text-[var(--text-muted)] font-normal text-sm">
              {legal.items.length}
            </span>
          </h3>
          <ul className="space-y-2 text-sm">
            {legal.items.map((it, i) => (
              <li key={i} className="flex gap-2">
                <span
                  className={
                    it.status === "violation"
                      ? "text-red-600"
                      : it.status === "risk"
                        ? "text-amber-600"
                        : "text-green-600"
                  }
                >
                  {it.status === "violation"
                    ? "✗"
                    : it.status === "risk"
                      ? "!"
                      : "✓"}
                </span>
                <div>
                  <div className="font-medium">{it.rule_title}</div>
                  <div className="text-slate-600">{it.description}</div>
                  {it.law_reference && (
                    <div className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
                      📖 {it.law_reference}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {hasComplaint && (
        <section className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-6">
          <h3 className="font-bold mb-3">📝 {t("analyze.complaint.title")}</h3>
          {draftDict ? (
            <div className="space-y-3 text-sm">
              {(
                [
                  "шапка",
                  "обстоятельства",
                  "нарушенные_нормы",
                  "просьба",
                ] as const
              ).map((k) =>
                draftDict[k] ? (
                  <div key={k}>
                    <div className="font-semibold text-[var(--text)]">{k}:</div>
                    <div className="text-slate-600 dark:text-slate-300 whitespace-pre-wrap">
                      {draftDict[k]}
                    </div>
                  </div>
                ) : null,
              )}
            </div>
          ) : (
            <div className="text-sm text-slate-600 dark:text-slate-300 whitespace-pre-wrap">
              {draft as string}
            </div>
          )}
        </section>
      )}

      <div className="flex gap-3 flex-wrap pt-2">
        <button
          onClick={() => onDownload("report")}
          className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-5 py-2.5 font-medium text-white transition hover:bg-emerald-400"
        >
          <span>⬇</span> Скачать отчёт DOCX
        </button>
        {hasComplaint && (
          <button
            onClick={() => onDownload("complaint")}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border-strong)] px-5 py-2.5 font-medium transition hover:bg-[var(--accent-glow)]"
          >
            <span>⬇</span> Скачать жалобу DOCX
          </button>
        )}
        <button
          onClick={onReset}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-medium transition"
          style={{ color: "var(--text-muted)" }}
        >
          <span>↻</span>
          {t("analyze.another")}
        </button>
      </div>
    </div>
  );
}
