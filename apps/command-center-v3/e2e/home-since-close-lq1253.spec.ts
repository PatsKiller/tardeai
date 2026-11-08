/** LQ-20261107-1253: the Home "Since last close" card — top of Home, 412 and 1440, no side scroll; one line while the
 *  session is open; pending states never blank. Synthetic wire only. LQ1253_PNG_DIR writes element screenshots. */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'

const PNG = process.env.LQ1253_PNG_DIR || ''
const win = (open: boolean) => ({ label: 'Since Mon 4:00 PM', close_tag: 'Mon close', session_date: '2026-11-09', session_open: open })
const mv = (symbol: string, held: boolean, pct: number, o: object = {}) => ({ symbol, held, price: 10, change_pct: pct, week_pct: 2.1, dollar_impact: held ? pct * 100 : null, close_tag: 'Mon close', big_move: Math.abs(pct) >= 3, news: [], no_news: false, ...o })
const wire = (open: boolean, extra: object = {}) => ({
  status: 'ok', window_now: win(open), generated_at: '2026-11-10T10:50:00Z',
  freshness: { age_seconds: 300, stale: false, window_current: true },
  moves: [mv('AAA', true, 8.6), mv('BBB', true, -4.4, { no_news: true }), mv('WWW', false, -18.2)],
  macro: { headlines: [], futures: { status: 'pending', label: 'futures feed pending', quotes: [] } },
  summary: { source: 'llm', text: 'Synthetic summary. AAA rose after a founder-sale headline. BBB fell with no news. The watchlist name WWW dropped sharply. Futures are pending. Look at BBB first.', lines: [] },
  cio_brief: { status: 'pending', label: 'CIO brief pending' },
  week_ahead: { events: [{ date: '2026-11-10', kind: 'macro', label: 'Consumer Price Index', time_et: '08:30', symbols: [] }, { date: '2026-11-12', kind: 'earnings', label: 'AAA earnings', time_et: null, symbols: ['AAA'] }], fed_speakers: 'no feed — not listed' },
  feed: [
    { title: 'Synthetic: AAA founder plans to sell 260k shares', source: 'yahoo_rss', published_at: '2026-11-10T01:00:00Z', kind: 'holding', exposure: 1086, so_what: 'You hold $1,086 here; AAA is +8.6% since Mon close.', holdings: [{ symbol: 'AAA', held: true, market_value: 1086, change_pct: 8.6 }] },
    { title: 'Synthetic: markets swoon amid AI fears', source: 'CNBC', published_at: '2026-11-09T23:00:00Z', kind: 'macro', exposure: 0, so_what: 'Market backdrop for the whole book ($9,000 held).', holdings: [] },
  ], ...extra,
})

async function open(page: Page, w: number, h: number, body: object) {
  await page.setViewportSize({ width: w, height: h })
  await homeFixtures(page)
  await page.route('**/api/v2/home/since-close*', r => r.fulfill({ json: { ok: true, data: body } }))
  await page.goto('/v3/')
}
const shot = async (page: Page, name: string) => { if (PNG) await page.getByTestId('since-close-card').screenshot({ path: `${PNG}/${name}.png` }) }
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)

for (const [w, h] of [[1440, 1000], [412, 915]] as const) {
  test(`${w}: overnight card is full, first on the page, readable, no side scroll`, async ({ page }) => {
    await open(page, w, h, wire(false))
    const card = page.getByTestId('since-close-card')
    await expect(card).toHaveAttribute('data-state', 'full')
    await expect(card).toContainText('Since Mon 4:00 PM')
    await expect(page.getByTestId('since-close-cio')).toContainText('CIO brief pending')
    await expect(page.getByTestId('since-close-futures')).toContainText('futures feed pending')
    await expect(page.getByTestId('since-close-feed')).toContainText('You hold $1,086 here')
    await expect(page.getByTestId('since-close-week')).toContainText('Consumer Price Index')
    const c = (await card.boundingBox())!, n = (await page.getByTestId('needs-you-card').or(page.getByTestId('home-do-now-page').locator('section,div').nth(1)).first().boundingBox())
    if (n) expect(c.y).toBeLessThanOrEqual(n.y)
    expect(c.x + c.width).toBeLessThanOrEqual(w + 1)
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `after-${w}`)
  })
}

test('412: session open collapses to one line that expands', async ({ page }) => {
  await open(page, 412, 915, wire(true))
  const card = page.getByTestId('since-close-card')
  await expect(card).toHaveAttribute('data-state', 'collapsed')
  expect((await card.boundingBox())!.height).toBeLessThan(70)
  await page.getByTestId('since-close-expand').click()
  await expect(page.getByTestId('since-close-feed')).toBeVisible()
})

test('412: no snapshot yet is a visible card, not blank', async ({ page }) => {
  await open(page, 412, 915, { status: 'no_snapshot', window: win(false) })
  await expect(page.getByTestId('since-close-none')).toBeVisible()
  await shot(page, 'after-none-412')
})

test('412: intraday collapsed line says what arrived; expanding shows Today so far', async ({ page }) => {
  const at = '2031-03-10T14:30:00Z' // the home fixture pins the browser clock to 2031-03-10 15:00Z
  await open(page, 412, 915, wire(true, {
    updated: { at, at_et: '10:30 ET', reason: 'new AAA article', kind: 'news', symbol: 'AAA', headline: 'Synthetic: AAA names a new CFO' },
    today: { label: 'Today so far', basis: 'move vs prior close', since: at, moves: [mv('AAA', true, 8.6)], news: [] },
  }))
  const card = page.getByTestId('since-close-card')
  await expect(card).toHaveAttribute('data-state', 'collapsed')
  await expect(card).toContainText('New: AAA Synthetic: AAA names a new CFO')
  expect(await noSideScroll(page)).toBeTruthy()
  await shot(page, 'intraday-collapsed-412')
  await page.getByTestId('since-close-expand').click()
  await expect(page.getByTestId('since-close-today')).toContainText('Today so far')
  await expect(page.getByTestId('since-close-updated')).toContainText('updated 10:30 ET — new AAA article')
  await shot(page, 'intraday-expanded-412')
})

// ---- amendments 3-5 (stamp strip, CIO bottom line, action list). The home fixture pins the browser clock to 2031-03-10 15:00Z.
const src = (key: string, label: string, ageText: string, warn = false, at = '2031-03-10T14:40:00Z') => ({ key, label, at, at_text: 'Mon 03-10 · 10:40 AM ET', age_text: ageText, warn, warn_text: warn ? '⚠ 4 days old' : null, note: null })
const fixed = ['10:00', '12:30', '13:15', '13:45', '14:30', '16:00', '18:00', '19:30', '20:15'].map((hm, i) => ({ at: `2031-03-10T${hm}:00Z`, text: ['6:00 AM', '8:30 AM', '9:15 AM', '9:45 AM', '10:30 AM', '12:00 PM', '2:00 PM', '3:30 PM', '4:15 PM'][i] }))
const stamp = (updated: string) => ({
  updated_at: updated, updated_text: '', next_refresh_at: '2031-03-10T16:00:00Z', next_refresh_text: 'Mon 03-10 · 12:00 PM ET', any_warn: true,
  sources: [src('news', 'News', '20 min ago'), src('positions', 'Positions', '2 h ago'), src('market_risk', 'Market risk', '1 h ago'), src('cio_brief', 'CIO brief', '3 h ago'), src('prices', 'Prices', 'Fri close'), src('stops', 'Schwab stops', '', true, '2031-03-06T20:55:00Z')],
  schedule: { trading_day: true, fixed, cio: [fixed[0].at, fixed[2].at, fixed[5].at, fixed[8].at], market_open: '2031-03-10T13:30:00Z', market_close: '2031-03-10T20:00:00Z', grace_min: 30 },
})
const cio = {
  status: 'available', generated_at: '2031-03-10T11:00:00Z', risk_tier: 'ORANGE', summary: 'Synthetic summary.',
  synopsis: { posture: 'Defensive', risk: 'ORANGE', verdict: 'Add one missing stop, raise one, and fix one quantity; nothing else needs you.', book: 'Down 1.2% Friday', market: null, reentry: 'None ready', this_week: 'CPI Tuesday', do_now: '3 stop changes', generated_at: '2031-03-10T11:00:00Z' },
  stop_advice: [
    { symbol: 'BBB', answer: 'RAISE', stop_now: 8.5, stop_suggested: 9.2, qty: 200, account: 'Roth', why: 'Higher low formed; the old stop is far below.' },
    { symbol: 'AAA', answer: 'ADD STOP', stop_suggested: 8.4, qty: 200, account: 'Brokerage', why: 'No stop on file for this lot.', short_answer: 'Yes — protect it.', question: 'Should I wait for the open?' },
    { symbol: 'DDD', answer: 'FIX QTY', stop_now: 9, stop_suggested: 9, qty: 50, held_qty: 50, account: 'IRA', why: 'Stop covers 80 shares; you hold 50.' },
    { symbol: 'WWW', answer: 'HOLD', why: 'Structure intact.' },
  ],
}

for (const [w, h] of [[1440, 1000], [412, 915]] as const) {
  test(`${w}: updated badge, CIO bottom line above the fold, numbered action list, source chips`, async ({ page }) => {
    await open(page, w, h, wire(false, { stamp: stamp('2031-03-10T14:50:00Z'), cio_brief: cio }))
    const card = page.getByTestId('since-close-card')
    await expect(page.getByTestId('stamp-badge')).toContainText('UPDATED 10:50 AM ET · MON 03-10')
    await expect(page.getByTestId('stamp-ago')).toContainText('10 min ago')
    const syn = page.getByTestId('since-close-synopsis')
    await expect(page.getByTestId('syn-verdict')).toContainText('Add one missing stop')
    await expect(page.getByTestId('syn-row-market')).toHaveCount(0) // a null row is not drawn
    await expect(page.getByTestId('syn-row-do_now')).toBeVisible()
    const sb = (await syn.boundingBox())!
    expect(sb.y + 90).toBeLessThan(h) // the verdict is above the fold (at 412 too)
    const rows = page.getByTestId('stop-row')
    await expect(rows).toHaveCount(3)
    await expect(rows.nth(0)).toHaveAttribute('data-kind', 'ADD_STOP')
    await expect(rows.nth(0)).toHaveAttribute('data-urgent', 'true')
    await expect(rows.nth(0)).toContainText('ADD A SELL STOP')
    await expect(rows.nth(0).getByTestId('stop-consequence')).toContainText('$2,000 has no stop')
    await expect(rows.nth(2)).toContainText('Locks in $140 of Friday')
    await expect(page.getByTestId('stops-quiet')).toContainText('WWW')
    await expect(page.getByTestId('stops-rule')).toContainText('never on a headline alone')
    // per-viewer Done toggle
    await rows.nth(0).getByRole('checkbox').check()
    await expect(rows.nth(0)).toHaveAttribute('data-done', 'true')
    await expect(page.getByTestId('stamp-src-stops')).toHaveAttribute('data-warn', 'true')
    await expect(page.getByTestId('stamp-src-prices')).toContainText('Fri close')
    await expect(page.getByTestId('slot-next')).toHaveCount(1)
    expect(await page.getByTestId('slot-done').count()).toBeGreaterThan(3)
    // order: synopsis, then actions, then the per-source strip
    const y = async (id: string) => (await page.getByTestId(id).first().boundingBox())!.y
    expect(await y('since-close-synopsis')).toBeLessThan(await y('since-close-stops'))
    expect(await y('since-close-stops')).toBeLessThan(await y('since-close-stamp-detail'))
    expect((await card.boundingBox())!.x + (await card.boundingBox())!.width).toBeLessThanOrEqual(w + 1)
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `amend345-${w}`)
  })
}

test('412: a missed fixed slot turns the badge amber and says so; a missing synopsis is stated', async ({ page }) => {
  // browser clock is 11:00 ET; the 9:45 slot is 75 min past and nothing was built since 9:00 ET
  await open(page, 412, 915, wire(false, { stamp: stamp('2031-03-10T13:00:00Z'), cio_brief: { status: 'available', generated_at: '2031-03-08T11:00:00Z', summary: 'x' } }))
  await expect(page.getByTestId('stamp-badge')).toHaveAttribute('data-warn', 'true')
  await expect(page.getByTestId('stamp-missed')).toContainText('9:45 AM update did not run')
  await expect(page.getByTestId('slot-missed')).toHaveCount(2) // 9:45 and 10:30 both passed with no build
  await expect(page.getByTestId('syn-notice')).toContainText('CIO synopsis not built since')
  await expect(page.getByTestId('stops-quiet')).toHaveCount(0)
  expect(await noSideScroll(page)).toBeTruthy()
})
