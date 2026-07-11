import { useState } from 'react'
import CountryFlag from './CountryFlag'
import HoldingReportLinks from './HoldingReportLinks'
import { fmt$ } from '../lib/format'
import { buildHoldingsRowModel } from '../lib/holdingsRowModel'
import { BB, stopStatusColor } from '../lib/holdingsTerminalTokens'
import { holdingReportEligible } from '../lib/reportLinks'

const LLM_LANE: Record<string, { label: string; c: string }> = {
  local: { label: 'G', c: '#2dd4bf' },
  grok: { label: 'G', c: '#f59e0b' },
  chatgpt: { label: 'GPT', c: '#a3e635' },
  claude: { label: 'C', c: '#d97757' },
}

export interface HoldingsTableRowContext {
  h: any
  pr?: any
  monitored?: any
  confirmedStop?: any
  reportEntry?: any
  coverage?: any[]
}

interface Props {
  rows: HoldingsTableRowContext[]
  acctColor: (a: string) => string
  focusKey?: string | null
  onOpenDetail: (ctx: HoldingsTableRowContext) => void
  onPrimaryAction: (ctx: HoldingsTableRowContext) => void
}

const GRID = '28px 72px 52px 108px 52px 72px 1.2fr 120px 72px 56px'

function AgentBadges({ cov }: { cov?: any[] }) {
  if (!cov?.length) return <span style={{ color: BB.text3, fontSize: 8 }}>—</span>
  const byLane: Record<string, any> = {}
  for (const c of cov) {
    const k = LLM_LANE[c.lane] ? c.lane : 'local'
    if (!byLane[k] || c.last_at > byLane[k].last_at) byLane[k] = c
  }
  return (
    <span style={{ display: 'inline-flex', gap: 2 }}>
      {Object.entries(byLane).map(([lane, c]: any) => {
        const m = LLM_LANE[lane]
        return (
          <span key={lane} title={`${c.model} · ${String(c.last_at).slice(0, 10)} · ${c.n} review(s)`}
            style={{ fontSize: 7, fontWeight: 800, padding: '1px 4px', borderRadius: 2, background: `${m.c}22`, color: m.c, border: `1px solid ${m.c}44`, cursor: 'help' }}>
            {m.label}
          </span>
        )
      })}
    </span>
  )
}

export default function HoldingsTableView({ rows, acctColor, focusKey, onOpenDetail, onPrimaryAction }: Props) {
  const [hoverKey, setHoverKey] = useState<string | null>(null)

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: GRID, gap: 6, padding: '6px 10px',
        fontSize: 8, fontWeight: 700, color: BB.text3, textTransform: 'uppercase', letterSpacing: 0.4,
        borderBottom: `1px solid ${BB.border}`, background: BB.bgRow,
        position: 'sticky', top: 0, zIndex: 2,
      }}>
        <span />
        <span>Symbol</span>
        <span>Acct</span>
        <span>Value · Today</span>
        <span>% Port</span>
        <span>Price / Cost</span>
        <span>Stop status</span>
        <span>Action</span>
        <span>Reports</span>
        <span>Agents</span>
      </div>

      <div style={{ maxHeight: 'calc(100vh - 320px)', overflowY: 'auto' }}>
        {rows.map((rowCtx, i) => {
          const h = rowCtx.h
          const m = buildHoldingsRowModel({
            h,
            pr: rowCtx.pr,
            confirmedStop: rowCtx.confirmedStop,
            monitored: rowCtx.monitored,
          })
          const ac = acctColor(h.account ?? 'unknown')
          const focused = focusKey === m.key.replace(':', '-')
          const hovered = hoverKey === m.key
          const bg = focused ? BB.bgRowHover : hovered ? BB.bgRowHover : i % 2 ? BB.bgRowAlt : BB.bgRow
          const actionColor = m.primaryAction.tone === 'amber' ? BB.amber
            : m.primaryAction.tone === 'green' ? BB.green
            : m.primaryAction.tone === 'red' ? BB.red : BB.text3

          return (
            <div
              key={m.key}
              id={`hold-${h.symbol}-${h.account}`}
              role="row"
              tabIndex={0}
              onKeyDown={e => { if (e.key === 'Enter') onOpenDetail(rowCtx) }}
              onMouseEnter={() => setHoverKey(m.key)}
              onMouseLeave={() => setHoverKey(null)}
              onClick={() => onOpenDetail(rowCtx)}
              style={{
                display: 'grid', gridTemplateColumns: GRID, gap: 6, alignItems: 'center',
                padding: '0 10px', minHeight: BB.rowH, background: bg,
                borderBottom: `1px solid ${BB.borderSubtle}`, cursor: 'pointer',
                outline: focused ? `2px solid ${BB.amber}` : 'none',
              }}
            >
              <span style={{ display: 'flex', justifyContent: 'center' }} onClick={e => e.stopPropagation()}>
                <button type="button" title="Full details" onClick={() => onOpenDetail(rowCtx)}
                  style={{ background: 'transparent', border: 'none', color: BB.text3, cursor: 'pointer', fontSize: 12, padding: 0 }}>⏵</button>
              </span>

              <div style={{ display: 'flex', alignItems: 'center', gap: 5, minWidth: 0 }}>
                <CountryFlag symbol={h.symbol} country={h.country} countryName={h.country_name} size={16} />
                <span style={{ fontFamily: BB.mono, fontWeight: 800, fontSize: 12, color: BB.text0 }}>{m.symbol}</span>
              </div>

              <span title={m.account} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 9, color: BB.text2, overflow: 'hidden' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: ac, flexShrink: 0 }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.accountShort}</span>
              </span>

              <div style={{ fontSize: 10, lineHeight: 1.25 }}>
                <div style={{ fontWeight: 700, color: BB.text0, fontFamily: BB.mono }}>{fmt$(m.marketValue, 0)}</div>
                {m.dayPct != null && (
                  <div style={{ fontSize: 9, fontWeight: 700, color: m.dayPct >= 0 ? BB.green : BB.red }}>
                    {m.dayPct >= 0 ? '+' : ''}{m.dayPct.toFixed(2)}%
                  </div>
                )}
              </div>

              <span style={{ fontSize: 10, fontFamily: BB.mono, color: BB.text2 }}>
                {m.portfolioPct != null ? `${m.portfolioPct.toFixed(1)}%` : '—'}
              </span>

              <div style={{ fontSize: 9, fontFamily: BB.mono, lineHeight: 1.3 }}>
                <div style={{ color: BB.text0 }}>{m.price != null ? `$${m.price.toFixed(2)}` : '—'}</div>
                <div style={{ color: BB.text3 }}>{m.cost != null ? `$${m.cost.toFixed(2)}` : '—'}</div>
              </div>

              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ width: 7, height: 7, borderRadius: 4, background: stopStatusColor(m.stopStatus), flexShrink: 0 }} />
                  <span style={{ fontSize: 9, fontWeight: 800, color: stopStatusColor(m.stopStatus) }}>{m.stopLabel}</span>
                  {m.stopDistPct != null && (
                    <span style={{ fontSize: 8, color: BB.text3, fontFamily: BB.mono }}>{m.stopDistPct.toFixed(1)}%</span>
                  )}
                </div>
                <div style={{ fontSize: 8, color: BB.text3, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={m.stopAdvisory}>
                  {m.stopAdvisory}
                </div>
              </div>

              <span onClick={e => { e.stopPropagation(); onPrimaryAction(rowCtx) }}>
                <button type="button" style={{
                  width: '100%', padding: '4px 8px', fontSize: 9, fontWeight: 800, borderRadius: 4, cursor: 'pointer',
                  border: `1px solid ${actionColor}66`,
                  background: m.primaryAction.tone === 'amber' ? BB.amberDim : m.primaryAction.tone === 'green' ? BB.greenDim : 'transparent',
                  color: actionColor, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>{m.primaryAction.label}</button>
              </span>

              <span onClick={e => e.stopPropagation()}>
                {holdingReportEligible(h) ? (
                  <HoldingReportLinks symbol={h.symbol} entry={rowCtx.reportEntry} compact reportType={rowCtx.reportEntry?.report_type} />
                ) : <span style={{ fontSize: 8, color: BB.text3 }}>—</span>}
              </span>

              <AgentBadges cov={rowCtx.coverage} />
            </div>
          )
        })}
      </div>

      <div style={{ fontSize: 8, color: BB.text3, padding: '6px 10px', borderTop: `1px solid ${BB.border}` }}>
        Terminal view · {rows.length} rows · Enter or click row for drawer · Amber = action needed
      </div>
    </div>
  )
}