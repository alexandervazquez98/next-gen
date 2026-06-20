// ESLint flat config for next-gen frontend (ESLint 9.x).
//
// DevDependency installation is finalized in PR3. The lint/format scripts in
// package.json use `pnpm dlx` to run pinned versions without touching the lockfile.
// See openspec/changes/ci-cd-pipeline/tasks.md T1.4.

import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import prettier from "eslint-config-prettier";

export default [
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "build/**",
      ".next/**",
      "coverage/**",
      "playwright-report/**",
      "test-results/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        // Browser globals common to this React 19 codebase
        window: "readonly", document: "readonly", console: "readonly",
        navigator: "readonly", fetch: "readonly", URL: "readonly",
        URLSearchParams: "readonly", Event: "readonly", CustomEvent: "readonly",
        HTMLElement: "readonly", HTMLDivElement: "readonly",
        HTMLInputElement: "readonly", HTMLButtonElement: "readonly",
        HTMLFormElement: "readonly", File: "readonly", Blob: "readonly",
        FormData: "readonly", AbortController: "readonly", AbortSignal: "readonly",
        ResizeObserver: "readonly", IntersectionObserver: "readonly",
        MutationObserver: "readonly", localStorage: "readonly",
        sessionStorage: "readonly", location: "readonly", history: "readonly",
        requestAnimationFrame: "readonly", cancelAnimationFrame: "readonly",
        getComputedStyle: "readonly", crypto: "readonly",
        setTimeout: "readonly", clearTimeout: "readonly",
        setInterval: "readonly", clearInterval: "readonly",
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // Permissive defaults for PR1 — tightened in PR3 once legacy files are swept.
      "@typescript-eslint/no-empty-object-type": "off",
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      "no-unused-vars": "off",
      "no-empty": ["error", { allowEmptyCatch: true }],
    },
  },
  prettier,
];
