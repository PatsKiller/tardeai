/** Options cards v5 (PR4, 2026-09-28) — the pure, testable half of OptionProposalCardV5 and
 *  OptionPositionCardV5. Everything here is FORMATTING and SELECTION of server-supplied
 *  fields: which metrics go in the hero row, which chips describe the row, which server
 *  sentence is the takeaway. No threshold produces a tone or a sentence here (AGENTS §13):
 *  tones map server enums (severity, edge_severity, flag tone, insight tone) one-to-one.
 *  No React import, so `node src/lib/optionsCardV5.test.ts` runs it. */
import type { Tone } from './designTokens'
import type { MetricGuideKey } from './metricGuide.keys.generated.ts'
import { fmt$, fmtNum } from './format.ts'

export type UiInsight = {
  headline: string
  tone: Tone
  drivers?: string[]
  source?: 'rule' | 'llm' | string
  as_of?: string | null
  provenance?: string | null
  decision?: { outcome?: string; confidence?: string; decision_id?: string } | null
}
export type MetricSpec = { guideKey: MetricGuideKey; label: string; value: string; tone?: Tone; meta?: string; values?: Record<string, unknown> }
export type ChipSpec = { label: string; tone: Tone; guideKey?: MetricGuideKey; title?: string }
export type ActionSpec = { action: string; label: string; locked: boolean; primary: boolean; guideKey?: MetricGuideKey }

type AnyRow = Record<string, any>

export const STRATEGY_LABEL: Record<string, string> = {
  covered_call: 'Covered Call', cash_secured_put: 'Cash-Secured Put', long_call: 'Long Call', long_put: 'Long Put',
  credit_spread: 'Credit Spread', protective_put: 'Protective Put', deep_itm_call: 'Deep ITM Call',
  atm_call: 'ATM Call', atm_put: 'ATM Put', short_put: 'Short Put', short_call: 'Short Call',
}
export const EXEC_ACTIONS = new Set(['sell_covered_call', 'sell_put', 'buy_put', 'buy_call', 'sell_credit_spread'])

export function strategyLabel(s?: string | null): string {
  const k = String(s || '')
  return STRATEGY_LABEL[k] || k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Option'
}

/** Server flag/verdict colour words → the closed tone vocabulary. */
export function flagTone(t?: string | null): Tone {
  switch (String(t || '').toLowerCase()) {
    case 'green': case 'teal': case 'success': return 'success'
    case 'red': case 'danger': case 'critical': return 'danger'
    case 'amber': case 'yellow': case 'warning': return 'warning'
    case 'blue': case 'info': return 'info'
    case 'purple': case 'ai': return 'ai'
    default: return 'neutral'
  }
}

/** Card severity enum (server) → tone. `blocked` reads as warning unless a REJECT flag is on the row. */
export function severityTone(severity?: string | null, flags?: Array<{ key?: string }> | null): Tone {
  const s = String(severity || '').toLowerCase()
  if (s === 'blocked') return (flags || []).some(f => /REJECT/i.test(String(f?.key || ''))) ? 'danger' : 'warning'
  if (/crit|urgent|danger/.test(s)) return 'danger'
  if (/warn/.test(s)) return 'warning'
  if (/pos|ready|good/.test(s)) return 'success'
  if (/info/.test(s)) return 'info'
  return 'neutral'
}

export function fmtExpiry(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function fmtIso(ts?: string | null): string {
  if (!ts) return ''
  const s = String(ts)
  return s.length > 16 ? s.slice(0, 16).replace('T', ' ') : s
}

const money = (v: unknown, d = 0) => (v == null || v === '' || Number.isNaN(Number(v)) ? '—' : fmt$(Number(v), d))
const pct = (v: unknown, d = 1) => (v == null || Number.isNaN(Number(v)) ? '—' : `${Number(v).toFixed(d)}%`)
const price = (v: unknown, d = 2) => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }))
const num = (v: unknown, d = 0) => (v == null || Number.isNaN(Number(v)) ? '—' : fmtNum(Number(v), d))
const signed$ = (v: unknown) => (v == null || Number.isNaN(Number(v)) ? '—' : `${Number(v) >= 0 ? '+' : '−'}${fmt$(Math.abs(Number(v)))}`)

/** "$520/$500 put spread · Nov 20, 2026 · 53 DTE" */
export function proposalContractLine(p: AnyRow): string {
  const parts: string[] = []
  if (p.short_strike != null && p.long_strike != null) parts.push(`$${num(p.short_strike)}/$${num(p.long_strike)} ${String(p.option_type || '').toLowerCase()} spread`.trim())
  else if (p.strike != null) parts.push(`$${price(p.strike, Number(p.strike) < 50 ? 2 : 0)} ${String(p.option_type || '').toLowerCase()}`.trim())
  if (p.expiration) parts.push(fmtExpiry(p.expiration))
  if (p.dte != null) parts.push(`${p.dte} DTE`)
  if (p.contracts != null) parts.push(`${p.contracts} contract${Number(p.contracts) === 1 ? '' : 's'}`)
  return parts.join(' · ')
}

/** Status chips: strategy · account · tier · data source · route · live/blocked · truth flags. */
export function proposalStatusChips(p: AnyRow): ChipSpec[] {
  const out: ChipSpec[] = []
  out.push({ label: strategyLabel(p.strategy), tone: 'info' })
  if (p.account_display || p.account) out.push({ label: String(p.account_display || p.account).replace(/_/g, ' '), tone: 'neutral' })
  if (p.desk_tier) out.push({ label: `Tier ${p.desk_tier}`, tone: 'neutral', guideKey: 'options.ui.proposal.desk_tier' })
  if (p.data_source === 'schwab_chain') out.push({ label: 'Schwab chain', tone: 'success', title: 'Live bid/ask from the Schwab option chain' })
  else if (p.data_source === 'bs_estimate') out.push({ label: 'BS estimate', tone: 'warning', title: 'Premium estimated by Black-Scholes; confirm on the chain' })
  if (p.market_session && p.market_session !== 'REGULAR') out.push({ label: String(p.market_session).replace(/_/g, ' ').toLowerCase(), tone: 'neutral' })
  const ent = p.enterprise || {}
  if (ent.live_eligible === true) out.push({ label: 'live eligible', tone: 'success', guideKey: 'options.ui.proposal.live_ok' })
  else if (ent.live_eligible === false) out.push({ label: 'not live eligible', tone: 'warning', guideKey: 'options.ui.proposal.live_blocked' })
  if (p.educational_paper_model) out.push({ label: 'paper lab', tone: 'warning', guideKey: 'options.alpaca_paper_only' })
  for (const f of (p.flags || []) as Array<{ key?: string; label?: string; tone?: string }>) {
    if (!f?.label) continue
    if (/^(INCOME|DEFINED_RISK_INCOME|INSURANCE|DIRECTIONAL)$/.test(String(f.key))) continue // purpose is the strategy chip
    out.push({ label: f.label, tone: flagTone(f.tone) })
  }
  return out
}

/** The four numbers a reader needs first, per strategy family. */
export function proposalHeroMetrics(p: AnyRow): MetricSpec[] {
  const econ = p.economics || {}
  const isCredit = p.cashflow_is_credit === true || (p.cashflow_is_credit == null && p.net_credit != null) || /covered_call|cash_secured_put|credit_spread|short_/.test(String(p.strategy))
  const basis = p.credit_basis ? `credit basis: ${p.credit_basis}` : undefined
  const out: MetricSpec[] = []
  if (p.strategy === 'protective_put') {
    out.push({ guideKey: 'options.total_debit', label: 'Cost', value: money(econ.option_cost_total ?? p.premium_total), tone: 'neutral' })
    out.push({ guideKey: 'options.hedged_max_loss_from_mark', label: 'Hedged max loss', value: money(econ.hedged_max_loss_from_mark), tone: 'warning' })
    out.push({ guideKey: 'options.floor_value', label: 'Floor', value: money(econ.floor_value_after_premium ?? p.floor_value) })
    out.push({ guideKey: 'options.insured_shares', label: 'Insured', value: econ.insured_shares != null ? `${num(econ.insured_shares)} sh${econ.uninsured_shares ? ` (+${num(econ.uninsured_shares)} not)` : ''}` : '—' })
    return out
  }
  out.push({
    guideKey: isCredit ? 'options.total_credit' : 'options.total_debit',
    label: isCredit ? 'Credit' : 'Debit',
    value: money(econ.credit_total ?? p.premium_total), tone: isCredit ? 'success' : 'neutral', meta: basis,
  })
  out.push({ guideKey: 'options.max_loss', label: p.max_loss_label || 'Max loss', value: money(econ.max_loss_total ?? p.max_loss), tone: 'warning' })
  out.push({ guideKey: 'options.pop', label: 'POP', value: pct(p.pop_pct, 1) })
  const edge = p.display_edge_score ?? p.edge_score
  out.push({ guideKey: 'options.edge', label: 'Edge', value: edge != null ? String(Math.round(Number(edge))) : '—', tone: p.edge_severity ? severityTone(p.edge_severity) : undefined })
  return out
}

/** Second row: model and structure numbers. */
export function proposalDetailMetrics(p: AnyRow): MetricSpec[] {
  const econ = p.economics || {}
  const out: MetricSpec[] = []
  const ev = econ.expected_pl_at_expiry ?? p.expected_value
  if (ev != null) out.push({ guideKey: 'options.ev', label: 'Expected P/L', value: signed$(ev), tone: 'neutral', meta: econ.ev_caveat ? 'model estimate' : undefined })
  // The % distance to breakeven is NOT computed here (§13): plain_english.breakeven_line carries it.
  if (p.breakeven != null) out.push({ guideKey: 'options.breakeven', label: p.breakeven_label || 'Breakeven', value: `$${price(p.breakeven)}` })
  if (p.iv_rank != null) out.push({ guideKey: 'options.iv_rank', label: 'IV rank', value: num(p.iv_rank) })
  const rr = p.reward_to_risk ?? p.risk_reward
  if (rr != null) out.push({ guideKey: 'options.rr', label: 'R:R', value: Number(rr).toFixed(2) })
  if (econ.collateral != null) out.push({ guideKey: 'options.collateral', label: 'Collateral', value: money(econ.collateral) })
  if (p.short_strike != null && p.long_strike != null) out.push({ guideKey: 'options.spread_width', label: 'Width', value: `$${num(Math.abs(Number(p.short_strike) - Number(p.long_strike)))}` })
  if (econ.net_cost_if_assigned_per_share != null) out.push({ guideKey: 'options.net_cost_if_assigned', label: 'If assigned', value: `$${price(econ.net_cost_if_assigned_per_share)}/sh${econ.discount_to_spot_pct != null ? ` (${Number(econ.discount_to_spot_pct).toFixed(1)}% below)` : ''}` })
  if (econ.called_away_price_per_share != null) out.push({ guideKey: 'options.called_away_price', label: 'If called away', value: `$${price(econ.called_away_price_per_share)}/sh` })
  if (p.delta != null) out.push({ guideKey: 'options.delta', label: 'Delta', value: Number(p.delta).toFixed(2) })
  if (p.oi != null) out.push({ guideKey: 'options.oi', label: 'OI', value: num(p.oi) })
  return out.slice(0, 6)
}

/** The takeaway: the server insight; else server sentences already on the row. */
export function proposalInsight(p: AnyRow): UiInsight {
  const i = p.insight
  if (i && typeof i === 'object' && i.headline) return i as UiInsight
  const pe = p.plain_english || {}
  const memo = p.committee_memo || {}
  const flags = (p.flags || []) as Array<{ key?: string; label?: string }>
  const notOk = flags.find(f => f?.key === 'NOT_APPROVABLE')
  const head = notOk?.label || pe.objective || memo.plain_summary || p.recommended_action || 'No takeaway on file for this idea.'
  const drivers = [...((p.thesis_blocks || []) as Array<{ reason?: string }>).map(b => b?.reason).filter(Boolean),
    ...(((p.enterprise || {}).blocks || []) as Array<{ reason?: string } | string>).map(b => (typeof b === 'string' ? b : b?.reason)).filter(Boolean)] as string[]
  return { headline: String(head), tone: severityTone(p.severity, flags), drivers: drivers.slice(0, 4), source: 'rule', as_of: p.generated_at || null, provenance: notOk ? 'desk truth flags' : 'plain_english' }
}

/** Same gating as OptionProposalCardV4: packet state hides execution buttons; unarmed locks them. */
export function visibleProposalActions(p: AnyRow, armed: boolean, buttons?: Array<{ action: string; label: string }>): ActionSpec[] {
  const packet = p.options_decision_packet || {}
  const preferred = p.recommendation_comparison?.comparison?.preferred_structure
  const state = packet.state
  const hide = preferred === 'neither' || state === 'BLOCKED' || state === 'REVIEW_REQUIRED' || packet.readiness?.cta === 'none'
  const manualOnly = p.execution_mode === 'manual' || p.broker === 'fidelity' || !p.auto_eligible
  return (buttons || p.action_buttons || []).filter((b: { action: string }) => !(hide && EXEC_ACTIONS.has(b.action))).map((b: { action: string; label: string }) => {
    const exec = EXEC_ACTIONS.has(b.action)
    const locked = exec && !armed && !manualOnly
    const guideKey: MetricGuideKey | undefined = b.action === 'hold' ? 'options.ui.actions.hold'
      : b.action === 'review_chain' ? 'options.ui.actions.review_chain'
        : locked ? 'options.ui.actions.preflight_locked'
          : manualOnly && exec ? 'options.ui.actions.preflight_manual'
            : exec ? 'options.ui.proposal.recommended' : undefined
    return { action: b.action, label: b.label, locked, primary: exec, guideKey }
  })
}

// ── Positions ─────────────────────────────────────────────────────────────

export function positionContractLine(p: AnyRow): string {
  const parts: string[] = []
  const side = p.side ? String(p.side).replace(/_/g, ' ') : ''
  parts.push([side, p.option_type ? String(p.option_type).toLowerCase() : ''].filter(Boolean).join(' ') || strategyLabel(p.strategy))
  if (p.strike != null) parts.push(`$${price(p.strike)}`)
  if (p.expiration) parts.push(fmtExpiry(p.expiration))
  if (p.dte != null) parts.push(`${p.dte} DTE`)
  if (p.qty != null) parts.push(`qty ${num(Math.abs(Number(p.qty)))}`)
  return parts.join(' · ')
}

const LIFECYCLE_TONE: Record<string, Tone> = { let_mature: 'success', harvest: 'warning', defend: 'danger', monitor: 'neutral' }

export function positionStatusChips(p: AnyRow): ChipSpec[] {
  const out: ChipSpec[] = []
  if (p.lifecycle_phase) out.push({ label: String(p.lifecycle_phase).replace(/_/g, ' ').toUpperCase(), tone: LIFECYCLE_TONE[p.lifecycle_phase] || 'neutral', guideKey: 'options.lifecycle_phase' })
  if (p.moneyness) out.push({ label: p.moneyness, tone: p.moneyness === 'ITM' ? 'danger' : p.moneyness === 'OTM' ? 'success' : 'warning', guideKey: 'options.moneyness' })
  if (p.execution_route_badge) out.push({ label: p.execution_route_badge, tone: p.execution_route_kind === 'schwab_live' ? 'success' : 'warning', title: p.execution_note })
  if (p.safety_status_badge?.label) out.push({ label: p.safety_status_badge.label, tone: flagTone(p.safety_status_badge.severity), title: p.safety_status_badge.tip })
  if (p.position_source === 'monitored') out.push({ label: 'monitored', tone: 'neutral' })
  if (p.paper_only) out.push({ label: 'paper only', tone: 'warning', guideKey: 'options.alpaca_paper_only' })
  if (p.account_key) out.push({ label: String(p.account_key).replace(/_/g, ' '), tone: 'neutral' })
  return out
}

export function positionHeroMetrics(p: AnyRow): MetricSpec[] {
  const pnl = p.unrealized_pnl
  const pnlUnknown = p.pnl_status === 'PNL_UNKNOWN' || (pnl == null && p.pnl_unknown_reason)
  return [
    { guideKey: 'position.unrealized_pnl', label: 'Unrealized P/L', value: pnlUnknown ? 'UNKNOWN' : signed$(pnl), tone: pnlUnknown ? 'neutral' : Number(pnl) >= 0 ? 'success' : 'danger', meta: pnlUnknown ? String(p.pnl_unknown_reason || 'no usable mark') : undefined },
    { guideKey: 'options.mark', label: 'Mark', value: p.mark != null ? `$${price(p.mark)}` : '—', meta: p.avg_entry != null ? `entry $${price(p.avg_entry)}` : undefined },
    { guideKey: 'options.profit_captured_pct', label: 'Captured', value: pct(p.profit_captured_pct, 0) },
    { guideKey: 'options.dte', label: 'DTE', value: p.dte != null ? String(p.dte) : '—' },
  ]
}

export function positionDetailMetrics(p: AnyRow): MetricSpec[] {
  const out: MetricSpec[] = []
  if (p.pop_otm_pct != null) out.push({ guideKey: 'options.pop', label: 'P(OTM)', value: pct(p.pop_otm_pct, 0) })
  if (p.delta != null) out.push({ guideKey: 'options.delta', label: 'Delta', value: Number(p.delta).toFixed(2) })
  if (p.theta != null) out.push({ guideKey: 'options.theta', label: 'Theta', value: signed$(p.theta) })
  if (p.vega != null) out.push({ guideKey: 'options.vega', label: 'Vega', value: price(p.vega) })
  if (p.iv_rank != null) out.push({ guideKey: 'options.iv_rank', label: 'IV rank', value: num(p.iv_rank) })
  if (p.margin_usd != null || p.margin_status) out.push({ guideKey: 'options.margin_usd', label: 'Margin', value: p.margin_usd != null ? money(p.margin_usd) : String(p.margin_status || '—'), meta: p.margin_note || undefined })
  if (p.max_profit_at_open != null) out.push({ guideKey: 'options.max_profit', label: 'Max profit', value: money(p.max_profit_at_open) })
  if (p.max_loss_at_open != null) out.push({ guideKey: 'options.max_loss', label: 'Max loss', value: money(p.max_loss_at_open) })
  return out.slice(0, 6)
}

/** Positions carry no server insight yet: the monitor's recommendation and rationale are the takeaway. */
export function positionInsight(p: AnyRow): UiInsight {
  const i = p.insight
  if (i && typeof i === 'object' && i.headline) return i as UiInsight
  const head = p.recommended_action || p.advice_label || 'No recommendation on file for this leg.'
  const tone: Tone = p.lifecycle_phase && LIFECYCLE_TONE[p.lifecycle_phase] ? LIFECYCLE_TONE[p.lifecycle_phase] : severityTone(p.severity)
  const drivers = [p.rationale, p.action_criterion, p.maturity_note].filter(Boolean).map(String)
  return { headline: String(head), tone, drivers: drivers.slice(0, 3), source: 'rule', as_of: p.monitored_at || null, provenance: 'options position monitor' }
}
