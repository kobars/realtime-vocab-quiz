// AI-ASSISTED: ESLint flat config: typescript-eslint strict, a type-aware rule subset and eslint-plugin-vue recommended.
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import { defineConfig, globalIgnores } from 'eslint/config'
import tseslint from 'typescript-eslint'

export default defineConfig(
  globalIgnores(['**/dist/', '**/coverage/', 'src/contracts/generated/']),
  js.configs.recommended,
  tseslint.configs.strict,
  pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
    // vue-tsc already reports undefined names; core no-undef does not know the DOM globals.
    rules: { 'no-undef': 'off' },
  },
  {
    // A type-aware subset, not strictTypeChecked: unhandled union members and lost promises.
    files: ['src/**/*.{ts,vue}', 'e2e/**/*.ts', '*.config.ts', 'packages/*/{src,gallery}/**/*.{ts,vue}', 'packages/*/*.config.ts'],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      '@typescript-eslint/switch-exhaustiveness-check': 'error',
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': 'error',
      '@typescript-eslint/await-thenable': 'error',
    },
  },
  {
    // The app reaches the design system only through its public entry points, and never the libraries it wraps.
    files: ['src/**/*.{ts,vue}', 'e2e/**/*.ts'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [
          {
            group: ['@quiz/clay/*', '!@quiz/clay/tokens', '!@quiz/clay/testing', '**/packages/*', '**/packages/*/**'],
            message: 'Import the design system from @quiz/clay (or its /tokens and /testing entries), not from its files.',
          },
          {
            group: ['class-variance-authority', 'clsx', 'reka-ui', 'tailwind-merge', 'vue-sonner', 'vue-sonner/*'],
            message: 'Use the @quiz/clay component or helper that wraps this library.',
          },
        ],
      }],
    },
  },
  {
    // A consumer's bundler resolves `@` to its own source, so the package imports its files relatively.
    files: ['packages/*/{src,gallery}/**/*.{ts,vue}'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [{ group: ['@/*'], message: 'Import package files relatively; `@` is the app\'s alias.' }],
      }],
    },
  },
  {
    // Copied in by the shadcn-vue CLI: one-word names and optional props without defaults.
    files: ['packages/clay/src/components/**/*.vue'],
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/require-default-prop': 'off',
    },
  },
)
