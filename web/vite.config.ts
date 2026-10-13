import { defineConfig, searchForWorkspaceRoot } from "vite";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), fileURLToPath(new URL("../backend/app/core/plans.json", import.meta.url))] },
    host: "127.0.0.1",
    port: 5173,
    allowedHosts: ["localhost", "127.0.0.1"],
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // НЕ rewrite — оставляем /api префикс (бэкенд ожидает его)
      },
    },
  },
});
