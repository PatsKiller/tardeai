/**
 * One run, two surfaces, the same numbers.
 *
 * The header (MetricStrip SETUPS tile) and the Trading panel both describe the
 * latest scanner run. They drifted before: the run-health helpers lived
 * unexported inside TradingHub.tsx, so the panel could see RUN_UNDERFILLED and
 * the header could not — it painted the same run healthy green for weeks.
 * They now share src/lib/runHealth.ts, and this asserts they stay in step.
 *
 * Compares DATA ATTRIBUTES, never rendered wording. The post-deploy audit
 * scraped prose and reported a false disagreement, because the panel prints
 * "RUN_HEALTHY" while the header prints "run 1087/40" — both correct for an
 * exception-driven surface. Values are comparable; phrasing is not.
 *
 * Deliberately does NOT assert any particular fault exists. A test that requires
 * an underfilled run only passes while the system is broken.
 *
 * Hermetic: every API call is stubbed from one fixture, so both surfaces are
 * provably fed identical input. No production call, no database, no backend.
 */
import { test, expect, type Page } from '@playwright/test'

type RunShape = {
  label: string
  runId: string
  scanned: number
  floor: number
  health: 'healthy' | 'underfilled' | 'partial' | 'failed'
  status: string
  reasons: string[]
  go: number
  wait: number
  nogo: number
  review: number
  integrity: string
}

const RUNS: RunShape[] = [
  { label: 'healthy', runId: '2026-09-05::1000', scanned: 1087, floor: 40,
    health: 'healthy', status: 'RUN_HEALTHY', reasons: [],
    go: 1, wait: 1, nogo: 1078, review: 7, integrity: 'RECONCILED' },
  { label: 'underfilled', runId: '2026-09-04::1730', scanned: 21, floor: 40,
    health: 'underfilled', status: 'RUN_UNDERFILLED', reasons: ['UNIVERSE_TOO_SMALL'],
    go: 1, wait: 1, nogo: 10, review: 9, integrity: 'RECONCILED' },
  { label: 'failed', runId: '2026-09-04::0400', scanned: 0, floor: 40,
    health: 'failed', status: 'RUN_FAILED', reasons: ['CSV_EMPTY'],
    go: 0, wait: 0, nogo: 0, review: 0, integrity: 'DATA_UNAVAILABLE' },
]

function tradeAiPayload(r: RunShape) {
  const classified = r.go + r.wait + r.nogo
  return {
    ok: true,
    run_id: r.runId,
    run_label: r.runId.split('::')[1],
    run_date: r.runId.split('::')[0],
    latest_run_label: r.runId.split('::')[1],
    latest_run_timestamp: `${r.runId.split('::')[0]}T12:00:00`,
    run_health_status: r.status,
    run_health_reason_codes: r.reasons,
    reason_codes: r.reasons,
    expected_min_symbols: r.floor,
    current_run_scanned: r.scanned,
    latest_run_symbols_scanned: r.scanned,
    ticker_count: r.scanned,
    vix: 14.3,
    stale: false,
    cache_age_sec: 5,
    cached_at: new Date().toISOString(),
    tickers: [],
    setup_run_summary: {
      contract_version: 'SetupRunSummary@v1',
      run_id: r.runId, run_label: r.runId.split('::')[1], run_date: r.runId.split('::')[0],
      run_timestamp: `${r.runId.split('::')[0]}T12:00:00`,
      scanned_count: r.scanned, classified_count: classified,
      go_count: r.go, wait_count: r.wait, nogo_count: r.nogo,
      review_count: r.review, excluded_count: 0, error_count: 0, unclassified_count: 0,
      accounted_count: classified + r.review, unaccounted_count: r.scanned - classified - r.review,
      freshness_status: r.status,
      quality: r.status === 'RUN_HEALTHY' ? 'OK' : 'DEGRADED',
      count_integrity: r.integrity,
      count_integrity_reason: null,
    },
  }
}

/** Serve the SAME run to every endpoint either surface reads. */
async function stub(page: Page, r: RunShape) {
  const trade = tradeAiPayload(r)
  await page.route('**/api/**', (route) => {
    const url = route.request().url()
    let body: any = { ok: true }
    if (/trade-ai/.test(url)) body = trade
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

async function factsFrom(page: Page, selector: string) {
  const el = page.locator(selector).first()
  await el.waitFor({ state: 'attached', timeout: 20_000 })
  return el.evaluate((n: Element) => ({
    id: n.getAttribute('data-run-id'),
    scanned: n.getAttribute('data-run-scanned'),
    floor: n.getAttribute('data-run-floor'),
    health: n.getAttribute('data-run-health'),
    integrity: n.getAttribute('data-run-integrity'),
  }))
}

for (const r of RUNS) {
  test(`header and Trading panel state the same run — ${r.label}`, async ({ page }) => {
    await stub(page, r)

    await page.goto('/v3/')
    await page.waitForTimeout(3000)
    const header = await factsFrom(page, '.metric-strip-tile [data-run-id]')

    await page.goto('/v3/trading')
    await page.waitForTimeout(3500)
    const panel = await factsFrom(page, '[data-testid="trade-ai-run-health-chip"]')

    // The header must carry the fixture's facts...
    expect(header.id, 'header run id').toBe(r.runId)
    expect(header.scanned, 'header scanned').toBe(String(r.scanned))
    expect(header.floor, 'header floor').toBe(String(r.floor))
    expect(header.health, 'header health tier').toBe(r.health)

    // ...and the panel must carry exactly the same ones.
    expect(panel, `panel must agree with the header for the ${r.label} run`).toEqual(header)
  })
}

test('the fixtures exercise more than one health tier', () => {
  // Vacuity guard: if every fixture were healthy, the agreement assertions above
  // would never exercise the loud path and would pass on a surface that cannot
  // render a fault at all.
  const tiers = new Set(RUNS.map((r) => r.health))
  expect(tiers.size, 'need healthy AND at least one fault tier').toBeGreaterThan(1)
})
