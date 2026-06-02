import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
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
