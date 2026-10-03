import { defineConfig } from '@playwright/test'

/**
 * LIVE CURRENT browser acceptance. Intercepts nothing: every /api call reaches
 * the served host. Post-deploy only (PR CI has no server). Run through
 * scripts/live_cio_browser_acceptance.sh, which also records the server's
 * process identity, restarts and RSS around the run.
 *
 *   LIVE_BASE_URL=http://localhost:7777 EXPECTED_SHA=<CURRENT GIT_SHA> \
 *     npx playwright test -c playwright.live.config.ts
 */
export default defineConfig({
  testDir: './e2e-live',
  timeout: 150_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['line']],
  use: {
    baseURL: process.env.LIVE_BASE_URL || 'http://localhost:7777',
    trace: 'off',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
