/** Home "Do now" redesign (operator-approved, 2026-10-22): fixture contract, no production calls or mutations.
 *
 *   npm run build && npm run preview -- --port 4173 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 npx playwright test e2e/home-do-now.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'

const iso = (msAgo = 0) => new Date(Date.now() - msAgo).toISOString()

function doNowItem(id: string, category: string, severity: string, title: string, money: number | null = null, where = '/v3/risk') {
  return { id, category, severity, title, why: `why ${id}`, action: { label: `Act ${id}`, where }, money_at_risk_usd: money,
    money_basis: money ? 'market value with no stop' : null, sources: ['risk'], since: iso() }
}

function doNow() {
  const items = [
    doNowItem('stops:unprotected', 'protect', 'P1', '8 positions with no stop', 410000),
    doNowItem('stop:SPCX', 'protect', 'P1', 'SPCX $116,250 has no stop', 116250, '/v3/risk?symbol=SPCX'),
    doNowItem('stop:XLB', 'protect', 'P2', 'XLB stop 1.6% away', 420),
    doNowItem('na:health:kill', 'protect', 'P1', 'Kill switch is on'),
    doNowItem('proposals:pending', 'decide', 'P2', '43 paper proposals waiting', null, '/v3/trading?tab=Proposals'),
    doNowItem('deploy:open', 'decide', 'P2', 'Redeploy $28,067 from the NFLX sale'),
    doNowItem('inbox:cio_review', 'decide', 'P2', '40+ CIO decisions need your review (14 d)'),
    ...Array.from({ length: 6 }, (_, i) => doNowItem(`fix${i}`, 'fix', i < 3 ? 'P1' : 'P2', `fix item ${i}`, null, '/v3/system?tab=Jobs')),
  ]
  return {
    schema: 'HomeDoNow@v1', authority: 'READ_ONLY_ADVISORY', as_of: iso(), status: 'OK', all_sources_answered: true,
    counts: { all: 13, protect: 4, decide: 3, fix: 6 }, items,
    rolled_up: { raw_items: 19, after_dedupe: 13, inbox_total: 135, needs_action_total: 18 },
    numbers: { status: 'OK', unprotected_positions: 8, unprotected_value_usd: 410000, unprotected_basis: 'no stop on record (risk snapshot); working-stop coverage not measured',
      unprotected_source: 'risk', heat_pct: 0.1, heat_limit_pct: 5, heat_basis: 'risk_management.json portfolio_heat_pct', as_of: iso(30_000),
      positions_source: 'holdings.json via data_broker.risk_snapshot (positions_current is not approved for Home)', stale: false },
    sources: Object.fromEntries(['needs_action', 'inbox', 'risk', 'desk_truth', 'proposals', 'deploy'].map(n => [n,
      { status: n === 'desk_truth' ? 'NO_RECEIPT' : 'OK', as_of: iso(), as_of_basis: 'read_at', age_s: 5, stale: false, ms: 10 }])),
  }
}

const overview = () => ({
  portfolio_value: 1255076, today_change: -6795, today_pct: -0.54, total_cash: 823000, position_count: 31, pipeline_status: 'stale',
  observation: { not_fresh_datasets: ['holdings'], envelopes: { holdings: { observed_at: iso(50 * 60_000), freshness: { status: 'STALE' } } } },
  top_movers: [{ symbol: 'SPCX', day_change: -6576, day_change_pct: -5.4 }, { symbol: 'SCHG', day_change: -1599 }, { symbol: 'SCHD', day_change: 1844 }, { symbol: 'V', day_change: 343 }],
  today_by_account: { schwab_roth: { change: 341, value: 54013 } },
})

const performance = () => ({
  current_value: 1255076, periods: { '1D': { change: -6795 }, YTD: { change: 30000, display_change: 25097, display_change_pct: 3.44, nav_is_not_market_only: true } },
  accounts: { schwab_rollover_ira: { current_value: 1131896, periods: { '1D': { change: -5510 }, YTD: { change: 20669 } } },
    schwab_roth: { current_value: 54013, periods: { '1D': { change: 341 }, YTD: { change: 1672 } } } },
})

async function fixtures(page: Page, opts: { doNowStatus?: number } = {}) {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url())
    const p = url.pathname
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (p === '/api/v2/home/do-now') return opts.doNowStatus ? json({ ok: false, error: 'unavailable' }, opts.doNowStatus) : json(doNow())
    if (p === '/api/v2/overview') return json(overview())
    if (p === '/api/v2/portfolio/performance') return json(performance())
    if (p === '/api/v2/risk-regime/latest') return json({ regime_label: 'risk_on_trend' })
    if (p === '/api/v2/trade-ai/summary') return json({ vix: 16.7, run_label: '0700', run_date: iso().slice(0, 10) })
    if (p === '/api/v2/defense/posture') return json({ momentum: { rows: [{ sector: 'Technology', etf: 'XLK', state: 'LAGGING', book_pct: 10.4 }, { sector: 'Energy', etf: 'XLE', state: 'LEADING' }] }, hedge_state: { state: 'waiting', line: 'waiting for a bounce day' } })
    if (p === '/api/v3/opportunities') return json({ ok: true, data: { as_of: iso(), items: [{ symbol: 'NAVN', type: 'new_position', conviction: 88, risk_reward: { rr: 4.8 } }] } })
    if (p === '/api/v2/command') return json({ llm_intelligence: { portfolio_risk: 'Portfolio risk: low market risk undercut by no stop coverage across 11 positions.' }, agent_health: [{ agent: 'maria', total_30d: 1645 }] })
    if (p === '/api/v2/inbox' || p === '/api/v2/needs-action') return json({ items: [], all_sources_answered: true, as_of: iso(), sources: {} })
    return json({ ok: true })
  })
}

test('slim header, one Do-now queue, right column, cards and collapsed drawers', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await fixtures(page)
  await page.goto('/v3/')
  await expect(page.getByTestId('home-do-now-page')).toBeVisible()
  await expect(page.getByTestId('home-portfolio')).toContainText('$1,255,076')
  await expect(page.getByTestId('home-today')).toContainText('−$6,795')
  await expect(page.getByTestId('home-ytd')).toContainText('+$25,097')
  await expect(page.getByTestId('home-market')).toContainText('VIX 16.7')
  await expect(page.getByTestId('positions-freshness')).toContainText('STALE')
  await expect(page.getByTestId('refresh-positions')).toHaveAttribute('href', '/v3/portfolio')
  await expect(page.getByTestId('do-now-item').first()).toBeVisible()
  // Every header number has a tooltip that names its source.
  await expect(page.getByTestId('home-portfolio')).toHaveAttribute('title', /\/api\/v2\/overview/)
  await expect(page.getByTestId('home-ytd')).toHaveAttribute('title', /ex|excluding transfers/)

  // ONE queue: top 7, Show all, tabs with counts, one action per row, money-at-risk first.
  const q = page.getByTestId('do-now')
  await expect(q.getByTestId('do-now-item')).toHaveCount(7)
  await expect(q.getByTestId('do-now-item').first()).toContainText('8 positions with no stop')
  await expect(q.getByTestId('do-now-item').first()).toContainText('$410,000 at risk')
  await expect(q.getByTestId('do-now-item').first().getByTestId('do-now-action')).toHaveCount(1)
  await q.getByTestId('do-now-show-all').click()
  await expect(q.getByTestId('do-now-item')).toHaveCount(13)
  await q.getByTestId('do-now-tab-fix').click()
  await expect(q.getByTestId('do-now-item')).toHaveCount(6)
  await q.getByTestId('do-now-tab-protect').click()
  await expect(q.getByTestId('do-now-item')).toHaveCount(4)
  await expect(q.getByTestId('do-now-tab-protect')).toHaveAttribute('aria-pressed', 'true')
  await expect(q.getByTestId('do-now-item').nth(1).getByTestId('do-now-action')).toHaveAttribute('href', '/v3/risk?symbol=SPCX')
  await expect(q.getByTestId('do-now-footer')).toContainText('135 inbox items rolled up')
  await expect(q.getByTestId('do-now-sources')).toContainText('6/6 sources answered')

  // The boxes the queue replaces are gone from the default view (the treemap too).
  await expect(page.getByTestId('needs-action-card')).toHaveCount(0)
  await expect(page.getByText('Operator inbox', { exact: false })).toHaveCount(0)
  await expect(page.getByTestId('home-decision')).toHaveCount(0)

  // Right column.
  await expect(page.getByTestId('home-accounts')).toContainText('Schwab Rollover Ira')
  await expect(page.getByTestId('home-movers').getByTestId('mover-row').first()).toContainText('SPCX')
  await expect(page.getByTestId('num-unprotected')).toContainText('8')
  await expect(page.getByTestId('num-unprotected')).toHaveAttribute('title', /positions_current is not approved for Home/)
  await expect(page.getByTestId('num-heat')).toContainText('0.1%')
  await expect(page.getByTestId('num-cash')).toContainText('65.6%')
  await expect(page.getByTestId('home-opportunities')).toContainText('NAVN')
  await expect(page.getByTestId('home-pulse')).toContainText('Release train')

  // Drawers start collapsed; the closed release drawer carries a STOP shortcut that opens the STOP control.
  for (const d of ['briefing', 'release', 'agents', 'news']) {
    await expect(page.getByTestId(`home-drawer-${d}`).getByRole('button', { expanded: false }).first()).toBeVisible()
  }
  await page.getByTestId('home-release-stop-shortcut').click()
  await expect(page.getByTestId('home-drawer-release').getByTestId('release-stop-button')).toBeVisible()
  await page.getByTestId('home-drawer-briefing').getByRole('button', { expanded: false }).click()
  await expect(page.getByTestId('home-drawer-briefing')).toContainText('no stop coverage across 11 positions')
  expect(errors).toEqual([])
})

test('classic view stays reachable for one release', async ({ page }) => {
  await fixtures(page)
  await page.goto('/v3/')
  await page.getByTestId('classic-view-link').click()
  await expect(page).toHaveURL(/view=classic/)
  await expect(page.getByTestId('needs-action-card')).toBeVisible()
  await expect(page.getByTestId('home-do-now-page')).toHaveCount(0)
  await page.getByTestId('new-home-link').click()
  await expect(page.getByTestId('home-do-now-page')).toBeVisible()
})

test('unavailable queue is never an all-clear', async ({ page }) => {
  await fixtures(page, { doNowStatus: 503 })
  await page.goto('/v3/')
  await expect(page.getByTestId('do-now-unavailable')).toContainText('not an all-clear')
  await expect(page.getByTestId('do-now-clear')).toHaveCount(0)
  await expect(page.getByTestId('num-unprotected')).toContainText('—')
})

test('390px: no horizontal page scroll', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await fixtures(page)
  await page.goto('/v3/')
  await expect(page.getByTestId('do-now-item').first()).toBeVisible()
  const overflow = await page.getByTestId('home-do-now-page').evaluate(el => el.scrollWidth - el.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})
