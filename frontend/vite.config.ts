import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend defaults to :8000. Override with VITE_API_TARGET when running it
// on another port.
const API_TARGET = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
})
