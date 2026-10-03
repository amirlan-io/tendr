import {
  ArrowUp,
  FileText,
  Paperclip,
  Sparkles,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";

type ComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onAttach: () => void;
  onRemoveFile: () => void;
  file: File | null;
  disabled?: boolean;
};

export function TendrChatComposer({
  value,
  onChange,
  onSubmit,
  onAttach,
  onRemoveFile,
  file,
  disabled = false,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "56px";
    element.style.height = `${Math.min(180, Math.max(56, element.scrollHeight))}px`;
  }, []);

  useEffect(() => resize(), [resize, value]);

  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!disabled && (value.trim() || file)) onSubmit();
    }
  };

  return (
    <div className="rounded-[22px] border border-white/[0.11] bg-[#111213] p-2 shadow-[0_24px_70px_-34px_rgba(0,0,0,.95)] transition focus-within:border-emerald-400/30 focus-within:shadow-[0_24px_80px_-34px_rgba(16,185,129,.2)]">
      {file && (
        <div className="mx-2 mt-2 flex items-center gap-3 rounded-xl border border-emerald-400/15 bg-emerald-400/[0.06] px-3 py-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-400/10 text-emerald-300">
            <FileText size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-white/80">{file.name}</p>
            <p className="mt-0.5 text-[10px] text-white/35">{(file.size / 1024 / 1024).toFixed(2)} МБ</p>
          </div>
          <button type="button" onClick={onRemoveFile} aria-label="Убрать выбранный файл" className="rounded-lg p-1.5 text-white/35 transition hover:bg-white/[0.06] hover:text-white">
            <X size={15} />
          </button>
        </div>
      )}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={keyDown}
        disabled={disabled}
        aria-label="Анализ лота"
        placeholder="Пришлите ссылку на лот или задайте вопрос по разбору…"
        className="block min-h-14 w-full resize-none overflow-y-auto bg-transparent px-4 py-3 text-[15px] leading-6 text-white outline-none placeholder:text-white/28 disabled:cursor-not-allowed disabled:opacity-50"
      />
      <div className="flex items-center justify-between px-2 pb-1 pt-1">
        <button type="button" onClick={onAttach} disabled={disabled} className="group inline-flex h-9 items-center gap-2 rounded-xl px-2.5 text-white/40 transition hover:bg-white/[0.055] hover:text-white disabled:opacity-35">
          <Paperclip size={17} />
          <span className="hidden text-xs sm:inline">Прикрепить</span>
        </button>
        <div className="flex items-center gap-3">
          <span className="hidden text-[10px] text-white/25 sm:inline">Enter — отправить · Shift+Enter — строка</span>
          <button
            type="button"
            onClick={onSubmit}
            disabled={disabled || (!value.trim() && !file)}
            aria-label="Анализировать"
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-400 text-[#07110d] transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:bg-white/[0.07] disabled:text-white/25"
          >
            {disabled ? <Sparkles className="animate-pulse" size={17} /> : <ArrowUp size={18} strokeWidth={2.3} />}
          </button>
        </div>
      </div>
    </div>
  );
}

export function AssistantBubble({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/[0.1] text-xs font-semibold text-emerald-300 shadow-[0_0_24px_rgba(16,185,129,.08)]">T</div>
      <div className="min-w-0 max-w-[880px] flex-1">{children}</div>
    </div>
  );
}

export function UserBubble({ children }: { children: ReactNode }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[78%] whitespace-pre-wrap rounded-[18px] rounded-br-md border border-white/[0.08] bg-white/[0.075] px-4 py-3 text-sm leading-6 text-white/80">
        {children}
      </div>
    </div>
  );
}
