/** Open option legs for the lifecycle desk tests (2026-10-22).
 *
 *  SYNTHETIC: the live /api/v2/options/open-positions served position_count 0 on 2026-10-22, so these
 *  rows are hand-built. Every field name and value shape follows scripts/options_engine.py:
 *  _monitor_position / monitor_positions exactly (action, action_criterion, lifecycle_phase,
 *  still_working, maturity_note, pnl_status, …), and the rule outcomes are the ones that function
 *  produces for these inputs:
 *    - XYZ short call, ITM, 5 DTE   → roll, "Short call ITM and DTE ≤ 7", defend, not working
 *    - ABC short put, OTM, 30 DTE, POP OTM 82%, gain → close_profit, harvest
 *    - QRS long call, OTM, 60 DTE, no rule fired → hold, monitor
 *    - LMN long put, entry basis missing → PNL_UNKNOWN, hold, monitor
 */
const RUN = '2026-10-22T14:45:10.000000+00:00'

const pos = (o: Record<string, unknown>) => ({ position_source: 'broker', monitored_at: RUN, ...o })

export const OPEN_POSITIONS_FIXTURE = {
  ok: true,
  data: {
    monitored_at: RUN,
    position_count: 4,
    still_working: 3,
    needs_action_count: 2,
    positions: [
      pos({ id: 'XYZ   261023C00050000', unified_id: 'broker:XYZ   261023C00050000', occ_symbol: 'XYZ   261023C00050000', underlying: 'XYZ', account_key: 'schwab_rollover_ira',
        strategy: 'short_call', option_type: 'call', side: 'short', strike: 50, expiration: '2026-10-27', dte: 5, qty: 2, underlying_price: 52.4, mark: 2.6,
        avg_entry: 1.1, entry_credit_debit: 220, unrealized_pnl: -300, pnl_status: 'OK', pnl_unknown_reason: null, moneyness: 'ITM', itm: true,
        pop_otm_pct: 22.0, pop_itm_pct: 78.0, delta: 0.74, profit_captured_pct: 0.0, lifecycle_phase: 'defend',
        maturity_note: 'Assignment risk elevated — roll or close; do not let mature unchecked.', still_working: false,
        recommended_action: 'Roll to Next Expiration', action: 'roll', action_criterion: 'Short call ITM and DTE ≤ 7',
        rationale: 'Short call ITM with ≤7 DTE — assignment risk elevated', severity: 'warning' }),
      pos({ id: 'ABC   261121P00040000', unified_id: 'broker:ABC   261121P00040000', underlying: 'ABC', account_key: 'schwab_roth_ira',
        strategy: 'short_put', option_type: 'put', side: 'short', strike: 40, expiration: '2026-11-21', dte: 30, qty: 1, underlying_price: 46.1, mark: 0.35,
        avg_entry: 1.2, entry_credit_debit: 120, unrealized_pnl: 85, pnl_status: 'OK', moneyness: 'OTM', itm: false,
        pop_otm_pct: 82.0, pop_itm_pct: 18.0, delta: -0.12, profit_captured_pct: 70.8, lifecycle_phase: 'harvest',
        maturity_note: 'Target reached — close to lock premium before theta/assignment risk rises.', still_working: true,
        recommended_action: 'Close for Profit', action: 'close_profit', action_criterion: 'POP OTM ≥ 70% and unrealized P&L > 0',
        rationale: 'Capture premium — 82% still OTM', severity: 'positive' }),
      pos({ id: 'QRS   261218C00100000', unified_id: 'broker:QRS   261218C00100000', underlying: 'QRS', account_key: 'schwab_individual',
        strategy: 'long_call', option_type: 'call', side: 'long', strike: 100, expiration: '2026-12-18', dte: 57, qty: 1, underlying_price: 96.0, mark: 4.1,
        avg_entry: 4.5, entry_credit_debit: -450, unrealized_pnl: -40, pnl_status: 'OK', moneyness: 'OTM', itm: false,
        pop_otm_pct: 58.0, pop_itm_pct: 42.0, delta: 0.45, profit_captured_pct: null, lifecycle_phase: 'monitor',
        maturity_note: 'Long call: OTM, 57 DTE — watch mark vs entry.', still_working: true,
        recommended_action: 'Hold', action: 'hold', action_criterion: 'Long call — no cut/take-profit threshold met',
        rationale: 'Long call: OTM, 57 DTE', severity: 'info' }),
      pos({ id: 'LMN   261120P00020000', unified_id: 'broker:LMN   261120P00020000', underlying: 'LMN', account_key: 'schwab_individual',
        strategy: 'long_put', option_type: 'put', side: 'long', strike: 20, expiration: '2026-11-20', dte: 29, qty: 3, underlying_price: 22.0, mark: 0.55,
        avg_entry: null, entry_credit_debit: null, unrealized_pnl: null, pnl_status: 'PNL_UNKNOWN', pnl_unknown_reason: 'missing avg_entry / fill basis',
        moneyness: 'OTM', itm: false, pop_otm_pct: 80.0, pop_itm_pct: 20.0, delta: -0.2, profit_captured_pct: null, lifecycle_phase: 'monitor',
        maturity_note: 'Long put: OTM, 29 DTE — watch mark vs entry.', still_working: true,
        recommended_action: 'Hold', action: 'hold', action_criterion: 'Long put — no cut/take-profit threshold met',
        rationale: 'Long put: OTM, 29 DTE', severity: 'info' }),
    ],
    alerts: [
      { id: 'XYZ   261023C00050000', underlying: 'XYZ', severity: 'warning', message: 'Short call ITM with ≤7 DTE — assignment risk elevated', action: 'Roll to Next Expiration' },
      { id: 'ABC   261121P00040000', underlying: 'ABC', severity: 'positive', message: 'Capture premium — 82% still OTM', action: 'Close for Profit' },
    ],
    summary: { itm_count: 1, otm_count: 3, total_unrealized_pnl: -255 },
    filtered_count: 4,
    unified_count: 4,
    monitored_count: 0,
    paper_lab_retired: true,
  },
}
