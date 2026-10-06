/** Isolated browser adapters. Every API request is fulfilled locally; no live 2FA/broker. */
import { expect, test } from '@playwright/test'

function economics(n = 1) {
  const per = { premium_total: 6523, capital_required: 6523, fees_total: null, max_profit: null, max_loss: 6523,
    greeks: { delta: 80, gamma: 1, theta: -3, vega: 30, rho: 20 } }
  return { ...per, premium_total: 6523 * n, capital_required: 6523 * n, max_loss: 6523 * n,
    per_contract: per, greeks: Object.fromEntries(Object.entries(per.greeks).map(([k, v]) => [k, v * n])),
    fees_basis: 'unknown; excluded', profit_unlimited: true, package_basis: 'options only', breakevens: [185.23],
    expiry_date: '2027-12-17', probability_basis: 'Model estimate unavailable', assignment_note: 'Early-assignment probability unavailable.',
    before_expiry_note: 'Expiry outcomes are not before-expiry price forecasts.',
    scenarios: [
      { underlying_price: 167.78, option_expiry_value: 4778 * n, option_pl: -1745 * n, option_return_pct: -26.75, stock_return_pct: 0, label: 'flat', moneyness: [{ strike: 120, option_type: 'call', state: 'ITM' }] },
      { underlying_price: 300, option_expiry_value: 18000 * n, option_pl: 11477 * n, option_return_pct: 175.95, stock_return_pct: 78.81, label: 'recorded target', moneyness: [{ strike: 120, option_type: 'call', state: 'ITM' }] },
    ] }
}
const accounts = [
  { account_key: 'fixture', display_name: 'Eligible fixture', account_type: 'IRA', broker: 'schwab', route: 'schwab', eligible: true,
    supported_tif: ['DAY', 'GTC'], freshness: 'fresh', buying_power: 20000, available_cash: 20000, capital_required: 6523, as_of: '2026-10-06T13:30:00Z', refusals: [] },
  { account_key: 'insufficient', display_name: 'Insufficient fixture', account_type: 'IRA', eligible: false, supported_tif: ['DAY'],
    refusals: [{ reason: 'This account has insufficient uncommitted capital' }] },
]
const seed = { id: 'fixture-source', symbol: 'TEST', strategy: 'long_call', expiration: '2027-12-17', strike: 120,
  premium: 65.23, contracts: 1, underlying_price: 167.78, dte: 437, enterprise: { blocks: [] },
  review_workflow: { state: 'READY_FOR_REVIEW', reason: 'Fixture only', next_action: 'Review', owner: 'Operator' } }

test('account, quantity, TIF, what-if and review bind to the same revision', async ({ page }) => {
  const writes: { path: string; body: any }[] = []
  let revision = 0
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    const body = request.method() === 'POST' ? request.postDataJSON() : {}
    if (request.method() !== 'GET') writes.push({ path, body })
    let result: any = {}
    if (path.endsWith('/options/proposals')) result = { proposals: [seed], quality_gate: {}, queue_counts: {}, count: 1 }
    if (path.endsWith('/options/overview')) result = { positions: {}, proposals: {} }
    if (path.endsWith('/options/intents')) result = { intents: [] }
    if (path.endsWith('/proposal/prepare')) {
      revision++
      result = { environment: 'dry_test', ok: !!body.account_key, accounts,
        refusals: body.account_key ? [] : [{ reason: 'Choose an eligible account' }] }
      if (body.account_key) result.proposal = { ...seed, id: `fixture:r:${revision}`, revision: `revision-${revision}`, account: body.account_key,
        contracts: body.contracts, tif: body.tif, analysis_lane: body.analysis_lane, workflow_economics: economics(body.contracts),
        legs: [{ expiration: seed.expiration, strike: 120, option_type: 'call', side: 'BUY', ratio: 1, multiplier: 100, bid: 65.20, ask: 65.26, quote_time: '2026-10-06T13:30:00Z' }] }
    }
    if (path.endsWith('/proposal/preview')) result = { ok: true, economics: economics(body.contracts) }
    if (path.endsWith('/proposal/analysis')) result = { ok: true, analysis: { status: 'completed', votes: [{ reasoning: 'Fixture explanation: flat stock loses time value.' }], objections: [] } }
    if (path.endsWith('/proposal/review')) result = { ok: true }
    if (path.endsWith('/options/preflight')) result = { ok: true, intent_id: 'fake-authorization-only' }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) })
  })
  await page.goto('/v3/trading?tab=Options&otab=Proposals&ui=v4')
  await page.getByRole('button', { name: 'Review strategy · account, quantity and time in force' }).click()
  const dialog = page.getByRole('dialog', { name: 'Strategy Proposal' })
  await expect(dialog.getByLabel('Number of contracts')).toHaveValue('1')
  expect(writes).toEqual([])
  await dialog.getByRole('button', { name: 'Refresh quotes and accounts' }).click()
  await expect(dialog).toContainText('DRY RUN ONLY — no order transmitted.')
  await expect(dialog.getByRole('radio', { name: /Insufficient fixture/ })).toBeDisabled()
  await dialog.getByRole('radio', { name: /Eligible fixture/ }).check()
  await dialog.getByLabel('Time in force').selectOption('GTC')
  await dialog.getByRole('button', { name: 'Refresh quotes and accounts' }).click()
  await expect(dialog).toContainText('What-if outcomes at expiry')
  await dialog.getByRole('button', { name: 'Explain delta', exact: true }).focus()
  await expect(page.getByRole('tooltip')).toContainText('not assignment probability')
  await dialog.getByLabel('Number of contracts').focus()
  await expect(dialog.getByRole('row').filter({ hasText: '$167.78 (flat)' })).toContainText('-$1,745.00')
  await dialog.getByRole('button', { name: 'Request analysis', exact: true }).click()
  await dialog.getByRole('button', { name: 'Review this revision' }).click()
  await expect(dialog.getByRole('button', { name: 'Continue to existing 2FA' })).toBeEnabled()
  await dialog.getByLabel('Number of contracts').fill('2')
  await expect(dialog.getByRole('button', { name: 'Continue to existing 2FA' })).toBeDisabled()
  await expect(dialog.getByRole('row').filter({ hasText: '$167.78 (flat)' })).toContainText('-$3,490.00')
  await dialog.getByLabel('Number of contracts').fill('0')
  await expect(dialog.getByRole('alert')).toContainText('positive whole number')
  await expect(dialog.getByRole('button', { name: 'Refresh quotes and accounts' })).toBeDisabled()
  await dialog.getByLabel('Number of contracts').fill('2')
  await dialog.getByRole('button', { name: 'Refresh quotes and accounts' }).click()
  await dialog.getByRole('button', { name: 'Request analysis', exact: true }).click()
  await dialog.getByRole('button', { name: 'Review this revision' }).click()
  await dialog.getByRole('button', { name: 'Continue to existing 2FA' }).click()
  await expect(dialog.getByRole('link', { name: 'Open Broker Orders' })).toBeVisible()
  expect(writes.filter(w => w.path.endsWith('/options/preflight'))).toEqual([
    { path: '/api/v2/options/preflight', body: { proposal_id: 'fixture:r:3', revision: 'revision-3', account_key: 'fixture' } },
  ])
  expect(writes.filter(w => /confirm|submit/.test(w.path))).toEqual([])
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('journal keeps strategy identities, filters and paginated totals', async ({ page }) => {
  const reads: string[] = []
  await page.route('**/api/**', async route => {
    const u = new URL(route.request().url())
    reads.push(u.pathname + u.search)
    let body: any = {}
    if (u.pathname.endsWith('/journal/options-summary')) {
      const next = u.searchParams.get('offset') === '25'
      body = { total: 26, has_more: !next, summary: { total_strategies: 26, known_outcomes: 3, known_realized_pnl: 150 },
        entries: [{ strategy_position_id: next ? 26 : 1, account_key: 'fixture', underlying: 'TEST', strategy_type: 'long_call',
          status: 'open', basis_status: 'unknown', legs: [], roll_root_id: 1,
          deep_link: '/v3/trading?tab=Options&otab=Lifecycle&spid=1', events: [{ event_id: 1, event: 'PARTIAL_FILL', ref: 'execution-1' }] }] }
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/v3/journal?tab=Options')
  const journal = page.getByRole('region', { name: 'Options TradeInView journal' })
  await expect(journal).toContainText('26 strategies')
  await journal.locator('summary').first().click()
  await expect(journal).toContainText('PARTIAL_FILL')
  await expect(journal.getByRole('link', { name: 'Open lifecycle' })).toBeVisible()
  await journal.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(journal).toContainText('#26')
  await expect(journal).toContainText('26 strategies')
  await journal.getByLabel('Strategy', { exact: true }).selectOption('long_call')
  await expect.poll(() => reads.some(r => r.includes('strategy=long_call') && r.includes('offset=0'))).toBe(true)
})


test('lifecycle filters preserve independent strategies and expose evidence', async ({ page }) => {
  const writes: string[] = []
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push(path)
    let body: any = {}
    if (path.endsWith('/options/execution/status')) body = { armed_for_execution: false }
    if (path.endsWith('/options/lifecycle')) body = { data: { health: [], positions: [
      { strategy_position_id: 101, underlying: 'TEST', account_key: 'fixture-a', broker: 'schwab', strategy_type: 'long_call',
        decision: { recommendation: 'HOLD', urgency: 'green', rationale: 'Fixture thesis intact', next_trigger: 'Recorded target crossing' },
        economics: { unrealized_pnl: 200, realized_pnl: 50, entry_value: 6523, fees: null, dte_nearest: 100, net: { delta: 80, rho: 20 } },
        findings: [{ code: 'fixture', line: 'Fixture quote and basis evidence' }],
        legs: [{ leg_id: 1, occ_symbol: 'TEST271217C00120000', strike: 120, option_type: 'call', expiration: '2027-12-17', side: 'long', status: 'open', contracts: 1, filled_quantity: 1, multiplier: 100, opening_price: 65.23 }] },
      { strategy_position_id: 102, underlying: 'TEST', account_key: 'fixture-b', broker: 'fidelity', strategy_type: 'covered_call',
        decision: { recommendation: 'DATA_BLOCKED', urgency: 'amber', rationale: 'Fixture basis incomplete' }, economics: {}, legs: [] },
    ] } }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/v3/trading?tab=Options&otab=Lifecycle&ui=v4')
  await expect(page.getByText('Fixture thesis intact', { exact: true })).toBeVisible()
  await expect(page.getByText('Fixture basis incomplete', { exact: true })).toBeVisible()
  await page.getByLabel('Account', { exact: true }).selectOption('fixture-a')
  await expect(page.getByText('Fixture basis incomplete', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Fixture quote and basis evidence', { exact: true })).toBeVisible()
  await expect(page.getByText('Next trigger: Recorded target crossing.')).toBeVisible()
  await expect(page.getByText('Realized P&L $50')).toBeVisible()
  await page.getByText('Complete legs and quantities', { exact: true }).click()
  await expect(page.getByRole('table')).toContainText('TEST271217C00120000')
  await expect(page.getByRole('link', { name: 'Journal, fills and event history' })).toHaveAttribute('href', '/v3/journal?tab=Options&spid=101')
  await page.getByLabel('Account', { exact: true }).selectOption('')
  await page.getByLabel('Strategy', { exact: true }).selectOption('covered_call')
  await expect(page.getByText('Fixture basis incomplete', { exact: true })).toBeVisible()
  await expect(page.getByText('Fixture thesis intact', { exact: true })).toHaveCount(0)
  expect(writes).toEqual([])
})
