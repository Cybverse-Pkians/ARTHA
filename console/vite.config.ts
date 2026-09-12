import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The console talks to the ARTHA decision service. In a bank deployment both are
// served from the same origin; in development the API runs on :8000 and this
// proxy keeps the client code origin-agnostic.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
