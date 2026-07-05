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

const STRAT_LABEL: Record<string, string> = {
  covered_call: 'Covered Call',
  cash_secured_put: 'Cash-Secured Put',
  long_call: 'Long Call',
  credit_spread: 'Credit Spread',
  protective_put: 'Protective Put',
  deep_itm_call: 'Deep ITM Call',
}

// Stage B (2026-07-05): disclosed-flag labels for paper-model (deep_itm_call) rows.
// Operator ratified: earnings before expiry is a disclosed flag, never a hidden pass.
const PAPER_FLAG_LABELS: Record<string, string> = {
  earnings_before_expiry_operator_flagged: '⚠ earnings before expiry',
  earnings_unknown: 'earnings date unknown',
  delta_proxy_itm_depth: 'Δ from ITM-depth proxy (chain carried no greeks)',
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
  onDrill,
  onManualLog,
  reviewBar,
}: {
  proposal: OptionProposal
  armed?: boolean
  novice?: boolean
  onAction: (action: string, id: string) => void
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

  // ── Stage B: paper-model (deep_itm_call) disclosures — amber, never green ──
  const paper = !!p.educational_paper_model
  const cand = p.meta?.analysis?.candidate
  const bucketDte = p.meta?.dte_bucket?.target_dte ?? p.dte
  const capPct = cand?.capital_vs_100_shares?.capital_ratio_pct
  const paperSummary = paper && cand ? [
    bucketDte != null ? `${bucketDte}d bucket` : null,
    cand.strike != null ? `$${fmtNum(cand.strike, cand.strike < 50 ? 2 : 0)} strike` : null,
    cand.delta != null ? `Δ${Number(cand.delta).toFixed(2)}` : 'Δ proxy',
    cand.breakeven != null
      ? `BE $${fmtNum(cand.breakeven, 2)}${cand.breakeven_move_pct != null ? ` (${cand.breakeven_move_pct > 0 ? '+' : ''}${Number(cand.breakeven_move_pct).toFixed(1)}%)` : ''}`
      : null,
    capPct != null ? `${Math.round(capPct)}% of share capital` : null,
  ].filter(Boolean).join(' · ') : ''
  const paperFlags = paper ? (p.meta?.gate_flags || []).map(f => PAPER_FLAG_LABELS[f] || f.replace(/_/g, ' ')) : []
  const discoveryRef = p.meta?.discovery_ref

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
                DEEP ITM · PAPER MODEL
              </span>
            )}
            {paper && p.validation_progress?.label && (
              <span title={p.validation_progress.message || 'Closed paper outcomes recorded vs the validation gate.'} style={{ ...chip(WL.signal.amber, true), cursor: 'help' }}>
                {p.validation_progress.label}
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
            {paperFlags.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 6 }}>
                {paperFlags.map(f => (
                  <span key={f} style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, color: WL.signal.amber, border: '1px solid rgba(245,166,35,.4)', background: 'transparent' }}>{f}</span>
                ))}
              </div>
            )}
            <div style={{ fontSize: 9.5, color: WL.text.dim, marginTop: 6 }}>
              {discoveryRef?.candidate_id != null
                ? `from discovery #${discoveryRef.candidate_id} · approved research`
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
