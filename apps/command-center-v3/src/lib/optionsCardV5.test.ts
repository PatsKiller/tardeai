// node src/lib/optionsCardV5.test.ts — the selection/formatting half of the v5 options cards.
// Fixture = the served DELL credit spread of 2026-09-28 (trimmed). No node:assert (CI tsc has no @types/node).
import {
  flagTone, severityTone, proposalContractLine, proposalStatusChips, proposalHeroMetrics, proposalDetailMetrics,
  proposalInsight, visibleProposalActions, positionHeroMetrics, positionInsight, positionStatusChips, positionContractLine,
} from './optionsCardV5.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: unknown) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

const DELL = {
  id: 'opt_dell', strategy: 'credit_spread', symbol: 'DELL', account: 'schwab_taxable', account_display: 'Schwab Taxable', option_type: 'put',
  short_strike: 520, long_strike: 500, strike: 520, expiration: '2026-11-20', dte: 53, contracts: 1, premium_total: 635, net_credit: 6.35,
  credit_basis: 'executable', underlying_price: 562.89, pop_pct: 58.5, max_profit: 635, max_loss: 1365, breakeven: 513.65, risk_reward: 0.465,
  expected_value: -132.79, edge_score: 70.5, iv_rank: 47.1, severity: 'blocked', edge_severity: 'positive', data_source: 'schwab_chain',
  market_session: 'PRE_MARKET', desk_tier: 'B', auto_eligible: true, execution_mode: 'auto_or_manual', broker: 'schwab',
  action_buttons: [{ action: 'sell_credit_spread', label: 'Sell Credit Spread' }, { action: 'review_chain', label: 'View Chain' }, { action: 'hold', label: 'Pass' }],
  enterprise: { tier: 'B', live_eligible: false, blocks: [{ code: 'awaiting_cio_decision', reason: 'CIO decision: monitor only' }] },
  thesis_blocks: [{ code: 'awaiting_cio_decision', reason: 'CIO decision: monitor only' }],
  economics: { credit_total: 635, collateral: 2000, max_loss_total: 1365, breakeven: 513.65, expected_pl_at_expiry: -132.79, ev_caveat: 'model estimate on a closed-market quote' },
  options_decision_packet: { state: 'BLOCKED', readiness: { cta: 'none' } },
  approvable: false,
  flags: [{ key: 'DEFINED_RISK_INCOME', label: 'Defined-risk income', tone: 'blue' }, { key: 'NOT_APPROVABLE', label: 'Not approvable: awaiting CIO decision', tone: 'red' },
    { key: 'THESIS_COMPLETE', label: 'Thesis complete', tone: 'green' }, { key: 'CLOSED_MARKET_CHAIN', label: 'Closed-market chain', tone: 'amber' }],
  plain_english: { objective: 'Income with a capped worst case.' },
  insight: { headline: 'Thesis is fundamentally sound.', tone: 'warning', drivers: ['Bid/ask spread 6.99% is wide'], source: 'llm', as_of: '2026-09-27T23:22:13+00:00', provenance: 'CIO review dec_df0d22a8', decision: { outcome: 'MONITOR_ONLY', confidence: 'MEDIUM' } },
  generated_at: '2026-09-28T12:18:06+00:00',
}

// tones are one-to-one with server enums
eq('flag tones', ['blue', 'red', 'amber', 'green', 'purple', 'x'].map(flagTone), ['info', 'danger', 'warning', 'success', 'ai', 'neutral'])
eq('blocked reads warning', severityTone('blocked', DELL.flags), 'warning')
eq('blocked + reject reads danger', severityTone('blocked', [{ key: 'CIO_REJECTED' }]), 'danger')
eq('positive', severityTone('positive'), 'success')

eq('contract line', proposalContractLine(DELL), '$520/$500 put spread · Nov 20, 2026 · 53 DTE · 1 contract')

const chips = proposalStatusChips(DELL)
eq('strategy chip first', chips[0], { label: 'Credit Spread', tone: 'info' })
ok('purpose flag folded into the strategy chip', !chips.some(c => c.label === 'Defined-risk income'))
ok('not-live chip carries its guide', chips.some(c => c.label === 'not live eligible' && c.guideKey === 'options.ui.proposal.live_blocked'))
ok('chain source is not a green approval', chips.some(c => c.label === 'Schwab chain' && c.tone === 'neutral'))
ok('truth flags keep their tone', chips.some(c => c.label.startsWith('Not approvable') && c.tone === 'danger'))

const hero = proposalHeroMetrics(DELL)
eq('hero keys', hero.map(m => m.guideKey), ['options.total_credit', 'options.max_loss', 'options.pop', 'options.edge'])
eq('credit value + basis', [hero[0].value, hero[0].meta], ['$635', 'credit basis: executable'])
eq('edge tone from edge_severity, not a threshold', hero[3].tone, 'success')
ok('never more than four hero metrics', hero.length <= 4)
const pp = proposalHeroMetrics({ strategy: 'protective_put', premium_total: 420, economics: { option_cost_total: 420, hedged_max_loss_from_mark: 1580, floor_value_after_premium: 22275, insured_shares: 100, uninsured_shares: 30 } })
eq('protective put hero', pp.map(m => [m.guideKey, m.value]), [['options.total_debit', '$420'], ['options.hedged_max_loss_from_mark', '$1,580'], ['options.floor_value', '$22,275'], ['options.insured_shares', '100 sh (+30 not)']])
const aapl = proposalHeroMetrics({ strategy: 'cash_secured_put', data_source: 'schwab_chain', bid: 2.54, ask: 2.66, premium_total: 260, max_loss: 31990 })
eq('single-leg midpoint is an estimate', [aapl[0].label, aapl[0].meta], ['Credit (mid est.)', 'midpoint estimate, not a fill; bid $2.54 / ask $2.66 per share'])
const xar = proposalHeroMetrics({ strategy: 'protective_put', data_source: 'schwab_chain', bid: 1.90, ask: 11.80, premium_total: 685, economics: { option_cost_total: 685 } })
eq('protective put cost is not an executable ask', [xar[0].label, xar[0].meta], ['Cost (mid est.)', 'midpoint estimate, not a fill; bid $1.90 / ask $11.80 per share'])
const acio = proposalHeroMetrics({ strategy: 'long_call', data_source: 'schwab_chain', bid: 0, ask: 2, premium_total: 100, max_loss: 100 })
eq('one-sided quote withholds headline debit', [acio[0].label, acio[0].value, acio[0].meta], ['Debit unverified', '—', 'no valid two-sided quote; amount withheld'])

const det = proposalDetailMetrics(DELL)
eq('detail: EV signed with model meta', [det[0].guideKey, det[0].value, det[0].meta], ['options.ev', '−$133', 'model estimate'])
ok('detail: breakeven shown without a computed % (plain_english carries it)', det.some(m => m.guideKey === 'options.breakeven' && m.value === '$513.65'))
ok('detail: width from the strikes', det.some(m => m.guideKey === 'options.spread_width' && m.value === '$20'))
ok('withheld expected P/L cannot fall back to legacy value', !proposalDetailMetrics({ ...DELL, expected_value: 999, economics: { expected_pl_at_expiry: null, expected_pl_status: 'withheld: quote not tradeable' } }).some(m => m.guideKey === 'options.ev'))

eq('desk block takes headline priority over positive model insight', proposalInsight(DELL).headline, 'Not approvable: awaiting CIO decision')
eq('server insight wins only when eligible', proposalInsight({ ...DELL, approvable: true, flags: [], enterprise: { live_eligible: true } }).headline, 'Thesis is fundamentally sound.')
const noI = proposalInsight({ ...DELL, insight: undefined })
eq('fallback = NOT_APPROVABLE flag label, warning, blocks as drivers', [noI.headline, noI.tone, noI.drivers, noI.provenance],
  ['Not approvable: awaiting CIO decision', 'warning', ['CIO decision: monitor only', 'CIO decision: monitor only'], 'desk truth flags'])
eq('eligible fallback without flags = objective', proposalInsight({ ...DELL, approvable: true, insight: undefined, flags: [], thesis_blocks: [], enterprise: {} }).headline, 'Income with a capped worst case.')

const acts = visibleProposalActions(DELL, false)
eq('BLOCKED packet hides the execution button', acts.map(a => a.action), ['review_chain', 'hold'])
eq('hold Pass reads Skip', acts.map(a => a.label), ['View Chain', 'Skip'])
eq('review/hold guide keys', acts.map(a => a.guideKey), ['options.ui.actions.review_chain', 'options.ui.actions.hold'])
ok('blocked card with stale READY packet still has no execution action', !visibleProposalActions({ ...DELL, options_decision_packet: { state: 'READY' } }, true).some(a => a.primary))
ok('missing live eligibility also hides execution', !visibleProposalActions({ ...DELL, approvable: true, flags: [], enterprise: {}, options_decision_packet: { state: 'READY' } }, true).some(a => a.primary))
const ready = { ...DELL, approvable: true, flags: [], enterprise: { live_eligible: true }, options_decision_packet: { state: 'READY' } }
const open = visibleProposalActions(ready, false)
eq('unarmed auto route locks execution', open.map(a => [a.action, a.locked, a.guideKey]), [['sell_credit_spread', true, 'options.ui.actions.preflight_locked'], ['review_chain', false, 'options.ui.actions.review_chain'], ['hold', false, 'options.ui.actions.hold']])
eq('armed unlocks', visibleProposalActions(ready, true)[0].locked, false)
eq('manual route never locks', visibleProposalActions({ ...ready, broker: 'fidelity' }, false)[0].guideKey, 'options.ui.actions.preflight_manual')

const POS = { id: 'p1', underlying: 'XAR', side: 'short', option_type: 'put', strike: 210, expiration: '2026-10-17', dte: 19, qty: -1, mark: 1.2, avg_entry: 2.4,
  unrealized_pnl: 120, profit_captured_pct: 50, lifecycle_phase: 'harvest', moneyness: 'OTM', recommended_action: 'Close at 50% of max profit', rationale: 'Harvest rule: half the premium captured',
  delta: -0.18, theta: 4.1, pop_otm_pct: 82, execution_route_badge: 'Schwab live', execution_route_kind: 'schwab_live' }
eq('position contract', positionContractLine(POS), 'short put · $210.00 · Oct 17, 2026 · 19 DTE · qty 1')
const ph = positionHeroMetrics(POS)
eq('position hero', ph.map(m => [m.guideKey, m.value, m.tone]), [['position.unrealized_pnl', '+$120', 'success'], ['options.mark', '$1.20', undefined], ['options.profit_captured_pct', '50%', undefined], ['options.dte', '19', undefined]])
eq('PNL_UNKNOWN never invents a number', positionHeroMetrics({ ...POS, unrealized_pnl: null, pnl_status: 'PNL_UNKNOWN', pnl_unknown_reason: 'no mark' })[0], { guideKey: 'position.unrealized_pnl', label: 'Unrealized P/L', value: 'UNKNOWN', tone: 'neutral', meta: 'no mark' })
const pi = positionInsight(POS)
eq('position takeaway = recommended action, lifecycle tone, rationale driver', [pi.headline, pi.tone, pi.drivers], ['Close at 50% of max profit', 'warning', ['Harvest rule: half the premium captured']])
eq('position chips', positionStatusChips(POS).map(c => [c.label, c.tone]), [['HARVEST', 'warning'], ['OTM', 'success'], ['Schwab live', 'success']])

if (failed) throw new Error(`optionsCardV5: ${failed} failed`)
console.log('[optionsCardV5] ok')
