// AI-ASSISTED: Vite serves and builds the component gallery (index.html, gallery/) on its own port, next to the app's 5173.
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: { port: 5180, strictPort: true },
  preview: { port: 5180, strictPort: true },
})
