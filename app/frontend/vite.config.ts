import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const backendPort = process.env.VITE_BACKEND_PORT ?? '8000'

// Lets the UI start the backend when it's down. The dev server is always up
// (it serves the UI), so it's the one process that can spawn a dead backend.
// Reached at POST /__yapoc/start (not under /api, so it is NOT proxied to :8000).
function backendControlPlugin(): Plugin {
  const projectRoot = fileURLToPath(new URL('../..', import.meta.url))
  return {
    name: 'yapoc-backend-control',
    configureServer(server) {
      server.middlewares.use('/__yapoc/start', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405
          res.end(JSON.stringify({ error: 'POST only' }))
          return
        }
        try {
          // `poetry run yapoc start` forks uvicorn (detached) and returns; it
          // also cleans up orphaned uvicorns first. shell:true → resolve poetry
          // from the user's PATH.
          const child = spawn('poetry run yapoc start', {
            cwd: projectRoot,
            shell: true,
            detached: true,
            stdio: 'ignore',
          })
          child.unref()
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ status: 'starting' }))
        } catch (e) {
          res.statusCode = 500
          res.end(JSON.stringify({ error: String(e) }))
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), backendControlPlugin()],
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
