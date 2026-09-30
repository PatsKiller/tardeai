/**
 * UI audit screenshots (2026-09-27): the "before" (and later "after") visual baseline for
 * docs/design/UI_AUDIT_2026-09.md. Read-only; no orders, no 2FA, no settings changes.
 *
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:7777 UI_AUDIT_DIR=before npx playwright test e2e/ui-audit-screenshots.spec.ts --reporter=line
 *
 * Output: e2e/screenshots/ui-audit/<UI_AUDIT_DIR>/<route-slug>[--<tab>].png at 1440x900, full page.
 * UI_AUDIT_ALL=1 adds the control-plane preview pages. UI_AUDIT_THEME=light|dark sets data-theme
 * before capture (no-op until the theme layer ships).
 */
import { test, type Page } from '@playwright/test'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const DIR = process.env.UI_AUDIT_DIR || 'before'
const THEME = process.env.UI_AUDIT_THEME || ''
const OUT = path.join(__dirname, 'screenshots', 'ui-audit', THEME ? `${DIR}-${THEME}` : DIR)

// Operator-facing routes from src/App.tsx (basename /v3). Tabbed hubs list their tab labels as
// rendered; a tab that is not found is skipped, never failed, so the audit run always completes.
const ROUTES: Array<{ path: string; slug: string; tabs?: string[] }> = [
  { path: '/', slug: 'home' },
  { path: '/portfolio', slug: 'portfolio', tabs: ['Holdings', 'Allocation', 'Look-through', 'Returns', 'Dividends', 'Forecast', 'Tax', 'Redeploy', 'Stop Management'] },
  { path: '/trading', slug: 'trading', tabs: ['Trade AI', 'Options', 'Open Trades', 'Proposals', 'Entry Desk', 'Execution', 'Broker Recon', 'Scalp', 'ATM Controls', 'Broker Orders', 'Schwab Accounts'] },
  { path: '/watch', slug: 'watch', tabs: ['Intelligence', 'Watchpool', 'Sectors', 'Pullback'] },
  { path: '/watch/intelligence/DELL', slug: 'symbol-DELL' },
  { path: '/risk', slug: 'risk', tabs: ['Exposure', 'Correlation', 'Regime', 'Recovery'] },
  { path: '/active-trader', slug: 'active-trader' },
  { path: '/journal', slug: 'journal' },
  { path: '/cio', slug: 'cio', tabs: ['Overview', 'Decisions', 'Research', 'Capital & Policy', 'Evidence & Comms'] },
  { path: '/advisory', slug: 'advisory' },
  { path: '/redeploy', slug: 'redeploy' },
  { path: '/rotation', slug: 'rotation' },
  { path: '/portfolio/re-entry', slug: 're-entry' },
  { path: '/research-intelligence', slug: 'research-intelligence' },
  { path: '/hermes', slug: 'hermes' },
  { path: '/intelligence', slug: 'intelligence' },
  { path: '/communications', slug: 'communications' },
  { path: '/reports', slug: 'reports' },
  { path: '/health', slug: 'health' },
  { path: '/consumption', slug: 'consumption' },
  { path: '/system', slug: 'system', tabs: ['Admin', 'LLM', 'Crons'] },
  { path: '/defense', slug: 'defense' },
  { path: '/retirement', slug: 'retirement' },
  { path: '/sectors', slug: 'sectors' },
]
const CONTROL_PLANE = ['agents', 'audit', 'data', 'identity', 'learning', 'maturity', 'notifications', 'research', 'system', 'workflows']
  .map(p => ({ path: `/control-plane/${p}`, slug: `control-plane-${p}` }))
const ALL = process.env.UI_AUDIT_ALL ? [...ROUTES, { path: '/control-plane', slug: 'control-plane' }, ...CONTROL_PLANE] : ROUTES

async function settle(page: Page, url: string) {
  await page.goto(`/v3${url}`, { waitUntil: 'networkidle', timeout: 60_000 }).catch(async () => {
    await page.goto(`/v3${url}`, { waitUntil: 'domcontentloaded', timeout: 45_000 })
  })
  if (THEME) await page.evaluate(t => { document.documentElement.dataset.theme = t }, THEME)
  await page.waitForTimeout(2500)
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true }).catch(() => {})
}

test.describe('ui audit screenshots', () => {
  test.use({ viewport: { width: 1440, height: 900 } })
  test.setTimeout(20 * 60_000)

  test(`capture ${DIR}${THEME ? ` (${THEME})` : ''}`, async ({ page }) => {
    fs.mkdirSync(OUT, { recursive: true })
    page.setDefaultTimeout(15_000)
    const manifest: Record<string, string[]> = {}
    for (const r of ALL) {
      manifest[r.slug] = []
      try {
        await settle(page, r.path)
        await shot(page, r.slug)
        manifest[r.slug].push(`${r.slug}.png`)
        for (const tab of r.tabs || []) {
          const el = page.getByRole('tab', { name: new RegExp(`^${tab}`, 'i') }).first()
          const alt = page.getByRole('button', { name: new RegExp(`^${tab}`, 'i') }).first()
          const target = (await el.count()) ? el : (await alt.count()) ? alt : null
          if (!target) continue
          await target.click({ timeout: 5_000 }).catch(() => {})
          await page.waitForTimeout(1800)
          const tslug = tab.toLowerCase().replace(/[^a-z0-9]+/g, '-')
          await shot(page, `${r.slug}--${tslug}`)
          manifest[r.slug].push(`${r.slug}--${tslug}.png`)
        }
      } catch (e) {
        manifest[r.slug].push(`ERROR: ${String(e).slice(0, 120)}`)
      }
    }
    fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify({ dir: DIR, theme: THEME || null, captured_at: new Date().toISOString(), routes: manifest }, null, 1))
  })
})
