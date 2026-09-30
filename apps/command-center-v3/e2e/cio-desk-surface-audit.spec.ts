import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Live CIO Desk surface audit — every primary tab + Evidence subtabs.
 *
 * Against portfolio-server (PLAYWRIGHT_BASE_URL default http://127.0.0.1:7777).
 * Opt-in: CIO_DESK_AUDIT=1 or CI=true.
 */
const enabled = process.env.CIO_DESK_AUDIT === '1' || process.env.CI === 'true'
const here = path.dirname(fileURLToPath(import.meta.url))
const shotDir = path.resolve(here, '../../../docs/_evidence/cio_desk_audit')

const PRIMARY_TABS = [
  { tab: 'overview', testId: 'cio-overview', mustHave: ['cio-scorecard-strip', 'cio-judgment-band'] },
  { tab: 'decisions', testId: null, mustHave: ['cio-now-section'] },
  { tab: 'research', testId: null, mustHave: ['cio-agent-research-ops', 'cio-universe-theses', 'cio-investment-books'] },
  { tab: 'capital-policy', testId: null, mustHave: ['cio-operator-policy'] },
  { tab: 'evidence-comms', testId: null, mustHave: ['report-section'] },
] as const

const EVIDENCE_SUBS = [
  { sub: 'report', testId: 'report-section' },
  { sub: 'audit', testId: 'evidence-section' },
  { sub: 'notification-gate', testId: 'cio-notification-gate' },
  { sub: 'telegram-receipts', testId: 'cio-telegram-receipts' },
  { sub: 'senses-evidence', testId: 'cio-senses-evidence' },
  { sub: 'full-brain', testId: 'cio-brain' },
] as const

const LEGACY_ALIASES = [
  { q: 'cio-now', expectTab: 'Decisions' },
  { q: 'universe-theses', expectTab: 'Research' },
  { q: 'capital-plan', expectTab: 'Capital & Policy' },
  { q: 'cio-brain', expectTab: 'Evidence & Comms' },
] as const

test.describe('CIO Desk live surface audit', () => {
  test.skip(!enabled, 'set CIO_DESK_AUDIT=1 (or CI) to run against live portfolio-server')
  test.setTimeout(180_000)

  test.beforeAll(() => {
    fs.mkdirSync(shotDir, { recursive: true })
  })

  test('Overview scorecard + judgment stamp are honest', async ({ page }) => {
    const scorecard = await page.request.get('/api/v3/cio/scorecard')
    expect(scorecard.ok()).toBeTruthy()
    const body = await scorecard.json()
    expect(body.path).toBe('light')
    expect(Array.isArray(body.tiles)).toBeTruthy()
    const hermes = (body.tiles || []).find((t: any) => t.id === 'hermes_research')
    const decisions = (body.tiles || []).find((t: any) => t.id === 'decisions')
    expect(hermes).toBeTruthy()
    // Prefer non-zero when coverage-stall has counts; soft if genuinely zero.
    const ok24 = hermes.metrics?.find((m: any) => m.label === 'DeepSeek ok 24h')?.value
    expect(typeof ok24 === 'number').toBeTruthy()
    expect(decisions.status).not.toBe('dark')

    await page.goto('/v3/cio?tab=overview')
    await expect(page.getByTestId('cio-hub')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('cio-scorecard-strip')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('cio-judgment-band')).toBeVisible({ timeout: 30_000 })
    // Judgment stamp should restore portfolio / recommendation when present.
    if (body.judgment?.ok) {
      await expect(page.getByTestId('cio-judgment-recommendation')).toBeVisible()
      await expect(page.getByTestId('cio-judgment-market')).toBeVisible()
      await expect(page.getByTestId('cio-judgment-missing')).toHaveCount(0)
    }
    await page.screenshot({ path: path.join(shotDir, 'overview.png'), fullPage: true })
  })

  for (const row of PRIMARY_TABS) {
    test(`primary tab ${row.tab} paints`, async ({ page }) => {
      await page.goto(`/v3/cio?tab=${row.tab}`)
      await expect(page.getByTestId('cio-hub')).toBeVisible({ timeout: 30_000 })
      const tabName =
        row.tab === 'capital-policy' ? 'Capital & Policy'
          : row.tab === 'evidence-comms' ? 'Evidence & Comms'
            : row.tab === 'overview' ? 'Overview'
              : row.tab === 'decisions' ? 'Decisions'
                : 'Research'
      await expect(page.getByRole('tab', { name: tabName, exact: true })).toHaveAttribute('aria-selected', 'true')
      for (const id of row.mustHave) {
        await expect(page.getByTestId(id)).toBeVisible({ timeout: 90_000 })
      }
      // No hard chrome errors stuck forever
      await expect(page.getByTestId('cio-home-error')).toHaveCount(0)
      await expect(page.getByTestId('cio-scorecard-error')).toHaveCount(0)
      await page.screenshot({ path: path.join(shotDir, `tab-${row.tab}.png`), fullPage: true })
    })
  }

  for (const row of EVIDENCE_SUBS) {
    test(`evidence sub ${row.sub} paints`, async ({ page }) => {
      await page.goto(`/v3/cio?tab=evidence-comms&sub=${row.sub}`)
      await expect(page.getByTestId('cio-hub')).toBeVisible({ timeout: 30_000 })
      // Senses can be slow; allow long paint but require panel mount.
      await expect(page.getByTestId(row.testId)).toBeVisible({ timeout: 120_000 })
      await page.screenshot({ path: path.join(shotDir, `evidence-${row.sub}.png`), fullPage: true })
    })
  }

  for (const row of LEGACY_ALIASES) {
    test(`legacy alias ?tab=${row.q}`, async ({ page }) => {
      await page.goto(`/v3/cio?tab=${row.q}`)
      await expect(page.getByTestId('cio-hub')).toBeVisible({ timeout: 30_000 })
      await expect(page.getByRole('tab', { name: row.expectTab })).toHaveAttribute('aria-selected', 'true')
    })
  }

  test('Research does not stick on universe Loading once data arrives', async ({ page }) => {
    await page.goto('/v3/cio?tab=research')
    await expect(page.getByTestId('cio-universe-theses')).toBeVisible({ timeout: 30_000 })
    // Wait for either metrics (success) or error chip — not endless Loading-only.
    await expect
      .poll(async () => {
        const loadingOnly = await page.getByTestId('cio-universe-theses-loading').count()
        const err = await page.getByTestId('cio-universe-theses-error').count()
        const hasStats = await page.getByText(/Held CURRENT|Research required|Material coverage/i).count()
        return err > 0 || hasStats > 0 || loadingOnly === 0
      }, { timeout: 100_000 })
      .toBeTruthy()
    await page.screenshot({ path: path.join(shotDir, 'research-universe.png'), fullPage: true })
  })
})
