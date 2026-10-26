/** Ticker Prospectus — synthetic fixtures for the e2e spec (public repo: made-up tickers and numbers only; no
 *  holdings, accounts or real companies). Shapes follow handoffs/prospectus-20261026/CONTRACT.md. */
import type { ProspectusDoc, ProspectusIndex } from '../lib/prospectusModel'

export const PROSPECTUS_INDEX: ProspectusIndex = {
  items: [
    { symbol: 'ACME', name: 'Acme Synthetic Corp', scope: 'holding', version: '20261026T120000Z', generated_at: '2026-10-26T12:00:00Z', model: 'claude-fable-5-1', cost_usd: 1.25, status: 'ready', stale: false, next_due: '2026-11-26', verdict_line: 'Hold: moat intact, valuation full; trim above the upper band.' },
    { symbol: 'BETA', name: 'Beta Fixture Industries', scope: 'holding', version: '20261001T120000Z', generated_at: '2026-10-01T12:00:00Z', model: 'claude-opus-5-5', cost_usd: 0.6, status: 'ready', stale: true, next_due: '2026-10-25', verdict_line: 'Add on pullbacks: margins expanding for three quarters.' },
    { symbol: 'GAMMA', name: 'Gamma Test Labs', scope: 'holding', version: null, generated_at: null, model: 'claude-opus-5-5', cost_usd: null, status: 'failed', stale: false, next_due: null, verdict_line: null, failure_reason: 'Writer refused: too few cited facts (2 of 6 required)' },
    { symbol: 'DELTA', name: 'Delta Mock Rail', scope: 'watch', version: null, generated_at: null, model: null, cost_usd: null, status: 'missing', stale: false, next_due: '2026-10-27', verdict_line: null },
    { symbol: 'EPSI', name: 'Epsilon Sample Energy', scope: 'watch', version: null, generated_at: null, model: 'claude-opus-5-5', cost_usd: null, status: 'queued', stale: false, next_due: '2026-10-26', verdict_line: null },
    { symbol: 'ZETA', name: 'Zeta Placeholder Bio', scope: 'watch', version: null, generated_at: null, model: 'claude-opus-5-5', cost_usd: null, status: 'running', stale: false, next_due: null, verdict_line: null },
    { symbol: 'THETA', name: 'Theta Demo Software', scope: 'watch', version: '20261020T120000Z', generated_at: '2026-10-20T16:30:00Z', model: 'claude-opus-5-5', cost_usd: 0.42, status: 'ready', stale: false, next_due: '2027-01-20', verdict_line: 'Watch: needs two quarters of positive free cash flow first.' },
  ],
  totals: { ready: 3, queued: 1, missing: 1, failed: 1 },
  budget: { credit_remaining_usd: 150.25, today_used_usd: 6.5, daily_cap_usd: 25 },
}

const cite = (id: string, source: string, url?: string) => ({ id, source, as_of: '2026-10-25', ...(url ? { url } : {}) })

export const PROSPECTUS_ACME: ProspectusDoc = {
  symbol: 'ACME', name: 'Acme Synthetic Corp', scope: 'holding', version: '20261026T120000Z', generated_at: '2026-10-26T12:00:00Z',
  model: 'claude-fable-5-1', status: 'ready', stale: false,
  verdict_line: 'Hold: moat intact, valuation full; trim above the upper band.',
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
