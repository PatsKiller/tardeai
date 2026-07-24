import { test, expect, type Page, type Route } from '@playwright/test'
import { createHash } from 'node:crypto'
import { readFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// The package is ESM, so __dirname is not defined.
const HERE = dirname(fileURLToPath(import.meta.url))

/**
 * Fixture-driven render gate for /v3/defense and /v3/sectors.
 *
 * Every API call is intercepted with a SANITIZED fixture, so the gate is deterministic
 * and independent of live market data, of the database, and of whatever the desks happen
 * to be showing on the day. It asserts the truth-hierarchy wording PR #166 introduces —
 * that an empty add lane says so, that model output is labelled as critique rather than
 * truth, that a failed hedge is withheld rather than guessed — plus layout integrity at
 * four viewports.
 *
 * It is a rendering gate, not a deployment: nothing here is served on port 7777.
 */

const FIXTURE_DIR = join(HERE, 'fixtures')
const SHOT_DIR = join(HERE, '..', '..', '..', 'docs', 'evidence',
  'defense-sectors-render-gate', '2026-07-24')

const FIXTURES: Record<string, string> = {
  '**/api/v2/defense/posture*': 'defense_posture.json',
  '**/api/v2/defense/industries*': 'defense_industries.json',
  '**/api/v2/defense/recommendations*': 'defense_recommendations.json',
  '**/api/v2/sectors/monitor*': 'sectors_monitor.json',
}

const VIEWPORTS = [
  { name: '1440x1000', width: 1440, height: 1000 },
  { name: '1280x800', width: 1280, height: 800 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
]

const ROUTES = ['/v3/defense', '/v3/sectors']

/** Recorded into the evidence report so a fixture edit invalidates a stale PASS. */
export function fixtureHashes(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const file of Object.values(FIXTURES)) {
    out[file] = createHash('sha256')
      .update(readFileSync(join(FIXTURE_DIR, file)))
      .digest('hex')
      .slice(0, 16)
  }
  return out
}

async function installFixtures(page: Page) {
  // ORDER MATTERS. Playwright matches handlers last-registered-first, so the catch-all
  // must be registered BEFORE the specific fixtures or it swallows them and every panel
  // renders empty — which looks like a passing layout test over a blank page.
  await page.route('**/api/**', (route: Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }))
  for (const [pattern, file] of Object.entries(FIXTURES)) {
    const body = readFileSync(join(FIXTURE_DIR, file), 'utf-8')
    await page.route(pattern, (route: Route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body }))
  }
}

type Collected = { consoleErrors: string[]; pageErrors: string[] }

function collect(page: Page): Collected {
  const c: Collected = { consoleErrors: [], pageErrors: [] }
  page.on('console', m => { if (m.type() === 'error') c.consoleErrors.push(m.text()) })
  page.on('pageerror', e => c.pageErrors.push(String(e)))
  return c
}

async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => {
    const d = document.documentElement
    return Math.max(0, d.scrollWidth - d.clientWidth)
  })
}

test.describe('Defense/Sectors fixture render gate', () => {
  mkdirSync(SHOT_DIR, { recursive: true })

  for (const route of ROUTES) {
    for (const vp of VIEWPORTS) {
      test(`${route} @ ${vp.name}`, async ({ page }) => {
        const errors = collect(page)
        await page.setViewportSize({ width: vp.width, height: vp.height })
        await installFixtures(page)
        await page.goto(route, { waitUntil: 'domcontentloaded' })
        // Fixtures resolve instantly; give the SPA a beat to paint its panels.
        await page.waitForTimeout(1500)

        const slug = route.replace(/\W+/g, '-').replace(/^-|-$/g, '')
        await page.screenshot({
          path: join(SHOT_DIR, `${slug}_${vp.name}.png`),
          fullPage: true,
        })

        // --- layout integrity -------------------------------------------------
        const overflow = await horizontalOverflow(page)
        expect(overflow, `horizontal document overflow at ${vp.name}`).toBeLessThanOrEqual(1)

        // --- runtime integrity ------------------------------------------------
        expect(errors.pageErrors, 'uncaught page errors').toEqual([])
        const realConsoleErrors = errors.consoleErrors.filter(
          // Intercepted routes can log benign network noise; only app errors count.
          t => !/Failed to load resource|net::ERR_|favicon/i.test(t))
        expect(realConsoleErrors, 'console errors').toEqual([])

        // --- primary heading is present and not clipped -----------------------
        const heading = page.locator('h1, h2, [role="heading"]').first()
        if (await heading.count()) {
          const box = await heading.boundingBox()
          if (box) {
            expect(box.width, 'heading has width').toBeGreaterThan(0)
            expect(box.x, 'heading not pushed off-canvas').toBeGreaterThanOrEqual(-1)
          }
        }

        // --- keyboard reachability -------------------------------------------
        await page.keyboard.press('Tab')
        const focusedTag = await page.evaluate(() => document.activeElement?.tagName ?? 'NONE')
        expect(['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'],
          'Tab reaches an interactive control').toContain(focusedTag)
      })
    }
  }

  // Content assertions run once, at the widest viewport, where every panel is visible.
  test('truth-hierarchy wording is rendered on /v3/defense', async ({ page }) => {
    collect(page)
    await page.setViewportSize({ width: 1440, height: 1000 })
    await installFixtures(page)
    await page.goto('/v3/defense', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1800)
    const body = await page.locator('body').innerText()

    // The add lane is empty in the fixture and must say so rather than render nothing.
    expect(body, 'empty add lane is stated, not silent').toMatch(/No governed add card is active/i)
    // Model output is a critique, never presented as market truth.
    expect(body, 'model output labelled critique-only').toMatch(/model critique only/i)
    // A failed hedge leg is withheld rather than guessed at.
    expect(body, 'withheld hedge structure surfaced').toMatch(/WITHHELD/)
  })

  test('sector hierarchy and screen-match wording render on /v3/sectors', async ({ page }) => {
    collect(page)
    await page.setViewportSize({ width: 1440, height: 1000 })
    await installFixtures(page)
    await page.goto('/v3/sectors', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1800)
    const body = await page.locator('body').innerText()

    // "setups" implies a tradeable plan; these are screen matches until governed.
    expect(body, '"screen matches" replaces "setups"').toMatch(/screen match/i)
    expect(body, 'research-watch lane labelled').toMatch(/RESEARCH WATCH/i)
    // Sector -> ETF hierarchy must be visible, not just a flat list.
    expect(body, 'sector ETF hierarchy visible').toMatch(/\bXL[A-Z]\b/)
  })
})
