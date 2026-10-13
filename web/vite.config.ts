import { defineConfig, searchForWorkspaceRoot } from "vite";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";

const apiPort = Number(process.env.TENDR_API_PORT ?? "8000");
if (!Number.isInteger(apiPort) || apiPort < 1 || apiPort > 65535) {
  throw new Error("TENDR_API_PORT must be a valid port number");
}

export default defineConfig({
  plugins: [react()],
  server: {
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), fileURLToPath(new URL("../backend/app/core/plans.json", import.meta.url))] },
    host: "127.0.0.1",
    port: 5173,
    allowedHosts: ["localhost", "127.0.0.1"],
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${apiPort}`,
        changeOrigin: true,
        // НЕ rewrite — оставляем /api префикс (бэкенд ожидает его)
      },
    },
  },
});
