/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], globals: true, include: ["src/**/*.test.{ts,tsx}"] },
});
