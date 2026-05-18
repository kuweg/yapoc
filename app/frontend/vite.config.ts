import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backendPort = process.env.VITE_BACKEND_PORT ?? '8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
        // Strip /api so frontend `/api/foo` hits the backend's `/foo` route.
        // All FastAPI routers (tasks, agents, voice, etc.) are mounted at
        // root; this rewrite keeps the frontend's `/api/*` convention without
        // requiring every backend router to add an explicit prefix.
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // WebSocket proxy. Without this, useWebSocket connects to
      // ws://localhost:5173/ws (the Vite dev server) which has no
      // matching route — Vite either returns its catch-all HTML or
      // collides with its HMR socket. Result: the connection upgrade
      // fails immediately and the page can get stuck in a tight
      // reconnect loop on refresh.
      '/ws': {
        target: `ws://127.0.0.1:${backendPort}`,
        ws: true,
        changeOrigin: true,
      },
    },
    watch: {
      ignored: ['**/data/**'],
    },
  },
})
