import { test, expect, type Page } from '@playwright/test'
test.use({ hasTouch: true })

// Protective SELL-stop drafts read as SELL … STOP (page audit 2026-10-25: they showed "BUY … STOP" with
// "NO STOP — risk undefined"). Display only. Synthetic fixture inputs; every /api request is intercepted,
// non-GET requests are aborted and live :7777 traffic fails the test.
const protective = {
  intent_id: 'fixture-protective-1', broker: 'schwab', symbol: 'FIXA', state: 'draft', updated_at: '2026-10-24T16:20:00Z',
  intent_json: {
    instrument: { symbol: 'FIXA' }, direction: 'LONG', entry: { method: 'STOP', stop_price: 101.25 },
    quantity: { qty: 7 }, broker: 'schwab', account_key: 'fixture_account', tif: 'GTC',
    meta: { strategy_id: 'PROTECTIVE_STOP_2C', created_by: 'operator', thesis: 'Fixture protective STOP on held FIXA',
      signal_evidence: { instruction: 'SELL', order_type: 'STOP', stop_price: 101.25 } },
  },
}
const entryDraft = {
  intent_id: 'fixture-entry-1', broker: 'schwab', symbol: 'FIXB', state: 'draft', updated_at: '2026-10-24T16:20:00Z',
  intent_json: { instrument: { symbol: 'FIXB' }, direction: 'LONG', entry: { method: 'LIMIT', limit_price: 20 },
    quantity: { qty: 5 }, account_key: 'fixture_account', tif: 'DAY', meta: { thesis: 'Fixture entry draft' } },
}

async function fixtures(page: Page) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.port === '7777') throw new Error('Live API traffic is forbidden')
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (route.request().method() !== 'GET') return route.abort()
    if (url.pathname === '/api/v2/broker-orders/drafts') return route.fulfill({ status: 200, json: { ok: true, data: { drafts: [protective, entryDraft] } } })
    return route.fulfill({ status: 200, json: {} })
  })
}

const size = (width: number) => ({ width, height: width === 412 ? 915 : width === 390 ? 844 : 1000 })

for (const width of [1440, 412, 390]) {
  test(`manual desk: protective stop draft reads SELL STOP ${width}`, async ({ page }) => {
    await page.setViewportSize(size(width))
    await fixtures(page)
    await page.goto('/v3/trading?tab=Proposals&section=path-a')
    const row = page.getByTestId('entry-desk-row').filter({ hasText: 'FIXA' }).first()
    await expect(row).toBeVisible()
    await expect(row).toContainText('SELL 7 FIXA STOP 101.25 GTC — protective stop')
    await expect(row.getByTestId('entry-desk-protective')).toHaveText('protective SELL STOP 101.25')
    const text = await row.innerText()
    expect(text).not.toMatch(/BUY 7 FIXA/)
    expect(text).not.toContain('NO STOP')
    const entry = page.getByTestId('entry-desk-row').filter({ hasText: 'FIXB' }).first()
    await expect(entry).toContainText('BUY 5 FIXB LIMIT 20.00 DAY')
  })
}
