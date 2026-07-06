import { useState } from 'react'
import { fmt$, fmtNum } from '../lib/format'
import { plainEnglishPosition } from '../lib/optionsNovice'
import { ACTIONS, POSITION } from '../lib/optionsTooltips'
import { WhatIfBox } from './OptionsNovicePanel'
import OptionMoneynessBar from './risk/OptionMoneynessBar'
import OptionsPnLProfile from './risk/OptionsPnLProfile'

const BLUE = '#60a5fa'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const RED = '#ef4444'
const MUTED = 'var(--text3)'
const TEXT0 = 'var(--text0)'
const TEXT1 = 'var(--text1)'
const TEXT2 = 'var(--text2)'

const SEV = (s?: string, working?: boolean) => {
  const v = (s || '').toLowerCase()
  if (/crit|urgent/.test(v)) return { c: RED, label: 'CRITICAL' }
  if (/warn/.test(v) || working === false) return { c: AMBER, label: 'ACTION' }
  if (/pos/.test(v)) return { c: GREEN, label: 'WORKING' }
  return { c: BLUE, label: 'INFO' }
}

const metricBox = {
  background: 'rgba(2,6,23,.32)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  padding: '7px 8px',
} as const

function Metric({ label, value, color = TEXT0, tip }: { label: string; value: React.ReactNode; color?: string; tip?: string }) {
  return (
    <div style={metricBox} title={tip}>
      <div style={{ fontSize: 8, color: MUTED, textTransform: 'uppercase', fontWeight: 800, letterSpacing: '.04em' }}>{label}</div>
      <div style={{ fontSize: 12.5, color, fontWeight: 850, marginTop: 2, cursor: tip ? 'help' : undefined }}>{value}</div>
    </div>
  )
}

export type OptionPosition = {
  id: string
  underlying: string
  occ_symbol?: string
  strategy?: string
  side?: string
  option_type?: string
  strike?: number
  expiration?: string
  dte?: number
  moneyness?: string
  pop_otm_pct?: number
  pop_itm_pct?: number
  unrealized_pnl?: number
  edge_score?: number
  still_working?: boolean
  recommended_action?: string
  rationale?: string
  severity?: string
  action_buttons?: { action: string; label: string }[]
  mark?: number
  underlying_price?: number
  avg_entry?: number
  qty?: number
  account_key?: string
  company_description?: string
  sector?: string
  industry?: string
  instrument_type?: string
  iv_rank?: number
  delta?: number
  theta?: number
  vega?: number
  risk_reward?: number
  max_profit_at_open?: number
  max_loss_at_open?: number
  profit_captured_pct?: number
  lifecycle_phase?: string
  maturity_note?: string
  position_source?: 'broker' | 'monitored'
  execution_route_badge?: string
  execution_route_kind?: string
  execution_note?: string
  safety_status_badge?: { label: string; kind: string; severity: string; tip: string }
  advice_label?: string
  paper_only?: boolean
  mfe?: number
  mae?: number
}

const LIFECYCLE_STYLE: Record<string, { c: string; label: string }> = {
  let_mature: { c: GREEN, label: 'LET MATURE' },
  harvest: { c: AMBER, label: 'HARVEST' },
  defend: { c: RED, label: 'DEFEND' },
  monitor: { c: BLUE, label: 'MONITOR' },
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

export default function OptionPositionCard({
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
  const sv = SEV(p.severity, p.still_working)
  const lc = LIFECYCLE_STYLE[p.lifecycle_phase || 'monitor'] || LIFECYCLE_STYLE.monitor
  const pnl = p.unrealized_pnl
  const pnlColor = pnl == null ? TEXT1 : pnl >= 0 ? GREEN : RED
  const strat = (p.strategy || 'option').replace(/_/g, ' ')
  const rrDisplay = p.risk_reward != null
    ? (p.risk_reward >= 1 ? `${p.risk_reward.toFixed(2)}:1` : `1:${(1 / Math.max(p.risk_reward, 0.01)).toFixed(1)}`)
    : '—'

  const btnStyle = (action: string): React.CSSProperties => {
    if (action === 'hold') return { fontSize: 10, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }
    if (action === 'review_chain') return { fontSize: 10, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: `1px solid ${BLUE}55`, background: 'transparent', color: BLUE, cursor: 'pointer' }
    if (/close|roll/.test(action)) return { fontSize: 10, fontWeight: 800, padding: '6px 12px', borderRadius: 6, border: 'none', background: AMBER, color: '#0f172a', cursor: 'pointer' }
    return { fontSize: 10, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: TEXT1, cursor: 'pointer' }
  }

  return (
    <div
      onClick={onDrill}
      style={{
        background: 'var(--bg1)',
        border: '1px solid var(--border)',
        borderLeft: `4px solid ${sv.c}`,
        borderRadius: 11,
        padding: '14px 15px',
        cursor: onDrill ? 'pointer' : 'default',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
        <div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <span title={POSITION.status} style={{ fontSize: 8.5, fontWeight: 900, padding: '1px 6px', borderRadius: 4, color: sv.c, background: `${sv.c}22`, cursor: 'help' }}>{sv.label}</span>
            <span title={POSITION.lifecycle} style={{ fontSize: 8.5, fontWeight: 900, padding: '1px 6px', borderRadius: 4, color: lc.c, background: `${lc.c}22`, cursor: 'help' }}>{lc.label}</span>
            <span style={{ fontSize: 9, color: MUTED }}>{strat}</span>
            <span style={{ fontSize: 13, fontWeight: 900, color: BLUE, fontFamily: 'monospace' }}>{p.underlying}</span>
            {p.moneyness && <span title={POSITION.moneyness} style={{ fontSize: 8, fontWeight: 800, padding: '2px 6px', borderRadius: 4, color: p.moneyness === 'ITM' ? RED : p.moneyness === 'OTM' ? GREEN : AMBER, background: 'var(--bg2)', cursor: 'help' }}>{p.moneyness}</span>}
          </div>
          <div style={{ fontSize: 13, fontWeight: 850, color: TEXT0, marginTop: 6 }}>
            ${fmtNum(p.strike, 2)} · {p.dte ?? '—'} DTE
            <span style={{ fontSize: 10, color: MUTED, marginLeft: 8 }}>{fmtExpiry(p.expiration)}</span>
          </div>
        </div>
        {p.recommended_action && (
          <span title={POSITION.recommended} style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: `${sv.c}18`, color: sv.c, whiteSpace: 'nowrap', cursor: 'help' }}>
            {p.recommended_action}
          </span>
        )}
      </div>

      {novice && (
        <div style={{ marginTop: 10, padding: '9px 10px', borderRadius: 8, background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.22)', fontSize: 10.5, color: TEXT2, lineHeight: 1.5 }}>
          <b style={{ color: BLUE }}>Your position:</b> {plainEnglishPosition(p)}
        </div>
      )}

      {novice && p.still_working === false && (
        <div style={{ marginTop: 8, padding: '6px 9px', borderRadius: 6, background: 'rgba(245,158,11,.12)', border: '1px solid rgba(245,158,11,.35)', fontSize: 10, color: AMBER, fontWeight: 700 }}>
          ⚠ This leg may need attention — see recommended action above.
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
          background: `${lc.c}12`, border: `1px solid ${lc.c}33`, color: TEXT2, cursor: 'help',
        }}>
          <span style={{ fontSize: 9, fontWeight: 800, color: lc.c, display: 'block', marginBottom: 3 }}>
            {p.lifecycle_phase === 'let_mature' ? 'Let contract mature' : p.lifecycle_phase === 'harvest' ? 'When to sell' : p.lifecycle_phase === 'defend' ? 'Action needed' : 'Trade management'}
          </span>
          {p.maturity_note}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(72px, 1fr))', gap: 7, marginTop: 11 }}>
        <Metric label="Spot" value={`$${fmtNum(p.underlying_price, 2)}`} tip="Current underlying price." />
        <Metric label="Mark" value={p.mark != null ? fmt$(p.mark, 2) : '—'} tip="Current option mark from broker." />
        <Metric label="Entry" value={p.avg_entry != null ? fmt$(p.avg_entry, 2) : '—'} tip="Average entry premium per contract." />
        <Metric label="P/L" value={pnl != null ? fmt$(pnl) : '—'} color={pnlColor} tip="Unrealized P&L on this leg." />
        <Metric label="R:R (live)" value={rrDisplay} color={BLUE} tip="Dynamic risk/reward vs max loss at open — updates each monitor refresh." />
        <Metric label="Max profit" value={p.max_profit_at_open != null ? fmt$(p.max_profit_at_open) : '—'} color={GREEN} tip="Best case at entry (short = full premium collected)." />
        <Metric label="Max loss" value={p.max_loss_at_open != null ? fmt$(p.max_loss_at_open) : '—'} color={AMBER} tip="Worst-case loss modeled at entry." />
        <Metric label="% captured" value={p.profit_captured_pct != null ? `${p.profit_captured_pct}%` : '—'} color={GREEN} tip="Short premium: % of entry credit already earned as mark decays." />
        <Metric label="Δ" value={p.delta != null ? p.delta.toFixed(2) : '—'} color={BLUE} tip="Delta from Schwab chain." />
        <Metric label="POP OTM" value={p.pop_otm_pct != null ? `${p.pop_otm_pct.toFixed(0)}%` : '—'} color={GREEN} tip="Chance option expires out of the money." />
        <Metric label="POP ITM" value={p.pop_itm_pct != null ? `${p.pop_itm_pct.toFixed(0)}%` : '—'} tip="Chance option finishes in the money." />
        <Metric label="DTE" value={p.dte ?? '—'} tip="Days to expiration — theta accelerates under ~14 DTE." />
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
            border: `1px solid ${BLUE}55`, background: showRisk ? 'rgba(96,165,250,.14)' : 'transparent', color: BLUE,
          }}
        >
          {showRisk ? '▾ Hide' : '▸ Show'} expiry P/L profile
        </button>
        {showRisk && p.strike && p.underlying_price && (
          <div style={{ marginTop: 8, padding: '8px 10px', borderRadius: 8, background: 'rgba(15,23,42,.45)', border: '1px solid var(--border)' }}>
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

      {p.rationale && (
        <div style={{ fontSize: 11, color: TEXT2, marginTop: 10, lineHeight: 1.45, borderTop: '1px solid var(--border-subtle)', paddingTop: 9 }}>
          {novice && <span style={{ fontSize: 9, fontWeight: 800, color: MUTED, display: 'block', marginBottom: 4 }}>WHY THIS ACTION</span>}
          {p.rationale}
        </div>
      )}

      {(p.company_description || p.sector) && (
        <div style={{ fontSize: 10, color: MUTED, marginTop: 8, lineHeight: 1.4 }}>
          {p.company_description && <span style={{ color: TEXT2 }}>{String(p.company_description).slice(0, 160)} </span>}
          {(p.sector || p.industry) && (
            <span>{[p.sector, p.industry, p.instrument_type].filter(Boolean).join(' · ')}</span>
          )}
        </div>
      )}

      {p.occ_symbol && <div style={{ fontSize: 9, color: MUTED, marginTop: 6, fontFamily: 'monospace' }}>{p.occ_symbol}</div>}

      <div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10, paddingTop: 9, borderTop: '1px solid var(--border-subtle)' }}>
        {(p.action_buttons || []).map((b, i) => (
          <button
            key={`${b.action}-${i}`}
            type="button"
            title={b.action === 'hold' ? ACTIONS.hold : b.action === 'review_chain' ? ACTIONS.reviewChain : /close|roll/.test(b.action) ? ACTIONS.closeRoll : undefined}
            onClick={() => onAction(b.action, p.id)}
            style={{ ...btnStyle(b.action), cursor: 'help' }}
          >
            {b.label}{b.action !== 'hold' ? ' →' : ''}
          </button>
        ))}
      </div>
    </div>
  )
}