/** Synthetic fixture only; no live provider calls or data. */
import type { Page } from '@playwright/test'

const NOW = Date.parse('2031-03-10T15:00:00Z')
const iso = (ago = 0) => new Date(NOW - ago).toISOString()
const action = (id: string, category = 'fix') => ({ id, category, severity: 'P2', title: `Example action ${id}`,
  why: `Synthetic evidence ${id}`, action: { label: 'Review', where: '/v3/health' }, sources: ['fixture'] })

export function currentCio(stale = false) {
  return { positions: { source: 'Synthetic CIO positions', as_of: iso(), unprotected_value_usd: 2400,
    rows: [
      { symbol: 'DEMOA', account_id: 'example_income', account_label: 'Example Income', stop_category: 'none', market_value: 2400 },
      { symbol: 'DEMOB', account_id: 'example_growth', account_label: 'Example Growth', stop_category: 'pending_activation', market_value: 600 },
      { symbol: 'DEMOC', account_id: 'example_income', account_label: 'Example Income', stop_category: 'filled', market_value: 500 },
      { symbol: 'DEMOD', account_id: 'example_growth', account_label: 'Example Growth', stop_category: 'active', market_value: 800 },
    ] }, stops: { unprotected_count: 1, stale, last_broker_read_at: iso(),
      gap: stale ? { reason: 'Synthetic broker read is old; review the source clock.' } : null,
      filled_awaiting_sync: [{ symbol: 'DEMOC', account_label: 'Example Income' }] } }
}

export async function homeFixtures(page: Page, opts: { stale?: boolean; unavailable?: boolean } = {}) {
  const writes: string[] = []
  await page.clock.install({ time: new Date(NOW) })
  await page.route('**/api/**', route => {
    const req = route.request(), p = new URL(req.url()).pathname
    if (req.method() !== 'GET') { writes.push(`${req.method()} ${p}`); return route.abort() }
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (p === '/api/v2/cio/pages') return opts.unavailable ? json({}, 503) : json({ ok: true, data: currentCio(opts.stale) })
    if (p === '/api/v2/home/do-now') return opts.unavailable ? json({}, 503) : json({ schema: 'HomeDoNow@v1', as_of: iso(),
      all_sources_answered: true, sources: { fixture: { status: 'OK', as_of: iso() } },
      // These two obsolete assertions must lose to the categorized Risk/CIO record.
      items: [{ ...action('stop:DEMOD', 'protect'), title: 'DEMOD is below its stop' },
        { ...action('stops:unprotected', 'protect'), title: '99 positions with no stop' },
        ...Array.from({ length: 7 }, (_, i) => action(`fix-${i}`)), action('decide-1', 'decide'), action('decide-2', 'decide')],
      numbers: { status: 'OK', unprotected_positions: 99, heat_pct: 0.3, heat_limit_pct: 5, as_of: iso() },
      rolled_up: { raw_items: 19, after_dedupe: 11, inbox_total: 20 } })
    if (p === '/api/v2/overview') return json({ portfolio_value: 20000, today_change: 75, today_pct: 0.375, total_cash: 4000,
      position_count: 4, pending_approvals: 2, pipeline_status: 'fresh', observation: { envelopes: { holdings: { observed_at: iso(), freshness: { status: 'FRESH' } } } },
      top_movers: [{ symbol: 'DEMOA', day_change: 50, account: 'example_income', account_label: 'Example Income' },
        { symbol: 'DEMOA', day_change: 25, account: 'example_growth', account_label: 'Example Growth' }] })
    if (p === '/api/v2/portfolio/performance') return json({ current_value: 20000, periods: { YTD: { display_change: 300, display_change_pct: 1.5 } },
      accounts: { example_income: { account_label: 'Example Income', current_value: 12000, periods: {} }, example_growth: { account_label: 'Example Growth', current_value: 8000, periods: {} } } })
    if (p === '/api/v2/risk-regime/latest') return json({ regime_label: 'example balanced' })
    if (p === '/api/v2/trade-ai/summary') return json({ vix: 18, run_label: '0900', run_date: iso().slice(0, 10) })
    if (p === '/api/v2/defense/posture') return json({ momentum: { rows: [{ sector: 'Example sector', state: 'LAGGING', book_pct: 12 }] } })
    if (p === '/api/v3/opportunities') return json({ ok: true, data: { items: [{ symbol: 'DEMOW', type: 'new_position', conviction: 82, risk_reward: { rr: 3.2 } }] } })
    if (p === '/api/v2/command') return json({ llm_intelligence: { portfolio_risk: 'Synthetic briefing for fixture proof.' }, agent_health: [{ agent: 'Example analyst', total_30d: 3 }] })
    return json({ ok: true, items: [], rows: [], data: {} })
  })
  return writes
}
