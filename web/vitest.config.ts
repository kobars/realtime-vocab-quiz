// AI-ASSISTED: Vitest runs the client tests in happy-dom with the Vue plugin.
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': '/src' } },
  // The style tests read the UI spec's token table, tokens.css and main.css as text.
  server: { fs: { allow: ['.', '../docs/spec'] } },
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
    css: { include: [/(tokens|main)\.css/] },
    // make check runs with --coverage; the thresholds are the measured values, rounded down.
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,vue}'],
      reporter: [['text', { skipFull: true }]],
      thresholds: { statements: 96, branches: 94, functions: 96, lines: 97 },
    },
  },
})
