import { defineConfig } from '@playwright/test'

/**
 * Smoke tests for Command Center v3 portfolio UX.
 * Expects the app served at baseURL (default: vite preview or local CC).
 *
 *   npx playwright install chromium
 *   npm run build && npm run preview -- --port 4173 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173/v3 npm run test:e2e
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  fullyParallel: false,
  retries: 0,
  use: {
    // Origin only — app is mounted at /v3/ (vite base). Paths must include /v3/.
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
