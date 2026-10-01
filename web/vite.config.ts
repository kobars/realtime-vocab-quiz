// AI-ASSISTED: Vite config: Vue, Tailwind, the `@` alias and the dev proxy for /api and /ws.
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  // One API node takes /api and /ws; QUIZ_API_URL points the dev server at another.
  const target = loadEnv(mode, '.', 'QUIZ_').QUIZ_API_URL?.trim() || 'http://127.0.0.1:8001'
  return {
    plugins: [vue(), tailwindcss()],
    resolve: { alias: { '@': '/src' } },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': { target, changeOrigin: true },
        '/ws': { target, changeOrigin: true, ws: true },
      },
    },
  }
})
