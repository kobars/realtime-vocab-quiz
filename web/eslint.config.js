// AI-ASSISTED: ESLint flat config: typescript-eslint strict and eslint-plugin-vue recommended.
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import { defineConfig, globalIgnores } from 'eslint/config'
import tseslint from 'typescript-eslint'

export default defineConfig(
  globalIgnores(['dist/', 'coverage/', 'src/contracts/generated/']),
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
    // Copied in by the shadcn-vue CLI: one-word names and optional props without defaults.
    files: ['src/components/ui/**/*.vue'],
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/require-default-prop': 'off',
    },
  },
)
