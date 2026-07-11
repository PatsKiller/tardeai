import { useState } from 'react'
import CountryFlag from './CountryFlag'
import HoldingReportLinks from './HoldingReportLinks'
import { fmt$ } from '../lib/format'
import { buildHoldingsRowModel } from '../lib/holdingsRowModel'
import { resolveCountry } from '../lib/country'
import {
  BB, type HoldingsCvdMode, primaryActionBg, primaryActionColor,
  semanticSigned, stopStatusBg, stopStatusColor,
} from '../lib/holdingsTerminalTokens'
import { holdingReportEligible } from '../lib/reportLinks'

const LLM_LANE: Record<string, { label: string; c: string }> = {
  local: { label: 'G', c: '#2dd4bf' },
  grok: { label: 'G', c: '#f59e0b' },
  chatgpt: { label: 'GPT', c: '#a3e635' },
  claude: { label: 'C', c: '#d97757' },
}

const COL_TIPS: Record<string, string> = {
  symbol: 'Ticker and HQ country flag',
  acct: 'Broker account for this row (same symbol may appear in multiple accounts)',
  value: 'Market value and today\'s % change',
  port: 'Portfolio weight — % of your TOTAL portfolio value across all accounts (not stop distance)',
  price: 'Last price and average cost per share',
  stop: 'Stop protection — status + advisory stop price. "X% below price" = how far stop is under current price, NOT % of portfolio',
  action: 'Opens this row\'s stop management drawer (2FA, tickets, replace stop)',
  reports: 'Analyst PDF / Word reports',
  agents: 'LLM lanes that reviewed this symbol (last 30d)',
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
  cvdMode?: HoldingsCvdMode
  onOpenDetail: (ctx: HoldingsTableRowContext) => void
  onPrimaryAction: (ctx: HoldingsTableRowContext) => void
}

const GRID = '32px 84px 60px 120px 58px 80px 1.35fr 140px 76px 62px'

function HeaderCell({ label, tip }: { label: string; tip: string }) {
  return <span title={tip} style={{ cursor: 'help' }}>{label}</span>
}

function AgentBadges({ cov }: { cov?: any[] }) {
  if (!cov?.length) return <span title="No LLM research in last 30 days" style={{ color: BB.text3, fontSize: 9 }}>—</span>
  const byLane: Record<string, any> = {}
  for (const c of cov) {
    const k = LLM_LANE[c.lane] ? c.lane : 'local'
    if (!byLane[k] || c.last_at > byLane[k].last_at) byLane[k] = c
  }
  return (
    <span style={{ display: 'inline-flex', gap: 3 }}>
      {Object.entries(byLane).map(([lane, c]: any) => {
        const m = LLM_LANE[lane]
        return (
          <span key={lane} title={`${c.model} · ${String(c.last_at).slice(0, 10)} · ${c.n} review(s) — advisory research only`}
            style={{ fontSize: 8, fontWeight: 800, padding: '2px 5px', borderRadius: 3, background: `${m.c}22`, color: m.c, border: `1px solid ${m.c}44`, cursor: 'help' }}>
            {m.label}
          </span>
        )
      })}
    </span>
  )
}

function rowTooltip(m: ReturnType<typeof buildHoldingsRowModel>, h: any): string {
  const ctry = resolveCountry({ symbol: h.symbol, country: h.country, countryName: h.country_name })
  const parts = [
    `${m.symbol}${h.name ? ` · ${h.name}` : ''}`,
    ctry ? `HQ: ${ctry.name}` : '',
    m.account,
    m.shares != null ? `${m.shares} shares` : '',
    m.needsAction ? '⚠ Action needed' : 'No urgent action',
    'Click row or Enter for full drawer',
  ].filter(Boolean)
  return parts.join('\n')
}

export default function HoldingsTableView({ rows, acctColor, focusKey, cvdMode = 'default', onOpenDetail, onPrimaryAction }: Props) {
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const actionableCount = rows.filter(r => buildHoldingsRowModel({ h: r.h, pr: r.pr, confirmedStop: r.confirmedStop, monitored: r.monitored }).needsAction).length

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: GRID, gap: 8, padding: '8px 12px',
        fontSize: 9, fontWeight: 700, color: BB.text3, textTransform: 'uppercase', letterSpacing: 0.4,
        borderBottom: `1px solid ${BB.border}`, background: BB.bgRow,
        position: 'sticky', top: 0, zIndex: 2,
      }}>
        <span />
        <HeaderCell label="Symbol" tip={COL_TIPS.symbol} />
        <HeaderCell label="Acct" tip={COL_TIPS.acct} />
        <HeaderCell label="Value · Today" tip={COL_TIPS.value} />
        <HeaderCell label="Wt %" tip={COL_TIPS.port} />
        <HeaderCell label="Price / Cost" tip={COL_TIPS.price} />
        <HeaderCell label="Stop status" tip={COL_TIPS.stop} />
        <HeaderCell label="Action" tip={COL_TIPS.action} />
        <HeaderCell label="Reports" tip={COL_TIPS.reports} />
        <HeaderCell label="Agents" tip={COL_TIPS.agents} />
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
          const bg = focused ? BB.bgRowFocus : hovered ? BB.bgRowHover : i % 2 ? BB.bgRowAlt : BB.bgRow
          const actionColor = primaryActionColor(m.primaryAction.tone, cvdMode)
          const actionBg = primaryActionBg(m.primaryAction.tone, cvdMode)
          const stopColor = stopStatusColor(m.stopStatus)
          const isAmberAction = m.primaryAction.tone === 'amber'
          const isRedAction = m.primaryAction.tone === 'red'
          const ctry = resolveCountry({ symbol: h.symbol, country: h.country, countryName: h.country_name })

          return (
            <div
              key={m.key}
              id={`hold-${h.symbol}-${h.account}`}
              role="row"
              tabIndex={0}
              title={rowTooltip(m, h)}
              onKeyDown={e => { if (e.key === 'Enter') onOpenDetail(rowCtx) }}
              onMouseEnter={() => setHoverKey(m.key)}
              onMouseLeave={() => setHoverKey(null)}
              onClick={() => onOpenDetail(rowCtx)}
              style={{
                display: 'grid', gridTemplateColumns: GRID, gap: 8, alignItems: 'center',
                padding: '0 12px', minHeight: BB.rowH, background: bg,
                borderBottom: `1px solid ${BB.borderSubtle}`, cursor: 'pointer',
                borderLeft: m.needsAction
                  ? `3px solid ${isRedAction ? BB.red : BB.amberAlt}`
                  : focused ? `3px solid ${BB.amber}` : '3px solid transparent',
                outline: focused ? `2px solid ${BB.amber}55` : 'none',
              }}
            >
              <span style={{ display: 'flex', justifyContent: 'center' }} onClick={e => e.stopPropagation()}>
                <button type="button" title="Open full drawer (charts, stops, reports)" onClick={() => onOpenDetail(rowCtx)}
                  style={{ background: 'transparent', border: 'none', color: BB.text2, cursor: 'pointer', fontSize: 13, padding: 0, lineHeight: 1 }}>⏵</button>
              </span>

              <div
                title={[m.symbol, h.name, ctry ? `HQ: ${ctry.name}` : '', m.shares != null ? `${m.shares} sh` : ''].filter(Boolean).join(' · ')}
                style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}
              >
                <CountryFlag symbol={h.symbol} country={h.country} countryName={h.country_name} size={18} />
                <span style={{ fontFamily: BB.mono, fontWeight: 800, fontSize: 13, color: BB.text0 }}>{m.symbol}</span>
              </div>

              <span title={`${m.account}${m.shares != null ? ` · ${m.shares} shares` : ''}`}
                style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: BB.text2, overflow: 'hidden' }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: ac, flexShrink: 0 }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.accountShort}</span>
              </span>

              <div
                title={[
                  `Market value ${fmt$(m.marketValue, 0)}`,
                  m.dayPct != null ? `Today ${m.dayPct >= 0 ? '+' : ''}${m.dayPct.toFixed(2)}%` : 'Today: no quote',
                  m.pl$ != null ? `Unrealized P/L ${m.pl$ >= 0 ? '+' : ''}${fmt$(m.pl$, 0)}` : '',
                ].filter(Boolean).join(' · ')}
                style={{ fontSize: 11, lineHeight: 1.3 }}
              >
                <div style={{ fontWeight: 700, color: BB.text0, fontFamily: BB.mono }}>{fmt$(m.marketValue, 0)}</div>
                {m.dayPct != null && (
                  <div style={{ fontSize: 10, fontWeight: 700, color: semanticSigned(m.dayPct, cvdMode) }}>
                    {m.dayPct >= 0 ? '+' : ''}{m.dayPct.toFixed(2)}%
                  </div>
                )}
              </div>

              <span
                title={m.portfolioPct != null
                  ? `${m.portfolioPct.toFixed(1)}% of your total portfolio ($${Math.round(m.marketValue / (m.portfolioPct / 100)).toLocaleString()} est. total) — portfolio weight, NOT stop distance`
                  : 'Portfolio weight unknown'}
                style={{ fontSize: 11, fontFamily: BB.mono, color: BB.text2, fontWeight: 700 }}
              >
                {m.portfolioPct != null ? `${m.portfolioPct.toFixed(1)}%` : '—'}
              </span>

              <div
                title={[
                  m.price != null ? `Last $${m.price.toFixed(2)}` : 'Price unavailable',
                  m.cost != null ? `Avg cost $${m.cost.toFixed(2)}/sh` : 'Cost basis unavailable (e.g. 401k fund)',
                ].join(' · ')}
                style={{ fontSize: 10, fontFamily: BB.mono, lineHeight: 1.35 }}
              >
                <div style={{ color: BB.text0 }}>{m.price != null ? `$${m.price.toFixed(2)}` : '—'}</div>
                <div style={{ color: BB.text3 }}>{m.cost != null ? `$${m.cost.toFixed(2)}` : '—'}</div>
              </div>

              <div
                title={[
                  `Stop status: ${m.stopLabel}`,
                  m.stopAdvisory,
                  m.stopDistPct != null ? `${m.stopDistPct.toFixed(1)}% below current price — NOT portfolio weight` : '',
                  m.portfolioPct != null ? `(Portfolio weight is ${m.portfolioPct.toFixed(1)}% in Wt % column)` : '',
                ].filter(Boolean).join('\n')}
                style={{
                  minWidth: 0, padding: '6px 8px', margin: '-6px -8px', borderRadius: 5,
                  background: stopStatusBg(m.stopStatus), borderLeft: `3px solid ${stopColor}`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 4, background: stopColor, flexShrink: 0 }} />
                  <span style={{ fontSize: 11, fontWeight: 800, color: stopColor, letterSpacing: 0.2 }}>{m.stopLabel}</span>
                </div>
                <div style={{ fontSize: 9, color: BB.text2, marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: BB.mono }}>
                  {m.stopAdvisory}
                </div>
              </div>

              <span onClick={e => { e.stopPropagation(); onPrimaryAction(rowCtx) }}>
                <button
                  type="button"
                  title={m.primaryActionTooltip}
                  style={{
                    width: '100%', padding: isAmberAction || isRedAction ? '7px 10px' : '5px 8px',
                    fontSize: isAmberAction || isRedAction ? 10 : 9, fontWeight: 800, borderRadius: 5, cursor: 'pointer',
                    border: isAmberAction
                      ? `2px solid ${BB.amberAlt}`
                      : isRedAction
                        ? `2px solid ${BB.red}`
                        : `1px solid ${actionColor}55`,
                    background: isAmberAction
                      ? 'rgba(255, 160, 40, 0.28)'
                      : isRedAction
                        ? BB.redDim
                        : actionBg,
                    color: isAmberAction ? BB.amberAlt : actionColor,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    boxShadow: isAmberAction ? '0 0 10px rgba(255, 176, 0, 0.22)' : undefined,
                  }}
                >{m.needsAction ? '▸ ' : ''}{m.primaryAction.label}</button>
              </span>

              <span onClick={e => e.stopPropagation()} title={holdingReportEligible(h) ? 'Download analyst reports' : 'No report on file'}>
                {holdingReportEligible(h) ? (
                  <HoldingReportLinks symbol={h.symbol} entry={rowCtx.reportEntry} compact reportType={rowCtx.reportEntry?.report_type} />
                ) : <span style={{ fontSize: 9, color: BB.text3 }}>—</span>}
              </span>

              <AgentBadges cov={rowCtx.coverage} />
            </div>
          )
        })}
      </div>

      <div style={{ fontSize: 9, color: BB.text3, padding: '8px 12px', borderTop: `1px solid ${BB.border}`, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <span>{rows.length} rows · hover for tooltips · Enter or click row for drawer</span>
        {actionableCount > 0 && (
          <span style={{ color: BB.amberAlt, fontWeight: 700 }}>▸ {actionableCount} need action (amber/red)</span>
        )}
      </div>
    </div>
  )
}