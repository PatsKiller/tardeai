/** C1 actual My Watchlist + Prospects screens; synthetic saved-CIO-record facts.
 * The fixture server serves static built assets only. All API reads are fulfilled;
 * every mutation, external request or websocket is rejected. No live server.
 */
import { expect, test, type Page } from '@playwright/test'
import { WATCH_LISTS_FIXTURE as LISTS } from '../src/fixtures/watchLists.fixture'
import { FIXTURE as PROSPECTS } from '../src/fixtures/watchProspects.fixture'
import { readFileSync } from 'node:fs'
const COMPANY = JSON.parse(readFileSync(new URL('./fixtures/watchCompanyFacts.fixture.json', import.meta.url), 'utf8'))

async function fixture(page: Page) {
  const curation = structuredClone(LISTS.curation)
  const prospects = structuredClone(PROSPECTS.prospects)
  const rows = curation.my_watchlist.rows.slice(0, 3).map((r: any, i: number) => {
    const f = structuredClone(COMPANY.facts)
    f.security_guid = r.security_guid
    f.symbol = r.symbol
    if (i === 1) f.catalyst = { headline: null, status: 'MISSING', missing_reason: 'no_dated_current_catalyst_on_file' } as any
    if (i === 2) {
      f.status = 'MISSING'
      f.missing_reason = 'company_facts_not_on_cio_record'
      for (const field of ['company', 'description', 'sector', 'industry']) (f as any)[field] = { value: null, source: null, observed_at: null, missing_reason: 'not_on_cio_record' }
      f.catalyst = { headline: null, status: 'MISSING', missing_reason: 'company_facts_not_on_cio_record' } as any
    }
    return { ...r, company: f.company.value, company_facts: f, lane: 'forming', stage: 'setup_forming' }
  })
  curation.my_watchlist = { ...curation.my_watchlist, rows, count: rows.length, unfiltered_count: rows.length }
  prospects.lanes = prospects.lanes.map((l: any) => ({ ...l, items: l.id === 'forming' ? rows : [], count: l.id === 'forming' ? rows.length : 0 }))
  const forbidden: string[] = []
  const origin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:4173').origin
  await page.routeWebSocket('**/*', ws => { forbidden.push(`websocket:${ws.url()}`); ws.close() })
  await page.route('**/*', async route => {
    const req = route.request()
    const u = new URL(req.url())
    if (u.origin !== origin || req.method() !== 'GET') {
      forbidden.push(`${req.method()} ${u.origin}${u.pathname}`)
      await route.abort()
      return
    }
    if (!u.pathname.startsWith('/api/')) { await route.continue(); return }
    const body = u.pathname === '/api/v3/data-broker/watch-curation' ? curation
      : u.pathname === '/api/v3/data-broker/watch-prospects' ? prospects
        : u.pathname === '/api/v2/watch/alerts/list' ? { ok: true, alerts: [] }
          : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  return forbidden
}

for (const width of [1440, 412]) {
  for (const tab of ['my-watchlist', 'prospects']) {
    test(`${tab} CIO company facts at ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1100 })
      const forbidden = await fixture(page)
      await page.goto(`/v3/watch?tab=${tab}&lane=forming`)
      const facts = page.getByTestId('watch-company-facts')
      await expect(facts).toHaveCount(3)
      await expect(facts.first()).toContainText('Fixture Precision Instruments Inc.')
      await expect(facts.first()).toContainText('Scientific & Technical Instruments')
      await expect(facts.first()).toContainText('2026-10-23')
      await expect(facts.first()).toContainText('Fixture company publication')
      await expect(facts.first().locator('a')).toHaveAttribute('href', 'https://example.invalid/acme-product')
      await expect(facts.nth(1)).toContainText('No catalyst on file')
      await expect(facts.nth(2)).toContainText('Company name unavailable')
      await expect(facts.nth(2)).toContainText('company facts not on cio record')
      const descriptions = await page.locator('.watch-company-description').evaluateAll(els => els.map(el => ({
        h: el.getBoundingClientRect().height, lh: parseFloat(getComputedStyle(el).lineHeight), title: el.getAttribute('title'), text: el.textContent,
      })))
      expect(descriptions.every(d => d.h <= 2 * d.lh + 1 && d.title?.includes(d.text || ''))).toBe(true)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      for (const box of await facts.evaluateAll(els => els.map(el => ({ w: el.clientWidth, s: el.scrollWidth })))) expect(box.s).toBeLessThanOrEqual(box.w + 1)
      expect(forbidden).toEqual([])
      if (width === 412) await facts.first().scrollIntoViewIfNeeded()
      await expect(facts.first()).toBeInViewport()
      if (process.env.COMPANY_FACTS_SHOTS_DIR) await page.screenshot({ path: `${process.env.COMPANY_FACTS_SHOTS_DIR}/${tab}-${width}.png`, fullPage: true })
    })
  }
}
