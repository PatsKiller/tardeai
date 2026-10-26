/** Ticker Prospectus — synthetic fixtures for the e2e spec (public repo: made-up tickers and numbers only; no
 *  holdings, accounts or real companies). Shapes follow handoffs/prospectus-20261026/CONTRACT.md. */
import type { ProspectusBlocks, ProspectusDoc, ProspectusIndex } from '../lib/prospectusModel'

export const PROSPECTUS_INDEX: ProspectusIndex = {
  items: [
    { symbol: 'ACME', name: 'Acme Synthetic Corp', scope: 'holding', version: '20261026T120000Z', generated_at: '2026-10-26T12:00:00Z', model: 'claude-fable-5-1', cost_usd: 1.25, status: 'ready', stale: false, next_due: '2026-11-26', verdict_line: 'HOLD — moat intact, valuation full; trim above the upper band.' },
    { symbol: 'BETA', name: 'Beta Fixture Industries', scope: 'holding', version: '20261001T120000Z', generated_at: '2026-10-01T12:00:00Z', model: 'claude-opus-5-5', cost_usd: 0.6, status: 'ready', stale: true, next_due: '2026-10-25', verdict_line: 'Add on pullbacks: margins expanding for three quarters.' },
    { symbol: 'GAMMA', name: 'Gamma Test Labs', scope: 'holding', version: null, generated_at: null, model: 'claude-opus-5-5', cost_usd: null, status: 'failed', stale: false, next_due: null, verdict_line: null, failure_reason: 'Writer refused: too few cited facts (2 of 6 required)' },
    { symbol: 'DELTA', name: 'Delta Mock Rail', scope: 'watch', version: null, generated_at: null, model: null, cost_usd: null, status: 'missing', stale: false, next_due: '2026-10-27', verdict_line: null },
    { symbol: 'EPSI', name: 'Epsilon Sample Energy', scope: 'watch', version: null, generated_at: null, model: 'claude-opus-5-5', cost_usd: null, status: 'queued', stale: false, next_due: '2026-10-26', verdict_line: null },
    { symbol: 'ZETA', name: 'Zeta Placeholder Bio', scope: 'watch', version: null, generated_at: null, model: 'claude-opus-5-5', cost_usd: null, status: 'running', stale: false, next_due: null, verdict_line: null },
    { symbol: 'THETA', name: 'Theta Demo Software', scope: 'watch', version: '20261020T120000Z', generated_at: '2026-10-20T16:30:00Z', model: 'claude-opus-5-5', cost_usd: 0.42, status: 'partial', stale: false, next_due: '2027-01-20', verdict_line: 'Watch: needs two quarters of positive free cash flow first.' },
  ],
  totals: { ready: 2, queued: 1, missing: 1, failed: 1 },
  budget: { credit_remaining_usd: 150.25, today_used_usd: 6.5, daily_cap_usd: 25 },
}

// Rebased-100 lines for one window: deterministic made-up paths.
function line(name: string, n: number, drift: number, wobble: number): { name: string; points: [string, number][] } {
  const pts: [string, number][] = []
  for (let i = 0; i < n; i++) {
    const d = new Date(Date.UTC(2026, 9, 26) - (n - 1 - i) * 7 * 86_400_000).toISOString().slice(0, 10)
    pts.push([d, Math.round((100 + drift * i / (n - 1) + wobble * Math.sin(i / 2)) * 100) / 100])
  }
  return { name, points: pts }
}
const relWin = (n: number, k: number) => [line('ACME', n, 18 * k, 2), line('XLK', n, 11 * k, 1.5), line('SPY', n, 9 * k, 1.2), line('QQQ', n, 13 * k, 1.8)]

export const ACME_BLOCKS: ProspectusBlocks = {
  relative_performance: {
    series: { '3M': relWin(13, 0.3), YTD: relWin(43, 0.8), '1Y': relWin(52, 1), '3Y': relWin(80, 2.4) },
    returns: [
      { name: 'ACME', '1W': 1.2, '1M': 3.4, '3M': 6.1, YTD: 14.2, '1Y': 18.0, '3Y': 41.5 },
      { name: 'XLK', '1W': 0.8, '1M': 2.1, '3M': 4.0, YTD: 9.9, '1Y': 11.0, '3Y': 30.2 },
      { name: 'SPY', '1W': 0.5, '1M': 1.6, '3M': 3.2, YTD: 8.1, '1Y': 9.0, '3Y': 24.0 },
      { name: 'QQQ', '1W': 0.9, '1M': 2.5, '3M': 4.4, YTD: 11.3, '1Y': 13.0, '3Y': 33.1 },
    ],
    excess_vs_spy: { '1W': 0.7, '1M': 1.8, '3M': 2.9, YTD: 6.1, '1Y': 9.0, '3Y': 17.5 },
    rank_in_industry: { rank: 3, of: 14, percentile: 86 }, rs_rating_12m: 81,
    sector_trend: { sector: 'Technology', trend: 'Leading' }, benchmarks: ['XLK', 'SPY', 'QQQ'],
    gaps: ['industry-group series: no rebased series in the house (momentum snapshot only)'],
  },
  peer_comparison: {
    industry: 'Fictional Widgets', fields: ['market_cap_b', 'forward_pe', 'ev_ebitda', 'sales_growth_past_5y_pct', 'oper_margin_pct', 'roe_pct', 'div_yield_pct', 'total_debt_equity', 'perf_year_pct'],
    rows: [
      { symbol: 'ACME', is_subject: true, market_cap_b: 12.4, forward_pe: 24, ev_ebitda: null, sales_growth_past_5y_pct: 8.2, oper_margin_pct: 21.5, roe_pct: 18.1, div_yield_pct: 1.2, total_debt_equity: 0.4, perf_year_pct: 18.0, consensus: 'Buy' },
      { symbol: 'PEER1', market_cap_b: 9.1, forward_pe: 18, ev_ebitda: null, sales_growth_past_5y_pct: 5.1, oper_margin_pct: 15.2, roe_pct: 12.4, div_yield_pct: 2.1, total_debt_equity: 0.8, perf_year_pct: 6.0, consensus: 'Hold' },
      { symbol: 'PEER2', market_cap_b: 15.8, forward_pe: 19, ev_ebitda: null, sales_growth_past_5y_pct: 6.3, oper_margin_pct: 17.0, roe_pct: 14.9, div_yield_pct: 1.8, total_debt_equity: 0.6, perf_year_pct: 10.5, consensus: 'Buy' },
      { symbol: 'PEER3', market_cap_b: 7.2, forward_pe: 21, ev_ebitda: null, sales_growth_past_5y_pct: 4.0, oper_margin_pct: 12.8, roe_pct: 9.9, div_yield_pct: 0.0, total_debt_equity: 1.1, perf_year_pct: -3.0, consensus: null },
    ],
    median: { market_cap_b: 9.1, forward_pe: 19, ev_ebitda: null, sales_growth_past_5y_pct: 5.1, oper_margin_pct: 15.2, roe_pct: 12.4, div_yield_pct: 1.8, total_debt_equity: 0.8, perf_year_pct: 6.0 },
    gaps: ['EV/EBITDA and net debt/EBITDA are not in the house fundamentals (Debt/Equity shown)'],
  },
  estimates: { eps_surprises: [{ date: '2026-08-12', actual: 1.45, estimate: 1.38, surprise_pct: 5.1 }], revisions_90d: { up: null, down: null }, next_report: '2026-11-12',
    gaps: ['EPS surprise history: the house keeps the latest quarter only (1 of 4)', '90-day estimate revisions: not in the house'] },
  ownership_flows: { institutional_pct: 71.2, short_float_pct: 2.4, days_to_cover: 1.9, insider_buys_90d: null, insider_sells_90d: null, etf_flows_30d: null, top_holders: null },
  risk_technicals: { beta_1y: 1.08, vol_annualized_pct: 24.6, max_drawdown_1y_pct: -12.3, correlation_to_book: 0.62, px_vs_sma50_pct: 3.1, px_vs_sma200_pct: 9.4, rsi14: 58.2, atr20: 1.12 },
  scenarios: { cases: [
    { case: 'bear', price: 44, probability_pct: 20, narrative: 'Margins slip below 40% and a top customer leaves.' },
    { case: 'base', price: 58, probability_pct: 55, narrative: 'Steady compounding; the multiple holds.' },
    { case: 'bull', price: 70, probability_pct: 25, narrative: 'Product refresh lands and peers lose share.' },
  ] },
  macro_sensitivity: { series: {
    DGS10: { label: '10-year Treasury yield', value: 4.1, as_of: '2026-10-23', chg_3m: 0.2, trend: 'rising', effect: 'headwind' },
    T10Y2Y: { label: 'Yield curve 10y–2y', value: 0.35, as_of: '2026-10-23', chg_3m: 0.1, trend: 'rising' },
    UNRATE: { label: 'Unemployment rate', value: 4.2, as_of: '2026-10-03', chg_3m: 0, trend: 'flat' },
  }, rate_beta_10y: -0.0012, next_events: [{ name: 'CPI', date: '2026-11-13' }, { name: 'FOMC', date: '2026-12-09' }] },
  sec_filings: { filings: [
    { form: '10-Q', filed_at: '2026-08-05', url: 'https://example.com/acme-10q', what_changed: 'Segment margin disclosure added' },
    { form: '8-K', filed_at: '2026-09-15', url: null, what_changed: 'New supply agreement' },
  ], form4_90d: { buys: 1, sells: 3 } },
  earnings_call: { bullets: ['Guidance raised one notch for the full year', 'Tone more confident than last call'], transcripts: [] },
  options_sentiment_dividends: { iv_pct: 27.5, iv_rank: null, put_call: null, unusual_flow: null, news_sentiment: { label: 'positive' }, social: null,
    dividend: { yield_pct: 1.2, annual_per_share: 0.6 }, debate: { verdict: 'agree' } },
}

export const ACME_FACTS = [
  { id: 'F1', kind: 'cio', label: 'CIO conviction', value: 72 },
  { id: 'F2', kind: 'price', label: 'Last close', value: 51 },
  { id: 'F3', kind: 'price', label: 'Day change %', value: 0.8 },
  { id: 'F4', kind: 'position', label: 'Market value $', value: 5100 },
  { id: 'F5', kind: 'position', label: 'Unrealized P/L $', value: 600 },
  { id: 'F6', kind: 'position', label: 'Unrealized P/L %', value: 13.3 },
  { id: 'F7', kind: 'position', label: 'Recorded protective stop level (Example Account, broker)', value: 42 },
  { id: 'F8', kind: 'position', label: 'Distance from last close to stop % (Example Account)', value: -17.6 },
  { id: 'F9', kind: 'fundamental', label: 'Dividend yield %', value: 1.2 },
]

export const ACME_COVERAGE = { domains: [
  { domain: 'holdings_accounts', status: 'used' }, { domain: 'broker_stops', status: 'used' }, { domain: 'prices', status: 'used' },
  { domain: 'fundamentals', status: 'used' }, { domain: 'sec_filings', status: 'used' }, { domain: 'fred_macro', status: 'used' },
  { domain: 'earnings_transcripts', status: 'stale', as_of: '2026-08-06' }, { domain: 'social_posts', status: 'stale', as_of: '2026-10-01' },
  { domain: 'private_company_proxy', status: 'not_applicable', reason: 'public company' }, { domain: 'yfinance_snapshot', status: 'failed', reason: 'timeout' },
], key_gaps: [] }

const cite = (id: string, source: string, url?: string) => ({ id, source, as_of: '2026-10-25', ...(url ? { url } : {}) })

export const PROSPECTUS_ACME: ProspectusDoc = {
  symbol: 'ACME', name: 'Acme Synthetic Corp', scope: 'holding', version: '20261026T120000Z', generated_at: '2026-10-26T12:00:00Z',
  model: 'claude-fable-5-1', status: 'ready', stale: false, next_due: '2026-11-26',
  verdict_line: 'HOLD — moat intact, valuation full; trim above the upper band.',
  blocks: ACME_BLOCKS, facts: ACME_FACTS, source_coverage: ACME_COVERAGE, inputs_digest: { cio_stance: 'HOLD' },
  sections: [
    { id: 'summary_verdict', title: 'Summary verdict', body_md: '**Hold.** The business compounds at a steady pace [c1] while the multiple already prices most of it [c2].\n\n- Keep the protective level in place\n- Revisit after the next report', citations: [cite('c1', 'house financials'), cite('c2', 'house valuation')] },
    { id: 'business_and_moat', title: 'Business and moat', body_md: 'Acme sells fictional widgets to fictional factories. Switching costs are high because tooling is custom [c3].', citations: [cite('c3', 'company profile')] },
    { id: 'financials_and_trend', title: 'Financials and trend', body_md: '## Revenue\nRevenue rose from 10.0 to 12.4 over four periods [c4].\n\n## Earnings\nEPS rose from 1.10 to 1.45 [c4].', citations: [cite('c4', 'house financials')] },
    { id: 'valuation_vs_peers', title: 'Valuation vs peers', body_md: 'Trades at 24x versus a peer median of 19x [c5].', citations: [cite('c5', 'peer table')] },
    { id: 'catalysts_and_dates', title: 'Catalysts and dates', body_md: '1. Next report on Nov 12 [c6]\n2. Product refresh in Q1 [c6]', citations: [cite('c6', 'catalyst calendar', 'https://example.com/acme-calendar')] },
    { id: 'risks', title: 'Risks', body_md: '- Customer concentration: top two buyers are 30% of sales [c7]\n- Input costs', citations: [cite('c7', 'annual filing')] },
    { id: 'analyst_view', title: 'Analyst view', body_md: 'Twelve analysts; mean target 58 with a range of 44 to 70 [c8].', citations: [cite('c8', 'analyst targets')] },
    { id: 'thesis_breakers', title: 'Thesis breakers', body_md: '- Gross margin below 40% for two quarters\n- Loss of either top customer', citations: [] },
    { id: 'position_and_plan', title: 'Position and plan', body_md: 'Held in the *Example Account*. Protective level at 42; add zone 45–47 [c9].', citations: [cite('c9', 'house position record')] },
  ],
  charts: [
    { id: 'price_1y', type: 'line', title: 'Price, 1 year', series: [{ name: 'Close', points: [['2025-11', 40], ['2026-01', 44], ['2026-03', 47], ['2026-05', 45], ['2026-07', 50], ['2026-09', 52], ['2026-10', 51]] }],
      annotations: [{ kind: 'stop', label: 'Stop 42', y: 42 }, { kind: 'entry', label: 'Entry 45', y: 45 }] },
    { id: 'revenue_eps_trend', type: 'bar', title: 'Revenue and EPS', series: [{ name: 'Revenue', points: [['FY23', 10], ['FY24', 11.1], ['FY25', 11.8], ['FY26', 12.4]] }, { name: 'EPS', points: [['FY23', 1.1], ['FY24', 1.2], ['FY25', 1.33], ['FY26', 1.45]] }] },
    { id: 'valuation_vs_peers', type: 'bar', title: 'P/E vs peers', series: [{ name: 'P/E', points: [['ACME', 24], ['PEER1', 18], ['PEER2', 19], ['PEER3', 21]] }] },
    { id: 'analyst_targets', type: 'range', title: 'Analyst targets', series: [{ name: 'Mean', points: [['mean', 58]] }], annotations: [{ kind: 'range', low: 44, high: 70 }, { kind: 'current', label: 'Price', y: 51 }] },
  ],
  versions: [
    { version: '20261026T120000Z', generated_at: '2026-10-26T12:00:00Z', model: 'claude-fable-5-1' },
    { version: '20260926T120000Z', generated_at: '2026-09-26T12:00:00Z', model: 'claude-opus-5-5' },
  ],
}

export const PROSPECTUS_ACME_OLD: ProspectusDoc = {
  ...PROSPECTUS_ACME, version: '20260926T120000Z', generated_at: '2026-09-26T12:00:00Z', model: 'claude-opus-5-5',
  sections: [{ id: 'summary_verdict', title: 'Summary verdict', body_md: 'Older version: **Add** below 46.', citations: [] }],
  charts: [],
}

export const PROSPECTUS_BETA: ProspectusDoc = {
  symbol: 'BETA', name: 'Beta Fixture Industries', scope: 'holding', version: '20261001T120000Z', generated_at: '2026-10-01T12:00:00Z',
  model: 'claude-opus-5-5', status: 'ready', stale: true,
  sections: [{ id: 'summary_verdict', title: 'Summary verdict', body_md: 'Add on pullbacks [c1].', citations: [cite('c1', 'house financials')] }],
  charts: [], versions: [{ version: '20261001T120000Z', generated_at: '2026-10-01T12:00:00Z', model: 'claude-opus-5-5' }],
}

export const PROSPECTUS_GAMMA_FAILED: ProspectusDoc = {
  symbol: 'GAMMA', name: 'Gamma Test Labs', scope: 'holding', status: 'failed', failure_reason: 'Writer refused: too few cited facts (2 of 6 required)', sections: [], charts: [], versions: [],
}

/** Partial report with no institutional blocks at all: every block must show "not available yet", never crash. */
export const PROSPECTUS_THETA_PARTIAL: ProspectusDoc = {
  symbol: 'THETA', name: 'Theta Demo Software', scope: 'watch', version: '20261020T120000Z', generated_at: '2026-10-20T16:30:00Z',
  model: 'claude-opus-5-5', status: 'partial', stale: false, partial_gaps: ['prices: empty (no house closes)'],
  verdict_line: 'WATCH — needs two quarters of positive free cash flow first.',
  sections: [{ id: 'summary_verdict', title: 'Summary verdict', body_md: 'Watch only.', citations: [] }, { id: 'risks', title: 'Risks', body_md: '- Cash burn', citations: [] }],
  charts: [], versions: [{ version: '20261020T120000Z', generated_at: '2026-10-20T16:30:00Z', model: 'claude-opus-5-5' }],
}
