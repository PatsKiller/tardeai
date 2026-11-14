import { test, expect, type Page } from '@playwright/test'

// OBS-H1 (operator, live Chrome, 2026-11-14): the shared header drew generic card labels as tracked ENTITIES —
// "Review BHVN (private)", "WATCH Card (private)", "Risk (private)" — each linking the BHVN thread. The rows are real
// ledger history (a pasted card's headings minted as name-only private entities and auto-tracked), so the fix is in the
// projection + the chip rule: only a typed identity (symbol / account / thread) becomes a chip.
//
// This spec feeds /api/v2/cio/asks/tracked synthetic rows of exactly that shape and asserts what the header NAMES.
// Every /api read is intercepted; live :7777 traffic fails the test.
//
//   npx vite build && npx vite preview --port 4183 &
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4183 npx playwright test e2e/header-tracked-chips.spec.ts --workers=1

const TRACKED = {
  ok: true,
  data: {
    tracked: [
      // the operator's real tracked security (the thread link must stay on it)
      { thread_id: 'thr_bhvn', key: 'sec_bhvn', symbol: 'BHVN', name: 'BHVN', kind: 'security', tracking: 'tracked' },
      // the card chrome, as the ledger tracked it
      { thread_id: 'thr_bhvn', key: 'ent_review', symbol: null, name: 'Review BHVN', kind: 'private_entity', tracking: 'tracked' },
      { thread_id: 'thr_bhvn', key: 'ent_watch', symbol: null, name: 'WATCH Card', kind: 'private_entity', tracking: 'tracked' },
      { thread_id: 'thr_bhvn', key: 'ent_risk', symbol: null, name: 'Risk', kind: 'private_entity', tracking: 'tracked' },
      // typed account / thread rows still chip
      { thread_id: 'thr_acct', key: 'ent_acct_1', name: 'Schwab Roth', kind: 'account', tracking: 'tracked' },
      { thread_id: 'thr_thr', key: 'ent_thread_1', name: 'BHVN thread', kind: 'thread', tracking: 'tracked' },
    ],
    status: 'OK',
  },
}

async function headerReads(page: Page) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.port === '7777') throw new Error('Live API traffic is forbidden')
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (route.request().method() !== 'GET') return route.abort()
    if (url.pathname === '/api/v2/cio/asks/tracked') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TRACKED) })
    }
    // Every other read: an empty successful body. This spec is about the chip rule, not any card's data.
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: {} }) })
  })
}

test('the shared header names typed tracked identities only', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await headerReads(page)
  await page.goto('/v3/')
  const strip = page.getByTestId('ask-cio-tracked')
  await expect(strip).toBeVisible()
  // Only the typed rows are chips: the symbol, the account, the thread.
  await expect(strip.getByRole('link')).toHaveText(['BHVN', 'Schwab Roth', 'BHVN thread'])
  // The card chrome is never an entity chip.
  for (const label of ['Review BHVN', 'WATCH Card', 'Risk']) {
    await expect(strip.getByText(label, { exact: true })).toHaveCount(0)
  }
  // "Keep the thread context": the BHVN chip opens the thread BHVN was asked in.
  await expect(strip.getByRole('link', { name: 'BHVN', exact: true })).toHaveAttribute('href', /thr_bhvn/)
})
