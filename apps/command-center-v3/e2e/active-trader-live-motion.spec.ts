import { test, expect, type Page, type Route } from '@playwright/test'

/**
 * Active Trader Live Motion UI — deterministic coverage using route interception + Playwright's
 * fake clock. Proves the bandwidth contract (ONE aggregate request per cycle, honored refresh
 * hints), in-place row updates that preserve selection, the evidence-state rendering
 * (WATCH → EXIT_ARMED → EXIT_SIGNAL, PROTECT_ONLY), honest stale/last-good handling, bounded retry,
 * and — critically — that NO order/flatten control ever appears from an exit signal.
 *
 * The aggregate endpoint GET /api/v3/active-trader/motion does not exist at this base; these tests
 * supply it purely via interception. Nothing here asserts a live backend.
 */

const MOTION_GLOB = '**/api/v3/active-trader/motion*'
const CONTRACT = 'active-trader-motion-snapshot-v1'

type MotionBody = Record<string, unknown>

function baseSnapshot(overrides: Partial<MotionBody> = {}): MotionBody {
  return {
    contract: CONTRACT,
    generated_at: 0,
    ui_refresh_after_s: 5,
    push_primary: true,
    max_pull_fallbacks_per_minute: 2,
    t2: {
      operating_cap: 2,
      provider_hard_cap: 8,
      leases: [{ lease_id: 't2_qttb', symbol: 'QTTB', admitted_at: 0, renewed_at: 0, expires_at: 20, priority: 100620, position_open: false }],
      decisions: [
        { symbol: 'QTTB', tier: 'T2', admitted: true, reason_code: 'admitted', refresh_after_s: 5, priority: 620 },
        { symbol: 'LASE', tier: 'T1', admitted: false, reason_code: 'not_near_fire', refresh_after_s: 10, priority: 210 },
        { symbol: 'XRX', tier: 'T1', admitted: false, reason_code: 't2_cooldown', refresh_after_s: 10, priority: 140 },
      ],
    },
    positions: [],
    exit_signals: [],
    ...overrides,
  }
}

function nvdaPosition(state: string, extra: Record<string, unknown> = {}) {
  return {
    symbol: 'NVDA', state, action: 'HOLD', reason_code: 'momentum_deteriorating',
    score: 0.61, confirmations: 2, drawdown_from_high_r: 0.42, armed_for_s: 6, fire_for_s: 0, recovery_for_s: 0,
    refresh_after_s: 5, price: 118.4, entry_price: 116.9, hard_stop_price: 115.2, high_watermark: 119.65, evidence_age_s: 2,
    ...extra,
  }
}

// Keep the rest of the page quiet: everything else under /api returns an empty object. Registered
// FIRST so the more-specific motion route (registered per-test, later) takes precedence.
async function quietBackend(page: Page) {
  await page.route('**/api/**', (route: Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
}

// Install the fake clock and a counting motion route, then open the Review page. `respond` receives
// the 1-based request index so a test can drive a payload sequence deterministically.
async function open(page: Page, respond: (index: number) => MotionBody | { status: number }) {
  const counter = { n: 0 }
  await quietBackend(page)
  await page.route(MOTION_GLOB, (route: Route) => {
    counter.n += 1
    const out = respond(counter.n)
    if ('status' in out && typeof (out as { status: number }).status === 'number') {
      route.fulfill({ status: (out as { status: number }).status, contentType: 'application/json', body: '{"error":"forced"}' })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(out) })
    }
  })
  await page.clock.install()
  await page.goto('/v3/active-trader')
  await expect(page.getByTestId('active-trader-motion')).toBeVisible({ timeout: 20_000 })
  return counter
}

const seam = (page: Page) => page.getByTestId('motion-request-count')
const motion = (page: Page) => page.getByTestId('active-trader-motion')

test.describe('Active Trader live motion', () => {
  test('one aggregate request updates multiple ticker rows', async ({ page }) => {
    await open(page, () => baseSnapshot())
    await expect(seam(page)).toHaveText('1')
    // Three rows from a single request — proves aggregate, not per-ticker.
    for (const sym of ['QTTB', 'LASE', 'XRX']) {
      await expect(motion(page).locator(`[data-symbol="${sym}"]`)).toBeVisible()
    }
    await expect(seam(page)).toHaveText('1')
  })

  test('5s hint honored with no per-symbol fan-out', async ({ page }) => {
    await open(page, () => baseSnapshot({ ui_refresh_after_s: 5 }))
    await expect(seam(page)).toHaveText('1')
    await page.clock.runFor(5000)
    await expect(seam(page)).toHaveText('2')   // +1 for 3 tickers, not +3
    await page.clock.runFor(5000)
    await expect(seam(page)).toHaveText('3')
  })

  test('10s hint honored for near-fire T1 cadence', async ({ page }) => {
    await open(page, () => baseSnapshot({ ui_refresh_after_s: 10 }))
    await expect(seam(page)).toHaveText('1')
    await page.clock.runFor(9000)
    await expect(seam(page)).toHaveText('1')   // not due yet
    await page.clock.runFor(2000)
    await expect(seam(page)).toHaveText('2')   // due at 10s
  })

  test('selection stays on the same ticker after a refresh', async ({ page }) => {
    await open(page, () => baseSnapshot({ ui_refresh_after_s: 5 }))
    const lase = motion(page).locator('[data-symbol="LASE"]')
    await lase.click()
    await expect(lase).toHaveAttribute('aria-pressed', 'true')
    await page.clock.runFor(5000)
    await expect(seam(page)).toHaveText('2')
    await expect(motion(page).locator('[data-symbol="LASE"]')).toHaveAttribute('aria-pressed', 'true')
  })

  test('temporary deterioration renders WATCH, never EXIT_SIGNAL', async ({ page }) => {
    await open(page, () => baseSnapshot({ positions: [nvdaPosition('WATCH')] }))
    await expect(motion(page).getByText('WATCH', { exact: true })).toBeVisible()
    await expect(motion(page).getByText('EXIT SIGNAL', { exact: true })).toHaveCount(0)
  })

  test('persistent payload renders WATCH -> EXIT_ARMED -> EXIT_SIGNAL', async ({ page }) => {
    const seq = ['WATCH', 'EXIT_ARMED', 'EXIT_SIGNAL']
    await open(page, (i) => baseSnapshot({
      ui_refresh_after_s: 5,
      positions: [nvdaPosition(seq[Math.min(i - 1, seq.length - 1)])],
    }))
    await expect(motion(page).getByText('WATCH', { exact: true })).toBeVisible()
    await page.clock.runFor(5000)
    await expect(motion(page).getByText('EXIT ARMED', { exact: true })).toBeVisible()
    await page.clock.runFor(5000)
    await expect(motion(page).getByText('EXIT SIGNAL', { exact: true })).toBeVisible()
  })

  test('stale evidence renders PROTECT_ONLY without implying an automated exit', async ({ page }) => {
    await open(page, () => baseSnapshot({ positions: [nvdaPosition('PROTECT_ONLY', { reason_code: 'market_data_stale' })] }))
    await expect(motion(page).getByText('PROTECT ONLY', { exact: true })).toBeVisible()
    await expect(motion(page).getByText(/protective stop is the operative defense/i)).toBeVisible()
    // No language claiming an exit happened, and no enabled control to make one.
    await expect(motion(page).getByRole('button', { name: /flatten|sell|exit now|submit|route|send order/i })).toHaveCount(0)
  })

  test('API failure preserves last-good with a stale badge and bounded retry', async ({ page }) => {
    await open(page, (i) => (i === 1 ? baseSnapshot({ ui_refresh_after_s: 5 }) : { status: 500 }))
    await expect(seam(page)).toHaveText('1')
    await expect(motion(page).getByText('MOTION LIVE')).toBeVisible()
    // First refresh fails.
    await page.clock.runFor(5000)
    await expect(seam(page)).toHaveText('2')
    await expect(motion(page).getByText('MOTION DATA STALE')).toBeVisible()
    // Last-good rows are still shown (never blanked, never fabricated fresh).
    await expect(motion(page).locator('[data-symbol="QTTB"]')).toBeVisible()
    // Bounded backoff: no tight loop — nothing fires in the next 1s...
    await page.clock.runFor(1000)
    await expect(seam(page)).toHaveText('2')
    // ...the next retry lands only after the >=5s backoff window.
    await page.clock.runFor(5000)
    await expect(seam(page)).toHaveText('3')
  })

  test('no enabled order or flatten control appears from an exit signal', async ({ page }) => {
    await open(page, () => baseSnapshot({
      positions: [nvdaPosition('EXIT_SIGNAL', { reason_code: 'persistent_momentum_failure' })],
      exit_signals: [{ symbol: 'NVDA', state: 'EXIT_SIGNAL', reason_code: 'persistent_momentum_failure', at: 0 }],
    }))
    await expect(motion(page).getByText('EXIT SIGNAL', { exact: true }).first()).toBeVisible()
    await expect(motion(page).getByText('DISPLAY ONLY · NO ORDER PATH').first()).toBeVisible()
    // No order-like control exists anywhere on the motion surface, enabled or not.
    await expect(motion(page).getByRole('button', { name: /flatten|sell|buy|submit|confirm|exit now|route|send order|place order/i })).toHaveCount(0)
    // Every button that DOES exist (row selection) is enabled-but-harmless; none is an order path.
    const enabledOrderish = await motion(page).locator('button:not([disabled])').evaluateAll(
      (els) => els.filter((e) => /flatten|sell|buy|submit|confirm|route|order/i.test(e.textContent || '')).length,
    )
    expect(enabledOrderish).toBe(0)
  })

  test('endpoint returning malformed data fails closed, never fabricates values', async ({ page }) => {
    await open(page, () => ({ contract: 'wrong', garbage: true } as unknown as MotionBody))
    // A bad payload still normalizes (empty), and the contract mismatch is surfaced honestly.
    await expect(motion(page).getByText('UNEXPECTED CONTRACT')).toBeVisible()
    await expect(motion(page).getByText('No near-fire candidates right now.')).toBeVisible()
    await expect(motion(page).getByText('No active paper/shadow positions.')).toBeVisible()
  })
})
