/** Isolated fixtures only: no live provider, order, research or production evidence. */
import { expect, test } from '@playwright/test'

test('coverage includes fractional holdings and paginates without implicit writes', async ({ page }) => {
  const writes: string[] = []
  const reads: string[] = []
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() !== 'GET') writes.push(url.pathname)
    reads.push(url.pathname + url.search)
    let body: unknown = {}
    if (url.pathname.endsWith('/options/coverage')) {
      const second = url.searchParams.get('offset') === '100'
      body = { status: 'PARTIAL', inventory_count: 101, total: 101, account_position_count: 2,
        chain_completed_count: 0, scan_enabled: false, rows: [{ symbol: second ? 'ZZZ' : 'V',
          source_lanes: ['holdings', 'watchlist', 'reentry'], status: 'PENDING', research_status: 'research_required',
          accounts: [{ account: 'roth', shares: 130, covered_call_capacity: 1 },
            { account: 'rollover', shares: .8, covered_call_capacity: 0 }], proposal_count: 0, ready_count: 0 }],
        source_receipts: { market_discovery: { status: 'PARTIAL', reason: 'fixture missing source total' } } }
    } else if (url.pathname.endsWith('/options/proposals')) {
      body = { proposals: [{ id: 'fixture-proposal', symbol: 'TEST', strategy: 'long_put',
        strike: 100, dte: 30, premium: 2, contracts: 1, max_loss: 200, max_profit: 9800,
        enterprise: { live_eligible: false, blocks: ['Fixture review required'] }, approvable: false,
        action_buttons: [], reasoning: 'Fixture bearish research expression' }],
        count: 1, filtered_count: 1, total_count: 1, ready_count: 0, queue_counts: {}, quality_gate: {} }
    } else if (url.pathname.endsWith('/options/positions')) {
      body = { positions: [], count: 0 }
    } else if (url.pathname.endsWith('/options/overview')) {
      body = { proposals: {}, positions: {} }
    } else if (url.pathname.endsWith('/options/scans')) {
      body = { ok: false, status: 'CONFIG_REQUIRED', error: 'Fixture capacity approval required' }
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/v3/trading?tab=Options&otab=All%20coverage&ui=v4')
  const coverage = page.getByRole('region', { name: 'Options coverage' })
  await expect(coverage).toBeVisible()
  await expect(coverage).toContainText('101 distinct securities')
  await expect(coverage).toContainText('rollover: 0.8 shares · 0 covered calls')
  await expect(coverage).toContainText('fixture missing source total')
  expect(writes).toEqual([])
  await coverage.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(coverage.getByRole('cell', { name: /ZZZ/ })).toBeVisible()
  expect(reads.some(url => url.includes('offset=100'))).toBe(true)
  expect(writes).toEqual([])
  await expect(coverage.getByRole('button', { name: 'Request full scan', exact: true })).toBeDisabled()
  expect(writes).toEqual([])
  writes.length = 0
  await page.goto('/v3/trading?tab=Options&otab=Proposals&ui=v4')
  await expect(page.getByText('TEST', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request model reviews', exact: true })).toBeVisible()
  expect(writes).toEqual([])
})


for (const ui of ['v4', 'v5']) {
  test(`investment review survives closed-market execution blocks (${ui})`, async ({ page }) => {
    const writes: string[] = []
    await page.route('**/api/**', async route => {
      const req = route.request()
      if (req.method() !== 'GET') writes.push(new URL(req.url()).pathname)
      const path = new URL(req.url()).pathname
      let body: unknown = {}
      if (path.endsWith('/options/proposals')) body = {
        proposals: [{ id: 'xar-fixture', symbol: 'XAR', strategy: 'protective_put', account: 'fixture',
          strike: 220, expiration: '2026-11-20', dte: 46, contracts: 1, underlying_price: 231.28,
          premium: 7, premium_total: 700, max_loss: 1828, max_profit: 'unlimited', breakeven: 238.28,
          data_source: 'schwab_chain', bid: .65, ask: 7, premium_basis: 'ask',
          price_basis: 'ask estimate; not a fill; session AFTER_HOURS',
          review_workflow: { state: 'READY_FOR_REVIEW', reason: 'Fixture thesis complete; decision pending',
            next_action: 'Review this strategy and account', owner: 'CIO / operator' },
          options_thesis: { pin: 'fixture@v1', missing_required: [] },
          enterprise: { live_eligible: false, blocks: ['awaiting_cio_decision'] }, approvable: false,
          action_buttons: [], economics: { option_cost_total: 700, insured_shares: 100,
            floor_value_after_premium: 21300, downside_to_floor_from_mark: 1828,
            stock_plus_put_breakeven_from_mark: 238.28 },
          floor_value: 21300, option_max_loss: 700, reasoning: 'Fixture insurance, not a live trade' }],
        count: 1, filtered_count: 1, ready_count: 0, queue_counts: {}, quality_gate: {},
        coverage: { inventory_count: 100, status_counts: { EVALUATED: 1, PENDING: 99 }, chain_completed_count: 0 },
        scan_status: 'LEGACY_PARTIAL', scan_capacity: { status: 'DISABLED', refresh_interval_minutes: 15,
          minimum_chain_requests_per_minute: 6.67 },
      }
      if (path.endsWith('/options/intents')) body = { mode: 'shadow', match_count: 1, unstaged_count: 1,
        intents: [{ symbol: 'XAR', plays: { cash_secured_put: {} }, llm_review: { target_type: 'options_intent', target_id: 'fixture-plan-version', content: 'Captured fixture plan', task: 'options_intent_quality' }, matches: {
          as_of: '2026-10-05T17:00:00Z', quote_time: '2026-10-05T16:59:00Z', spot: 230,
          plays: { cash_secured_put: [{ play: 'cash_secured_put', exp: '2026-11-20', strike: 200, mid: 2,
            delta: -.28, annualized_pct: 12, desk_status: 'NOT_STAGED', quote_time: '2026-10-05T16:59:00Z' }] },
        } }] }
      if (path.endsWith('/options/overview')) body = { proposals: {}, positions: {} }
      if (path.endsWith('/inference/ensemble')) body = { result: { created_at: '2026-10-05T17:05:00Z', final_decision: 'block', votes: [{ lane: 'chatgpt', score: 3, reasoning: 'Fixture model summary: confirm cash and current quotes before considering assignment.' }] } }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.goto(`/v3/trading?tab=Options&otab=Proposals&ui=${ui}`)
    const review = page.getByTestId('options-review-stage-READY_FOR_REVIEW')
    await expect(review).toContainText('Ready for investment review · 1 card')
    await expect(page.getByTestId('options-evaluation-summary')).toContainText('99 pending')
    await expect(page.getByTestId('options-evaluation-summary')).toContainText('Expanded scan: DISABLED')
    await expect(page.getByTestId('options-standing-intents')).toContainText('Captured spot')
    await expect(page.getByTestId('options-standing-intents')).toContainText('Not staged as an account-specific proposal')
    await expect(page.getByTestId('options-standing-intents')).not.toContainText('28% assigned')
    const intents = page.getByTestId('options-standing-intents')
    await intents.getByRole('button', { name: 'Explain Cash-secured puts — get paid to buy lower' }).focus()
    await expect(intents.getByRole('tooltip')).toContainText('reserve the cash')
    await page.mouse.click(1, 1)
    await intents.getByRole('button', { name: 'Explain risk and reward' }).focus()
    await expect(intents.getByRole('tooltip')).toContainText('not the chance of winning')
    await page.mouse.click(1, 1)
    await intents.getByText('LLM summary of this standing plan', { exact: true }).click()
    await expect(intents.getByRole('region', { name: 'LLM standing plan summary' })).toContainText('Fixture model summary')
    await expect(review).toContainText('$700')
    await expect(review).not.toContainText('$383')
    expect(writes).toEqual([])
  })
}


test('standing plan modal previews, invalidates edits and saves only after explicit confirmation', async ({ page }) => {
  const writes: any[] = []
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname
    let body: any = {}
    if (path.endsWith('/options/intents')) {
      if (req.method() === 'POST') {
        const value = req.postDataJSON(); writes.push(value)
        body = { ok: true, dry_run: value.dry_run, symbol: value.symbol, intent: value, action: 'insert' }
      } else body = { intents: [] }
    }
    if (path.endsWith('/options/proposals')) body = { proposals: [], quality_gate: {}, queue_counts: {} }
    if (path.endsWith('/options/overview')) body = { proposals: {}, positions: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/v3/trading?tab=Options&otab=Proposals&ui=v4')
  await page.getByRole('button', { name: 'Create standing plan', exact: true }).click()
  const modal = page.getByRole('dialog', { name: 'Create standing plan' })
  await modal.getByLabel('Ticker', { exact: true }).fill('V')
  await modal.getByLabel('Accumulate shares with cash-secured puts').check()
  await modal.getByLabel('Maximum purchase strike').fill('300')
  await modal.getByRole('button', { name: 'Preview plan', exact: true }).click()
  await expect(modal.getByRole('region', { name: 'Standing plan preview' })).toContainText('V')
  expect(writes).toHaveLength(1); expect(writes[0].dry_run).toBe(true)
  await modal.getByRole('button', { name: 'Edit plan', exact: true }).click()
  await expect(modal.getByRole('button', { name: 'Save advisory plan' })).toHaveCount(0)
  await modal.getByLabel('Maximum purchase strike').fill('290')
  await modal.getByRole('button', { name: 'Preview plan', exact: true }).click()
  await expect(modal.getByRole('button', { name: 'Save advisory plan' })).toBeEnabled()
  await modal.getByRole('button', { name: 'Save advisory plan' }).click()
  await expect(modal).toHaveCount(0)
  expect(writes).toHaveLength(3)
  expect(writes[2].dry_run).toBe(false)
  expect(writes[2].plays.cash_secured_put.strike_max).toBe(290)
  expect(writes[2].expected_intent_updated_at).toBe(null)
  await expect(page.getByRole('status')).toContainText('Advisory plan saved')
  await page.getByRole('button', { name: 'Create standing plan', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(writes).toHaveLength(3)
})
