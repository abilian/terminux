// Style enforcement only (formatting itself is prettier's job): 1TBS —
// every control-flow body gets braces, opening brace on the same line.
// Prettier already handles brace placement; `curly` adds the mandatory
// braces prettier deliberately leaves alone.
import tseslint from "typescript-eslint";

export default [
  {
    files: ["src/**/*.{ts,tsx}", "test/**/*.ts"],
    languageOptions: { parser: tseslint.parser },
    rules: {
      curly: ["error", "all"],
      "brace-style": ["error", "1tbs"],
    },
  },
];
