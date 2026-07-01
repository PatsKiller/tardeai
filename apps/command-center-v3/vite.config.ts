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
        const meta = { ui_version: UI_VERSION, built_at: new Date().toISOString() }
        fs.writeFileSync(
          path.resolve(__dirname, 'dist/build-meta.json'),
          JSON.stringify(meta, null, 2),
        )
      },
    },
  ],
  define: {
    __ANALYST_UI_VERSION__: JSON.stringify(UI_VERSION),
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
