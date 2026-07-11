import { useState } from 'react'
import { fmt$, fmtNum } from '../lib/format'
import { plainEnglishPosition } from '../lib/optionsNovice'
import { ACTIONS, POSITION } from '../lib/optionsTooltips'
import { OpenPositionEducation, WhatIfBox } from './OptionsNovicePanel'
import OptionMoneynessBar from './risk/OptionMoneynessBar'
import OptionsPnLProfile from './risk/OptionsPnLProfile'
import { composeWhy } from '../lib/watchlistCardV4'
import { WL, numStyle } from '../lib/watchlistCardTokens'
import type { ActionUrgency, CardVerdict } from '../lib/watchlistCardAction'
import { useTerminalUi } from '../lib/terminalUi'
import { cardShell, modRow, modLabel, gridClass, gridCellClass, statusStrip, ctxLine, ctxKey } from '../lib/terminalCardTheme'
import {
  BB,
  numStyle as termNumStyle,
  terminalRail,
  terminalButton,
  terminalVerdictBg,
  terminalVerdictColor,
} from '../lib/watchlistTerminalTokens'
import type { OptionPosition } from './OptionPositionCard'

// Option Position Card v4 — options-desk member of the card-v4 family (2026-07-04).
// Bloomberg Terminal UI mode (2026-07-11): dense shell, hairline borders, amber primary
// actions when terminalUi on; legacy v4 chrome when off. All functionality preserved.

type Tone = { c: string; label: string }

function optionVerdictFromStatus(severity?: string, working?: boolean, lifecycle?: string): { verdict: CardVerdict; urgency: ActionUrgency } {
  const v = (severity || '').toLowerCase()
  if (/crit|urgent/.test(v) || lifecycle === 'defend') return { verdict: 'FIX', urgency: 'red' }
  if (/warn/.test(v) || working === false || lifecycle === 'harvest') return { verdict: 'WAIT', urgency: 'amber' }
  if (/pos/.test(v) || lifecycle === 'let_mature') return { verdict: 'READY', urgency: 'green' }
  return { verdict: 'WATCH', urgency: 'none' }
}

const statusTone = (s?: string, working?: boolean, terminal?: boolean): Tone => {
  const v = (s || '').toLowerCase()
  if (/crit|urgent/.test(v)) return { c: terminal ? BB.red : WL.signal.red, label: 'CRITICAL' }
  if (/warn/.test(v) || working === false) return { c: terminal ? BB.amber : WL.signal.amber, label: 'ACTION' }
  if (/pos/.test(v)) return { c: terminal ? BB.green : WL.signal.teal, label: 'WORKING' }
  return { c: terminal ? BB.text2 : WL.text.secondary, label: 'INFO' }
}

const LIFECYCLE_STYLE = (terminal?: boolean): Record<string, Tone> => ({
  let_mature: { c: terminal ? BB.green : WL.signal.teal, label: 'LET MATURE' },
  harvest: { c: terminal ? BB.amber : WL.signal.amber, label: 'HARVEST' },
  defend: { c: terminal ? BB.red : WL.signal.red, label: 'DEFEND' },
  monitor: { c: terminal ? BB.text2 : WL.text.secondary, label: 'MONITOR' },
})

const heroBg = (c: string, terminal?: boolean) => {
  if (terminal) {
    if (c === BB.red) return { bg: BB.redDim, border: BB.red }
    if (c === BB.amber) return { bg: BB.amberDim, border: BB.amber }
    if (c === BB.green) return { bg: BB.greenDim, border: BB.green }
    return { bg: 'rgba(148, 163, 184, 0.06)', border: BB.border }
  }
  return c === WL.signal.red ? { bg: 'rgba(239,83,80,.07)', border: 'rgba(239,83,80,.25)' }
    : c === WL.signal.amber ? { bg: 'rgba(245,166,35,.07)', border: 'rgba(245,166,35,.25)' }
      : c === WL.signal.teal ? { bg: 'rgba(45,212,191,.08)', border: 'rgba(45,212,191,.28)' }
        : { bg: 'rgba(148,163,184,.06)', border: 'rgba(148,163,184,.16)' }
}

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

function Metric({
  label, value, color, tip, terminal,
}: { label: string; value: React.ReactNode; color?: string; tip?: string; terminal?: boolean }) {
  if (terminal) {
    return (
      <div title={tip} style={{ padding: '4px 2px', minWidth: 0, cursor: tip ? 'help' : undefined }}>
        <div style={{ fontSize: 8, color: BB.text3, textTransform: 'uppercase', fontWeight: 800, letterSpacing: '.04em' }}>{label}</div>
        <div style={{ ...termNumStyle, fontSize: 11, color: color || BB.text0, fontWeight: 800, marginTop: 1 }}>{value}</div>
      </div>
    )
  }
  return (
    <div title={tip} style={{ background: WL.surface.inset, border: `1px solid ${WL.surface.edge}`, borderRadius: 8, padding: '7px 8px' }}>
      <div style={{ fontSize: 8, color: WL.text.dim, textTransform: 'uppercase', fontWeight: 800, letterSpacing: '.04em' }}>{label}</div>
      <div style={{ ...numStyle, fontSize: 12.5, color: color || WL.text.primary, fontWeight: 800, marginTop: 2, cursor: tip ? 'help' : undefined }}>{value}</div>
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
  const [terminalUi] = useTerminalUi()
  const [showRisk, setShowRisk] = useState(false)
  const hair = `1px solid ${BB.border}`
  const ns = terminalUi ? termNumStyle : numStyle
  const lifecycleStyles = LIFECYCLE_STYLE(terminalUi)
  const status = statusTone(p.severity, p.still_working, terminalUi)
  const lc = lifecycleStyles[p.lifecycle_phase || 'monitor'] || lifecycleStyles.monitor
  const { verdict, urgency } = optionVerdictFromStatus(p.severity, p.still_working, p.lifecycle_phase)
  const rail = terminalUi ? terminalRail(verdict, urgency) : (status.c === WL.text.secondary ? lc.c : status.c)
  const verdictColor = terminalVerdictColor(verdict, urgency)
  const verdictBg = terminalVerdictBg(verdict, urgency)
  const toneColor = status.c === (terminalUi ? BB.text2 : WL.text.secondary) ? lc.c : status.c
  const hero = heroBg(toneColor, terminalUi)
  const pnl = p.unrealized_pnl
  const pnlColor = pnl == null
    ? (terminalUi ? BB.text0 : WL.text.primary)
    : terminalUi
      ? (pnl >= 0 ? BB.green : BB.red)
      : (pnl >= 0 ? WL.price.up : WL.price.down)
  const strat = (p.strategy || 'option').replace(/_/g, ' ')
  const rrDisplay = p.risk_reward != null
    ? (p.risk_reward >= 1 ? `${p.risk_reward.toFixed(2)}:1` : `1:${(1 / Math.max(p.risk_reward, 0.01)).toFixed(1)}`)
    : '—'
  const moneyColor = p.moneyness === 'ITM'
    ? (terminalUi ? BB.red : WL.signal.red)
    : p.moneyness === 'OTM'
      ? (terminalUi ? BB.green : WL.signal.teal)
      : (terminalUi ? BB.amber : WL.signal.amber)

  const whyLine = composeWhy([p.recommended_action, p.rationale])

  const btnStyle = (action: string): React.CSSProperties => {
    if (terminalUi) {
      if (action === 'hold') return terminalButton('ghost')
      if (action === 'review_chain') return terminalButton('secondary')
      if (/close|roll/.test(action)) return terminalButton('primary')
      return terminalButton('secondary')
    }
    const base: React.CSSProperties = { fontSize: 10, fontWeight: 700, padding: '5px 11px', borderRadius: 6, whiteSpace: 'nowrap', cursor: 'help' }
    if (action === 'hold') return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.dim }
    if (action === 'review_chain') return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.secondary }
    if (/close|roll/.test(action)) return { ...base, fontWeight: 800, border: `1px solid ${WL.signal.amber}`, background: WL.signal.amber, color: '#231602' }
    return { ...base, border: '1px solid rgba(148,163,184,.25)', background: 'transparent', color: WL.text.secondary }
  }

  const statKeyStyle = terminalUi ? { color: BB.text3, fontWeight: 700 } : { color: WL.text.dim, fontWeight: 700 }
  const bodyPad = terminalUi ? { ...modRow(terminalUi) } : { padding: '0 15px 12px' }

  return (
    <div
      onClick={onDrill}
      style={{
        ...cardShell(rail, terminalUi),
        cursor: onDrill ? 'pointer' : 'default',
        boxShadow: terminalUi ? undefined : WL.card.shadow,
      }}
    >
      {/* ① Header — identity + contract */}
      <div
        style={terminalUi
          ? { display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', padding: '5px 10px', borderBottom: hair }
          : { display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', padding: '10px 15px 8px' }}
        onClick={e => e.stopPropagation()}
      >
        <span style={{ ...ns, fontSize: terminalUi ? 16 : 18, fontWeight: 800, color: terminalUi ? BB.text0 : undefined }}>{p.underlying}</span>
        <span style={{ fontSize: terminalUi ? 9 : 10, color: terminalUi ? BB.text3 : WL.text.dim, textTransform: terminalUi ? 'uppercase' : undefined, letterSpacing: terminalUi ? '.05em' : undefined }}>{strat}</span>
        <span style={{ ...ns, fontSize: terminalUi ? 12 : 13, fontWeight: 700, color: terminalUi ? BB.text2 : WL.text.secondary }}>${fmtNum(p.strike, 2)}</span>
        <span style={{ fontSize: terminalUi ? 9.5 : 10.5, color: terminalUi ? BB.text3 : WL.text.dim }}>{fmtExpiry(p.expiration)}</span>
        {p.execution_route_badge && (
          <span
            title={p.execution_note || p.execution_route_badge}
            className={terminalUi ? 'wlc-term-tag' : undefined}
            style={{
              fontSize: terminalUi ? 8 : 8.5, fontWeight: 800, padding: terminalUi ? undefined : '2px 7px',
              borderRadius: terminalUi ? undefined : 4, letterSpacing: '.04em',
              color: p.execution_route_kind === 'schwab_live' ? (terminalUi ? BB.green : WL.signal.teal) : BB.amber,
              border: terminalUi ? undefined : `1px solid ${p.execution_route_kind === 'schwab_live' ? 'rgba(45,212,191,.35)' : 'rgba(245,158,11,.4)'}`,
              cursor: 'help',
            }}
          >
            {p.execution_route_badge}
          </span>
        )}
        {p.safety_status_badge?.label && (
          <span
            title={p.safety_status_badge.tip}
            className={terminalUi ? 'wlc-term-tag' : undefined}
            style={{
              fontSize: terminalUi ? 8 : 8.5, fontWeight: 800, padding: terminalUi ? undefined : '2px 7px',
              borderRadius: terminalUi ? undefined : 4, letterSpacing: '.04em',
              color: p.safety_status_badge.severity === 'danger' ? (terminalUi ? BB.red : WL.signal.red) : (terminalUi ? BB.amber : WL.signal.amber),
              border: terminalUi ? undefined : `1px solid ${p.safety_status_badge.severity === 'danger' ? 'rgba(239,83,80,.4)' : 'rgba(245,166,35,.45)'}`,
              cursor: 'help',
            }}
          >
            {p.safety_status_badge.label}
          </span>
        )}
        {p.position_source === 'monitored' && (
          <span style={{ fontSize: 8, fontWeight: 700, color: terminalUi ? BB.text3 : WL.text.dim, letterSpacing: '.05em' }}>LIFECYCLE</span>
        )}
      </div>

      {/* ② Hero — lifecycle + action + headline metrics */}
      <div
        onClick={e => e.stopPropagation()}
        style={terminalUi
          ? { ...statusStrip(verdictBg, true), flexDirection: 'column', alignItems: 'stretch', gap: 4 }
          : { background: hero.bg, borderTop: `1px solid ${hero.border}`, borderBottom: `1px solid ${hero.border}`, padding: '10px 15px 9px', display: 'flex', flexDirection: 'column', gap: 7 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: terminalUi ? 8 : 10 }}>
          <span
            title={POSITION.lifecycle}
            style={{
              fontSize: terminalUi ? 10 : 10.5, fontWeight: 800, letterSpacing: '.08em',
              color: terminalUi ? verdictColor : lc.c, flexShrink: 0, cursor: 'help',
            }}
          >
            {lc.label}
          </span>
          <span
            title={[POSITION.recommended, p.recommended_action, p.rationale].filter(Boolean).join('\n')}
            style={{
              fontSize: terminalUi ? 10 : 12.5, fontWeight: terminalUi ? 600 : 700,
              color: terminalUi ? BB.text0 : WL.text.primary, minWidth: 0, flex: 1,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
          >
            {whyLine || '—'}
          </span>
          <span title="Unrealized P&L on this leg." style={{ ...ns, fontSize: terminalUi ? 12 : 13.5, fontWeight: 800, color: pnlColor, flexShrink: 0, cursor: 'help' }}>
            {pnl != null ? `${pnl >= 0 ? '+' : ''}${fmt$(pnl)}` : '—'}
          </span>
          <span style={{ display: 'inline-flex', gap: terminalUi ? 4 : 6, flexShrink: 0 }}>
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
        <div style={{
          display: 'flex', alignItems: 'center', gap: terminalUi ? 10 : 12, flexWrap: 'wrap',
          fontSize: terminalUi ? 9.5 : 11, color: terminalUi ? BB.text2 : WL.text.secondary,
        }}>
          {p.moneyness && (
            <b title={POSITION.moneyness} style={{ color: moneyColor, cursor: 'help' }}>{p.moneyness}</b>
          )}
          <span title="Delta from Schwab chain."><span style={statKeyStyle}>Δ </span><span style={ns}>{p.delta != null ? p.delta.toFixed(2) : '—'}</span></span>
          <span title="Days to expiration — theta accelerates under ~14 DTE."><span style={statKeyStyle}>DTE </span><span style={ns}>{p.dte ?? '—'}</span></span>
          <span title="Current option mark from broker vs average entry premium per contract.">
            <span style={statKeyStyle}>mark </span><span style={ns}>{p.mark != null ? fmt$(p.mark, 2) : '—'}</span>
            <span style={{ color: terminalUi ? BB.text3 : WL.text.dim }}> vs </span><span style={ns}>{p.avg_entry != null ? fmt$(p.avg_entry, 2) : '—'}</span>
            <span style={{ color: terminalUi ? BB.text3 : WL.text.dim }}> entry</span>
          </span>
          <span title={POSITION.status} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto', cursor: 'help' }}>
            <span style={{ width: terminalUi ? 5 : 6, height: terminalUi ? 5 : 6, borderRadius: terminalUi ? 1 : '50%', background: terminalUi ? verdictColor : status.c, flex: 'none' }} />
            <b style={{ color: terminalUi ? verdictColor : status.c, fontSize: 10, letterSpacing: '.06em' }}>{status.label}</b>
          </span>
        </div>
      </div>

      <div style={bodyPad} onClick={e => e.stopPropagation()}>
        {novice && (
          <div style={{
            marginTop: terminalUi ? 0 : 10, padding: terminalUi ? '5px 0' : '9px 10px',
            borderRadius: terminalUi ? 0 : 8,
            background: terminalUi ? 'transparent' : 'rgba(148,163,184,.07)',
            border: terminalUi ? 'none' : '1px solid rgba(148,163,184,.18)',
            fontSize: terminalUi ? 9.5 : 10.5,
            color: terminalUi ? BB.text2 : WL.text.secondary, lineHeight: 1.5,
            borderTop: terminalUi ? hair : undefined,
          }}>
            <b style={{ color: terminalUi ? BB.text0 : WL.text.primary }}>Your position:</b> {plainEnglishPosition(p)}
          </div>
        )}
        {novice && (p.position_source === 'monitored' || p.paper_only) && (
          <OpenPositionEducation position={{
            strategy: p.strategy || 'deep_itm_call',
            symbol: p.underlying,
            underlying: p.underlying,
            strike: p.strike,
            entry_fill_price: p.avg_entry,
            mark: p.mark,
            unrealized_pnl: p.unrealized_pnl,
            advice_label: p.advice_label,
            paper_only: p.paper_only,
            execution_route: p.execution_route_kind,
          }} />
        )}

        {novice && p.still_working === false && (
          <div style={{
            marginTop: 8, padding: terminalUi ? '4px 0' : '6px 9px', borderRadius: terminalUi ? 0 : 6,
            background: terminalUi ? 'transparent' : 'rgba(245,166,35,.12)',
            border: terminalUi ? 'none' : '1px solid rgba(245,166,35,.35)',
            fontSize: terminalUi ? 9 : 10, color: terminalUi ? BB.amber : WL.signal.amber, fontWeight: 700,
          }}>
            ⚠ This leg may need attention — see the recommended action in the banner.
          </div>
        )}

        <div style={terminalUi ? { ...modRow(terminalUi), borderTop: hair } : { marginTop: 10 }}>
          <OptionMoneynessBar
            moneyness={p.moneyness}
            spot={Number(p.underlying_price)}
            strike={Number(p.strike)}
            popOtm={p.pop_otm_pct}
            popItm={p.pop_itm_pct}
            optionType={p.option_type || 'call'}
            compact
          />
        </div>

        {p.maturity_note && (
          <div
            title={POSITION.maturityBox}
            style={{
              marginTop: terminalUi ? 0 : 10,
              padding: terminalUi ? '5px 0' : '8px 10px',
              borderRadius: terminalUi ? 0 : 8,
              fontSize: terminalUi ? 9.5 : 10.5,
              lineHeight: 1.45,
              background: terminalUi ? 'transparent' : `${lc.c}12`,
              border: terminalUi ? 'none' : `1px solid ${lc.c}33`,
              borderTop: terminalUi ? hair : undefined,
              color: terminalUi ? BB.text2 : WL.text.secondary,
              cursor: 'help',
            }}
          >
            <span style={{ fontSize: 9, fontWeight: 800, color: terminalUi ? verdictColor : lc.c, display: 'block', marginBottom: 3 }}>
              {p.lifecycle_phase === 'let_mature' ? 'Let contract mature' : p.lifecycle_phase === 'harvest' ? 'When to sell' : p.lifecycle_phase === 'defend' ? 'Action needed' : 'Trade management'}
            </span>
            {p.maturity_note}
          </div>
        )}

        {/* ③ Economics grid */}
        <div className={gridClass(terminalUi)} style={terminalUi ? undefined : { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(72px, 1fr))', gap: 7, marginTop: 11 }}>
          <div className={gridCellClass(terminalUi)} style={terminalUi ? undefined : { gridColumn: '1 / -1' }}>
            <div style={modLabel(terminalUi)}><span>Economics</span></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: terminalUi ? 4 : 7 }}>
              <Metric label="Spot" value={`$${fmtNum(p.underlying_price, 2)}`} tip="Current underlying price." terminal={terminalUi} />
              <Metric label="R:R (live)" value={rrDisplay} tip="Dynamic risk/reward vs max loss at open — updates each monitor refresh." terminal={terminalUi} />
              <Metric label="Max profit" value={p.max_profit_at_open != null ? fmt$(p.max_profit_at_open) : '—'} color={terminalUi ? BB.green : WL.price.up} tip="Best case at entry (short = full premium collected)." terminal={terminalUi} />
              <Metric label="Max loss" value={p.max_loss_at_open != null ? fmt$(p.max_loss_at_open) : '—'} color={terminalUi ? BB.amber : WL.signal.amber} tip="Worst-case loss modeled at entry." terminal={terminalUi} />
              <Metric label="% captured" value={p.profit_captured_pct != null ? `${p.profit_captured_pct}%` : '—'} color={terminalUi ? BB.green : WL.price.up} tip="Short premium: % of entry credit already earned as mark decays." terminal={terminalUi} />
              <Metric label="POP OTM" value={p.pop_otm_pct != null ? `${p.pop_otm_pct.toFixed(0)}%` : '—'} color={terminalUi ? BB.green : WL.signal.teal} tip="Chance option expires out of the money." terminal={terminalUi} />
              <Metric label="POP ITM" value={p.pop_itm_pct != null ? `${p.pop_itm_pct.toFixed(0)}%` : '—'} terminal={terminalUi} tip="Chance option finishes in the money." />
              <Metric label="Qty" value={p.qty ?? '—'} tip="Contracts held (negative = short)." terminal={terminalUi} />
              <Metric label="Edge" value={p.edge_score != null ? Math.round(p.edge_score) : '—'} tip="Monitor edge score from POP and IV." terminal={terminalUi} />
            </div>
          </div>
        </div>

        <div onClick={e => e.stopPropagation()} style={terminalUi ? { ...modRow(terminalUi) } : { marginTop: 10 }}>
          <button
            type="button"
            title={POSITION.expiryPnl}
            onClick={() => setShowRisk(v => !v)}
            style={terminalUi
              ? terminalButton(showRisk ? 'secondary' : 'ghost')
              : {
                fontSize: 9, fontWeight: 800, padding: '5px 10px', borderRadius: 6, cursor: 'help',
                border: '1px solid rgba(148,163,184,.3)', background: showRisk ? 'rgba(148,163,184,.12)' : 'transparent', color: WL.text.secondary,
              }}
          >
            {showRisk ? '▾ Hide' : '▸ Show'} expiry P/L profile
          </button>
          {showRisk && p.strike && p.underlying_price && (
            <div style={{
              marginTop: 8, padding: terminalUi ? '6px 0' : '8px 10px',
              borderRadius: terminalUi ? 0 : 8,
              background: terminalUi ? BB.bgShift : WL.surface.inset,
              border: terminalUi ? 'none' : `1px solid ${WL.surface.edge}`,
            }}>
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

        {(p.company_description || p.sector) && (
          <div style={{
            ...(terminalUi ? ctxLine(terminalUi) : { fontSize: 10, color: WL.text.dim }),
            marginTop: 10, lineHeight: 1.45,
            borderTop: terminalUi ? hair : `1px solid ${WL.surface.divider}`,
            paddingTop: terminalUi ? 5 : 8,
          }}>
            {p.company_description && <span style={{ color: terminalUi ? BB.text2 : WL.text.secondary }}>{String(p.company_description).slice(0, 160)} </span>}
            {(p.sector || p.industry) && (
              <span style={terminalUi ? ctxKey(terminalUi) : undefined}>{[p.sector, p.industry, p.instrument_type].filter(Boolean).join(' · ')}</span>
            )}
          </div>
        )}

        {p.occ_symbol && (
          <div style={{ ...ns, fontSize: 9, color: terminalUi ? BB.text3 : WL.text.dim, marginTop: 8, padding: terminalUi ? '4px 0' : undefined, borderTop: terminalUi ? hair : undefined }}>
            {p.occ_symbol}
          </div>
        )}
      </div>
    </div>
  )
}