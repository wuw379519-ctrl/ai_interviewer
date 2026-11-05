import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/node_modules/**",
      "**/.venv*/**",
      "**/__pycache__/**",
      "**/.mypy_cache/**",
      "**/.pytest_cache/**",
      "**/.ruff_cache/**",
      "**/.next/**",
      "**/.next-*/**",
      "**/dist/**",
      "**/coverage/**",
      "**/migrations/**",
      "**/.data/**",
      "**/test-results/**",
      "**/playwright-report/**",
      "**/*.config.mjs",
      "**/next-env.d.ts",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["apps/practice/*.js"],
    languageOptions: {
      globals: { document: "readonly", window: "readonly", sessionStorage: "readonly", crypto: "readonly",
        fetch: "readonly", FormData: "readonly" },
    },
  },
  {
    files: ["**/*.ts", "**/*.tsx"],
    languageOptions: {
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: "module",
      },
    },
    rules: {
      // 规格硬性要求：禁止 any
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/consistent-type-imports": ["error", { prefer: "type-imports" }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "no-console": "off",
      eqeqeq: ["error", "always"],
    },
  },
  {
    files: ["**/*.test.ts", "**/*.test.tsx", "**/scripts/**"],
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
);
