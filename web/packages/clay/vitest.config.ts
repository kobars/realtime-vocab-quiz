// AI-ASSISTED: Vitest runs the design-system tests in happy-dom; the root config runs this project next to the app's.
import vue from '@vitejs/plugin-vue'
import { defineProject } from 'vitest/config'

export default defineProject({
  plugins: [vue()],
  // The token tests read the UI spec's token table, tokens.css and theme.css as text.
  server: { fs: { allow: ['.', '../../../docs/spec'] } },
  test: {
    name: 'clay',
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
    css: { include: [/(tokens|theme|fonts)\.css/] },
  },
})
