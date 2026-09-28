type Props = {
  lines?: number;
  className?: string;
};

/** Скелетон загрузки: нейтральные блоки вместо прыгающего layout. */
export function Skeleton({ lines = 3, className = "" }: Props) {
  return (
    <div role="status" aria-label="Загрузка данных" className={`space-y-3 ${className}`}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="h-16 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.03]"
        />
      ))}
      <span className="sr-only">Загрузка…</span>
    </div>
  );
}
