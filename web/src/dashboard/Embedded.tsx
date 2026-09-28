import { createContext, useContext, type ReactNode } from "react";
import { Layout } from "../Layout";

const EmbedContext = createContext(false);

/** true внутри DashboardLayout: страница рисуется без landing-обёртки. */
export function useEmbedded(): boolean {
  return useContext(EmbedContext);
}

export function EmbedProvider({ children }: { children: ReactNode }) {
  return <EmbedContext.Provider value>{children}</EmbedContext.Provider>;
}

/**
 * Обёртка для переиспользования существующих страниц внутри dashboard.
 * Standalone-маршруты рисуют landing-Layout, вложенные — только контент,
 * без дублирования логики страниц.
 */
export function LayoutOrEmbed({
  embedded,
  children,
}: {
  embedded: boolean;
  children: ReactNode;
}) {
  if (embedded) return <>{children}</>;
  return <Layout>{children}</Layout>;
}
