import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  if (process.env.VERCEL === '1') {
    const apiBase = loadEnv(mode, process.cwd(), 'VITE_').VITE_API_BASE
    if (!apiBase) throw new Error('Set VITE_API_BASE to the hosted HTTPS API URL ending /api/v1 before deploying.')
    const url = new URL(apiBase)
    if (url.protocol !== 'https:' || url.pathname !== '/api/v1' || url.username || url.password || url.search || url.hash) {
      throw new Error('VITE_API_BASE must be an HTTPS URL ending exactly /api/v1, without credentials, query or fragment.')
    }
  }
  return {
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.BACKEND_PROXY ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  }
})
