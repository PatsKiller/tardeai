import { useState } from 'react'
import { fmt$, fmtNum } from '../lib/format'
import { plainEnglishProposal, proposalRiskFlags, strikeDistance, strategyGuide } from '../lib/optionsNovice'
import { ACTIONS, PROPOSAL } from '../lib/optionsTooltips'
import { RiskFlagChips, StrikeDistanceBar, WhatIfBox } from './OptionsNovicePanel'
import { composeWhy } from '../lib/watchlistCardV4'
import { WL, numStyle } from '../lib/watchlistCardTokens'
import {
  alpacaPaperButtonLabel,
  allowsManualLog,
  cashflowColor,
  cashflowIsCredit,
  executionRouteBadge,
  isCardBlocked,
  liquidityWarnings,
  optionCashflowLabel,
  plainEnglishHint,
  primeChipStyle,
  primeDisplayLabel,
  safetyStatusBadge,
  sanitizeActionButtons,
  type PrimeDisplay,
  type SafetyStatusBadge,
} from '../lib/optionsCardSemantics'
import type { OptionProposal } from './OptionProposalCard'

// Option Proposal Card v4 — options-desk member of the card-v4 family (2026-07-04).
// v3 (OptionProposalCard) stays untouched; the global cc.cards.v4 toggle selects.
// One tinted two-row hero owns the card: row 1 = strategy word + one deduped
// sentence (composeWhy over Aegis-stripped reasoning) + headline credit + actions;
// row 2 = edge · EV · POP · R:R · DTE · aegis verdict + severity dot.
// Color discipline: teal/amber/red = signal only; green = money numerals only.
//
// INTELLIGENCE PARITY CHECKLIST — every field the v3 card renders, and where v4 renders it:
//   [PASS] severity badge (SEV label)             → hero row 2: severity dot + label
//   [PASS] strategy label + guide emoji/oneLiner  → hero row 1 state word (tooltip = guide one-liner)
//   [PASS] symbol                                 → header identity
//   [PASS] data_source badge (Schwab chain / BS)  → header chip (BS estimate = amber signal)
//   [PASS] intent_sleeve "income sleeve" badge    → header chip (neutral)
//   [PASS] edge score badge                       → hero row 2 (teal/amber/red thresholds unchanged)
//   [PASS] enterprise.live_eligible badge         → header chip (teal)
//   [PASS] enterprise.blocks badge + tooltip      → header chip (red, blocks in tooltip)
//   [PASS] execution_label badge                  → header chip (manual = neutral, else amber)
//   [PASS] strike / short-long spread headline    → header (spread-pair tooltip kept)
//   [PASS] DTE                                    → hero row 2 (tooltip kept)
//   [PASS] desk_tier                              → header (tooltip kept)
//   [PASS] expiration (fmtExpiry)                 → header
//   [PASS] account chip                           → header right
//   [PASS] novice plain-English box               → below hero (unchanged)
//   [PASS] novice strike-distance bar + label     → below hero (unchanged)
//   [PASS] novice risk-flag chips                 → below hero (unchanged)
//   [PASS] Spot metric                            → economics grid
//   [PASS] Strike metric                          → economics grid
//   [PASS] Premium metric                         → economics grid (money numeral green)
//   [PASS] Total credit metric                    → hero row 1 headline economics + grid
//   [PASS] POP metric                             → hero row 2
//   [PASS] R:R metric                             → hero row 2
//   [PASS] Breakeven metric                       → economics grid
//   [PASS] EV metric                              → hero row 2
//   [PASS] Max profit metric                      → economics grid
//   [PASS] Stock risk metric (covered call)       → economics grid (max_loss_note tooltip kept)
//   [PASS] Upside cap metric (covered call)       → economics grid (upside_cap_note tooltip kept)
//   [PASS] Max loss metric (non-CC)               → economics grid
//   [PASS] IV rank metric                         → economics grid
//   [PASS] Contracts metric                       → economics grid
//   [PASS] Delta metric (conditional)             → economics grid
//   [PASS] OI metric (conditional)                → economics grid
//   [PASS] novice WhatIfBox                       → below grid (unchanged)
//   [PASS] reviewBar slot                         → below grid (unchanged)
//   [PASS] reasoning, Aegis-stripped              → hero row 1 sentence (full text in tooltip)
//   [PASS] execution_note                         → footer italic line
//   [PASS] company_description + sector · industry · instrument_type
//                                                 → underlying-context line below grid
//   [PASS] action_buttons w/ exec-lock + tooltips → hero row 1 (lock/manual logic unchanged)
//   [PASS] "Executed manually" button             → footer
//   [ADD ] aegis_verdict (+ aegis_note tooltip)   → hero row 2 (typed in v3 but never rendered)
//   [ADD ] iv_context line (2026-07-06)           → paper-model disclosure block: 'IV rank N% — verdict'
//                                                   (teal cheap / amber rich / dim building-unavailable)
//   [ADD ] prime rubric chip (Stage 3)            → header chip: PRIME <score> (dim NOT_PRIME · teal
//                                                   PRIME_FOR_PAPER · amber live-review label) — advisory only
//   [ADD ] Alpaca lane chip + buttons (Stage 3)   → paper block: per-state chip (READY/SUBMITTED/FILLED@px/
//                                                   REJECTED/CLOSED/OUTCOME ✓/LIVE REVIEW) + operator actions
//                                                   Send-to-Alpaca (two-step confirm) · Mark outcome ·
//                                                   Promote to Live Review (mandatory no-order confirm text)
//   [ADD ] earnings vertical spread block         → paper block (EARNINGS-SPREADS Stage 3, family
//          (legs table · package economics ·        earnings_vertical_*): meta.strategy_json.legs table,
//           event line · risk pills)                net debit/max loss/max gain/BE(+move%)/R:R/slippage,
//                                                   event line (earnings date · DTE · implied vs historical
//                                                   move), event-risk amber pills (incl. credit-lane
//                                                   assignment/gap disclosures). Send-to-Alpaca additionally
//                                                   requires registry multi_leg_proven (both flags false
//                                                   today ⇒ button never renders); Promote-to-Live-Review is
//                                                   HARD-BLOCKED for earnings families regardless of prime
//                                                   verdict (operator spec: no live review until a separate
//                                                   explicit policy enables it).

const STRAT_LABEL: Record<string, string> = {
  covered_call: 'Covered Call',
  cash_secured_put: 'Cash-Secured Put',
  long_call: 'Long Call',
  credit_spread: 'Credit Spread',
  protective_put: 'Protective Put',
  deep_itm_call: 'Deep ITM Call',
  atm_call: 'ATM Call',
  atm_put: 'ATM Put',
  earnings_put_debit_spread: 'Earnings Put Debit Spread',
  earnings_put_credit_spread: 'Earnings Put Credit Spread',
}

// MULTI-STRATEGY Stage 2: strategy-family badge text for paper-model rows
// (rendered next to PAPER MODEL, amber outline — same treatment for all).
const PAPER_FAMILY_BADGE: Record<string, string> = {
  deep_itm_call: 'DEEP ITM',
  atm_call: 'ATM CALL',
  atm_put: 'ATM PUT',
  earnings_put_debit_spread: 'EARNINGS PUT DEBIT SPREAD',
  earnings_put_credit_spread: 'EARNINGS PUT CREDIT SPREAD',
}

// Stage B (2026-07-05): disclosed-flag labels for paper-model rows.
// Operator ratified: earnings before expiry is a disclosed flag, never a hidden pass.
// EARNINGS-SPREADS Stage 3 adds the event-risk vocabulary: generator gate_flags
// (iv_rich, historical_move_below_breakeven) + event_json.risk_flags
// (thin_history, wide_quotes, event_stale) + credit-lane disclosure keys.
const PAPER_FLAG_LABELS: Record<string, string> = {
  earnings_before_expiry_operator_flagged: '⚠ earnings before expiry',
  earnings_before_expiry_flagged: '⚠ earnings before expiry', // ATM lane flag name
  earnings_unknown: 'earnings date unknown',
  delta_proxy_itm_depth: 'Δ from ITM-depth proxy (chain carried no greeks)',
  delta_proxy_nearest_the_money: 'Δ proxy — nearest-the-money (chain carried no greeks)',
  iv_rich_pay_up_warning: '⚠ IV rich — pay-up warning',
  iv_rich: '⚠ IV rich into event',
  historical_move_below_breakeven: '⚠ historical move < breakeven requirement',
  thin_history: 'thin earnings-move history',
  wide_quotes: '⚠ wide quotes',
  event_stale: '⚠ event date stale',
  assignment_risk: '⚠ assignment risk (short put)',
  gap_risk: '⚠ gap risk through short strike',
  short_leg_lifecycle: '⚠ short-leg lifecycle management required',
}

// MULTI-STRATEGY Stage 2: other-strategies mini-list glyphs (matcher verdicts).
const MATCH_STATUS_GLYPH: Record<string, { glyph: string; color: string }> = {
  pass: { glyph: '✓', color: WL.signal.teal },
  watch: { glyph: '⚠', color: WL.signal.amber },
  fail: { glyph: '✗', color: WL.signal.red },
  not_applicable: { glyph: '—', color: WL.text.dim },
  skipped: { glyph: '—', color: WL.text.dim },
}

// ── ALPACA-OPTIONS Stage 3: paper-lane state + prime rubric (data wiring) ──
// queue meta passthrough on paper-model rows: meta.alpaca_json (order audit)
// + meta.prime_json (advisory rubric). Verdicts are LABELS — the card never
// transitions state itself; every action goes through the operator API routes.
export type AlpacaLaneAction = 'send' | 'mark_outcome' | 'promote_live'
export type AlpacaActionResult = { ok: boolean; message?: string }
type PaperLaneFields = {
  queue_status?: string
  alpaca_json?: {
    response?: { id?: string }
    fill?: { price?: number; filled_at?: string }
    close?: { exit_price?: number; pnl?: number }
    reject?: { reason?: string }
  }
  prime_json?: { prime_score?: number; verdict?: string }
}

const PRIME_VERDICT_LIVE = 'READY_FOR_LIVE_REVIEW_OPERATOR_ONLY'

function primeChipColor(display?: PrimeDisplay | null): string {
  if (!display) return WL.text.dim
  return primeChipStyle(display.color)
}

function laneChip(status?: string, aj?: PaperLaneFields['alpaca_json']): { label: string; color: string; tip: string } | null {
  switch (status) {
    case 'READY_FOR_ALPACA_PAPER':
      return { label: 'READY', color: WL.signal.amber, tip: 'Operator-marked ready for the Alpaca PAPER lane — no order exists yet.' }
    case 'ALPACA_PAPER_SUBMITTED':
      return { label: 'SUBMITTED', color: WL.text.secondary, tip: `Paper LIMIT order working on Alpaca${aj?.response?.id ? ` (order ${aj.response.id})` : ''} — reconcile polls for the fill.` }
    case 'ALPACA_PAPER_FILLED':
      return { label: aj?.fill?.price != null ? `FILLED@${fmt$(aj.fill.price, 2)}` : 'FILLED', color: WL.signal.teal, tip: 'Paper order filled — position open on Alpaca paper.' }
    case 'ALPACA_PAPER_REJECTED':
      return { label: 'REJECTED', color: WL.signal.red, tip: `Alpaca rejected/canceled the paper order${aj?.reject?.reason ? `: ${aj.reject.reason}` : ''}.` }
    case 'ALPACA_PAPER_CLOSED':
      return { label: 'CLOSED', color: WL.text.secondary, tip: 'Position closed on Alpaca paper — outcome not yet recorded in the validation ledger.' }
    case 'OUTCOME_RECORDED':
      return { label: 'OUTCOME ✓', color: WL.signal.teal, tip: `Closed paper outcome recorded${aj?.close?.pnl != null ? ` (P/L ${fmt$(aj.close.pnl)})` : ''} — feeds the 30-trade validation gate.` }
    case 'READY_FOR_LIVE_REVIEW':
      return { label: 'LIVE REVIEW', color: WL.signal.amber, tip: 'Operator-promoted for live review. No order placed — 2FA + broker preview/read-back still required.' }
    default:
      return null
  }
}

type HeroTone = { c: string; bg: string; border: string; label: string }

const heroTone = (s?: string): HeroTone => {
  const v = (s || '').toLowerCase()
  if (/crit|urgent|danger/.test(v)) return { c: WL.signal.red, bg: 'rgba(239,83,80,.07)', border: 'rgba(239,83,80,.25)', label: 'CRITICAL' }
  if (/warn|caution/.test(v)) return { c: WL.signal.amber, bg: 'rgba(245,166,35,.07)', border: 'rgba(245,166,35,.25)', label: 'WARNING' }
  if (/pos|ok|good/.test(v)) return { c: WL.signal.teal, bg: 'rgba(45,212,191,.08)', border: 'rgba(45,212,191,.28)', label: 'POSITIVE' }
  return { c: WL.text.secondary, bg: 'rgba(148,163,184,.06)', border: 'rgba(148,163,184,.16)', label: 'INFO' }
}

const TIPS = {
  spot: 'Current underlying price from Schwab chain or technical snapshot.',
  strike: 'Option strike price for this contract.',
  dte: 'Days to expiration — theta decay accelerates in the final 2 weeks.',
  premium: 'Estimated mid price per contract (×100 shares). See data-source badge.',
  totalCashflow: 'Total debit/credit if filled: premium × 100 × contracts.',
  maxProfit: 'Best-case profit if the trade works as modeled.',
  maxLoss: 'Stock downside if price falls to $0 (you still own the shares). Premium reduces this slightly.',
  upsideCap: 'If assigned, you sell shares at this strike — gains above strike are forgone.',
  breakeven: 'Underlying price where P&L crosses zero at expiration.',
  rr: 'Risk/reward: max profit ÷ max loss (higher is better for defined-risk trades).',
  ev: 'Expected value ≈ total credit × POP% — probabilistic edge.',
  pop: 'Probability of profit at expiration (OTM for short premium, ITM edge for long).',
  ivRank: 'IV rank vs 52-week range — higher usually means richer premiums.',
  contracts: 'Contracts sized to shares held (CC) or risk budget.',
  account: 'Account that holds the underlying or will fund the trade.',
  edge: 'Composite quality score from POP, IV rank, R:R, and conviction. Gate ≥62.',
  delta: 'Option delta — approximate $ move per $1 underlying move.',
  oi: 'Open interest — liquidity; thin OI can mean wider fills.',
}

function fmtExpiry(iso?: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return iso
  }
}

function fmtMoneyish(v: number | string | null | undefined): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v
  return fmt$(v, v < 10 ? 2 : 0)
}

const chip = (c: string, quiet = false): React.CSSProperties => ({
  fontSize: 8.5, fontWeight: 800, padding: '2px 6px', borderRadius: 4, whiteSpace: 'nowrap',
  color: c, background: quiet ? 'rgba(148,163,184,.08)' : `${c}18`,
  border: `1px solid ${quiet ? 'rgba(148,163,184,.2)' : `${c}44`}`,
})

const statKey: React.CSSProperties = { color: WL.text.dim, fontWeight: 700 }

function Metric({ label, value, color = WL.text.primary, tip }: { label: string; value: React.ReactNode; color?: string; tip?: string }) {
  return (
    <div title={tip} style={{ background: WL.surface.inset, border: `1px solid ${WL.surface.edge}`, borderRadius: 8, padding: '7px 8px' }}>
      <div style={{ fontSize: 8, color: WL.text.dim, textTransform: 'uppercase', fontWeight: 800, letterSpacing: '.04em' }}>{label}</div>
      <div style={{ ...numStyle, fontSize: 12.5, color, fontWeight: 800, marginTop: 2, cursor: tip ? 'help' : undefined }}>{value}</div>
    </div>
  )
}

const EXEC_ACTIONS = new Set(['sell_covered_call', 'sell_put', 'buy_put', 'buy_call', 'sell_credit_spread'])

export default function OptionProposalCardV4({
  proposal: p,
  armed,
  novice,
  onAction,
  onAlpacaAction,
  onDrill,
  onManualLog,
  reviewBar,
}: {
  proposal: OptionProposal
  armed?: boolean
  novice?: boolean
  onAction: (action: string, id: string) => void
  /** Stage 3: operator actions for the Alpaca paper lane (fetches live in the hub). */
  onAlpacaAction?: (action: AlpacaLaneAction, proposalId: string, payload?: { exitPremium?: number }) => Promise<AlpacaActionResult>
  onDrill?: () => void
  onManualLog?: () => void
  reviewBar?: React.ReactNode
}) {
  const ext = p as OptionProposal & Record<string, unknown>
  const blocked = isCardBlocked(ext)
  const safetyBadge: SafetyStatusBadge | null = safetyStatusBadge(ext)
  const cashflowLabel = String(ext.cashflow_label || optionCashflowLabel(p.strategy, p.side))
  const isCredit = ext.cashflow_is_credit === true || (ext.cashflow_is_credit == null && cashflowIsCredit(p.strategy, p.side))
  const cfColor = cashflowColor(isCredit)
  const actionButtons = sanitizeActionButtons(p)
  const route = executionRouteBadge(ext)
  const liqWarnings = liquidityWarnings(p)
  const displayEdgeRaw = ext.display_edge_score ?? p.edge_score
  const tone = heroTone(p.severity || (displayEdgeRaw && Number(displayEdgeRaw) >= 75 ? 'positive' : 'info'))
  const strat = STRAT_LABEL[p.strategy] || p.strategy.replace(/_/g, ' ')
  const edge = displayEdgeRaw != null ? Math.round(Number(displayEdgeRaw)) : null
  const edgeColor = edge == null ? WL.text.dim : edge >= 72 ? WL.signal.teal : edge >= 50 ? WL.signal.amber : WL.signal.red
  const ds = p.data_source === 'schwab_chain'
    ? { label: 'Schwab chain', c: WL.signal.teal, tip: 'Live bid/ask mid from Schwab option chain.' }
    : p.data_source === 'bs_estimate'
      ? { label: 'BS estimate', c: WL.signal.amber, tip: 'Premium estimated via Black-Scholes — confirm on chain before sizing.' }
      : null
  const guide = strategyGuide(p.strategy)
  const dist = strikeDistance(p)
  const risks = novice ? proposalRiskFlags(p) : []
  const stockRisk = p.stock_downside_risk ?? (
    p.strategy === 'covered_call' && p.underlying_price && p.contracts
      ? Math.round(p.underlying_price * p.contracts * 100 - (p.premium_total ?? 0))
      : typeof p.max_loss === 'number' ? p.max_loss : null
  )

  // Rule-of-one hero sentence — Aegis restatements stripped exactly as v3 does,
  // then composeWhy drops any residual duplication. Full text lives in the tooltip.
  const strippedReasoning = p.reasoning
    ? (p.reasoning.replace(/\s*·\s*Aegis:[^·]+/g, '').replace(/\s*Aegis:[^·]+/g, '').trim() || p.reasoning)
    : ''
  const whyLine = composeWhy([strippedReasoning])

  const manualOnly = p.execution_mode === 'manual' || p.broker === 'fidelity' || !p.auto_eligible
  const showManualLog = !!onManualLog && allowsManualLog(ext)

  // ── Stage B: paper-model disclosures — amber, never green ──
  const paper = !!p.educational_paper_model
  const paperFamily = PAPER_FAMILY_BADGE[p.strategy] || (p.strategy || '').replace(/_/g, ' ').toUpperCase()
  const cand = p.meta?.analysis?.candidate
  const bucketDte = p.meta?.dte_bucket?.target_dte ?? p.dte
  const capPct = cand?.capital_vs_100_shares?.capital_ratio_pct
  // ATM analysis shape (MULTI-STRATEGY Stage 2) has no capital_vs_100_shares —
  // its summary line renders max-loss/spread/OI/vol/IV instead (deep-ITM line unchanged).
  const atmShape = paper && !!cand && cand.capital_vs_100_shares == null
  const paperSummary = paper && cand ? [
    bucketDte != null ? `${bucketDte}d bucket` : null,
    cand.strike != null ? `$${fmtNum(cand.strike, cand.strike < 50 ? 2 : 0)} strike` : null,
    cand.delta != null ? `Δ${Number(cand.delta).toFixed(2)}` : 'Δ proxy',
    cand.breakeven != null
      ? `BE $${fmtNum(cand.breakeven, 2)}${cand.breakeven_move_pct != null ? ` (${cand.breakeven_move_pct > 0 ? '+' : ''}${Number(cand.breakeven_move_pct).toFixed(1)}%)` : ''}`
      : null,
    capPct != null ? `${Math.round(capPct)}% of share capital` : null,
    ...(atmShape ? [
      cand.max_loss != null ? `max loss ${fmt$(cand.max_loss)} (= debit)` : null,
      cand.spread_pct != null ? `spread ${Number(cand.spread_pct).toFixed(1)}%` : null,
      cand.oi != null ? `OI ${fmtNum(cand.oi, 0)}` : null,
      cand.volume != null ? `vol ${fmtNum(cand.volume, 0)}` : null,
      cand.iv != null ? `IV ${Number(cand.iv).toFixed(0)}%` : null,
    ] : []),
  ].filter(Boolean).join(' · ') : ''
  // ── EARNINGS-SPREADS Stage 3: vertical-spread rows (family earnings_vertical_*) ──
  const isEarnSpread = paper
    && (p.strategy_family || p.meta?.strategy_json?.family || '').startsWith('earnings_vertical')
  const eventJson = p.meta?.event_json
  const spreadAnalysis = p.meta?.analysis
  const spreadLegs = isEarnSpread ? (p.meta?.strategy_json?.legs || []) : []
  const disclosures = p.meta?.disclosures || {}
  const spreadSummary = isEarnSpread ? [
    p.net_debit != null ? `net debit $${fmtNum(p.net_debit, 2)}`
      : p.net_credit != null ? `net credit $${fmtNum(p.net_credit, 2)}` : null,
    p.max_loss != null ? `max loss ${fmtMoneyish(p.max_loss)}` : null,
    p.max_profit != null ? `max gain ${fmtMoneyish(p.max_profit)}` : null,
    p.breakeven != null
      ? `BE $${fmtNum(p.breakeven, 2)}${p.breakeven_move_pct != null ? ` (${p.breakeven_move_pct > 0 ? '+' : ''}${Number(p.breakeven_move_pct).toFixed(1)}%)` : ''}`
      : null,
    (p.reward_to_risk ?? p.risk_reward) != null ? `R:R ${Number(p.reward_to_risk ?? p.risk_reward).toFixed(2)}` : null,
    spreadAnalysis?.package_slippage_pct != null ? `pkg slippage ${Number(spreadAnalysis.package_slippage_pct).toFixed(1)}%` : null,
  ].filter(Boolean).join(' · ') : ''
  // Event line: earnings date · DTE · implied move vs historical (honest when unavailable)
  const im = eventJson?.implied_move_pct
  const hist = eventJson?.historical_earnings_moves
  const eventLine = isEarnSpread ? [
    eventJson?.earnings_date?.date ? `earnings ${eventJson.earnings_date.date}` : 'earnings date unavailable',
    p.dte != null ? `${p.dte}d to expiry` : null,
    im?.available && im.pct != null ? `implied move ${Number(im.pct).toFixed(1)}%` : 'implied move unavailable',
    hist?.available && hist.avg_abs_move_pct != null
      ? `vs historical avg |move| ${Number(hist.avg_abs_move_pct).toFixed(1)}% (${hist.samples ?? 0} sample${hist.samples === 1 ? '' : 's'})`
      : 'no historical move data',
    eventJson?.event_confidence != null ? `event confidence ${Math.round(Number(eventJson.event_confidence) * 100)}%` : null,
  ].filter(Boolean).join(' · ') : ''
  // Amber event-risk pills: generator gate_flags + (earnings rows) event_json
  // risk_flags + credit-lane disclosure keys — deduped; disclosure text in tooltip.
  const paperFlags = paper
    ? [...new Set([
        ...(p.meta?.gate_flags || []),
        ...(isEarnSpread ? (eventJson?.risk_flags || []) : []),
        ...(isEarnSpread ? Object.keys(disclosures) : []),
      ])].map(k => ({ key: k, label: PAPER_FLAG_LABELS[k] || k.replace(/_/g, ' '), tip: disclosures[k] }))
    : []
  const discoveryRef = p.meta?.discovery_ref

  // ── MULTI-STRATEGY Stage 2: why-matched + thesis + other-strategies context ──
  const matchJson = p.meta?.match_json
  const intel = p.meta?.underlying_intel
  const thesisLine = paper && intel ? [
    intel.conviction_source ? `thesis: ${String(intel.conviction_source).replace(/_/g, ' ')}` : null,
    intel.watchlist_verdict ? `verdict ${String(intel.watchlist_verdict).replace(/_/g, ' ')}` : null,
    intel.conviction != null ? `conviction ${Math.round(Number(intel.conviction) * 100)}%` : null,
    intel.held_shares ? `${fmtNum(intel.held_shares, 0)} sh held` : null,
    intel.hedge_of_held ? 'hedge of held' : null,
  ].filter(Boolean).join(' · ') : ''
  const otherStrategies = paper && matchJson?.other_strategies
    ? Object.entries(matchJson.other_strategies) : []
  const [othersOpen, setOthersOpen] = useState(false)

  // ── Stage 3: Alpaca paper lane — state chip, prime score, operator actions ──
  const lane = p as OptionProposal & PaperLaneFields
  const queueStatus = lane.queue_status
  // Part F: named flattened fields (alpaca_paper_status/order_id/fill_price/
  // submitted_at/filled_at) win over the raw meta.alpaca_json passthrough.
  const alpacaJson: PaperLaneFields['alpaca_json'] = {
    ...lane.alpaca_json,
    response: { ...lane.alpaca_json?.response, id: p.alpaca_order_id ?? lane.alpaca_json?.response?.id },
    fill: (p.alpaca_fill_price != null || lane.alpaca_json?.fill)
      ? {
          ...lane.alpaca_json?.fill,
          price: p.alpaca_fill_price ?? lane.alpaca_json?.fill?.price,
          filled_at: p.alpaca_filled_at ?? lane.alpaca_json?.fill?.filled_at,
        }
      : undefined,
  }
  const prime = lane.prime_json
  const primeDisplay: PrimeDisplay | null = prime?.prime_score != null
    ? ((ext.prime_display as PrimeDisplay | undefined) || primeDisplayLabel(prime.prime_score, prime.verdict))
    : null
  const laneState = paper ? laneChip(p.alpaca_paper_status || queueStatus, alpacaJson) : null
  const [laneConfirm, setLaneConfirm] = useState<AlpacaLaneAction | null>(null)
  const [exitPremium, setExitPremium] = useState('')
  const [laneBusy, setLaneBusy] = useState(false)
  const [laneMsg, setLaneMsg] = useState<string | null>(null)
  // MULTI-STRATEGY Stage 2: Send-to-Alpaca-Paper only when the REGISTRY says
  // alpaca_paper_enabled for this strategy (scan-time meta / API-flattened
  // field; deep_itm_call fallback covers rows queued before Stage 2). ATM
  // strategies ship false → the button must NOT render for them.
  const alpacaEnabled = p.alpaca_paper_enabled
    ?? p.meta?.alpaca_paper_enabled
    ?? (p.strategy === 'deep_itm_call')
  // EARNINGS-SPREADS Stage 3: spread rows ADDITIONALLY require the Part-G
  // multi_leg_proven registry key (API-flattened; absent == false). Both flags
  // are false for earnings strategies today, so Send never renders until the
  // operator flips them in config/options_strategy_registry.yaml — mirroring
  // the executor's assert_spread_allowed triple gate.
  const multiLegProven = (p.multi_leg_proven ?? p.meta?.multi_leg_proven) === true
  const canSend = paper && !!onAlpacaAction && alpacaEnabled
    && (!isEarnSpread || multiLegProven)
    && (queueStatus === 'pending' || queueStatus === 'approved' || queueStatus === 'READY_FOR_ALPACA_PAPER')
  const canMarkOutcome = paper && !!onAlpacaAction
    && (queueStatus === 'ALPACA_PAPER_FILLED' || queueStatus === 'ALPACA_PAPER_CLOSED')
  // EARNINGS-SPREADS Stage 3: Promote-to-Live-Review must NOT appear for
  // earnings spread families regardless of prime verdict (operator spec —
  // live review stays off until explicitly enabled by separate policy).
  // Card-semantics pass: verdict read from primeDisplay (server-enriched
  // prime_display wins; falls back to local band mapping).
  const canPromote = paper && !!onAlpacaAction && !isEarnSpread
    && queueStatus === 'OUTCOME_RECORDED' && primeDisplay?.verdict === PRIME_VERDICT_LIVE

  const runLane = async (action: AlpacaLaneAction, payload?: { exitPremium?: number }) => {
    if (!onAlpacaAction || laneBusy) return
    setLaneBusy(true)
    setLaneMsg(null)
    try {
      const res = await onAlpacaAction(action, p.id, payload)
      setLaneMsg(res.message || (res.ok ? 'Done.' : 'Refused.'))
    } catch (e: any) {
      setLaneMsg(String(e?.message || e))
    } finally {
      setLaneBusy(false)
      setLaneConfirm(null)
      setExitPremium('')
    }
  }

  const laneBtn: React.CSSProperties = {
    fontSize: 9.5, fontWeight: 800, padding: '4px 9px', borderRadius: 5, cursor: 'pointer',
    border: '1px solid rgba(148,163,184,.3)', background: 'transparent', color: WL.text.secondary, whiteSpace: 'nowrap',
  }

  // IV-rank context line (2026-07-06) — advisory disclosure, one line:
  // teal = extrinsic cheap · amber = extrinsic rich (pay-up) · dim = building/unavailable.
  const ivc = p.iv_context || p.meta?.analysis?.iv_context
  const ivLine = !ivc ? '' : ivc.available
    ? `IV rank ${Math.round(ivc.iv_rank ?? 0)}% — ${ivc.verdict_label || ivc.verdict || 'normal'}`
    : ivc.days != null
      ? `IV history building — ${ivc.days}/${ivc.required_days ?? 20} days`
      : `IV context unavailable — ${ivc.reason || 'no data'}`
  const ivColor = !ivc?.available ? WL.text.dim
    : ivc.verdict === 'extrinsic_cheap' ? WL.signal.teal
      : ivc.verdict === 'extrinsic_rich' ? WL.signal.amber
        : WL.text.secondary

  const btnStyle = (action: string): React.CSSProperties => {
    const base: React.CSSProperties = { fontSize: 10, fontWeight: 700, padding: '5px 11px', borderRadius: 6, whiteSpace: 'nowrap', cursor: 'pointer' }
    if (action === 'hold') return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.dim }
    if (action === 'review_chain' || action === 'review_block_reason' || action === 'rerun_review') {
      return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.secondary }
    }
    if (EXEC_ACTIONS.has(action)) {
      const locked = !armed && !manualOnly
      return {
        ...base, fontWeight: 800, padding: '5px 13px', border: locked ? '1px solid rgba(148,163,184,.25)' : `1px solid ${WL.signal.teal}`,
        background: locked ? 'transparent' : WL.signal.teal, color: locked ? WL.text.dim : '#06231f',
        cursor: locked ? 'not-allowed' : 'pointer', opacity: locked ? 0.75 : 1,
      }
    }
    return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.secondary }
  }

  return (
    <div
      onClick={onDrill}
      style={{
        background: WL.surface.card,
        border: `1px solid ${WL.surface.edge}`,
        borderLeft: `3px solid ${tone.c}`,
        borderRadius: WL.card.radius,
        boxShadow: WL.card.shadow,
        cursor: onDrill ? 'pointer' : 'default',
        minWidth: 0,
        overflow: 'hidden',
        color: WL.text.primary,
      }}
    >
      {/* ① Header — identity + contract + provenance chips; quiet */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, padding: '10px 15px 8px' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <span style={{ ...numStyle, fontSize: 18, fontWeight: 800 }}>{p.symbol}</span>
            <span style={{ ...numStyle, fontSize: 13, fontWeight: 700, color: WL.text.secondary }}>
              {p.short_strike && p.long_strike
                ? <span title={PROPOSAL.spreadPair} style={{ cursor: 'help' }}>${fmtNum(p.short_strike, 0)}/${fmtNum(p.long_strike, 0)} spread</span>
                : `$${fmtNum(p.strike, p.strike < 50 ? 2 : 0)}`}
            </span>
            {p.desk_tier && (
              <span title={PROPOSAL.deskTier} style={{ fontSize: 9, fontWeight: 800, color: p.desk_tier === 'A' ? WL.signal.teal : WL.text.secondary, cursor: 'help' }}>Tier {p.desk_tier}</span>
            )}
            <span style={{ fontSize: 10.5, color: WL.text.dim }}>{fmtExpiry(p.expiration)}</span>
          </div>
          <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap', marginTop: 5 }}>
            {paper && (
              <span
                title="Educational paper model — manual review only, never live-eligible. Outcomes feed the strategy validation gate (30 paper outcomes, PF>1.3, WR>55%) before any live consideration."
                style={{ ...chip(WL.signal.amber), background: 'transparent', cursor: 'help' }}
              >
                {paperFamily} · PAPER MODEL
              </span>
            )}
            {paper && p.validation_progress?.label && (
              <span title={p.validation_progress.message || 'Closed paper outcomes recorded vs the validation gate.'} style={{ ...chip(WL.signal.amber, true), cursor: 'help' }}>
                {p.validation_progress.label}
              </span>
            )}
            {paper && primeDisplay && (
              <span
                title={`Prime rubric ${prime?.prime_score?.toFixed(1) ?? '—'}/100 → ${primeDisplay.label}. Advisory label only — never places orders.`}
                style={{ ...chip(primeChipColor(primeDisplay), primeDisplay.verdict === 'NOT_PRIME'), cursor: 'help' }}
              >
                {primeDisplay.shortLabel}
              </span>
            )}
            {laneState && (
              <span title={laneState.tip} style={{ ...chip(laneState.color), cursor: 'help' }}>
                ALPACA {laneState.label}
              </span>
            )}
            {ds && <span title={ds.tip} style={chip(ds.c)}>{ds.label}</span>}
            <span title="Execution route — distinct from data source (Schwab chain)" style={chip(
              route.kind === 'schwab_live' ? WL.signal.amber
                : route.kind === 'fidelity_manual' ? WL.text.secondary
                  : route.kind === 'alpaca_paper' || route.kind === 'paper_model' ? WL.signal.amber
                    : WL.text.dim,
              route.kind === 'review_only',
            )}>
              {route.label}
            </span>
            {p.intent_sleeve && <span title="Portfolio intent covered-call sleeve (V/SCHD/LMT) — relaxed edge floor 52 vs 62" style={chip(WL.text.secondary, true)}>income sleeve</span>}
            {p.enterprise?.live_eligible && !paper && <span title={PROPOSAL.liveOk} style={{ ...chip(WL.signal.teal), cursor: 'help' }}>live eligible</span>}
            {paper && !p.enterprise?.live_eligible && (
              <span title="Paper-model rows are never live-eligible until validation gate met" style={{ ...chip(WL.signal.red), cursor: 'help' }}>live eligible false</span>
            )}
            {safetyBadge && (
              <span
                title={safetyBadge.tip}
                style={{
                  ...chip(safetyBadge.severity === 'danger' ? WL.signal.red : WL.signal.amber),
                  fontWeight: 900,
                  cursor: 'help',
                  background: safetyBadge.kind === 'no_live_path' ? 'rgba(245,166,35,.1)' : undefined,
                }}
              >
                {safetyBadge.label}
              </span>
            )}
          </div>
        </div>
        {p.account && (
          <span title={TIPS.account} style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: WL.surface.inset, border: `1px solid ${WL.surface.edge}`, color: WL.text.secondary, whiteSpace: 'nowrap', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', flexShrink: 0 }}>
            {p.account.replace(/_/g, ' ')}
          </span>
        )}
      </div>

      {/* ② Hero — two rows, the only tinted surface, owns the card */}
      <div
        onClick={e => e.stopPropagation()}
        style={{ background: tone.bg, borderTop: `1px solid ${tone.border}`, borderBottom: `1px solid ${tone.border}`, padding: '10px 15px 9px', display: 'flex', flexDirection: 'column', gap: 7 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span title={`${guide.oneLiner}`} style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: tone.c, flexShrink: 0, cursor: 'help' }}>
            {guide.emoji} {strat}
          </span>
          <span
            title={p.reasoning || undefined}
            style={{ fontSize: 12.5, fontWeight: 700, color: WL.text.primary, minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          >
            {whyLine || '—'}
          </span>
          <span title={TIPS.totalCashflow} style={{ ...numStyle, fontSize: 13.5, fontWeight: 800, color: cfColor, flexShrink: 0, cursor: 'help' }}>
            {p.premium_total != null ? fmt$(p.premium_total) : '—'}
          </span>
          <span style={{ display: 'inline-flex', gap: 6, flexShrink: 0 }}>
            {actionButtons.map((b, i) => {
              const execLocked = EXEC_ACTIONS.has(b.action) && !armed && !manualOnly
              return (
                <button
                  key={`${b.action}-${i}`}
                  type="button"
                  title={
                    b.action === 'hold' ? ACTIONS.hold
                      : b.action === 'review_chain' ? ACTIONS.reviewChain
                        : execLocked ? ACTIONS.preflightLocked
                          : manualOnly && EXEC_ACTIONS.has(b.action) ? ACTIONS.preflightManual
                            : EXEC_ACTIONS.has(b.action) ? PROPOSAL.recommended
                              : undefined
                  }
                  disabled={execLocked}
                  onClick={() => onAction(b.action, p.id)}
                  style={btnStyle(b.action)}
                >
                  {/* EARNINGS-SPREADS Stage 3: the review-chain drilldown opens the
                      put chain for the spread — label it honestly as a spread review */}
                  {b.action === 'review_chain' && isEarnSpread ? 'Review spread' : b.label}{b.action !== 'hold' ? ' →' : ''}
                </button>
              )
            })}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: 11, color: WL.text.secondary }}>
          <span title={TIPS.edge} style={{ ...numStyle, fontWeight: 800, color: edgeColor }}>edge {edge ?? '—'}</span>
          <span title={TIPS.ev}><span style={statKey}>EV </span><span style={numStyle}>{fmt$(p.expected_value)}</span></span>
          <span title={TIPS.pop}>
            <span style={statKey}>POP </span>
            <span style={{ ...numStyle, fontWeight: 700, color: p.pop_pct != null && p.pop_pct >= 60 ? WL.signal.teal : WL.signal.amber }}>
              {p.pop_pct != null ? `${p.pop_pct.toFixed(1)}%` : '—'}
            </span>
          </span>
          <span title={TIPS.rr}>
            <span style={statKey}>R:R </span>
            <span style={{ ...numStyle, fontWeight: 700, color: p.risk_reward != null && p.risk_reward >= 0.3 ? WL.signal.teal : WL.text.primary }}>
              {p.risk_reward != null ? p.risk_reward.toFixed(2) : '—'}
            </span>
          </span>
          <span title={TIPS.dte}><span style={statKey}>DTE </span><span style={numStyle}>{p.dte ?? '—'}</span></span>
          <span title={[tone.label, p.aegis_note].filter(Boolean).join(' — ') || PROPOSAL.recommended} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto', cursor: 'help' }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: tone.c, flex: 'none' }} />
            <b style={{ color: tone.c, fontSize: 10, letterSpacing: '.06em' }}>{tone.label}</b>
            {p.aegis_verdict && <span style={{ color: WL.text.dim }}>aegis {String(p.aegis_verdict).replace(/_/g, ' ')}</span>}
          </span>
        </div>
      </div>

      {liqWarnings.length > 0 && (
        <div style={{ padding: '6px 15px 0' }}>
          {liqWarnings.map(w => (
            <div
              key={w.code}
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: w.severity === 'danger' ? WL.signal.red : WL.signal.amber,
                padding: '5px 8px',
                borderRadius: 6,
                border: `1px solid ${w.severity === 'danger' ? 'rgba(239,83,80,.35)' : 'rgba(245,166,35,.35)'}`,
                background: w.severity === 'danger' ? 'rgba(239,83,80,.08)' : 'rgba(245,166,35,.06)',
                marginBottom: 4,
              }}
            >
              {w.message}
            </div>
          ))}
        </div>
      )}

      <div style={{ padding: '0 15px 12px' }}>
        {/* Stage B: paper-model disclosure block — analysis one-liner, disclosed
            flags, discovery lineage. Amber-only; no live affordance exists here. */}
        {paper && (
          <div style={{ marginTop: 10, padding: '9px 10px', borderRadius: 8, background: 'rgba(245,166,35,.06)', border: '1px solid rgba(245,166,35,.28)', fontSize: 10.5, lineHeight: 1.55, color: WL.text.secondary }}>
            {/* EARNINGS-SPREADS Stage 3: vertical-spread block — legs table from
                meta.strategy_json.legs, package economics, event context line.
                Amber-block members only; no live affordance exists here. */}
            {isEarnSpread && spreadLegs.length > 0 && (
              <div style={{ overflowX: 'auto', marginBottom: 6 }}>
                <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 10 }}>
                  <thead>
                    <tr>
                      {['leg', 'exp', 'mid', 'OI', 'vol', 'spread%'].map(h => (
                        <th key={h} style={{ textAlign: h === 'leg' ? 'left' : 'right', padding: '1px 6px 3px 0', fontSize: 8, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase', color: WL.text.dim, borderBottom: '1px solid rgba(245,166,35,.22)' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {spreadLegs.map((l, i) => (
                      <tr key={`${l.side}-${l.strike}-${i}`}>
                        <td style={{ ...numStyle, padding: '3px 6px 1px 0', fontWeight: 800, color: WL.text.primary, whiteSpace: 'nowrap' }}>
                          {(l.side || '').toUpperCase()} ${fmtNum(l.strike, (l.strike ?? 0) < 50 ? 2 : 0)}{(l.type || 'put')[0].toUpperCase()}
                        </td>
                        <td style={{ ...numStyle, padding: '3px 6px 1px 0', textAlign: 'right', whiteSpace: 'nowrap' }}>{l.exp || '—'}</td>
                        <td style={{ ...numStyle, padding: '3px 6px 1px 0', textAlign: 'right' }}>{l.mid != null ? fmt$(l.mid, 2) : '—'}</td>
                        <td style={{ ...numStyle, padding: '3px 6px 1px 0', textAlign: 'right' }}>{l.oi != null ? fmtNum(l.oi, 0) : '—'}</td>
                        <td style={{ ...numStyle, padding: '3px 6px 1px 0', textAlign: 'right' }}>{l.volume != null ? fmtNum(l.volume, 0) : '—'}</td>
                        <td style={{ ...numStyle, padding: '3px 0 1px 0', textAlign: 'right' }}>{l.spread_pct != null ? `${Number(l.spread_pct).toFixed(1)}%` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {isEarnSpread && spreadSummary && (
              <div style={{ ...numStyle, fontSize: 11, fontWeight: 700, color: WL.text.primary }}>{spreadSummary}</div>
            )}
            {isEarnSpread && eventLine && (
              <div
                title="Earnings-event context from the event model (implied move = ATM straddle mid at the event expiration; historical = past post-earnings |moves| on stored dates). Unavailable pieces are reported honestly, never fabricated."
                style={{ fontSize: 10, fontWeight: 700, color: WL.signal.amber, marginTop: spreadSummary ? 5 : 0, cursor: 'help' }}
              >
                {eventLine}
              </div>
            )}
            {paperSummary && (
              <div style={{ ...numStyle, fontSize: 11, fontWeight: 700, color: WL.text.primary }}>{paperSummary}</div>
            )}
            {/* MULTI-STRATEGY Stage 2: why this strategy matched (matcher pass
                reason + thesis source) — dim disclosure line, never a signal color */}
            {matchJson?.why_matched && (
              <div
                title={`Strategy matcher verdict for ${matchJson.strategy || p.strategy}: ${matchJson.status || '—'}. The matcher owns thesis gating (bullish for calls, bearish for puts); generators own contract math.`}
                style={{ fontSize: 10, color: WL.text.dim, marginTop: (paperSummary || spreadSummary) ? 5 : 0, cursor: 'help' }}
              >
                matched: {matchJson.why_matched}
              </div>
            )}
            {thesisLine && !matchJson?.why_matched && (
              <div style={{ fontSize: 10, color: WL.text.dim, marginTop: (paperSummary || spreadSummary) ? 5 : 0 }}>
                {thesisLine}
              </div>
            )}
            {/* MULTI-STRATEGY Stage 2: collapsible cross-strategy mini-list —
                what every other scanned strategy said for this underlying */}
            {otherStrategies.length > 0 && (
              <div onClick={e => e.stopPropagation()} style={{ marginTop: 5 }}>
                <button
                  type="button"
                  onClick={() => setOthersOpen(o => !o)}
                  title="Other strategies the scanner evaluated for this underlying in the same run, with the matcher's honest verdict for each."
                  style={{ fontSize: 9, fontWeight: 800, letterSpacing: '.05em', color: WL.text.dim, background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', textTransform: 'uppercase' }}
                >
                  other strategies ({otherStrategies.length}) {othersOpen ? '▾' : '▸'}
                </button>
                {othersOpen && (
                  <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {otherStrategies.map(([sid, d]) => {
                      const g = MATCH_STATUS_GLYPH[d?.status || ''] || MATCH_STATUS_GLYPH.not_applicable
                      return (
                        <div key={sid} style={{ fontSize: 9.5, color: WL.text.dim, lineHeight: 1.45 }}>
                          <span style={{ color: g.color, fontWeight: 800 }}>{g.glyph}</span>
                          {' '}
                          <span style={{ color: WL.text.secondary, fontWeight: 700 }}>{STRAT_LABEL[sid] || sid.replace(/_/g, ' ')}</span>
                          {d?.reason ? <span> — {d.reason}</span> : null}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
            {ivLine && (
              <div
                title={ivc?.available
                  ? `ATM IV ${ivc.atm_iv != null ? `${Number(ivc.atm_iv).toFixed(1)}%` : '—'} vs 52-week stored range · percentile ${ivc.percentile != null ? `${ivc.percentile}%` : '—'} · advisory only — informs edge ranking (×1.1 cheap / ×0.9 rich), never rejects`
                  : 'IV rank needs ≥20 daily ATM-IV snapshots — reported honestly as unavailable until then, never fabricated from thin data'}
                style={{ fontSize: 10, fontWeight: 700, color: ivColor, marginTop: (paperSummary || spreadSummary) ? 5 : 0, cursor: 'help' }}
              >
                {ivLine}
              </div>
            )}
            {paperFlags.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 6 }}>
                {paperFlags.map(f => (
                  <span key={f.key} title={f.tip} style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, color: WL.signal.amber, border: '1px solid rgba(245,166,35,.4)', background: 'transparent', cursor: f.tip ? 'help' : undefined }}>{f.label}</span>
                ))}
              </div>
            )}
            {/* Stage 3: Alpaca paper lane — operator buttons + two-step confirms.
                Every click routes through the paper-locked state machine API
                (mark-ready → confirm-required submit); nothing here is automatic. */}
            {onAlpacaAction && (canSend || canMarkOutcome || canPromote || laneState || laneMsg) && (
              <div onClick={e => e.stopPropagation()} style={{ marginTop: 8, paddingTop: 7, borderTop: '1px solid rgba(245,166,35,.22)' }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 8.5, fontWeight: 800, letterSpacing: '.06em', color: WL.text.dim, textTransform: 'uppercase' }}>Alpaca paper lane</span>
                  {canSend && laneConfirm !== 'send' && (
                    <button type="button" disabled={laneBusy} onClick={() => setLaneConfirm('send')}
                      title="Two-step: mark-ready, then confirm submit of a single simulated paper LIMIT order. No live broker order."
                      style={{ ...laneBtn, border: `1px solid ${WL.signal.teal}55`, color: WL.signal.teal }}>
                      {alpacaPaperButtonLabel(queueStatus, false)} ▸
                    </button>
                  )}
                  {canMarkOutcome && laneConfirm !== 'mark_outcome' && (
                    <button type="button" disabled={laneBusy} onClick={() => setLaneConfirm('mark_outcome')}
                      title="Record the closed paper outcome: enter the exit premium — P/L feeds the 30-trade validation gate."
                      style={laneBtn}>
                      Mark outcome ▸
                    </button>
                  )}
                  {canPromote && laneConfirm !== 'promote_live' && (
                    <button type="button" disabled={laneBusy} onClick={() => setLaneConfirm('promote_live')}
                      title="Operator-only review mark. Does NOT place an order — 2FA + broker preview/read-back still required."
                      style={{ ...laneBtn, border: `1px solid ${WL.signal.amber}66`, color: WL.signal.amber }}>
                      Promote to Live Review ▸
                    </button>
                  )}
                  {laneBusy && <span style={{ fontSize: 9, color: WL.text.dim }}>working…</span>}
                </div>
                <div style={{ fontSize: 9.5, color: WL.text.dim, marginTop: 6, lineHeight: 1.45 }}>
                  Alpaca paper only — simulated 1-contract limit order. No live broker order. Validation credit starts only after fill, close, and outcome reconciliation.
                </div>
                {laneConfirm === 'send' && (
                  <div style={{ marginTop: 6, padding: '7px 9px', borderRadius: 6, border: `1px solid ${WL.signal.teal}44`, background: 'rgba(45,212,191,.05)', fontSize: 10, color: WL.text.secondary }}>
                    <b style={{ color: WL.text.primary }}>Confirm simulated paper order?</b> Alpaca paper only · {isEarnSpread ? 'net-debit LIMIT · 1 spread (2 legs)' : 'limit · 1 contract'} · no live broker path
                    <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                      <button type="button" disabled={laneBusy} onClick={() => runLane('send')}
                        style={{ ...laneBtn, background: WL.signal.teal, border: `1px solid ${WL.signal.teal}`, color: '#06231f' }}>
                        {alpacaPaperButtonLabel(queueStatus, true)}
                      </button>
                      <button type="button" onClick={() => setLaneConfirm(null)} style={laneBtn}>Cancel</button>
                    </div>
                  </div>
                )}
                {laneConfirm === 'mark_outcome' && (
                  <div style={{ marginTop: 6, padding: '7px 9px', borderRadius: 6, border: '1px solid rgba(148,163,184,.3)', background: 'rgba(148,163,184,.06)', fontSize: 10, color: WL.text.secondary }}>
                    <b style={{ color: WL.text.primary }}>Record outcome</b> — exit premium per contract
                    {alpacaJson?.fill?.price != null && <span> (entry fill {fmt$(alpacaJson.fill.price, 2)})</span>}
                    <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
                      <input
                        value={exitPremium}
                        onChange={e => setExitPremium(e.target.value)}
                        placeholder="e.g. 43.85"
                        inputMode="decimal"
                        style={{ width: 80, fontSize: 10, padding: '4px 6px', borderRadius: 5, border: `1px solid ${WL.surface.edge}`, background: WL.surface.inset, color: WL.text.primary }}
                      />
                      <button type="button" disabled={laneBusy || !(Number(exitPremium) >= 0) || exitPremium.trim() === ''}
                        onClick={() => runLane('mark_outcome', { exitPremium: Number(exitPremium) })}
                        style={{ ...laneBtn, opacity: exitPremium.trim() === '' ? 0.6 : 1 }}>
                        Record
                      </button>
                      <button type="button" onClick={() => setLaneConfirm(null)} style={laneBtn}>Cancel</button>
                    </div>
                  </div>
                )}
                {laneConfirm === 'promote_live' && (
                  <div style={{ marginTop: 6, padding: '7px 9px', borderRadius: 6, border: `1px solid ${WL.signal.amber}55`, background: 'rgba(245,166,35,.06)', fontSize: 10, color: WL.text.secondary, lineHeight: 1.55 }}>
                    <b style={{ color: WL.signal.amber }}>Promote to Live Review?</b>
                    <div>This does not place an order.</div>
                    <div>Requires operator 2FA.</div>
                    <div>Requires broker preview/read-back.</div>
                    <div>Model is unvalidated until 30 paper outcomes / 3 months.</div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                      <button type="button" disabled={laneBusy} onClick={() => runLane('promote_live')}
                        style={{ ...laneBtn, border: `1px solid ${WL.signal.amber}`, color: WL.signal.amber }}>
                        Confirm — mark for live review
                      </button>
                      <button type="button" onClick={() => setLaneConfirm(null)} style={laneBtn}>Cancel</button>
                    </div>
                  </div>
                )}
                {laneMsg && <div style={{ fontSize: 9.5, color: WL.text.secondary, marginTop: 5 }}>{laneMsg}</div>}
              </div>
            )}
            <div style={{ fontSize: 9.5, color: WL.text.dim, marginTop: 6 }}>
              {discoveryRef?.candidate_id != null
                ? `from discovery #${discoveryRef.candidate_id} · approved research`
                : matchJson
                  ? `from ${(STRAT_LABEL[matchJson.strategy || p.strategy] || p.strategy)} strategy scanner`
                  : 'discovery lineage unavailable'}
              {p.queue_status ? ` · queue: ${p.queue_status} (manual review)` : ''}
            </div>
          </div>
        )}

        {novice && (
          <div style={{ marginTop: 10, padding: '9px 10px', borderRadius: 8, background: 'rgba(148,163,184,.07)', border: '1px solid rgba(148,163,184,.18)', fontSize: 10.5, color: WL.text.secondary, lineHeight: 1.5 }}>
            <b style={{ color: WL.text.primary }}>In plain English:</b>{' '}
            {(ext.plain_english_hint as string | undefined) || plainEnglishHint(p.strategy) || plainEnglishProposal(p)}
          </div>
        )}

        {novice && dist && p.underlying_price && (
          <div title={dist.label}>
            <div style={{ fontSize: 9, color: WL.text.dim, marginTop: 8 }}>{dist.label}</div>
            <StrikeDistanceBar spot={p.underlying_price} strike={p.strike} side={dist.side} />
          </div>
        )}

        {novice && <RiskFlagChips flags={risks} />}

        {/* ③ Economics grid — headline stats live in the hero; contract detail lives here */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(72px, 1fr))', gap: 7, marginTop: 11 }}>
          <Metric label="Spot" value={`$${fmtNum(p.underlying_price, 2)}`} tip={TIPS.spot} />
          <Metric label="Strike" value={`$${fmtNum(p.strike, p.strike < 50 ? 2 : 0)}`} tip={TIPS.strike} />
          <Metric label="Premium" value={p.premium != null ? fmt$(p.premium, 2) : '—'} color={isCredit ? WL.price.up : WL.text.primary} tip={TIPS.premium} />
          <Metric label={cashflowLabel} value={fmt$(p.premium_total)} color={cfColor} tip={TIPS.totalCashflow} />
          <Metric label="Breakeven" value={p.breakeven != null ? `$${fmtNum(p.breakeven, 2)}` : '—'} tip={TIPS.breakeven} />
          <Metric label="Max profit" value={fmtMoneyish(p.max_profit)} color={WL.price.up} tip={TIPS.maxProfit} />
          {p.strategy === 'covered_call' ? (
            <>
              <Metric label="Stock risk" value={fmt$(stockRisk)} color={WL.signal.red} tip={p.max_loss_note || TIPS.maxLoss} />
              <Metric label="Upside cap" value={p.upside_cap ?? `$${fmtNum(p.strike, p.strike < 50 ? 2 : 0)} if assigned`} color={WL.signal.amber} tip={p.upside_cap_note || TIPS.upsideCap} />
            </>
          ) : (
            <Metric label="Max loss" value={fmtMoneyish(p.max_loss)} color={WL.signal.red} tip={TIPS.maxLoss} />
          )}
          <Metric label="IV rank" value={p.iv_rank != null ? `${p.iv_rank}%` : '—'} tip={TIPS.ivRank} />
          <Metric label="Contracts" value={p.contracts ?? '—'} tip={TIPS.contracts} />
          {p.delta != null && <Metric label="Delta" value={p.delta.toFixed(2)} tip={TIPS.delta} />}
          {p.oi != null && <Metric label="OI" value={fmtNum(p.oi, 0)} tip={TIPS.oi} />}
        </div>

        {novice && <WhatIfBox strategy={p.strategy} symbol={p.symbol} />}

        {reviewBar}

        {/* ④ Underlying context — company + sector · industry · instrument (added 2026-07-04) */}
        {(p.company_description || p.sector) && (
          <div style={{ fontSize: 10, color: WL.text.dim, marginTop: 10, lineHeight: 1.45, borderTop: `1px solid ${WL.surface.divider}`, paddingTop: 8 }}>
            {p.company_description && <span style={{ color: WL.text.secondary }}>{String(p.company_description).slice(0, 160)} </span>}
            {(p.sector || p.industry) && (
              <span>{[p.sector, p.industry, p.instrument_type].filter(Boolean).join(' · ')}</span>
            )}
          </div>
        )}

        {/* ⑤ Footer — execution path + manual log (manual log hidden for paper
            models: there is nothing to execute; desk review/ack is the only action) */}
        {(p.execution_note || showManualLog) && (
          <div onClick={e => e.stopPropagation()} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 9, paddingTop: 8, borderTop: `1px solid ${WL.surface.divider}` }}>
            <span title="Execution route — not data source" style={{ fontSize: 9.5, color: WL.text.dim, fontStyle: 'italic', lineHeight: 1.4, minWidth: 0 }}>
              {p.execution_note || route.label}
            </span>
            {showManualLog && (
              <button type="button" title={ACTIONS.manualLog} onClick={onManualLog} style={{ fontSize: 10, fontWeight: 800, padding: '5px 11px', borderRadius: 6, border: '1px solid rgba(148,163,184,.3)', background: 'transparent', color: WL.text.secondary, cursor: 'help', flexShrink: 0 }}>
                Executed manually
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
