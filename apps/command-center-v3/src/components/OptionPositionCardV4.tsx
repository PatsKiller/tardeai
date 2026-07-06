import { useState } from 'react'
import { fmt$, fmtNum } from '../lib/format'
import { plainEnglishPosition } from '../lib/optionsNovice'
import { ACTIONS, POSITION } from '../lib/optionsTooltips'
import { WhatIfBox } from './OptionsNovicePanel'
import OptionMoneynessBar from './risk/OptionMoneynessBar'
import OptionsPnLProfile from './risk/OptionsPnLProfile'
import { composeWhy } from '../lib/watchlistCardV4'
import { WL, numStyle } from '../lib/watchlistCardTokens'
import type { OptionPosition } from './OptionPositionCard'

// Option Position Card v4 — options-desk member of the card-v4 family (2026-07-04).
// v3 (OptionPositionCard) stays untouched; the global cc.cards.v4 toggle selects.
// One tinted two-row hero owns the card: row 1 = lifecycle word + one deduped
// sentence (composeWhy over recommended_action + rationale) + headline P&L + actions;
// row 2 = moneyness · delta · DTE · mark vs entry · still-working status dot.
// Color discipline: teal/amber/red = signal only; green = P&L numerals only.
//
// INTELLIGENCE PARITY CHECKLIST — every field the v3 card renders, and where v4 renders it:
//   [PASS] SEV status badge (severity/still_working) → hero row 2: status dot + word (WORKING/ACTION/CRITICAL/INFO)
//   [PASS] lifecycle badge (LET MATURE/HARVEST/…)    → hero row 1 state word (tooltip kept)
//   [PASS] strategy label                            → header
//   [PASS] underlying symbol                         → header identity
//   [PASS] moneyness badge (ITM/OTM/ATM)             → hero row 2 (tooltip kept; ITM red / OTM teal / ATM amber)
//   [PASS] strike headline                           → header
//   [PASS] DTE headline + DTE metric                 → hero row 2 (theta tooltip kept)
//   [PASS] expiration (fmtExpiry)                    → header
//   [PASS] recommended_action chip                   → hero row 1 sentence (leads composeWhy; tooltip kept)
//   [PASS] novice plain-English position box         → below hero (unchanged)
//   [PASS] novice still_working warning box          → below hero (unchanged)
//   [PASS] OptionMoneynessBar                        → below hero (unchanged)
//   [PASS] maturity_note box + lifecycle heading     → below moneyness bar (signal-toned)
//   [PASS] Spot metric                               → economics grid
//   [PASS] Mark metric                               → hero row 2 "mark X vs entry Y" + grid tooltip
//   [PASS] Entry metric                              → hero row 2 "mark X vs entry Y"
//   [PASS] P/L metric                                → hero row 1 headline economics
//   [PASS] R:R (live) metric                         → economics grid
//   [PASS] Max profit metric                         → economics grid
//   [PASS] Max loss metric                           → economics grid
//   [PASS] % captured metric                         → economics grid
//   [PASS] Δ (delta) metric                          → hero row 2
//   [PASS] POP OTM metric                            → economics grid
//   [PASS] POP ITM metric                            → economics grid
//   [PASS] Qty metric                                → economics grid
//   [PASS] Edge metric                               → economics grid
//   [PASS] expiry P/L profile toggle + chart         → below grid (unchanged)
//   [PASS] novice WhatIfBox                          → below grid (unchanged)
//   [PASS] rationale (WHY THIS ACTION)               → hero row 1 sentence (full text in tooltip)
//   [PASS] company_description + sector · industry · instrument_type
//                                                    → underlying-context line below grid
//   [PASS] occ_symbol mono line                      → footer
//   [PASS] action_buttons w/ tooltips                → hero row 1 (close/roll = amber signal)

type Tone = { c: string; label: string }

const statusTone = (s?: string, working?: boolean): Tone => {
  const v = (s || '').toLowerCase()
  if (/crit|urgent/.test(v)) return { c: WL.signal.red, label: 'CRITICAL' }
  if (/warn/.test(v) || working === false) return { c: WL.signal.amber, label: 'ACTION' }
  if (/pos/.test(v)) return { c: WL.signal.teal, label: 'WORKING' }
  return { c: WL.text.secondary, label: 'INFO' }
}

const LIFECYCLE_STYLE: Record<string, Tone> = {
  let_mature: { c: WL.signal.teal, label: 'LET MATURE' },
  harvest: { c: WL.signal.amber, label: 'HARVEST' },
  defend: { c: WL.signal.red, label: 'DEFEND' },
  monitor: { c: WL.text.secondary, label: 'MONITOR' },
}

const heroBg = (c: string) =>
  c === WL.signal.red ? { bg: 'rgba(239,83,80,.07)', border: 'rgba(239,83,80,.25)' }
    : c === WL.signal.amber ? { bg: 'rgba(245,166,35,.07)', border: 'rgba(245,166,35,.25)' }
      : c === WL.signal.teal ? { bg: 'rgba(45,212,191,.08)', border: 'rgba(45,212,191,.28)' }
        : { bg: 'rgba(148,163,184,.06)', border: 'rgba(148,163,184,.16)' }

function fmtExpiry(iso?: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return iso
  }
}

const statKey: React.CSSProperties = { color: WL.text.dim, fontWeight: 700 }

function Metric({ label, value, color = WL.text.primary, tip }: { label: string; value: React.ReactNode; color?: string; tip?: string }) {
  return (
    <div title={tip} style={{ background: WL.surface.inset, border: `1px solid ${WL.surface.edge}`, borderRadius: 8, padding: '7px 8px' }}>
      <div style={{ fontSize: 8, color: WL.text.dim, textTransform: 'uppercase', fontWeight: 800, letterSpacing: '.04em' }}>{label}</div>
      <div style={{ ...numStyle, fontSize: 12.5, color, fontWeight: 800, marginTop: 2, cursor: tip ? 'help' : undefined }}>{value}</div>
    </div>
  )
}

export default function OptionPositionCardV4({
  position: p,
  novice,
  onAction,
  onDrill,
}: {
  position: OptionPosition
  novice?: boolean
  onAction: (action: string, id: string) => void
  onDrill?: () => void
}) {
  const [showRisk, setShowRisk] = useState(false)
  const status = statusTone(p.severity, p.still_working)
  const lc = LIFECYCLE_STYLE[p.lifecycle_phase || 'monitor'] || LIFECYCLE_STYLE.monitor
  // The card's tone follows urgency: status wins when it signals, else lifecycle.
  const toneColor = status.c === WL.text.secondary ? lc.c : status.c
  const hero = heroBg(toneColor)
  const pnl = p.unrealized_pnl
  const pnlColor = pnl == null ? WL.text.primary : pnl >= 0 ? WL.price.up : WL.price.down
  const strat = (p.strategy || 'option').replace(/_/g, ' ')
  const rrDisplay = p.risk_reward != null
    ? (p.risk_reward >= 1 ? `${p.risk_reward.toFixed(2)}:1` : `1:${(1 / Math.max(p.risk_reward, 0.01)).toFixed(1)}`)
    : '—'
  const moneyColor = p.moneyness === 'ITM' ? WL.signal.red : p.moneyness === 'OTM' ? WL.signal.teal : WL.signal.amber

  // Rule-of-one hero sentence — recommended action leads, rationale follows;
  // composeWhy drops a rationale that just restates the action.
  const whyLine = composeWhy([p.recommended_action, p.rationale])

  const btnStyle = (action: string): React.CSSProperties => {
    const base: React.CSSProperties = { fontSize: 10, fontWeight: 700, padding: '5px 11px', borderRadius: 6, whiteSpace: 'nowrap', cursor: 'help' }
    if (action === 'hold') return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.dim }
    if (action === 'review_chain') return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.secondary }
    if (/close|roll/.test(action)) return { ...base, fontWeight: 800, border: `1px solid ${WL.signal.amber}`, background: WL.signal.amber, color: '#231602' }
    return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.secondary }
  }

  return (
    <div
      onClick={onDrill}
      style={{
        background: WL.surface.card,
        border: `1px solid ${WL.surface.edge}`,
        borderLeft: `3px solid ${toneColor}`,
        borderRadius: WL.card.radius,
        boxShadow: WL.card.shadow,
        cursor: onDrill ? 'pointer' : 'default',
        minWidth: 0,
        overflow: 'hidden',
        color: WL.text.primary,
      }}
    >
      {/* ① Header — identity + contract; quiet */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', padding: '10px 15px 8px' }}>
        <span style={{ ...numStyle, fontSize: 18, fontWeight: 800 }}>{p.underlying}</span>
        <span style={{ fontSize: 10, color: WL.text.dim }}>{strat}</span>
        <span style={{ ...numStyle, fontSize: 13, fontWeight: 700, color: WL.text.secondary }}>${fmtNum(p.strike, 2)}</span>
        <span style={{ fontSize: 10.5, color: WL.text.dim }}>{fmtExpiry(p.expiration)}</span>
        {p.execution_route_badge && (
          <span
            title={p.execution_note || p.execution_route_badge}
            style={{ fontSize: 8.5, fontWeight: 800, padding: '2px 7px', borderRadius: 4, letterSpacing: '.04em',
              color: p.execution_route_kind === 'schwab_live' ? WL.signal.teal : '#f59e0b',
              border: `1px solid ${p.execution_route_kind === 'schwab_live' ? 'rgba(45,212,191,.35)' : 'rgba(245,158,11,.4)'}`,
              cursor: 'help' }}
          >
            {p.execution_route_badge}
          </span>
        )}
        {p.safety_status_badge?.label && (
          <span
            title={p.safety_status_badge.tip}
            style={{ fontSize: 8.5, fontWeight: 800, padding: '2px 7px', borderRadius: 4, letterSpacing: '.04em',
              color: p.safety_status_badge.severity === 'danger' ? WL.signal.red : WL.signal.amber,
              border: `1px solid ${p.safety_status_badge.severity === 'danger' ? 'rgba(239,83,80,.4)' : 'rgba(245,166,35,.45)'}`,
              cursor: 'help' }}
          >
            {p.safety_status_badge.label}
          </span>
        )}
        {p.position_source === 'monitored' && (
          <span style={{ fontSize: 8, fontWeight: 700, color: WL.text.dim, letterSpacing: '.05em' }}>LIFECYCLE</span>
        )}
      </div>

      {/* ② Hero — two rows, the only tinted surface, owns the card */}
      <div
        onClick={e => e.stopPropagation()}
        style={{ background: hero.bg, borderTop: `1px solid ${hero.border}`, borderBottom: `1px solid ${hero.border}`, padding: '10px 15px 9px', display: 'flex', flexDirection: 'column', gap: 7 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span title={POSITION.lifecycle} style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: '.08em', color: lc.c, flexShrink: 0, cursor: 'help' }}>
            {lc.label}
          </span>
          <span
            title={[POSITION.recommended, p.recommended_action, p.rationale].filter(Boolean).join('\n')}
            style={{ fontSize: 12.5, fontWeight: 700, color: WL.text.primary, minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          >
            {whyLine || '—'}
          </span>
          <span title="Unrealized P&L on this leg." style={{ ...numStyle, fontSize: 13.5, fontWeight: 800, color: pnlColor, flexShrink: 0, cursor: 'help' }}>
            {pnl != null ? `${pnl >= 0 ? '+' : ''}${fmt$(pnl)}` : '—'}
          </span>
          <span style={{ display: 'inline-flex', gap: 6, flexShrink: 0 }}>
            {(p.action_buttons || []).map((b, i) => (
              <button
                key={`${b.action}-${i}`}
                type="button"
                title={b.action === 'hold' ? ACTIONS.hold : b.action === 'review_chain' ? ACTIONS.reviewChain : /close|roll/.test(b.action) ? ACTIONS.closeRoll : undefined}
                onClick={() => onAction(b.action, p.id)}
                style={btnStyle(b.action)}
              >
                {b.label}{b.action !== 'hold' ? ' →' : ''}
              </button>
            ))}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: 11, color: WL.text.secondary }}>
          {p.moneyness && (
            <b title={POSITION.moneyness} style={{ color: moneyColor, cursor: 'help' }}>{p.moneyness}</b>
          )}
          <span title="Delta from Schwab chain."><span style={statKey}>Δ </span><span style={numStyle}>{p.delta != null ? p.delta.toFixed(2) : '—'}</span></span>
          <span title="Days to expiration — theta accelerates under ~14 DTE."><span style={statKey}>DTE </span><span style={numStyle}>{p.dte ?? '—'}</span></span>
          <span title="Current option mark from broker vs average entry premium per contract.">
            <span style={statKey}>mark </span><span style={numStyle}>{p.mark != null ? fmt$(p.mark, 2) : '—'}</span>
            <span style={{ color: WL.text.dim }}> vs </span><span style={numStyle}>{p.avg_entry != null ? fmt$(p.avg_entry, 2) : '—'}</span>
            <span style={{ color: WL.text.dim }}> entry</span>
          </span>
          <span title={POSITION.status} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto', cursor: 'help' }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: status.c, flex: 'none' }} />
            <b style={{ color: status.c, fontSize: 10, letterSpacing: '.06em' }}>{status.label}</b>
          </span>
        </div>
      </div>

      <div style={{ padding: '0 15px 12px' }}>
        {novice && (
          <div style={{ marginTop: 10, padding: '9px 10px', borderRadius: 8, background: 'rgba(148,163,184,.07)', border: '1px solid rgba(148,163,184,.18)', fontSize: 10.5, color: WL.text.secondary, lineHeight: 1.5 }}>
            <b style={{ color: WL.text.primary }}>Your position:</b> {plainEnglishPosition(p)}
          </div>
        )}

        {novice && p.still_working === false && (
          <div style={{ marginTop: 8, padding: '6px 9px', borderRadius: 6, background: 'rgba(245,166,35,.12)', border: '1px solid rgba(245,166,35,.35)', fontSize: 10, color: WL.signal.amber, fontWeight: 700 }}>
            ⚠ This leg may need attention — see the recommended action in the banner.
          </div>
        )}

        <OptionMoneynessBar
          moneyness={p.moneyness}
          spot={Number(p.underlying_price)}
          strike={Number(p.strike)}
          popOtm={p.pop_otm_pct}
          popItm={p.pop_itm_pct}
          optionType={p.option_type || 'call'}
          compact
        />

        {p.maturity_note && (
          <div title={POSITION.maturityBox} style={{
            marginTop: 10, padding: '8px 10px', borderRadius: 8, fontSize: 10.5, lineHeight: 1.45,
            background: `${lc.c}12`, border: `1px solid ${lc.c}33`, color: WL.text.secondary, cursor: 'help',
          }}>
            <span style={{ fontSize: 9, fontWeight: 800, color: lc.c, display: 'block', marginBottom: 3 }}>
              {p.lifecycle_phase === 'let_mature' ? 'Let contract mature' : p.lifecycle_phase === 'harvest' ? 'When to sell' : p.lifecycle_phase === 'defend' ? 'Action needed' : 'Trade management'}
            </span>
            {p.maturity_note}
          </div>
        )}

        {/* ③ Economics grid — headline stats live in the hero; risk detail lives here */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(72px, 1fr))', gap: 7, marginTop: 11 }}>
          <Metric label="Spot" value={`$${fmtNum(p.underlying_price, 2)}`} tip="Current underlying price." />
          <Metric label="R:R (live)" value={rrDisplay} tip="Dynamic risk/reward vs max loss at open — updates each monitor refresh." />
          <Metric label="Max profit" value={p.max_profit_at_open != null ? fmt$(p.max_profit_at_open) : '—'} color={WL.price.up} tip="Best case at entry (short = full premium collected)." />
          <Metric label="Max loss" value={p.max_loss_at_open != null ? fmt$(p.max_loss_at_open) : '—'} color={WL.signal.amber} tip="Worst-case loss modeled at entry." />
          <Metric label="% captured" value={p.profit_captured_pct != null ? `${p.profit_captured_pct}%` : '—'} color={WL.price.up} tip="Short premium: % of entry credit already earned as mark decays." />
          <Metric label="POP OTM" value={p.pop_otm_pct != null ? `${p.pop_otm_pct.toFixed(0)}%` : '—'} color={WL.signal.teal} tip="Chance option expires out of the money." />
          <Metric label="POP ITM" value={p.pop_itm_pct != null ? `${p.pop_itm_pct.toFixed(0)}%` : '—'} tip="Chance option finishes in the money." />
          <Metric label="Qty" value={p.qty ?? '—'} tip="Contracts held (negative = short)." />
          <Metric label="Edge" value={p.edge_score != null ? Math.round(p.edge_score) : '—'} tip="Monitor edge score from POP and IV." />
        </div>

        <div onClick={e => e.stopPropagation()} style={{ marginTop: 10 }}>
          <button
            type="button"
            title={POSITION.expiryPnl}
            onClick={() => setShowRisk(v => !v)}
            style={{
              fontSize: 9, fontWeight: 800, padding: '5px 10px', borderRadius: 6, cursor: 'help',
              border: '1px solid rgba(148,163,184,.3)', background: showRisk ? 'rgba(148,163,184,.12)' : 'transparent', color: WL.text.secondary,
            }}
          >
            {showRisk ? '▾ Hide' : '▸ Show'} expiry P/L profile
          </button>
          {showRisk && p.strike && p.underlying_price && (
            <div style={{ marginTop: 8, padding: '8px 10px', borderRadius: 8, background: WL.surface.inset, border: `1px solid ${WL.surface.edge}` }}>
              <OptionsPnLProfile
                underlying={p.underlying}
                side={p.side || p.strategy}
                optionType={p.option_type || 'call'}
                strike={Number(p.strike)}
                spot={Number(p.underlying_price)}
                qty={Math.abs(Number(p.qty) || 1)}
                avgEntry={Number(p.avg_entry)}
                mark={Number(p.mark)}
                compact
                hideTitle
              />
            </div>
          )}
        </div>

        {novice && p.strategy && <WhatIfBox strategy={(p.strategy === 'short_put' ? 'cash_secured_put' : p.strategy === 'short_call' ? 'covered_call' : p.strategy.replace(/^long_/, 'long_'))} symbol={p.underlying} />}

        {/* ④ Underlying context — company + sector · industry · instrument (added 2026-07-04) */}
        {(p.company_description || p.sector) && (
          <div style={{ fontSize: 10, color: WL.text.dim, marginTop: 10, lineHeight: 1.45, borderTop: `1px solid ${WL.surface.divider}`, paddingTop: 8 }}>
            {p.company_description && <span style={{ color: WL.text.secondary }}>{String(p.company_description).slice(0, 160)} </span>}
            {(p.sector || p.industry) && (
              <span>{[p.sector, p.industry, p.instrument_type].filter(Boolean).join(' · ')}</span>
            )}
          </div>
        )}

        {/* ⑤ Footer — OCC contract identity */}
        {p.occ_symbol && <div style={{ ...numStyle, fontSize: 9, color: WL.text.dim, marginTop: 8 }}>{p.occ_symbol}</div>}
      </div>
    </div>
  )
}
