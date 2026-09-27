/// <reference types="vitest" />
import path from "path";
import { fileURLToPath } from "url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    server: {
      port: 3000,
      host: "0.0.0.0",
      proxy: {
        "/api": {
          target: process.env.VITE_API_TARGET || "http://nexgen_backend:8000",
          changeOrigin: true,
          secure: false,
        },
      },
    },
    plugins: [react()],
    optimizeDeps: {
      // `maplibre-gl` ships its own worker ESM at `maplibre-gl-worker.mjs`.
      // Vite's default pre-bundling step cannot follow that worker file and
      // ends up producing an empty optimize-deps bundle, which manifests at
      // runtime as `The file does not exist at
      // "/app/node_modules/.vite/deps/maplibre-gl-worker.mjs"`. Excluding
      // the package from pre-bundling lets the browser load the worker
      // directly from node_modules. This is the documented Vite workaround
      // for the same pattern in MapLibre's own issues.
      exclude: ["maplibre-gl"],
    },
    define: {
      "process.env.API_KEY": JSON.stringify(env.GEMINI_API_KEY),
      "process.env.GEMINI_API_KEY": JSON.stringify(env.GEMINI_API_KEY),
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "."),
      },
    },
    test: {
      forbidOnly: true,
      globals: true,
      environment: "jsdom",
      setupFiles: ["./test/setup.ts"],
      include: ["**/*.test.{ts,tsx}"],
      coverage: {
        provider: "v8",
        reporter: ["text", "lcov"],
        include: ["**/*.{ts,tsx}"],
        exclude: ["test/**", "node_modules/**", "dist/**", "**/*.d.ts", "**/*.config.*"],
      },
    },
  };
});
