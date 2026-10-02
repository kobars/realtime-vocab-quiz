// AI-ASSISTED: Vitest runs the app's tests and each workspace package's own project, all in happy-dom with the Vue plugin.
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    projects: [
      {
        plugins: [vue()],
        resolve: { alias: { '@': '/src' } },
        // The join form's validation reads its display-name rules from the specs.
        server: { fs: { allow: ['.', '../docs/spec'] } },
        // The design-system guard reads the app's Tailwind entry as text.
        test: { name: 'app', environment: 'happy-dom', include: ['src/**/*.test.ts'], css: { include: [/main\.css/] } },
      },
      'packages/*',
    ],
    // make check runs with --coverage; the thresholds are the measured values, rounded down.
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,vue}', 'packages/*/src/**/*.{ts,vue}'],
      reporter: [['text', { skipFull: true }]],
      thresholds: { statements: 96, branches: 94, functions: 96, lines: 97 },
    },
  },
})
