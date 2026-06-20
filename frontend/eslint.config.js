// ESLint flat config for next-gen frontend (ESLint 9.x).
//
// PR1 ships a permissive built-in-only config so that lint runs without devDep
// installation. The full TypeScript/React/Hooks/Prettier rule set is added in
// PR3 when @eslint/js, typescript-eslint, eslint-plugin-react-hooks,
// eslint-plugin-react-refresh, and eslint-config-prettier are installed as
// devDependencies. See openspec/changes/ci-cd-pipeline/tasks.md T1.4 and T3.1.

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
  {
    files: ["**/*.{js,jsx,ts,tsx,cjs,mjs}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        window: "readonly",
        document: "readonly",
        console: "readonly",
        navigator: "readonly",
        fetch: "readonly",
        URL: "readonly",
        URLSearchParams: "readonly",
        Event: "readonly",
        CustomEvent: "readonly",
        HTMLElement: "readonly",
        HTMLDivElement: "readonly",
        HTMLInputElement: "readonly",
        HTMLButtonElement: "readonly",
        HTMLFormElement: "readonly",
        File: "readonly",
        Blob: "readonly",
        FormData: "readonly",
        AbortController: "readonly",
        AbortSignal: "readonly",
        ResizeObserver: "readonly",
        IntersectionObserver: "readonly",
        MutationObserver: "readonly",
        localStorage: "readonly",
        sessionStorage: "readonly",
        location: "readonly",
        history: "readonly",
        requestAnimationFrame: "readonly",
        cancelAnimationFrame: "readonly",
        getComputedStyle: "readonly",
        crypto: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        process: "readonly",
        globalThis: "readonly",
      },
    },
    rules: {
      // Built-in ESLint rules only; permissive defaults for PR1.
      // TypeScript/React-specific rules are added in PR3 when devDeps land.
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "no-undef": "error",
      "no-console": "warn",
      "prefer-const": "warn",
      eqeqeq: ["error", "always"],
      "no-var": "error",
    },
  },
];
