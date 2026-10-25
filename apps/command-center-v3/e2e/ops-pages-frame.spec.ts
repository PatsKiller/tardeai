import { test, expect, type Locator, type Page } from '@playwright/test'
import path from 'node:path'
test.use({ hasTouch: true })

// Batch 27 (W4 ops-pages directive + boards 0/16): every ops page sits in the shared desk frame (purpose, Source
// clocks with writer state + last successful run, Decisions band) and embeds the ONE Jobs & health view in its Jobs
// tab. Fixture inputs only — every /api request is intercepted; live :7777 traffic fails the test.
const at = '2026-10-24T16:20:00Z'
const jobs = { schema: 'JobsHealth@v1', as_of: at, offset: 0, limit: 50, has_more: false, total: 1, incident_count: 1,
  summary: { due_today: 2, succeeded: 1, failed: 1, missed: 0, paused: 0, retired: 0 },
  monitor: { observed_at: at, status: 'OK', cause: null, notification: { delivered: false, status: 'NOT_REQUESTED' } }, coverage_gaps: [],
  rows: [{ lane_id: 'fixture-wrapper', job: 'Fixture wrapper job', scheduler: 'cron', state: 'ACTIVE', result: 'failed',
    cause: 'Lock wrapper refused the release path', last_run_at: at, last_success_at: null, next_due_at: '2026-10-24T16:25:00Z', market_hours_only: false }] }

type Spec = { key: string; route: string; title: string; jobsTab?: (page: Page) => Locator }
const PAGES: Spec[] = [
  { key: 'jobs', route: '/v3/ops/jobs', title: 'Jobs & health' },
  { key: 'health', route: '/v3/health', title: 'Health', jobsTab: p => p.getByRole('button', { name: 'Jobs & health', exact: true }) },
  { key: 'coordination', route: '/v3/coordination', title: 'Coordination', jobsTab: p => p.getByTestId('coordination-tab-jobs') },
  { key: 'releases', route: '/v3/system/releases', title: 'Releases & Schedules', jobsTab: p => p.getByTestId('rs-tab-jobs') },
  { key: 'controls', route: '/v3/system/ops-controls', title: 'Ops Controls', jobsTab: p => p.getByRole('tab', { name: /^Jobs/ }) },
  { key: 'system', route: '/v3/system', title: 'System', jobsTab: p => p.getByTestId('system-tabs').getByRole('button', { name: 'Jobs', exact: true }) },
  { key: 'llm', route: '/v3/consumption', title: 'LLM Spend' },
  { key: 'broker', route: '/v3/system/broker-access', title: 'Broker Access' },
]

for (const width of [1440, 412, 390]) for (const spec of PAGES) {
  test(`ops frame ${spec.key} ${width}`, async ({ page }) => {
    const height = width === 412 ? 915 : width === 390 ? 844 : 1000
    await page.setViewportSize({ width, height })
    const errors: string[] = []
    page.on('pageerror', e => errors.push(String(e)))
    await page.route('**/*', route => {
      const url = new URL(route.request().url())
      if (url.port === '7777') throw new Error('Live API traffic is forbidden')
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (route.request().method() !== 'GET') return route.abort()
      if (url.pathname === '/api/v2/jobs-health') return route.fulfill({ status: 200, json: { ok: true, data: jobs } })
      if (url.pathname === '/api/v2/desk-sources') {
        const lanes = (url.searchParams.get('lanes') || '').split(',').filter(Boolean)
        return route.fulfill({ status: 200, json: { ok: true, data: { observed_at: at, writers: lanes.map(lane_id => ({ lane_id, state: 'ACTIVE',
          last_success_at: at, evidence_source: 'fixture receipt', evidence_as_of: at, reason: null })) } } })
      }
      return route.fulfill({ status: 200, json: {} })
    })
    await page.goto(spec.route)
    const heading = page.getByRole('heading', { level: 1, name: spec.title, exact: true })
    await expect(heading).toBeVisible()
    const clocks = page.getByRole('region', { name: 'Source clocks' })
    await expect(clocks).toBeVisible()
    await expect(clocks).toContainText('Writer ACTIVE')
    await expect(clocks).toContainText('Last successful run')
    const decisions = page.getByRole('region', { name: 'Decisions for you' })
    await expect(decisions.getByRole('link', { name: /Approvals waiting on you/ })).toHaveAttribute('href', /\/approvals$/)
    await expect(page.getByTestId(`ops-frame-${spec.key}`)).toBeAttached()
    if (spec.jobsTab) {
      const tab = spec.jobsTab(page)
      await tab.scrollIntoViewIfNeeded()
      if (width < 820) {
        expect((await tab.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
        await tab.tap()
      } else await tab.click()
      expect(new URL(page.url()).searchParams.get('tab')?.toLowerCase()).toBe('jobs')
      const embedded = page.getByTestId('jobs-health')
      await expect(embedded).toBeVisible()
      await expect(embedded).toContainText('Lock wrapper refused the release path')
      await embedded.scrollIntoViewIfNeeded()
      await expect(embedded).toBeInViewport()
    }
    if (spec.key === 'jobs') await expect(page.getByTestId('jobs-health')).toContainText('Lock wrapper refused the release path')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no horizontal page scroll').toBeTruthy()
    expect(errors).toEqual([])
    if (process.env.B27_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.B27_SCREENSHOT_DIR, `impl-ops-${spec.key}-${width}.png`), fullPage: false })
  })
}
