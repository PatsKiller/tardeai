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
  await coverage.getByRole('button', { name: 'Request full scan', exact: true }).click()
  await expect.poll(() => writes).toEqual(['/api/v2/options/scans'])
  writes.length = 0
  await page.goto('/v3/trading?tab=Options&otab=Proposals&ui=v4')
  await expect(page.getByText('TEST', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request model reviews', exact: true })).toBeVisible()
  expect(writes).toEqual([])
})
