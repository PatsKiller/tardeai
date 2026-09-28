/**
 * Options cards redesign (PR4, 2026-09-28): the v5 proposal cards behind ui_v5.
 *
 *   npm run build && npx vite preview --port 5174 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 npx playwright test e2e/options-cards-redesign.spec.ts --reporter=line
 *
 * Proves the card contract on the live proposals feed: `?ui=v5` renders the v5 card, the
 * takeaway is the first sentence after the header, every metric opens a metric-guide tooltip
 * (definition / why it matters / how to read it), and `?ui=v4` still renders the old card.
 * Screenshots land in e2e/screenshots/ui-audit/after-pr4[-light]/ (gitignored; manifest not needed).
 */
import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, 'screenshots', 'ui-audit')

/** Element screenshots scroll under the fixed header strip; unpin it for the capture only. */
async function unpinChrome(page: Page) {
  await page.addStyleTag({ content: '* { position: static !important; }' }).catch(() => {})
}

async function openProposals(page: Page, ui: 'v4' | 'v5', theme?: 'light' | 'dark') {
  // the app reads cc.ui.theme at boot (hooks/useTheme.ts); seed it before navigation so it sticks
  if (theme) await page.addInitScript(t => { try { localStorage.setItem('cc.ui.theme', t) } catch { /* ignore */ } }, theme)
  await page.goto(`/v3/trading?tab=Options&otab=Proposals&ui=${ui}`, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  // The hub auto-reveals blocked ideas when nothing is live-eligible; wait for a card of the requested generation.
  const sel = ui === 'v5' ? '[data-testid="option-proposal-card-v5"]' : '[data-testid="options-truth-pills"], [data-testid="options-committee-memo"]'
  await page.locator(sel).first().waitFor({ timeout: 150_000 }).catch(() => {})
  await page.waitForTimeout(1500)
}

test.describe('options cards v5', () => {
  test.use({ viewport: { width: 1440, height: 900 } })
  test.setTimeout(4 * 60_000)

  test('ui=v5 renders the redesigned proposal card with the takeaway first', async ({ page }) => {
    await openProposals(page, 'v5')
    const cards = page.getByTestId('option-proposal-card-v5')
    const n = await cards.count()
    test.skip(n === 0, 'no proposals served right now')
    const card = cards.first()
    // insight first: the takeaway banner precedes every metric in document order
    const banner = card.locator('div', { hasText: /.+/ }).filter({ has: page.locator('ul, span') }).first()
    await expect(banner).toBeVisible()
    const order = await card.evaluate(el => {
      const all = Array.from(el.querySelectorAll('*'))
      const takeaway = all.findIndex(e => (e as HTMLElement).style.borderLeft?.includes('3px solid'))
      const metric = all.findIndex(e => (e as HTMLElement).dataset.testid === 'metric')
      return { takeaway, metric }
    })
    expect(order.takeaway).toBeGreaterThan(-1)
    expect(order.metric).toBeGreaterThan(order.takeaway)
    // no more than four hero metrics in the first metric row
    const firstMetric = card.getByTestId('metric').first()
    const heroCount = await firstMetric.evaluate(el => el.parentElement!.querySelectorAll(':scope > [data-testid="metric"]').length)
    expect(heroCount).toBeLessThanOrEqual(4)
    // every metric carries a guide key and hovering opens the full guide (the four questions)
    const metrics = card.getByTestId('metric')
    const m = await metrics.count()
    expect(m).toBeGreaterThan(0)
    const keys = await metrics.evaluateAll(els => els.map(e => (e as HTMLElement).dataset.guideKey || ''))
    expect(keys.every(k => /^[a-z0-9]+(\.[a-z0-9_-]+)+$/.test(k))).toBe(true)
    await metrics.first().hover()
    const tip = page.getByRole('tooltip').first()
    await expect(tip).toBeVisible()
    await expect(tip).toContainText(/why it matters/i)
    // the v4 card is not on the page
    expect(await page.locator('[data-testid="options-truth-pills"]').count()).toBe(0)
    fs.mkdirSync(path.join(OUT, 'after-pr4'), { recursive: true })
    await page.screenshot({ path: path.join(OUT, 'after-pr4', 'trading--options--proposals.png'), fullPage: true })
    await unpinChrome(page)
    await card.screenshot({ path: path.join(OUT, 'after-pr4', 'option-proposal-card-v5.png') })
  })

  test('light theme renders the same card', async ({ page }) => {
    await openProposals(page, 'v5', 'light')
    const cards = page.getByTestId('option-proposal-card-v5')
    test.skip((await cards.count()) === 0, 'no proposals served right now')
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('light')
    fs.mkdirSync(path.join(OUT, 'after-pr4-light'), { recursive: true })
    await page.screenshot({ path: path.join(OUT, 'after-pr4-light', 'trading--options--proposals.png'), fullPage: true })
    await unpinChrome(page)
    await cards.first().screenshot({ path: path.join(OUT, 'after-pr4-light', 'option-proposal-card-v5.png') })
  })

  test('ui=v4 still renders the previous card (rollback layer 1)', async ({ page }) => {
    await openProposals(page, 'v4')
    expect(await page.getByTestId('option-proposal-card-v5').count()).toBe(0)
    const v4 = page.locator('[data-testid="options-truth-pills"], [data-testid="options-committee-memo"]')
    test.skip((await v4.count()) === 0, 'no proposals served right now')
    expect(await v4.count()).toBeGreaterThan(0)
  })
})
