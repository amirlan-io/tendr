import { FormEvent, useEffect, useState } from "react";
import { Bot, ExternalLink, Send, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { api, ApiError } from "../../clientId";
import { useModalFocus } from "../../hooks/useModalFocus";

type DockMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions?: Array<{ label: string; href: string }>;
};

const STORAGE_KEY = "tendr_assistant_dock:v1";

function cleanText(value: string): string {
  return value
    .replace(/^[ \t]*#{1,6}[ \t]*/gm, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/^[ \t]*[-*][ \t]+/gm, "• ")
    .replace(/```|`|\*/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function loadMessages(): DockMessage[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.slice(-12) : [];
  } catch {
    return [];
  }
}

function id(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function AssistantDock() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<DockMessage[]>(loadMessages);
  const dialogRef = useModalFocus<HTMLElement>(open, () => setOpen(false));

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-12)));
  }, [messages]);

  if (location.pathname === "/dashboard/analyze") return null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const question = value.trim();
    if (!question || busy) return;
    const userMessage: DockMessage = { id: id(), role: "user", content: question };
    const history = messages.slice(-8).map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, userMessage]);
    setValue("");
    setBusy(true);
    setError(null);
    try {
      const response = await api<{ answer: string; actions?: Array<{ label: string; href: string }> }>("/api/lots/assistant/chat", {
        method: "POST",
        body: JSON.stringify({ message: question, history, page_path: location.pathname }),
      });
      setMessages((current) => [...current, { id: id(), role: "assistant", content: response.answer, actions: response.actions }]);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Помощник временно недоступен.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Открыть помощника Tendr"
        className="fixed bottom-20 right-4 z-50 flex h-12 items-center gap-2 rounded-2xl border border-emerald-300/25 bg-[#111313] px-4 text-xs font-semibold text-emerald-200 shadow-[0_18px_50px_rgba(0,0,0,.55)] transition hover:-translate-y-0.5 hover:bg-[#151918] sm:bottom-6 sm:right-6"
      >
        <Bot size={17} /> Спросить Tendr
      </button>

      {open && (
        <div className="fixed inset-0 z-[80] bg-black/55 backdrop-blur-[2px]" onMouseDown={(event) => { if (event.currentTarget === event.target) setOpen(false); }}>
        <section ref={dialogRef} role="dialog" aria-modal="true" aria-label="Помощник Tendr" className="fixed bottom-3 right-3 flex h-[min(620px,calc(100vh-24px))] w-[min(390px,calc(100vw-24px))] flex-col overflow-hidden rounded-2xl border border-white/[0.1] bg-[#0d0d0e] shadow-[0_28px_90px_rgba(0,0,0,.75)]">
          <header className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3.5">
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-400/[0.1] text-emerald-300"><Bot size={16} /></span>
              <div><h2 className="text-sm font-semibold text-white">Помощник Tendr</h2><p className="mt-0.5 text-xs text-white/55">Знает текущий раздел</p></div>
            </div>
            <button type="button" onClick={() => setOpen(false)} aria-label="Закрыть помощника" className="flex h-11 w-11 items-center justify-center rounded-lg text-white/55 hover:bg-white/[0.05] hover:text-white"><X size={17} /></button>
          </header>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
            {messages.length === 0 && (
              <div className="rounded-xl border border-white/[0.065] bg-white/[0.02] p-4 text-xs leading-5 text-white/42">
                Спросите, что делать на этой странице, где найти функцию или какой следующий шаг по закупке.
              </div>
            )}
            {messages.map((message) => (
              <div key={message.id} className={message.role === "user" ? "ml-8 rounded-xl bg-white/[0.075] px-3.5 py-3 text-xs leading-5 text-white/75" : "mr-3 text-xs leading-5 text-white/62"}>
                <div className="whitespace-pre-wrap">{message.role === "assistant" ? cleanText(message.content) : message.content}</div>
                {message.actions?.length ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {message.actions.filter((action) => /^\/dashboard(?:\/|$)/.test(action.href)).slice(0, 2).map((action) => (
                      <Link key={action.href} to={action.href} onClick={() => setOpen(false)} className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-400/20 bg-emerald-400/[0.07] px-2.5 py-1.5 text-[10px] font-medium text-emerald-200"><ExternalLink size={11} />{action.label}</Link>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
            {busy && <p className="text-xs text-white/30">Думаю…</p>}
            {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
          </div>

          <form onSubmit={(event) => void submit(event)} className="border-t border-white/[0.07] p-3">
            <div className="flex items-end gap-2 rounded-xl border border-white/[0.09] bg-white/[0.025] p-2">
              <textarea value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} rows={2} placeholder="Спросите о странице или закупке…" className="min-h-10 flex-1 resize-none bg-transparent px-1.5 py-1 text-xs leading-5 text-white outline-none placeholder:text-white/25" />
              <button type="submit" disabled={!value.trim() || busy} aria-label="Отправить вопрос" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-400 text-[#062016] disabled:opacity-35"><Send size={14} /></button>
            </div>
          </form>
        </section>
        </div>
      )}
    </>
  );
}
