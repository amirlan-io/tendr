type Props = {
  label: string;
  value: string;
  note: string;
  accent?: "emerald" | "blue" | "gold";
};

const COLORS: Record<NonNullable<Props["accent"]>, string> = {
  emerald: "from-emerald-400/20 text-emerald-300",
  blue: "from-sky-400/20 text-sky-300",
  gold: "from-[#d6bb63]/20 text-[#d6bb63]",
};

export function StatCard({ label, value, note, accent = "emerald" }: Props) {
  return (
    <article className="relative overflow-hidden rounded-xl border border-white/[0.075] bg-[#121213]/90 p-5 transition hover:border-white/[0.14] hover:bg-[#151516]">
      <div
        aria-hidden
        className={`pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r ${COLORS[accent]} to-transparent opacity-25`}
      />
      <p className="relative text-xs text-white/35">{label}</p>
      <div className="relative mt-5 flex items-end justify-between gap-2">
        <strong className="font-mono text-3xl font-light tracking-[-.06em] text-white/90">
          {value}
        </strong>
        <span className="pb-1 text-right text-[10px] text-white/25">{note}</span>
      </div>
    </article>
  );
}
