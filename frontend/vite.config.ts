import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The dashboard talks to the FastAPI backend. In development Vite proxies the
// API paths so the browser sees one origin; in the container the built assets
// are served by nginx, which proxies the same paths (see docker/nginx.conf).
//
// VITE_API_BASE_URL overrides this with an absolute URL when the API lives
// somewhere the proxy cannot reach.
const API_PROXY_TARGET = process.env.VITE_DEV_API_TARGET ?? 'http://localhost:8000'

const API_PATHS = [
  '/tickets',
  '/workflows',
  '/approvals',
  '/metrics',
  '/health',
]

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((path) => [path, { target: API_PROXY_TARGET, changeOrigin: true }]),
    ),
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
