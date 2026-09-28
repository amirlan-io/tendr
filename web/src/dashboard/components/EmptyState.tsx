import { Link } from "react-router-dom";

type Props = {
  title: string;
  text: string;
  actionTo?: string;
  actionLabel?: string;
};

/** Честное пустое состояние: без фейковых данных и рабочих обещаний. */
export function EmptyState({ title, text, actionTo, actionLabel }: Props) {
  return (
    <div className="flex min-h-[180px] flex-col items-center justify-center px-6 py-10 text-center">
      <span
        aria-hidden
        className="flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-400/15 bg-emerald-400/[0.06]"
      >
        <svg
          width={20}
          height={20}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.7}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-emerald-300"
        >
          <path d="m12 3 1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6L12 3Z" />
        </svg>
      </span>
      <h2 className="mt-5 text-base font-medium text-white">{title}</h2>
      <p className="mt-2 max-w-sm text-sm leading-6 text-white/35">{text}</p>
      {actionTo && actionLabel && (
        <Link
          to={actionTo}
          className="mt-5 rounded-lg px-2 py-1 text-sm font-medium text-emerald-300 hover:text-emerald-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
        >
          {actionLabel}
        </Link>
      )}
    </div>
  );
}
