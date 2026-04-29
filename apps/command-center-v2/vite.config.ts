import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/v2/',
  server: {
    port: 7788,
    host: '0.0.0.0',
    proxy: {
      '/api': 'http://127.0.0.1:7777',
      '/data': 'http://127.0.0.1:7777',
      '/config': 'http://127.0.0.1:7777',
      '/reports': 'http://127.0.0.1:7777',
    },
  },
})
