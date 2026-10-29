/** Prospectus "My history" + fund profile — synthetic fixtures for e2e/prospectus-my-history.spec.ts (public repo:
 *  made-up tickers, accounts and numbers only). Shapes follow scripts/lib/prospectus/my_history.py (MyHistory@v1) and
 *  etf_profile.py (fund_profile). Three round trips: a win, a loss re-bought 10 days later (wash-sale window) and a win. */
import type { FundProfile, MyHistory } from '../lib/myHistoryModel'
import type { ProspectusDoc } from '../lib/prospectusModel'
import { PROSPECTUS_ACME } from './prospectus.fixture'

export const MY_HISTORY_FIXTURE: MyHistory = {
  scope: 'held',
  open_lots: [
    { account: 'Fixture Brokerage', shares: 30, avg_cost: 60, market_value: 2100, unrealized_usd: 300, unrealized_pct: 16.67,
      acquired_first: '2026-04-25', holding_days: 184, term: 'short', tax_character: 'taxable', lot_dating: 'fifo_reconciled' },
    { account: 'Fixture Roth IRA', shares: 10, avg_cost: 55, market_value: 700, unrealized_usd: 150, unrealized_pct: 27.27,
      acquired_first: '2026-05-15', holding_days: 164, term: 'short', tax_character: 'tax-advantaged', lot_dating: 'unreconciled',
      lot_dating_note: 'journal FIFO holds 0 shares vs 10 in the position store' },
  ],
  current_hold: { since: '2026-04-25', days: 184, while_held: [
    { date: '2026-06-04', kind: 'catalyst', type: 'analyst_upgrade', headline: 'Fixture bank upgrades ACME', next_day_pct: 2.1, five_day_pct: 3.4 },
  ] },
  trips: [
    { trip: 1, account: 'Fixture Brokerage', entry_date: '2025-03-21', entry_price: 52, exit_date: '2025-05-20', exit_price: 58, shares: 20,
      hold_days: 60, realized_usd: 120, realized_pct: 11.54, r_multiple: null, origin: 'watchlist', sources_before_entry: ['watchlist'],
      thesis_at_entry: 'Synthetic widget demand thesis.', journaled: false, stopped_out: false, term: 'short', tax_character: 'taxable',
      entry_vs_52w_range_pct: 41, while_held: [] },
    { trip: 2, account: 'Fixture Brokerage', entry_date: '2025-06-29', entry_price: 61, exit_date: '2025-08-08', exit_price: 55, shares: 25,
      hold_days: 40, realized_usd: -150, realized_pct: -9.84, r_multiple: -1, origin: 'research', sources_before_entry: ['watchlist', 'hermes_research'],
      thesis_at_entry: 'Synthetic widget demand thesis.', journaled: true, journal: { realized_r: -1, lesson: 'Chased the breakout near the high.', exit_type: 'hard_stop' },
      stopped_out: true, term: 'short', tax_character: 'taxable', entry_vs_52w_range_pct: 88,
      wash_sale: { flag: true, window: ['2025-07-09', '2025-09-07'], replacements: [{ account: 'Fixture Brokerage', date: '2025-08-18', shares: 15, when: 'after_sale' }], evidence: 'trade_transactions sale row' },
      while_held: [
        { date: '2025-07-19', kind: 'earnings', type: 'earnings_beat', headline: 'ACME beats synthetic estimates', next_day_pct: -0.9, five_day_pct: -5.16 },
        { date: '2025-08-08', kind: 'stop_fill', type: 'stop filled', headline: 'Stop filled at 55 (Fixture Brokerage)', next_day_pct: 0.15, five_day_pct: 2.07 },
      ] },
    { trip: 3, account: 'Fixture Brokerage', entry_date: '2025-08-18', entry_price: 54, exit_date: '2025-10-17', exit_price: 63, shares: 15,
      hold_days: 60, realized_usd: 135, realized_pct: 16.67, r_multiple: 1.8, origin: 'research', sources_before_entry: ['watchlist', 'hermes_research'],
      journaled: true, journal: { realized_r: 1.8, lesson: 'Waited for the pullback; patience paid.', exit_type: 'trailing_stop' },
      stopped_out: true, term: 'short', tax_character: 'taxable', entry_vs_52w_range_pct: 35,
      while_held: [{ date: '2025-10-07', kind: 'big_move', type: null, move_pct: 12.4, next_day_pct: -1.2, five_day_pct: 0.8 }] },
  ],
  totals: { trips: 3, wins: 2, losses: 1, win_rate_pct: 66.7, realized_usd: 105, avg_win_usd: 127.5, avg_loss_usd: -150, avg_win_pct: 14.11,
    avg_loss_pct: -9.84, avg_hold_days: 53.33, best: { trip: 3, realized_usd: 135, realized_pct: 16.67 }, worst: { trip: 2, realized_usd: -150, realized_pct: -9.84 } },
  lessons: {
    stats: [
      { id: 'payoff', label: 'payoff ratio (average win $ ÷ |average loss $|)', value: 0.85, unit: '', n: 3 },
      { id: 'stop_rate', label: 'share of journaled trips that ended at a stop %', value: 100, unit: '%', n: 2 },
      { id: 'reentry_after_loss', label: 'losing trips followed by a re-entry within 30 days', value: 1, unit: '', n: 1 },
    ],
    journal_notes: [{ trip: 2, lesson: 'Chased the breakout near the high.' }, { trip: 3, lesson: 'Waited for the pullback; patience paid.' }],
  },
  tax: {
    flags: [{ trip: 2, kind: 'wash_sale', sale_date: '2025-08-08', replacement_dates: ['2025-08-18'] }],
    accounts: [{ account: 'Fixture Brokerage', character: 'taxable' }, { account: 'Fixture Roth IRA', character: 'tax-advantaged' }],
    open_window: null, note: 'FIFO_FROM_TRADE_TRANSACTIONS — verify with your tax context.',
  },
  writer_note: { summary: 'You hold 40 shares at an average cost near $58.75 and are up $450 on the open lots; across three round trips you realized +$105.', lessons: 'Your stopped-out trip was the one bought near the top of its range.' },
  gaps: [],
}

export const FUND_PROFILE_FIXTURE: FundProfile = {
  category: 'Aerospace & Defense', category_basis: 'config symbol map', sector: 'Industrials', sector_etf: 'XLI', peers: ['PEERF1', 'PEERF2'],
  expense_ratio_pct: 0.35, aum_usd: null, dividend_yield_pct: 0.21, ttm_distribution: 0.4, last_distribution: 0.11,
  last_distribution_date: '2026-09-21', distribution_cadence: 'quarterly', next_distribution_est: '2026-12-21',
  top_holdings: [{ name: 'HOLD1', weight_pct: 4.1 }, { name: 'HOLD2', weight_pct: 3.9 }], top10_weight_pct: 8,
  dividend_history: [{ ex_date: '2026-09-21', amount: 0.11 }], analyst_look_through_pct: 12.5, analyst_basis: 'holdings look-through (5 constituents)',
  gaps: ['assets under management: not held in any house store (symbol_profiles / enrichment cache)'],
}

export const PROSPECTUS_ACME_MY_HISTORY: ProspectusDoc = {
  ...PROSPECTUS_ACME,
  blocks: { ...(PROSPECTUS_ACME.blocks ?? {}), my_history: MY_HISTORY_FIXTURE, fund_profile: FUND_PROFILE_FIXTURE } as ProspectusDoc['blocks'],
}

export const PROSPECTUS_ACME_NEVER_TRADED: ProspectusDoc = {
  ...PROSPECTUS_ACME,
  blocks: { ...(PROSPECTUS_ACME.blocks ?? {}), my_history: { scope: 'never_traded', gaps: [] } } as ProspectusDoc['blocks'],
}
