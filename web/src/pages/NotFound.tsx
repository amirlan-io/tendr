import { Link } from "react-router-dom";
import { Layout } from "../Layout";

export function NotFoundPage() {
  return (
    <Layout>
      <div className="max-w-md mx-auto px-6 py-24 text-center">
        <div className="text-6xl font-bold tracking-tight text-[var(--text-muted)]">
          404
        </div>
        <h1 className="text-xl font-semibold mt-4 mb-2">
          Страница не найдена
        </h1>
        <p className="text-sm text-[var(--text-muted)] mb-8">
          Такой страницы нет. Возможно, ссылка устарела или в ней опечатка.
        </p>
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-medium text-white"
          style={{ background: "var(--accent)" }}
        >
          ← На главную
        </Link>
      </div>
    </Layout>
  );
}
