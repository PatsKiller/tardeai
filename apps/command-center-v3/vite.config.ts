import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

const UI_VERSION = '3.10'

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'build-meta',
      closeBundle() {
        // ui_version drives the server's forced client-reload (portfolio_server injects a check
        // vs sessionStorage). It MUST change every build or browsers never auto-pick-up a new
        // bundle — append a per-build stamp so every deploy triggers a one-time reload.
        const stamp = Date.now().toString(36)
        const meta = { ui_version: `${UI_VERSION}+${stamp}`, base_version: UI_VERSION, built_at: new Date().toISOString() }
        fs.writeFileSync(
          path.resolve(__dirname, 'dist/build-meta.json'),
          JSON.stringify(meta, null, 2),
        )
      },
    },
  ],
  define: {
    __ANALYST_UI_VERSION__: JSON.stringify(UI_VERSION),
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
