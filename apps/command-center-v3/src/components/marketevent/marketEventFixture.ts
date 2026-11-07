/** Synthetic MarketEvent@v1 body for tests and the stub (no real data: this repo is public). */
export const SYNTHETIC_MARKET_EVENT = {
  schema: 'MarketEvent@v1',
  episode: { id: 'ME-SYN-1', state: 'OPEN', title: 'Nov 5–6 selloff', tier: 'RED', opened_at: '2026-11-06T14:30:00Z', baseline_date: '2026-11-04', summary: 'Broad selloff (synthetic)' },
  market_gate: { state: 'not_yet', chips: [{ id: 'mkt', label: 'Market gate: not yet', state: 'partial' }, { id: 'breadth', label: 'Breadth: improving', state: 'pass' }, { id: 'fut', label: 'Futures: n/a', state: 'unknown' }] },
  candidates: [
    { symbol: 'AAA', state: 'READY', rank: 1, baseline_price: 75.1, last_price: 57.5, drawdown_pct: -23.4, beta_expected_drawdown_pct: -14.0, quality_score: 82, discount_score: 71, fwd_pe: 18.2, sector_median_pe: 24.0, peg: 1.3, roic_pct: 19, orders_backlog: null, fell_for_reason: false, reason_evidence: 'sector move, no own catalyst', universe: 'holding',
      gates: [{ id: 'sup', label: 'Holds support (4 sessions)', state: 'pass' }, { id: 'rsi', label: 'RSI turning up', state: 'pass' }, { id: 'obv', label: 'OBV: selling easing', state: 'partial' }, { id: 'sma', label: 'Reclaim SMA20: not yet', state: 'unknown' }],
      plan: { tranches: [
        { n: 1, pct: 30, account_label: 'Account A', shares: 40, usd: 2310, entry_low: 56.5, entry_high: 58.0, condition: null, status: 'now' },
        { n: 2, pct: 30, account_label: 'Account A', shares: null, usd: null, entry_low: null, entry_high: null, condition: 'needs market gate to confirm', status: 'waiting' },
        { n: 3, pct: 40, account_label: 'Account A', shares: null, usd: null, entry_low: null, entry_high: null, condition: 'needs reclaim of SMA20', status: 'waiting' }],
        invalidation: 52.4, risk_usd: 190, risk_budget_usd: 250, notes: ['Account B (IRA): same plan; no wash-sale limit applies in an IRA.'] },
      source: ['market_event_candidates'] },
    { symbol: 'CCC', state: 'STABILIZING', rank: 2, baseline_price: 40, last_price: 27.6, drawdown_pct: -31.0, beta_expected_drawdown_pct: null, quality_score: 71, discount_score: 66, fwd_pe: 14.1, sector_median_pe: null, peg: null, roic_pct: null, orders_backlog: null, fell_for_reason: false, reason_evidence: null, universe: 'stop-out', gates: [], plan: null, source: [] },
    { symbol: 'EEE', state: 'WATCH', rank: 3, baseline_price: 20, last_price: 12.3, drawdown_pct: -38.5, beta_expected_drawdown_pct: null, quality_score: null, discount_score: null, fwd_pe: null, sector_median_pe: null, peg: null, roic_pct: null, orders_backlog: null, fell_for_reason: true, reason_evidence: 'Guidance cut', universe: 'watchlist', gates: [], plan: null, source: [] },
  ],
  accounts: [{ account_label: 'Account A', deployable_usd: 12400, reserve_usd: 650 }, { account_label: 'Account B (IRA)', deployable_usd: 8150, reserve_usd: 430 }],
  computed_at: '2026-11-07T21:30:00-05:00', stale: false,
}
