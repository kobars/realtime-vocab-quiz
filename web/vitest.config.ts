// AI-ASSISTED: Vitest runs the client tests in happy-dom with the Vue plugin.
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': '/src' } },
  // The token test reads the UI spec's token table and tokens.css as text.
  server: { fs: { allow: ['.', '../docs/spec'] } },
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
    css: { include: [/tokens\.css/] },
  },
})
