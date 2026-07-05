import { useState } from 'react'
import { fmt$, fmtNum } from '../lib/format'
import { plainEnglishProposal, proposalRiskFlags, strikeDistance, strategyGuide } from '../lib/optionsNovice'
import { ACTIONS, PROPOSAL } from '../lib/optionsTooltips'
import { RiskFlagChips, StrikeDistanceBar, WhatIfBox } from './OptionsNovicePanel'
import { composeWhy } from '../lib/watchlistCardV4'
import { WL, numStyle } from '../lib/watchlistCardTokens'
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

const STRAT_LABEL: Record<string, string> = {
  covered_call: 'Covered Call',
  cash_secured_put: 'Cash-Secured Put',
  long_call: 'Long Call',
  credit_spread: 'Credit Spread',
  protective_put: 'Protective Put',
  deep_itm_call: 'Deep ITM Call',
  atm_call: 'ATM Call',
  atm_put: 'ATM Put',
}

// MULTI-STRATEGY Stage 2: strategy-family badge text for paper-model rows
// (rendered next to PAPER MODEL, amber outline — same treatment for all).
const PAPER_FAMILY_BADGE: Record<string, string> = {
  deep_itm_call: 'DEEP ITM',
  atm_call: 'ATM CALL',
  atm_put: 'ATM PUT',
}

// Stage B (2026-07-05): disclosed-flag labels for paper-model rows.
// Operator ratified: earnings before expiry is a disclosed flag, never a hidden pass.
const PAPER_FLAG_LABELS: Record<string, string> = {
  earnings_before_expiry_operator_flagged: '⚠ earnings before expiry',
  earnings_before_expiry_flagged: '⚠ earnings before expiry', // ATM lane flag name
  earnings_unknown: 'earnings date unknown',
  delta_proxy_itm_depth: 'Δ from ITM-depth proxy (chain carried no greeks)',
  delta_proxy_nearest_the_money: 'Δ proxy — nearest-the-money (chain carried no greeks)',
  iv_rich_pay_up_warning: '⚠ IV rich — pay-up warning',
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

function primeChipColor(verdict?: string): string {
  if (verdict === 'PRIME_FOR_PAPER') return WL.signal.teal
  if (verdict === PRIME_VERDICT_LIVE) return WL.signal.amber
  if (verdict === 'PAPER_ONLY') return WL.text.secondary
  return WL.text.dim // NOT_PRIME / unknown → dim
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
  totalCredit: 'Total credit if filled: premium × 100 × contracts.',
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
  const tone = heroTone(p.severity || (p.edge_score && p.edge_score >= 75 ? 'positive' : 'info'))
  const strat = STRAT_LABEL[p.strategy] || p.strategy.replace(/_/g, ' ')
  const edge = p.edge_score != null ? Math.round(p.edge_score) : null
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
  const paperFlags = paper ? (p.meta?.gate_flags || []).map(f => PAPER_FLAG_LABELS[f] || f.replace(/_/g, ' ')) : []
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
  const canSend = paper && !!onAlpacaAction && alpacaEnabled
    && (queueStatus === 'pending' || queueStatus === 'approved' || queueStatus === 'READY_FOR_ALPACA_PAPER')
  const canMarkOutcome = paper && !!onAlpacaAction
    && (queueStatus === 'ALPACA_PAPER_FILLED' || queueStatus === 'ALPACA_PAPER_CLOSED')
  const canPromote = paper && !!onAlpacaAction
    && queueStatus === 'OUTCOME_RECORDED' && prime?.verdict === PRIME_VERDICT_LIVE

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
    if (action === 'review_chain') return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.secondary }
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
            {paper && prime?.prime_score != null && (
              <span
                title={`Prime rubric ${prime.prime_score.toFixed(1)}/100 → ${(prime.verdict || '').replace(/_/g, ' ')}. Advisory label only — 10 weighted components (spread, OI/volume, delta fit, extrinsic, breakeven, IV rank, earnings, sizing, thesis freshness, fill quality). It never transitions state or places orders.`}
                style={{ ...chip(primeChipColor(prime.verdict), prime.verdict === 'NOT_PRIME'), cursor: 'help' }}
              >
                PRIME {Math.round(prime.prime_score)}
              </span>
            )}
            {laneState && (
              <span title={laneState.tip} style={{ ...chip(laneState.color), cursor: 'help' }}>
                ALPACA {laneState.label}
              </span>
            )}
            {ds && <span title={ds.tip} style={chip(ds.c)}>{ds.label}</span>}
            {p.intent_sleeve && <span title="Portfolio intent covered-call sleeve (V/SCHD/LMT) — relaxed edge floor 52 vs 62" style={chip(WL.text.secondary, true)}>income sleeve</span>}
            {p.enterprise?.live_eligible && <span title={PROPOSAL.liveOk} style={{ ...chip(WL.signal.teal), cursor: 'help' }}>live eligible</span>}
            {(p.enterprise?.blocks?.length ?? 0) > 0 && (
              <span title={`${PROPOSAL.liveBlocked} ${p.enterprise!.blocks!.join('; ')}`} style={{ ...chip(WL.signal.red), cursor: 'help' }}>blocked</span>
            )}
            {p.execution_label && (
              <span title="Execution path for this proposal" style={chip(p.execution_mode === 'manual' ? WL.text.secondary : WL.signal.amber, p.execution_mode === 'manual')}>
                {p.execution_label}
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
          <span title={TIPS.totalCredit} style={{ ...numStyle, fontSize: 13.5, fontWeight: 800, color: WL.price.up, flexShrink: 0, cursor: 'help' }}>
            {p.premium_total != null ? fmt$(p.premium_total) : '—'}
          </span>
          <span style={{ display: 'inline-flex', gap: 6, flexShrink: 0 }}>
            {(p.action_buttons || []).map((b, i) => {
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
                  {b.label}{b.action !== 'hold' ? ' →' : ''}
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

      <div style={{ padding: '0 15px 12px' }}>
        {/* Stage B: paper-model disclosure block — analysis one-liner, disclosed
            flags, discovery lineage. Amber-only; no live affordance exists here. */}
        {paper && (
          <div style={{ marginTop: 10, padding: '9px 10px', borderRadius: 8, background: 'rgba(245,166,35,.06)', border: '1px solid rgba(245,166,35,.28)', fontSize: 10.5, lineHeight: 1.55, color: WL.text.secondary }}>
            {paperSummary && (
              <div style={{ ...numStyle, fontSize: 11, fontWeight: 700, color: WL.text.primary }}>{paperSummary}</div>
            )}
            {/* MULTI-STRATEGY Stage 2: why this strategy matched (matcher pass
                reason + thesis source) — dim disclosure line, never a signal color */}
            {matchJson?.why_matched && (
              <div
                title={`Strategy matcher verdict for ${matchJson.strategy || p.strategy}: ${matchJson.status || '—'}. The matcher owns thesis gating (bullish for calls, bearish for puts); generators own contract math.`}
                style={{ fontSize: 10, color: WL.text.dim, marginTop: paperSummary ? 5 : 0, cursor: 'help' }}
              >
                matched: {matchJson.why_matched}
              </div>
            )}
            {thesisLine && !matchJson?.why_matched && (
              <div style={{ fontSize: 10, color: WL.text.dim, marginTop: paperSummary ? 5 : 0 }}>
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
                style={{ fontSize: 10, fontWeight: 700, color: ivColor, marginTop: paperSummary ? 5 : 0, cursor: 'help' }}
              >
                {ivLine}
              </div>
            )}
            {paperFlags.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 6 }}>
                {paperFlags.map(f => (
                  <span key={f} style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, color: WL.signal.amber, border: '1px solid rgba(245,166,35,.4)', background: 'transparent' }}>{f}</span>
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
                      title="Two-step: confirm, then operator mark-ready + submit a single paper LIMIT order. Paper endpoint only — there is no live order path here."
                      style={{ ...laneBtn, border: `1px solid ${WL.signal.teal}55`, color: WL.signal.teal }}>
                      Send to Alpaca Paper ▸
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
                {laneConfirm === 'send' && (
                  <div style={{ marginTop: 6, padding: '7px 9px', borderRadius: 6, border: `1px solid ${WL.signal.teal}44`, background: 'rgba(45,212,191,.05)', fontSize: 10, color: WL.text.secondary }}>
                    <b style={{ color: WL.text.primary }}>Send to Alpaca Paper?</b> paper endpoint only · limit · 1 contract
                    <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                      <button type="button" disabled={laneBusy} onClick={() => runLane('send')}
                        style={{ ...laneBtn, background: WL.signal.teal, border: `1px solid ${WL.signal.teal}`, color: '#06231f' }}>
                        Confirm — submit paper order
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
            <b style={{ color: WL.text.primary }}>In plain English:</b> {plainEnglishProposal(p)}
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
          <Metric label="Premium" value={p.premium != null ? fmt$(p.premium, 2) : '—'} color={WL.price.up} tip={TIPS.premium} />
          <Metric label="Total credit" value={fmt$(p.premium_total)} color={WL.price.up} tip={TIPS.totalCredit} />
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
        {(p.execution_note || (onManualLog && !paper)) && (
          <div onClick={e => e.stopPropagation()} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 9, paddingTop: 8, borderTop: `1px solid ${WL.surface.divider}` }}>
            <span title="Live execution path status" style={{ fontSize: 9.5, color: WL.text.dim, fontStyle: 'italic', lineHeight: 1.4, minWidth: 0 }}>
              {p.execution_note || ''}
            </span>
            {onManualLog && !paper && (
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
