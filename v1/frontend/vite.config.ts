import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Bind to 127.0.0.1 only — no network exposure per SPEC §2.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    passWithNoTests: true,
  },
});
