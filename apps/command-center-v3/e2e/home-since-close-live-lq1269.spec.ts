/** LQ-20261107-1269 — operator 18:15 ET: the Home CIO bottom line must be LIVE, not static.
 *
 *  Proof, at 412 px, against a build of this branch with synthetic fixtures only (the repo is PUBLIC):
 *   1. a VISIBLE tab re-reads every 60 s and the card's text changes WITHOUT a reload;
 *   2. the same at real wall-clock speed (the operator's "within 70 s"), not just under a fake clock;
 *   3. coming back to a visible tab re-reads immediately, before any interval elapses;
 *   4. a snapshot older than the operator's limit shows the amber stale badge (30 min in market hours, 4 h closed);
 *   5. nothing scrolls sideways at 412 px while it does any of this.
 *
 *  The browser clock is pinned by `homeFixtures` to Mon 2031-03-10 15:00Z (11:00 ET); the regular session is
 *  13:30–20:00 UTC, so every case here is "market hours" unless it says otherwise. */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'

const PATH = '**/api/v2/home/since-close*'
const at = (h: number, m = 0) => `2031-03-10T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00Z`

const stamp = (updated: string, fixed: Array<[string, string]> = []) => ({
  updated_at: updated, updated_text: '', next_refresh_at: at(22), next_refresh_text: 'Mon 03-10 · 6:00 PM ET', any_warn: false,
  sources: [], schedule: { trading_day: true, fixed: fixed.map(([a, t]) => ({ at: a, text: t })), cio: [],
    market_open: at(13, 30), market_close: at(20, 0), grace_min: 30 },
})

/** The full overnight card with one CIO synopsis; `verdict` is the text the live-update proof watches change. */
const wire = (verdict: string, o: { updated?: string; fixed?: Array<[string, string]> } = {}) => ({
  status: 'ok',
  window_now: { label: 'Since Mon 4:00 PM', close_tag: 'Mon close', session_date: '2031-03-10', session_open: false },
  generated_at: at(14, 50), freshness: { age_seconds: 600, stale: false, window_current: true },
  moves: [{ symbol: 'AAA', held: true, price: 10, change_pct: 8.6, week_pct: 2.1, dollar_impact: 860, close_tag: 'Mon close', big_move: true, news: [], no_news: false }],
  macro: { headlines: [], futures: { status: 'pending', label: 'futures feed pending', quotes: [] } },
  summary: { source: 'llm', text: 'Synthetic summary.', lines: [] },
  cio_brief: { status: 'available', generated_at: at(14, 50), risk_tier: 'ORANGE', summary: 'Synthetic summary.',
    synopsis: { posture: 'Defensive', risk: 'ORANGE', verdict, book: 'Down 1.2%', market: null, reentry: 'None ready',
      this_week: 'CPI Tuesday', do_now: '3 stop changes', generated_at: at(14, 50) } },
  week_ahead: { events: [], fed_speakers: 'none' },
  feed: [],
  stamp: stamp(o.updated ?? at(14, 50), o.fixed),
})

async function open(page: Page, body: () => object, opts: { clock?: 'fake' | 'real' } = {}) {
  await page.setViewportSize({ width: 412, height: 915 })
  await homeFixtures(page)
  // Registered AFTER homeFixtures, so it wins for this path (Playwright matches the newest route first).
  await page.route(PATH, r => r.fulfill({ json: { ok: true, data: body() } }))
  await page.goto('/v3/')
  if (opts.clock === 'real') await page.clock.resume()   // let wall-clock time flow: the literal 70 s proof
}

const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)

test('412: a visible tab re-reads within 60 s and the CIO bottom line changes WITHOUT a reload', async ({ page }) => {
  let verdict = 'FIRST: nothing needs you before the open.'
  const reads: string[] = []
  // Counted from before the first load, so one entry is the initial read and the next is a poll in the SAME document.
  page.on('request', r => { if (r.url().includes('/api/v2/home/since-close')) reads.push(r.url()) })
  await open(page, () => wire(verdict))

  await expect(page.getByTestId('syn-verdict')).toContainText('FIRST')
  // A marker on window survives ONLY if the page is never reloaded or navigated.
  await page.evaluate(() => { (window as any).__lq1269_no_reload = 'kept' })

  verdict = 'SECOND: a new stop is missing on BBB — added by the producer after the page loaded.'
  await page.clock.fastForward(60_000)                    // the 60 s interval, exactly one tick

  await expect(page.getByTestId('syn-verdict')).toContainText('SECOND', { timeout: 15_000 })
  expect(await page.evaluate(() => (window as any).__lq1269_no_reload)).toBe('kept')
  expect(reads.length).toBeGreaterThanOrEqual(2)          // the first load + the poll (same document)
  expect(await noSideScroll(page)).toBeTruthy()
})

test('412: the live update lands within 70 s of real wall-clock time', async ({ page }) => {
  test.setTimeout(120_000)
  let verdict = 'FIRST (wall clock): the desk is clear.'
  await open(page, () => wire(verdict), { clock: 'real' })   // NO fastForward: the real setInterval must fire
  await expect(page.getByTestId('syn-verdict')).toContainText('FIRST')

  verdict = 'SECOND (wall clock): the producer rebuilt while the tab was open.'
  const started = Date.now()
  await expect(page.getByTestId('syn-verdict')).toContainText('SECOND', { timeout: 70_000 })
  expect(Date.now() - started).toBeLessThan(70_000)
})

test('412: returning to a visible tab re-reads at once, before the interval elapses', async ({ page }) => {
  let verdict = 'FIRST: while you were away.'
  await open(page, () => wire(verdict))
  await expect(page.getByTestId('syn-verdict')).toContainText('FIRST')

  // Hide the tab: no timer may run. Then make the producer write and show the tab again.
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  verdict = 'SECOND: built while the tab was hidden.'
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  // Well under the 60 s poll: only the visibilitychange path can deliver it this fast.
  await expect(page.getByTestId('syn-verdict')).toContainText('SECOND', { timeout: 5_000 })
  expect(await noSideScroll(page)).toBeTruthy()
})

test('412: a snapshot older than 30 min in market hours is an amber stale badge that says so', async ({ page }) => {
  // 14:20Z is 40 min before the pinned 15:00Z clock, inside the 13:30–20:00Z session; no fixed slot exists, so the
  // missed-slot alarm cannot fire — the age alone has to raise the badge.
  await open(page, () => wire('Unchanged verdict.', { updated: at(14, 20) }))
  const badge = page.getByTestId('stamp-badge')
  await expect(badge).toHaveAttribute('data-warn', 'true')
  await expect(badge).toHaveAttribute('data-stale', 'true')
  await expect(page.getByTestId('stamp-stale')).toContainText('past the 30 min during market hours limit')
  await expect(page.getByTestId('stamp-ago')).toContainText('40 min ago')
  expect(await noSideScroll(page)).toBeTruthy()
})

test('412: a closed market does NOT use the 30 min limit (2 h old is fresh after the close)', async ({ page }) => {
  // Built at 00:00Z on 03-11; the tab's clock is moved to 02:00Z, two hours later and past the 20:00Z close. A 30 min
  // limit would scream here; the operator's closed-market limit is 4 h, so the badge must stay quiet.
  await open(page, () => wire('Unchanged verdict.', { updated: '2031-03-11T00:00:00Z' }))
  await page.clock.setSystemTime(new Date('2031-03-11T02:00:00Z'))   // no timers fire: re-render comes from the tick below
  await page.clock.fastForward(30_000)                               // useNow's own 30 s tick
  const badge = page.getByTestId('stamp-badge')
  await expect(badge).toHaveAttribute('data-stale', 'false')
  await expect(page.getByTestId('stamp-stale')).toHaveCount(0)
  await expect(page.getByTestId('stamp-ago')).toContainText('2 h ago')
})
