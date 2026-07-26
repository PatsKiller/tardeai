import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// 3.14 = MetricStrip STALE parity + unprotected taxonomy + Operator Inbox plain language
const UI_VERSION = '3.14'
// Single stamp per build — must match build-meta.json or AnalystReportsPanel false-positives "stale".
const BUILD_STAMP = Date.now().toString(36)
const FULL_UI_VERSION = `${UI_VERSION}+${BUILD_STAMP}`

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'build-meta',
      closeBundle() {
        // ui_version drives the server's forced client-reload (portfolio_server injects a check
        // vs sessionStorage). It MUST change every build or browsers never auto-pick-up a new
        // bundle — append a per-build stamp so every deploy triggers a one-time reload.
        const meta = {
          ui_version: FULL_UI_VERSION,
          base_version: UI_VERSION,
          built_at: new Date().toISOString(),
          release_notes: 'home-inbox-parity: MetricStrip STALE, No-stop gauge taxonomy, Operator Inbox plain language',
        }
        fs.writeFileSync(
          path.resolve(__dirname, 'dist/build-meta.json'),
          JSON.stringify(meta, null, 2),
        )
      },
    },
  ],
  define: {
    __ANALYST_UI_VERSION__: JSON.stringify(FULL_UI_VERSION),
    __BUILD_DATE__: JSON.stringify(new Date().toISOString().slice(0, 10)),
  },
  base: '/v3/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 7789,
    host: '0.0.0.0',
    proxy: {
      '/api': 'http://127.0.0.1:7777',
    },
  },
})
