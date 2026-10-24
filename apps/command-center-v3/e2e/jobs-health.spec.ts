import { test, expect } from '@playwright/test'
import path from 'node:path'
test.use({ hasTouch: true })

// Artificial job names and values are pinned test inputs, never a live health claim.
const at = '2026-10-23T16:20:00Z'
const rows = [
  { lane_id: 'fixture-wrapper', job: 'Fixture wrapper job', scheduler: 'cron', state: 'ACTIVE', result: 'failed', cause: 'Lock wrapper refused the release path', last_run_at: at, last_success_at: null, next_due_at: '2026-10-23T16:25:00Z', market_hours_only: true },
  { lane_id: 'fixture-regime', job: 'Fixture classifier', scheduler: 'n8n', state: 'RETIRED', result: 'retired', cause: 'Writer is retired; restore decision pending', last_run_at: null, last_success_at: null, next_due_at: null, market_hours_only: false },
  { lane_id: 'fixture-good', job: 'Fixture receipt job', scheduler: 'n8n', state: 'ACTIVE', result: 'succeeded', cause: 'Successful execution receipt; output checked separately', last_run_at: at, last_success_at: at, next_due_at: '2026-10-23T16:25:00Z', market_hours_only: false },
  { lane_id: 'fixture-miss', job: 'Fixture missed job', scheduler: 'cron', state: 'ACTIVE', result: 'missed', cause: 'Two scheduled opportunities elapsed without success', last_run_at: null, last_success_at: null, next_due_at: '2026-10-23T16:25:00Z', market_hours_only: false },
]
const base = { schema: 'JobsHealth@v1', as_of: at, summary: { due_today: 3, succeeded: 1, failed: 1, missed: 1, paused: 0, retired: 1 }, monitor: { observed_at: at, status: 'CRIT', cause: null, notification: { delivered: false, status: 'NOT_REQUESTED' } }, coverage_gaps: [], incident_count: 2, offset: 0, limit: 50, has_more: false }

for (const width of [1440, 412, 390]) for (const state of ['attention', 'all', 'empty', 'unavailable'] as const) {
  test(`Jobs ${state} fixture ${width}`, async ({ page }) => {
    const apiRequests: string[] = []
    await page.setViewportSize({ width, height: width === 412 ? 915 : width === 390 ? 844 : 1000 })
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url())
      apiRequests.push(url.pathname)
      if (url.port === '7777') throw new Error('Live API traffic is forbidden')
      if (url.pathname !== '/api/v2/jobs-health') return route.fulfill({ status: 200, json: {} })
      if (state === 'unavailable') return route.fulfill({ status: 503, json: {error: 'Fixture observation unavailable'} })
      const filter = url.searchParams.get('filter')
      const selected = state === 'empty' ? [] : filter === 'all' ? rows : rows.filter(r => r.result === 'failed' || r.result === 'missed')
      return route.fulfill({status: 200, json: { ...base, rows: selected, total: selected.length }})
    })
    await page.goto(process.env.W4_JOBS_FIXTURE_PATH || '/v3/ops/jobs')
    const jobs = page.getByTestId('jobs-health')
    await expect(jobs).toBeVisible()
    if (state === 'all') await jobs.getByRole('button', {name: 'All jobs', exact: true}).click()
    if (state === 'unavailable') await expect(jobs.getByRole('alert')).toContainText('Jobs could not be read')
    else if (state === 'empty') await expect(jobs).toContainText('No jobs in this filter')
    else await expect(jobs).toContainText('Lock wrapper refused the release path')
    if (state === 'all') await expect(jobs.getByRole('article', {name: 'Fixture classifier'})).toContainText('Retired')
    if (width < 800 && (state === 'attention' || state === 'all')) {
      const filterButton = jobs.getByRole('button', {name: 'All jobs', exact: true})
      expect((await filterButton.boundingBox())?.height).toBeGreaterThanOrEqual(44)
      await filterButton.tap()
      await expect(filterButton).toHaveAttribute('aria-pressed', 'true')
      const review = jobs.getByRole('article', {name: 'Fixture wrapper job'}).getByRole('button', {name: 'Review job'})
      expect((await review.boundingBox())?.height).toBeGreaterThanOrEqual(44)
      await review.tap()
      const sheet = page.getByTestId('job-evidence-sheet')
      await expect(sheet).toBeInViewport()
      await expect(sheet.getByRole('heading', {name: 'Fixture wrapper job'})).toBeInViewport()
      expect((await sheet.boundingBox())?.height).toBe(width === 412 ? 915 : 844)
      if (process.env.W4_SCREENSHOT_DIR) await page.screenshot({path: path.join(process.env.W4_SCREENSHOT_DIR, `impl-16-detail-${width}.png`), fullPage: true})
      await page.goBack()
      await expect(sheet).not.toBeVisible()
      await review.tap()
      await sheet.getByRole('button', {name: 'Back to jobs', exact: true}).tap()
      await expect(sheet).not.toBeVisible()
      await expect(review).toBeInViewport()
      if (state === 'attention') await jobs.getByRole('button', {name: 'Needs attention', exact: true}).tap()
    }
    expect(apiRequests.every(p => p === '/api/v2/jobs-health')).toBeTruthy()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    if (process.env.W4_SCREENSHOT_DIR) await page.screenshot({path: path.join(process.env.W4_SCREENSHOT_DIR, `impl-16-${state}-${width}.png`), fullPage: true})
  })
}
