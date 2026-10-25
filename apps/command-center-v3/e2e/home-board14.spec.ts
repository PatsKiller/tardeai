/** Board 14 Home display. Synthetic fixtures only. No production calls.
 *
 *   npm run build && npm run preview -- --port 4189 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4189 npx playwright test e2e/home-board14.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'

test.use({ hasTouch: true })

const PHRASE = 'Market closed · last broker sync Fri 16:52 ET · next Mon 09:07 ET'

function payload() {
  return {
    conflicts: { findings: [] },
    portfolio: {
      positions_as_of: '2026-10-23T20:52:00Z',
      market_closed_phrase: PHRASE,
      sync_missed: false,
      gap: null,
    },
    do_now: {
      as_of: '2026-10-23T20:30:00Z',
      items: [
        {
          id: 'protection:taxable_a:SYM002',
          kind: 'STOP',
          symbol: 'SYM002',
          title: 'stop filled · awaiting holdings sync',
          why: 'Synthetic account',
          cta: 'Review protection',
          action: { label: 'Review protection', where: '/v3/risk' },
        },
        {
          id: 'protection:no-broker-stop',
          kind: 'REVIEW',
          symbol: '2 names',
          title: 'no broker stop',
          why: 'SYM001 ×2, SYM003',
          cta: 'See list',
          action: { label: 'See list', where: '/v3/risk' },
        },
      ],
    },
    stops: {
      active_count: 1, pending_count: 0, position_count: 3, awaiting_fill: [], awaiting_fill_count: 0,
      filled_awaiting_sync: [], nearest: { symbol: 'SYM004', distance_pct: 1.5 },
      last_broker_read_label: 'Fri 20:55 ET', stale: false, gap: null,
    },
    regime: {
      label: 'Fixture regime', vix: null, as_of: '2026-10-23T20:30:00Z',
      since_label: null, since_gap: 'Regime start is not in the fetched history',
      vix_gap: { reason: 'VIX input unavailable for classifier snapshot' }, gap: null,
    },
    sectors: { favoured: ['Fixture sector'] },
    approvals: { total: 2, gap: null },
    questions: { count: 3, gap: null },
    releases: { count: null, gap: { reason: 'Releases census receipt not published' } },
    jobs: { as_of: null, phrase: null, gap: { reason: 'Jobs monitor receipt not published' } },
  }
}

function overflowPayload() {
  const base = payload()
  const rows = Array.from({ length: 8 }, (_, i) => ({
    id: `protection:acct_${i + 1}:SYM${String(i + 1).padStart(3, '0')}`, kind: 'STOP', symbol: `SYM${String(i + 1).padStart(3, '0')}`,
    title: 'stop awaiting activation', why: 'Synthetic account', cta: 'Review protection', action: { label: 'Review protection', where: '/v3/risk' },
  }))
  const approval = { id: 'approvals:pending', kind: 'REVIEW', symbol: '', title: '3 approvals waiting', why: 'Review the typed approval queues',
    cta: 'Review approvals', action: { label: 'Review approvals', where: '/v3/trading?tab=Proposals' } }
  return { ...base, do_now: { ...base.do_now, items: [...rows.slice(0, 6), approval], all_items: [...rows, approval], total: 9, limit: 7, hidden_count: 2 } }
}

async function stub(page: Page, body: () => unknown = payload) {
  const writes: string[] = []
  await page.route('**/api/**', route => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    if (req.method() !== 'GET') { writes.push(`${req.method()} ${path}`); return route.abort() }
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/api/v2/cio/pages') return json({ ok: true, data: body() })
    if (path.startsWith('/api/v2/desk-sources')) return json({ ok: true, data: { observed_at: '2026-10-25T20:00:00Z', writers: [] } })
    return json({ ok: true, items: [], rows: [], data: {} })
  })
  return writes
}

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
  test(`Home Board 14 ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await stub(page)
    await page.goto('/v3/')
    await expect(page.getByTestId('desk-source-note').filter({ hasText: PHRASE })).toBeVisible()
    await expect(page.getByText('Jobs monitor receipt not published')).toBeVisible()
    await expect(page.getByTestId('home-do-now-kind').nth(0)).toHaveText('STOP')
    await expect(page.getByTestId('home-do-now-kind').nth(1)).toHaveText('REVIEW')
    await expect(page.getByTestId('home-regime')).toContainText('Fixture regime')
    await expect(page.getByTestId('home-regime')).toContainText('Regime start is not in the fetched history')
    await expect(page.getByTestId('home-regime')).toContainText('Not available')
    await expect(page.getByText('VIX input unavailable for classifier snapshot')).toBeVisible()
    await expect(page.getByTestId('home-questions-count')).toHaveText('3 new')
    await expect(page.getByTestId('home-releases-count')).toHaveText('Not available')
    await expect(page.getByText('Releases census receipt not published')).toBeVisible()
    const overflowX = await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)
    expect(overflowX).toBeLessThanOrEqual(1)
    if (width < 821) {
      const link = page.getByRole('link', { name: 'See list →' })
      const box = (await link.boundingBox())!
      expect(box.height).toBeGreaterThanOrEqual(44)
      await link.tap()
      await expect(page).toHaveURL(/\/v3\/risk/)
    }
    expect(writes).toEqual([])
  })
}

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
  test(`Home Do now shows +N more and keeps approvals ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await stub(page, overflowPayload)
    await page.goto('/v3/')
    await expect(page.getByTestId('home-do-now-row')).toHaveCount(7)
    await expect(page.getByTestId('home-do-now-row').last()).toContainText('3 approvals waiting')
    await expect(page.getByTestId('home-do-now')).toContainText('top 7 of 9')
    await expect(page.getByRole('link', { name: 'Releases to merge' })).toHaveAttribute('href', '/v3/system/releases')
    const more = page.getByTestId('home-do-now-more')
    await expect(more).toHaveText(/\+2 more/)
    const box = (await more.boundingBox())!
    expect(box.height).toBeGreaterThanOrEqual(44)
    if (width < 821) await more.tap(); else await more.click()
    const sheet = page.getByRole('dialog', { name: 'Do now · all 9' })
    await expect(sheet).toBeVisible()
    await expect(sheet.getByTestId('home-do-now-all-row')).toHaveCount(9)
    await expect(page).toHaveURL(/detail=do-now-all/)
    if (width < 821) {
      const sheetBox = (await sheet.boundingBox())!
      expect(sheetBox.width).toBeGreaterThanOrEqual(width - 1)
      expect(sheetBox.y).toBeLessThanOrEqual(1)
      await sheet.getByRole('button', { name: '← Back' }).tap()
    } else {
      await sheet.getByRole('button', { name: '← Back' }).click()
    }
    await expect(sheet).toHaveCount(0)
    await expect(page.getByTestId('home-do-now-more')).toBeVisible()
    const overflowX = await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)
    expect(overflowX).toBeLessThanOrEqual(1)
    expect(writes).toEqual([])
  })

  test(`Home Do now with no overflow shows no more button ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    await stub(page)
    await page.goto('/v3/')
    await expect(page.getByTestId('home-do-now-row')).toHaveCount(2)
    await expect(page.getByTestId('home-do-now-more')).toHaveCount(0)
  })
}
