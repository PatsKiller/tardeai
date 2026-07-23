import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Separate bundle, separate route base. /v3 (command-center-v3) is untouched.
export default defineConfig({
  base: '/v3-next/',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 7790, // distinct from /v3 dev (7789); loopback only
    host: '127.0.0.1',
    proxy: { '/api/v3': 'http://127.0.0.1:8134' }, // Stage 4 read API (manual/off by default)
  },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
});
