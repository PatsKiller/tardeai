import { test, expect, type Page } from '@playwright/test'
test.use({ hasTouch: true })

// A gap is a gap, never 0 (live audit 2026-10-25): Jobs "Missed 0" while most jobs were unmeasured, and Ops →
// Data approvals tiles 0 while the live scan was still checking. Synthetic fixture inputs only; every /api request
// is intercepted, non-GET requests are aborted and live :7777 traffic fails the test.
const at = '2026-10-24T16:20:00Z'
const jobRow = { lane_id: 'fixture-unmeasured', job: 'Fixture unmeasured job', scheduler: 'cron', state: 'ACTIVE', result: 'unknown',
  cause: 'Schedule is not measured', last_run_at: null, last_success_at: null, next_due_at: null, market_hours_only: false }
const jobs = (summary: Record<string, unknown>) => ({ schema: 'JobsHealth@v1', as_of: at, offset: 0, limit: 50, has_more: false, total: 1,
  incident_count: 1, coverage_gaps: [], rows: [jobRow], summary,
  monitor: { observed_at: null, status: 'UNKNOWN', cause: 'Independent monitor receipt missing, stale or a dry run', notification: null } })
const UNMEASURED = { due_today: 12, succeeded: 3, failed: 1, missed: 0, paused: 1, retired: 2, unknown: 8, not_measured: 8, missed_measured: false,
  gap_reasons: { missed: '8 jobs not measured (no run receipt or no measurable schedule), so missed runs among them cannot be counted',
    not_measured: 'No run receipt or no measurable schedule' } }
const MEASURED = { due_today: 4, succeeded: 4, failed: 0, missed: 0, paused: 0, retired: 0, unknown: 0, not_measured: 0, missed_measured: true,
  gap_reasons: { missed: null, not_measured: null } }

const domain = (name: string, verdict: string | null) => ({ domain: `fixture_${name}`, title: `Fixture ${name}`, verdict, store: verdict ? 'table:fixture' : undefined,
  live: verdict ? { writer_files: { count: 1, files: ['scripts/fixture.py'] }, surface_reads: {}, store_readers: { count: 0, files: [] }, findings: [], warn_count: 0 } : null })
const opsState = (running: boolean) => ({ data_approvals: { state: 'OK', reason: null,
  scan: running ? { state: 'RUNNING' } : { state: 'DONE', age_s: 30, duration_s: 4 },
  rows: running ? [domain('a', 'APPROVED'), domain('b', null), domain('c', null)] : [domain('a', 'APPROVED'), domain('b', 'NOT_READY'), domain('c', 'READY_TO_APPROVE')] } })

async function fixtures(page: Page, jobsSummary: Record<string, unknown>, scanRunning: boolean) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.port === '7777') throw new Error('Live API traffic is forbidden')
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (route.request().method() !== 'GET') return route.abort()
    if (url.pathname === '/api/v2/jobs-health') return route.fulfill({ status: 200, json: { ok: true, data: jobs(jobsSummary) } })
    if (url.pathname.endsWith('/ops/controls/state')) return route.fulfill({ status: 200, json: { ok: true, data: opsState(scanRunning) } })
    return route.fulfill({ status: 200, json: {} })
  })
}

const size = (width: number) => ({ width, height: width === 412 ? 915 : width === 390 ? 844 : 1000 })

for (const width of [1440, 412, 390]) {
  test(`jobs: missed is a gap while jobs are unmeasured ${width}`, async ({ page }) => {
    await page.setViewportSize(size(width))
    await fixtures(page, UNMEASURED, true)
    await page.goto('/v3/ops/jobs')
    const missed = page.getByTestId('jobs-tile-missed')
    await expect(missed).toBeVisible()
    await expect(missed).toHaveAttribute('data-measured', 'false')
    await expect(missed.locator('strong')).toHaveText('—')
    await expect(page.getByTestId('jobs-tile-missed-reason')).toContainText('8 jobs not measured')
    await expect(page.getByTestId('jobs-tile-not-measured').locator('strong')).toHaveText('8')
    await expect(page.getByTestId('jobs-tile-failed').locator('strong')).toHaveText('1')
    if (width < 820) {
      const all = page.getByRole('button', { name: 'All jobs', exact: true })
      expect((await all.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
      await all.tap()
      await expect(all).toHaveAttribute('aria-pressed', 'true')
      await expect(missed.locator('strong')).toHaveText('—')
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  })

  test(`jobs: a fully measured report shows a real 0 ${width}`, async ({ page }) => {
    await page.setViewportSize(size(width))
    await fixtures(page, MEASURED, false)
    await page.goto('/v3/ops/jobs')
    await expect(page.getByTestId('jobs-tile-missed')).toHaveAttribute('data-measured', 'true')
    await expect(page.getByTestId('jobs-tile-missed').locator('strong')).toHaveText('0')
    await expect(page.getByTestId('jobs-tile-not-measured').locator('strong')).toHaveText('0')
  })

  for (const running of [true, false]) {
    test(`ops data approvals tiles ${running ? 'gap while scan running' : 'counts when checked'} ${width}`, async ({ page }) => {
      await page.setViewportSize(size(width))
      await fixtures(page, MEASURED, running)
      await page.goto('/v3/system/ops-controls')
      const tab = page.getByRole('tab', { name: /^Data approvals/ })
      await tab.scrollIntoViewIfNeeded()
      if (width < 820) {
        expect((await tab.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
        await tab.tap()
      } else await tab.click()
      const approved = page.getByTestId('ops-data-approved')
      await expect(approved).toBeVisible()
      if (running) {
        for (const id of ['ops-data-approved', 'ops-data-ready', 'ops-data-not-ready', 'ops-data-findings']) {
          await expect(page.getByTestId(id).locator('strong')).toHaveText('—')
          await expect(page.getByTestId(`${id}-reason`)).toHaveText('Scan running · 1 of 3 checked')
        }
      } else {
        await expect(approved.locator('strong')).toHaveText('1')
        await expect(page.getByTestId('ops-data-ready').locator('strong')).toHaveText('1')
        await expect(page.getByTestId('ops-data-findings').locator('strong')).toHaveText('0')
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    })
  }
}
