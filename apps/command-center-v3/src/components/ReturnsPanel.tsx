/**
 * Portfolio → Returns: aggregate performance with account filter + largest winners/losers.
 * Periods from /api/v2/portfolio/performance (portfolio + per-account).
 * Name-level winners/losers use holdings day_change (1D market) filtered by account.
 */
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { fmt$ } from '../lib/format'
import { accountFullName } from '../lib/holdingsRowModel'
import DrawdownChart from './risk/DrawdownChart'
import RiskContributionBars from './risk/RiskContributionBars'

const PERIOD_ORDER = ['1D', '1W', '1M', '3M', '6M', 'YTD', '1Y'] as const

type PeriodData = {
  change_pct?: number | null
  change?: number | null
  source?: string
  estimated?: boolean
  snapshot_replaced?: boolean | null
  snapshot_1d_pct?: number | null
  start_value?: number | null
  end_value?: number | null
  start_date?: string | null
  quality?: string
  flags?: string[]
  is_false_positive?: boolean
  nav_is_not_market_only?: boolean
  adjusted_change?: number | null
  adjusted_change_pct?: number | null
  estimated_net_flow?: number | null
  display_change?: number | null
  display_change_pct?: number | null
  display_label?: string | null
  adjustment_note?: string | null
  transfer_notes?: string[]
  provenance_note?: string | null
}

type PerfAccount = {
  current_value?: number
  periods?: Record<string, PeriodData>
  transfer_notes?: string[]
}

type BenchPeriod = {
  change_pct?: number | null
  alpha_pct?: number | null
  source?: string
}

type BenchmarkItem = {
  symbol?: string
  label?: string
  short?: string
  periods?: Record<string, BenchPeriod>
}

type PerfData = {
  current_value?: number
  periods?: Record<string, PeriodData>
  accounts?: Record<string, PerfAccount>
  max_drawdown_pct?: number | null
  max_drawdown_pct_30d?: number | null
  snapshot_outliers?: string[]
  warning?: string
  period_quality_note?: string
  drawdown_series?: { date?: string; drawdown?: number; value?: number }[]
  benchmarks?: {
    items?: BenchmarkItem[]
    by_symbol?: Record<string, BenchmarkItem>
    alpha?: Record<string, Record<string, { alpha_pct?: number | null }>>
    as_of_source?: string
  }
  transfer_notifications?: {
    id?: number
    kind?: string
    title?: string
    body?: string
    severity?: string
  }[]
  transfer_season?: {
    notes_by_account?: Record<string, string[]>
    active_kinds?: string[]
  }
}

function isDeadLot(h: any): boolean {
  const mv = Number(h?.market_value)
  if (!Number.isFinite(mv) || mv <= 1) return true
  const sym = String(h?.symbol || '').toUpperCase()
  if (/^\d+$/.test(sym) && mv < 50) return true
  if (['SRNE', 'SNDL'].includes(sym) && mv < 50) return true
  return false
}

function periodDisplay(d?: PeriodData | null): { ch: number | null; pct: number | null; label: string; warn: boolean } {
  if (!d) return { ch: null, pct: null, label: 'NAV', warn: false }
  const preferAdj = Boolean(d.nav_is_not_market_only || d.is_false_positive)
  const ch = preferAdj && d.display_change != null ? d.display_change
    : preferAdj && d.adjusted_change != null ? d.adjusted_change
      : (d.change ?? null)
  const pct = preferAdj && d.display_change_pct != null ? d.display_change_pct
    : preferAdj && d.adjusted_change_pct != null ? d.adjusted_change_pct
      : (d.change_pct ?? null)
  const label = preferAdj
    ? (d.display_label || '≈ market (ex-transfers)')
    : (d.display_label || 'NAV')
  return { ch: ch ?? null, pct: pct ?? null, label, warn: preferAdj }
}

interface Props {
  perfData: PerfData
  holdings: any[]
  riskPositions?: any[]
  acctColor: (a: string) => string
  /** Optional external account filter (from Portfolio chips). */
  initialAccount?: string | null
  onOpenHolding?: (symbol: string, account: string) => void
}

function signedColor(n: number | null | undefined) {
  if (n == null || n === 0) return 'var(--text2)'
  return n > 0 ? '#22c55e' : '#ef4444'
}

export default function ReturnsPanel({
  perfData, holdings, riskPositions = [], acctColor, initialAccount = null, onOpenHolding,
}: Props) {
  const [activeAcct, setActiveAcct] = useState<string | null>(initialAccount ?? null)
  useEffect(() => {
    if (initialAccount !== undefined) setActiveAcct(initialAccount)
  }, [initialAccount])

  const accountKeys = useMemo(() => {
    const fromPerf = Object.keys(perfData.accounts || {})
    if (fromPerf.length) return fromPerf.sort()
    const s = new Set<string>()
    for (const h of holdings || []) {
      if (h?.account) s.add(String(h.account))
    }
    return [...s].sort()
  }, [perfData.accounts, holdings])

  const view = useMemo(() => {
    if (activeAcct && perfData.accounts?.[activeAcct]) {
      const a = perfData.accounts[activeAcct]
      return {
        label: accountFullName(activeAcct),
        current: a.current_value ?? 0,
        periods: a.periods || {},
        scope: 'account' as const,
      }
    }
    return {
      label: 'All accounts',
      current: perfData.current_value ?? 0,
      periods: perfData.periods || {},
      scope: 'portfolio' as const,
    }
  }, [activeAcct, perfData])

  // Aggregate comparison table: all accounts × periods
  const periodCols = useMemo(() => {
    const keys = new Set<string>(Object.keys(perfData.periods || {}))
    for (const a of Object.values(perfData.accounts || {})) {
      for (const k of Object.keys(a.periods || {})) keys.add(k)
    }
    return PERIOD_ORDER.filter(k => keys.has(k))
  }, [perfData])

  // Winners / losers from holdings day_change (1D) — exclude dead $0 lots (false losers)
  const { winners, losers } = useMemo(() => {
    let rows = (holdings || []).filter((h: any) => !h?.is_cash && h?.symbol && !isDeadLot(h))
    if (activeAcct) rows = rows.filter((h: any) => String(h.account) === activeAcct)
    const scored = rows
      .map((h: any) => ({
        symbol: String(h.symbol || '').toUpperCase(),
        account: String(h.account || ''),
        day: Number(h.day_change),
        dayPct: h.day_change_pct != null ? Number(h.day_change_pct) : null,
        unreal: h.gain_loss != null ? Number(h.gain_loss) : null,
        unrealPct: h.gain_loss_pct != null ? Number(h.gain_loss_pct) : null,
        value: Number(h.market_value) || 0,
      }))
      .filter(r => Number.isFinite(r.day))
    const byDay = [...scored].sort((a, b) => b.day - a.day)
    return {
      winners: byDay.filter(r => r.day > 0).slice(0, 8),
      losers: [...byDay].filter(r => r.day < 0).sort((a, b) => a.day - b.day).slice(0, 8),
    }
  }, [holdings, activeAcct])

  const filteredRisk = useMemo(() => {
    if (!activeAcct) return riskPositions
    return (riskPositions || []).filter((p: any) => String(p.account || '') === activeAcct)
  }, [riskPositions, activeAcct])

  return (
    <div data-testid="returns-panel" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Account filter */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', marginRight: 4 }}>Account</span>
        <button
          type="button"
          data-testid="returns-acct-all"
          onClick={() => setActiveAcct(null)}
          style={chipStyle(activeAcct == null, '#60a5fa')}
        >
          All accounts
        </button>
        {accountKeys.map(a => (
          <button
            key={a}
            type="button"
            data-testid={`returns-acct-${a}`}
            onClick={() => setActiveAcct(activeAcct === a ? null : a)}
            style={chipStyle(activeAcct === a, acctColor(a))}
          >
            <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: acctColor(a), marginRight: 5 }} />
            {accountFullName(a)}
          </button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 340px) 1fr', gap: 14 }}>
        {/* Period returns for selected scope */}
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>
            {view.scope === 'account' ? view.label : 'Portfolio Performance'}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>
            {view.scope === 'account' ? 'Account · periods (≈ market when transfers flagged)' : 'All accounts aggregated'}
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)', marginBottom: 12, fontFamily: 'monospace' }}>
            {fmt$(view.current, 0)}
          </div>
          {(perfData.max_drawdown_pct_30d ?? perfData.max_drawdown_pct) != null && view.scope === 'portfolio' && (
            <div style={{ fontSize: 10, color: '#ef4444', marginBottom: 10 }}>
              Max drawdown (30d) <b>{(perfData.max_drawdown_pct_30d ?? perfData.max_drawdown_pct)!.toFixed(1)}%</b>
              {perfData.max_drawdown_pct_30d != null && perfData.max_drawdown_pct != null
                && perfData.max_drawdown_pct_30d !== perfData.max_drawdown_pct && (
                <span style={{ fontSize: 8, color: 'var(--text4)', marginLeft: 6 }}>
                  all-time {perfData.max_drawdown_pct.toFixed(1)}%
                </span>
              )}
            </div>
          )}
          {periodCols.map(period => {
            const data = view.periods[period]
            const disp = periodDisplay(data)
            const src = data?.source === 'market_day' ? 'market' : (data?.estimated ? 'est.' : (data?.source ?? ''))
            const spyA = (perfData.benchmarks?.by_symbol?.SPY?.periods?.[period] as BenchPeriod | undefined)?.alpha_pct
            const qqqA = (perfData.benchmarks?.by_symbol?.QQQ?.periods?.[period] as BenchPeriod | undefined)?.alpha_pct
            return (
              <div key={period} style={{ padding: '7px 4px', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--text2)', fontWeight: 700, minWidth: 36 }}>
                    {period}
                    {period === '1D' && src === 'market' && <span style={{ fontSize: 8, color: 'var(--text4)', marginLeft: 4 }}>market day</span>}
                  </span>
                  <span style={{ color: signedColor(disp.pct), fontFamily: 'monospace', fontWeight: 700 }}>
                    {disp.pct != null ? `${disp.pct >= 0 ? '+' : ''}${Number(disp.pct).toFixed(2)}%` : '—'}
                  </span>
                  <span style={{ color: signedColor(disp.ch), fontFamily: 'monospace', minWidth: 72, textAlign: 'right' }}>
                    {disp.ch != null ? `${disp.ch >= 0 ? '+' : ''}${fmt$(disp.ch, 0)}` : '—'}
                  </span>
                </div>
                {view.scope === 'portfolio' && (spyA != null || qqqA != null) && (
                  <div style={{ fontSize: 9, marginTop: 2, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {spyA != null && (
                      <span style={{ color: signedColor(spyA), fontWeight: 700 }}>
                        vs SPY {spyA >= 0 ? '+' : ''}{Number(spyA).toFixed(2)}%
                      </span>
                    )}
                    {qqqA != null && (
                      <span style={{ color: signedColor(qqqA), fontWeight: 700 }}>
                        vs QQQ {qqqA >= 0 ? '+' : ''}{Number(qqqA).toFixed(2)}%
                      </span>
                    )}
                  </div>
                )}
                {disp.warn && (
                  <div style={{ fontSize: 9, color: '#f59e0b', marginTop: 2, fontWeight: 700 }}>
                    {data?.is_false_positive ? '⚠ funding baseline (false %)' : '⚠ includes transfers'}
                    {' · '}{disp.label}
                    {data?.provenance_note && data.provenance_note !== disp.label && (
                      <span style={{ fontWeight: 600 }}> · {data.provenance_note}</span>
                    )}
                    {data?.change != null && data?.adjusted_change != null && (
                      <span style={{ color: 'var(--text3)', fontWeight: 500 }}>
                        {' '}· NAV was {data.change >= 0 ? '+' : ''}{fmt$(data.change, 0)}
                        {data.estimated_net_flow != null ? ` · flow ${data.estimated_net_flow >= 0 ? '+' : ''}${fmt$(data.estimated_net_flow, 0)}` : ''}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )
          })}
          {perfData.period_quality_note && (
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8, lineHeight: 1.4 }}>{perfData.period_quality_note}</div>
          )}
          {(perfData.transfer_notifications || []).slice(0, 2).map(n => (
            <div
              key={n.id ?? n.title}
              style={{
                fontSize: 10, marginTop: 8, lineHeight: 1.4, padding: '8px 10px', borderRadius: 8,
                background: n.severity === 'warning' ? 'rgba(245,158,11,.1)' : 'rgba(96,165,250,.08)',
                border: `1px solid ${n.severity === 'warning' ? 'rgba(245,158,11,.4)' : 'rgba(96,165,250,.35)'}`,
                color: 'var(--text1)',
              }}
            >
              <div style={{ fontWeight: 800, color: n.severity === 'warning' ? '#f59e0b' : '#60a5fa', marginBottom: 4 }}>
                {n.title || 'Transfer normalization'}
              </div>
              <div style={{ whiteSpace: 'pre-wrap', fontSize: 9, color: 'var(--text2)' }}>
                {(n.body || '').slice(0, 420)}{(n.body || '').length > 420 ? '…' : ''}
              </div>
            </div>
          ))}
          {perfData.snapshot_outliers && perfData.snapshot_outliers.length > 0 && view.scope === 'portfolio' && (
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>
              Drawdown excludes {perfData.snapshot_outliers.length} reconciliation outlier snapshot{perfData.snapshot_outliers.length > 1 ? 's' : ''} ({perfData.snapshot_outliers.slice(-2).join(', ')}).
            </div>
          )}
          {perfData.warning && <div style={{ fontSize: 9, color: '#f59e0b', marginTop: 8 }}>{perfData.warning}</div>}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/portfolio/performance{activeAcct ? ` → accounts.${activeAcct}` : ''}</div>
        </div>

        {/* Per-account matrix (always show so aggregate filters are visible) */}
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, overflowX: 'auto' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>By account · all periods</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>
            Click a row to filter. Shows <b style={{ color: 'var(--text2)' }}>≈ market (ex-transfers)</b> when NAV is polluted by funding/transfers; amber = do not trust raw NAV %.
            Benchmarks: SPY = S&amp;P 500, QQQ = Nasdaq-100, IWM = Russell 2000, DIA = Dow. Alpha = book − index.
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, minWidth: 520 }}>
            <thead>
              <tr style={{ color: 'var(--text3)', textAlign: 'right' }}>
                <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 700 }}>Account</th>
                <th style={{ padding: '6px 8px', fontWeight: 700 }}>Value</th>
                {periodCols.map(p => (
                  <th key={p} style={{ padding: '6px 8px', fontWeight: 700 }}>{p}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* Portfolio row */}
              <tr
                data-testid="returns-matrix-all"
                onClick={() => setActiveAcct(null)}
                style={{
                  borderTop: '1px solid var(--border)', cursor: 'pointer',
                  background: activeAcct == null ? 'rgba(96,165,250,.08)' : 'transparent',
                }}
              >
                <td style={{ padding: '8px', fontWeight: 800, color: 'var(--text0)', textAlign: 'left' }}>All accounts</td>
                <td style={{ padding: '8px', fontFamily: 'monospace', fontWeight: 700 }}>{fmt$(perfData.current_value ?? 0, 0)}</td>
                {periodCols.map(p => {
                  const d = perfData.periods?.[p]
                  const disp = periodDisplay(d)
                  return (
                    <td key={p} style={{ padding: '6px 8px', fontFamily: 'monospace', textAlign: 'right' }}>
                      <div style={{ color: signedColor(disp.ch), fontWeight: 700 }}>{disp.ch != null ? `${disp.ch >= 0 ? '+' : ''}${fmt$(disp.ch, 0)}` : '—'}</div>
                      <div style={{ fontSize: 9, color: disp.warn ? '#f59e0b' : signedColor(disp.pct) }}>
                        {disp.pct != null ? `${disp.pct >= 0 ? '+' : ''}${Number(disp.pct).toFixed(2)}%` : ''}
                        {disp.warn ? ' ⚠' : ''}
                      </div>
                    </td>
                  )
                })}
              </tr>
              {/* Index benchmarks */}
              {(perfData.benchmarks?.items || []).map((b) => (
                <tr
                  key={b.symbol}
                  data-testid={`returns-bench-${b.symbol}`}
                  style={{ borderTop: '1px solid var(--border)', background: 'rgba(148,163,184,.04)' }}
                >
                  <td style={{ padding: '8px', textAlign: 'left' }}>
                    <span style={{ fontWeight: 800, color: '#94a3b8', fontFamily: 'monospace' }}>{b.symbol}</span>
                    <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 6 }}>{b.label}</span>
                  </td>
                  <td style={{ padding: '8px', fontFamily: 'monospace', color: 'var(--text3)', fontSize: 10 }}>index</td>
                  {periodCols.map(p => {
                    const bp = b.periods?.[p]
                    const pct = bp?.change_pct
                    const alpha = bp?.alpha_pct
                    return (
                      <td key={p} style={{ padding: '6px 8px', fontFamily: 'monospace', textAlign: 'right' }} title={bp?.source || ''}>
                        <div style={{ color: signedColor(pct), fontWeight: 700 }}>
                          {pct != null ? `${pct >= 0 ? '+' : ''}${Number(pct).toFixed(2)}%` : '—'}
                        </div>
                        {alpha != null && (
                          <div style={{ fontSize: 9, color: signedColor(alpha), fontWeight: 700 }}>
                            α {alpha >= 0 ? '+' : ''}{Number(alpha).toFixed(2)}%
                          </div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
              {accountKeys.map(a => {
                const row = perfData.accounts?.[a]
                const sel = activeAcct === a
                return (
                  <tr
                    key={a}
                    data-testid={`returns-matrix-${a}`}
                    onClick={() => setActiveAcct(sel ? null : a)}
                    style={{
                      borderTop: '1px solid var(--border)', cursor: 'pointer',
                      background: sel ? `${acctColor(a)}14` : 'transparent',
                    }}
                  >
                    <td style={{ padding: '8px', textAlign: 'left' }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 700, color: sel ? acctColor(a) : 'var(--text1)' }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: acctColor(a) }} />
                        {accountFullName(a)}
                      </span>
                      {(() => {
                        const notes = row?.transfer_notes
                          || row?.periods?.YTD?.transfer_notes
                          || (row?.periods?.YTD?.provenance_note ? [row.periods.YTD.provenance_note] : [])
                          || perfData.transfer_season?.notes_by_account?.[a]
                          || []
                        if (!notes.length) return null
                        return (
                          <div style={{ fontSize: 8, color: '#f59e0b', fontWeight: 700, marginTop: 3, maxWidth: 180, lineHeight: 1.3 }}>
                            {notes.slice(0, 2).join(' · ')}
                          </div>
                        )
                      })()}
                    </td>
                    <td style={{ padding: '8px', fontFamily: 'monospace', fontWeight: 700 }}>{fmt$(row?.current_value ?? 0, 0)}</td>
                    {periodCols.map(p => {
                      const d = row?.periods?.[p]
                      const disp = periodDisplay(d)
                      return (
                        <td key={p} style={{ padding: '6px 8px', fontFamily: 'monospace', textAlign: 'right' }} title={d?.adjustment_note || d?.display_label || ''}>
                          <div style={{ color: signedColor(disp.ch), fontWeight: 700 }}>{disp.ch != null ? `${disp.ch >= 0 ? '+' : ''}${fmt$(disp.ch, 0)}` : '—'}</div>
                          <div style={{ fontSize: 9, color: disp.warn ? '#f59e0b' : signedColor(disp.pct) }}>
                            {disp.pct != null ? `${disp.pct >= 0 ? '+' : ''}${Number(disp.pct).toFixed(2)}%` : ''}
                            {disp.warn ? ' ⚠' : ''}
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Winners / Losers (1D day change) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <MoverList
          title="Largest winners (today)"
          subtitle={activeAcct ? accountFullName(activeAcct) : 'All accounts'}
          rows={winners}
          tone="win"
          acctColor={acctColor}
          onOpen={onOpenHolding}
          empty="No positive day movers in this filter."
        />
        <MoverList
          title="Largest losers (today)"
          subtitle={activeAcct ? accountFullName(activeAcct) : 'All accounts'}
          rows={losers}
          tone="lose"
          acctColor={acctColor}
          onOpen={onOpenHolding}
          empty="No negative day movers in this filter."
        />
      </div>

      {(perfData.drawdown_series?.length ?? 0) > 1 && view.scope === 'portfolio' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <DrawdownChart
            title="Portfolio underwater / drawdown"
            data={(perfData.drawdown_series || []).map((p) => ({
              date: String(p.date || '').slice(5) || String(p.date || ''),
              drawdown: Number(p.drawdown ?? 0),
              value: Number(p.value ?? 0),
            }))}
            valueKey="drawdown"
          />
        </div>
      )}

      {filteredRisk.length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <RiskContributionBars
            positions={filteredRisk}
            title={`Risk contribution (max loss)${activeAcct ? ` · ${accountFullName(activeAcct)}` : ''}`}
            mode="risk"
            height={220}
          />
        </div>
      )}
    </div>
  )
}

function chipStyle(on: boolean, color: string): CSSProperties {
  return {
    padding: '4px 11px', fontSize: 10, borderRadius: 12, cursor: 'pointer',
    border: `1px solid ${on ? color : 'var(--border)'}`,
    background: on ? `${color}22` : 'var(--bg2)',
    color: on ? color : 'var(--text3)', fontWeight: on ? 800 : 500,
  }
}

function MoverList({ title, subtitle, rows, tone, acctColor, onOpen, empty }: {
  title: string
  subtitle: string
  rows: { symbol: string; account: string; day: number; dayPct: number | null; value: number }[]
  tone: 'win' | 'lose'
  acctColor: (a: string) => string
  onOpen?: (symbol: string, account: string) => void
  empty: string
}) {
  const accent = tone === 'win' ? '#22c55e' : '#ef4444'
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, borderTop: `3px solid ${accent}` }}>
      <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>{title}</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>{subtitle} · day $ change</div>
      {rows.length === 0 ? (
        <div style={{ fontSize: 11, color: 'var(--text3)' }}>{empty}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {rows.map((r, i) => (
            <button
              key={`${r.symbol}:${r.account}:${i}`}
              type="button"
              data-testid={`returns-${tone}-${r.symbol}`}
              onClick={() => onOpen?.(r.symbol, r.account)}
              style={{
                display: 'grid', gridTemplateColumns: '28px 56px 1fr auto', gap: 8, alignItems: 'center',
                padding: '7px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)',
                cursor: onOpen ? 'pointer' : 'default', textAlign: 'left',
              }}
            >
              <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 700 }}>#{i + 1}</span>
              <span style={{ fontFamily: 'monospace', fontWeight: 800, color: 'var(--text0)', fontSize: 12 }}>{r.symbol}</span>
              <span style={{ fontSize: 10, color: 'var(--text3)', display: 'inline-flex', alignItems: 'center', gap: 5, overflow: 'hidden' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: acctColor(r.account), flexShrink: 0 }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{accountFullName(r.account)}</span>
              </span>
              <span style={{ textAlign: 'right' }}>
                <div style={{ fontFamily: 'monospace', fontWeight: 800, color: accent, fontSize: 12 }}>
                  {r.day >= 0 ? '+' : ''}{fmt$(r.day, 0)}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)', fontFamily: 'monospace' }}>
                  {r.dayPct != null ? `${r.dayPct >= 0 ? '+' : ''}${r.dayPct.toFixed(2)}%` : '—'}
                </div>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
