/** SchedulerOperations@v1 fixture contract; no production calls or mutations. */
import { test, expect, type Page } from '@playwright/test'

function payload(old = false) {
  const at = new Date(Date.now() - (old ? 86_400_000 : 0)).toISOString()
  const base = {
    domain: 'platform', owner: 'platform', declared_state: 'ACTIVE', schedule: '*/5 * * * *',
    next_due: null, last_requested: at, last_started: at, last_completed: at,
    last_exit: 0, duration: 2, receipt: 'fixture-receipt', output_signal: { kind: 'file_mtime', path: 'data/runtime/result.json' },
    output_age: 12, freshness: 'FRESH', lock_skips_24h: null, failures_24h: null,
    duplicate_scheduler: false, scheduler_drift: false, code_sha: 'a'.repeat(40),
    code_root: '/fixture/CURRENT', consumer: 'operator', evidence_class: 'TEST_ONLY',
    health_reason: 'fixture receipt and output', slo_verdict: 'NOT_MEASURED', completion_ratio: null,
    timeline: [{ run_id: 'fixture-receipt', mode: 'live', state: 'RUN_DONE', requested_at: at,
      started_at: at, finished_at: at, exit_code: 0, receipt: { lock_skipped: false, output_signal: 'data/runtime/result.json' } }],
  }
  return { schema: 'SchedulerOperations@v1', authority: 'READ_ONLY_ADVISORY', status: 'OK', as_of: at,
    source_sha: 'eec946b2cebaa1378dab285c506c789f6dff1fb4', rows: [
      { ...base, lane_id: 'cron-fresh', scheduler_type: 'cron', runtime_state: 'LIVE' },
      { ...base, lane_id: 'systemd-missing', scheduler_type: 'systemd', runtime_state: 'ORPHANED', scheduler_drift: true },
      { ...base, lane_id: 'n8n-lock-skip', scheduler_type: 'n8n', runtime_state: 'RUN_SKIPPED_LOCK', lock_skips_24h: 1 },
      { ...base, lane_id: 'openclaw-unknown', scheduler_type: 'openclaw', runtime_state: 'NO_SIGNAL', output_signal: { kind: 'none', reason: 'no durable receipt' } },
    ] }
}

async function fixtures(page: Page, old = false, unavailable = false) {
  await page.route('**/api/**', route => {
    const scheduler = route.request().url().includes('/api/v2/scheduler-operations')
    return route.fulfill({ status: scheduler && unavailable ? 503 : 200, contentType: 'application/json',
      body: JSON.stringify(scheduler ? unavailable ? { ok: false, error: 'unavailable' } : { ok: true, data: payload(old) } : { ok: true }) })
  })
}

test('scheduler rows, problem filter and durable run timeline', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  await fixtures(page)
  await page.goto('/v3/coordination')
  const view = page.getByTestId('scheduler-operations')
  await expect(view.getByRole('heading', { name: 'Automation / Scheduler Operations' })).toBeVisible()
  await expect(view).toContainText('CURRENT eec946b2ceba')
  await expect(view.getByRole('row')).toHaveCount(5)
  await expect(page.getByTestId('scheduler-row-cron-fresh')).toContainText('LIVE')
  // Unknown failures and lock skips stay unknown; they must not render fake zeros.
  const cells = page.getByTestId('scheduler-row-cron-fresh').getByRole('cell')
  await expect(cells.nth(10)).toHaveText('NOT_MEASURED')
  await expect(cells.nth(11)).toHaveText('NOT_MEASURED')
  await view.getByRole('button', { name: 'Problems', exact: true }).click()
  await expect(page.getByTestId('scheduler-row-cron-fresh')).toHaveCount(0)
  await expect(page.getByTestId('scheduler-row-systemd-missing')).toBeVisible()
  await view.getByRole('button', { name: 'n8n', exact: true }).click()
  await expect(view.getByRole('row')).toHaveCount(2)
  await view.getByRole('button', { name: 'Inspect n8n-lock-skip' }).click()
  await expect(page.getByTestId('scheduler-drilldown')).toContainText('fixture-receipt')
  await expect(page.getByTestId('scheduler-drilldown')).toContainText('Requested')
  await expect(view).not.toContainText('Loading scheduler observations')
  await expect(view.locator('pre')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('expired successful response cannot label a row current LIVE', async ({ page }) => {
  await fixtures(page, true)
  await page.goto('/v3/coordination')
  await expect(page.getByTestId('scheduler-operations')).toContainText('STALE / NOT_MEASURED')
  await expect(page.getByTestId('scheduler-row-cron-fresh').getByRole('cell').nth(4)).toHaveText('NOT_MEASURED')
})

test('unavailable endpoint ends loading without inventing counts', async ({ page }) => {
  await fixtures(page, false, true)
  await page.goto('/v3/coordination')
  await expect(page.getByTestId('scheduler-operations').getByRole('alert')).toContainText('No current counts')
  await expect(page.getByTestId('scheduler-operations')).not.toContainText('Loading scheduler observations')
})

test('390px keeps wide table scrolling inside its panel', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await fixtures(page)
  await page.goto('/v3/coordination')
  await expect(page.getByTestId('scheduler-row-cron-fresh')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
