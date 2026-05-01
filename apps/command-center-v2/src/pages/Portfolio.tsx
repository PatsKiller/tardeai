import { useEffect, useState, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import DataGrid from '../components/DataGrid'
import MetricTile from '../components/MetricTile'
import { DoughnutChart, BarChartJS, LineChart } from '../components/charts'
import PeriodReturnBars from '../components/PeriodReturnBars'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, fmtN, deltaColor, fmtCompact } from '../lib/format'
import AccountBadge from '../components/AccountBadge'

interface Holding {
  symbol: string; name: string; account: string; shares: number; price: number
  market_value: number; portfolio_pct: number; day_change: number; day_change_pct: number
  sector: string; signal: string; yield_pct: number | null
  rsi: number | null; beta: number | null; pe: number | null; forward_pe: number | null
  eps_ttm: number | null; sma20_pct: number | null; sma50_pct: number | null; sma200_pct: number | null
  atr: number | null; short_float_pct: number | null; week52_high_pct: number | null
  market_cap_b: number | null; company: string; industry: string
  is_cash?: boolean; cost_basis?: number; gain_loss?: number; pi_score?: number | null
}
interface HoldingsData { count: number; holdings: Holding[]; as_of: string; equity_curve: { date: string; value: number }[] }
interface PerfData { current_value: number; periods: Record<string, { change_pct: number; change: number; start_value: number; start_date: string; estimated?: boolean }>; warning?: string | null }

const ACCT = { fidelity_401k: '401k', schwab_rollover_ira: 'Roll IRA', schwab_roth: 'Roth', schwab_taxable: 'Taxable' } as Record<string, string>
const SIG_COLOR: Record<string, string> = { GO: 'var(--green)', ADD: 'var(--green)', HOLD: 'var(--accent)', TRIM: 'var(--amber)', WAIT: 'var(--amber)', AVOID: 'var(--red)', SELL: 'var(--red)' }
const SIG_BG: Record<string, string> = { GO: 'var(--green-dim)', ADD: 'var(--green-dim)', HOLD: 'var(--accent-dim)', TRIM: 'var(--amber-dim)', WAIT: 'var(--amber-dim)', AVOID: 'var(--red-dim)', SELL: 'var(--red-dim)' }

export default function Portfolio() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { data: hd } = useApi<HoldingsData>('/api/v2/portfolio/holdings')
  const { data: perf } = useApi<PerfData>('/api/v2/portfolio/performance')
  const [selected, setSelected] = useState<string | null>(null)
  const [acctFilter, setAcctFilter] = useState(() => params.get('account') || 'all')
  const [drillPeriod, setDrillPeriod] = useState<string | null>(null)
  const filterParam = params.get('filter')
  const activeFilter = filterParam || null

  const positions = useMemo(() => {
    let raw = hd?.holdings ?? []
    const symbol = params.get('symbol')?.toUpperCase()
    const sector = params.get('sector')
    if (acctFilter !== 'all') raw = raw.filter(p => p.account === acctFilter)
    if (sector) raw = raw.filter(p => p.sector === sector)
    if (activeFilter === 'cash') raw = raw.filter(p => p.is_cash || (p.symbol || '').toUpperCase() === 'CASH')
    if (symbol) {
      const exact = raw.find(p => p.symbol === symbol)
      if (exact) return [exact, ...raw.filter(p => !(p.symbol === exact.symbol && p.account === exact.account))]
    }
    return raw
  }, [hd, acctFilter, params, activeFilter])

  const accounts = useMemo(() => ['all', ...Array.from(new Set((hd?.holdings ?? []).map(p => p.account)))], [hd])
  const sel = positions.find(p => p.symbol + ':' + p.account === selected)
  useEffect(() => {
    const symbol = params.get('symbol')?.toUpperCase()
    if (!symbol || !positions.length) return
    const found = positions.find(p => p.symbol === symbol)
    if (found) setSelected(found.symbol + ':' + found.account)
  }, [params, positions])
  const periods = perf?.periods ?? {}
  const total = perf?.current_value ?? 0

  // Allocation data for doughnut
  const top10 = [...(hd?.holdings ?? [])].sort((a, b) => b.market_value - a.market_value).slice(0, 10)
  const top10Total = top10.reduce((s, p) => s + p.market_value, 0)
  const otherTotal = total - top10Total

  // Sector aggregation for bar chart
  const sectors: Record<string, number> = {}
  for (const p of hd?.holdings ?? []) {
    const s = p.sector || 'Other'
    sectors[s] = (sectors[s] || 0) + p.market_value
  }
  const sectorEntries = Object.entries(sectors).sort((a, b) => b[1] - a[1]).slice(0, 8)

  const columns = [
    { key: 'signal', label: 'Decision', width: 55, render: (r: Holding) => r.signal ? (
      <span title={r.signal === 'ADD' ? 'Add shares — use available cash in this account' : r.signal === 'TRIM' ? 'Reduce position — sell in THIS account, proceeds stay here' : r.signal === 'HOLD' ? 'No change recommended' : r.signal === 'WAIT' || r.signal === 'MONITOR' ? 'AI flagged — check AI Analyst for details' : r.signal === 'GO' ? 'Scalp setup — Taxable account only' : r.signal} style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: SIG_BG[r.signal] || 'var(--bg3)', color: SIG_COLOR[r.signal] || 'var(--text3)' }}>{r.signal}{r.account?.includes('401k') && (r.signal === 'TRIM' || r.signal === 'SELL') ? ' (via Fidelity)' : ''}</span>
    ) : <span style={{ color: 'var(--text3)', fontSize: 8 }}>—</span> },
    { key: 'symbol', label: 'Symbol', width: 55, render: (r: Holding) => <span style={{ fontWeight: 700 }}>{r.symbol}</span> },
    { key: 'account', label: 'Acct', width: 50, render: (r: Holding) => <span style={{ fontSize: 9, color: 'var(--text3)' }}>{ACCT[r.account] || r.account}</span> },
    { key: 'market_value', label: 'Value', width: 65, align: 'right' as const, sortKey: (r: Holding) => r.market_value, render: (r: Holding) => fmt$(r.market_value) },
    { key: 'portfolio_pct', label: '%', width: 38, align: 'right' as const, sortKey: (r: Holding) => r.portfolio_pct, render: (r: Holding) => (
      <span style={{ color: r.portfolio_pct >= 12 ? 'var(--red)' : 'var(--text1)' }}>{r.portfolio_pct.toFixed(1)}</span>
    )},
    { key: 'day_change', label: 'Day $', width: 55, align: 'right' as const, sortKey: (r: Holding) => r.day_change, render: (r: Holding) => (
      <span style={{ color: deltaColor(r.day_change) }}>{r.day_change >= 0 ? '+' : ''}{fmt$(r.day_change)}</span>
    )},
    { key: 'day_change_pct', label: 'Day %', width: 50, align: 'right' as const, sortKey: (r: Holding) => r.day_change_pct ?? 0, render: (r: Holding) => (
      <span style={{ color: deltaColor(r.day_change_pct ?? 0) }}>{r.day_change_pct != null ? fmtPct(r.day_change_pct) : '—'}</span>
    )},
    { key: 'gain_loss', label: 'Gain $', width: 60, align: 'right' as const, sortKey: (r: Holding) => (r as unknown as Record<string,number>).gain_loss ?? 0, render: (r: Holding) => {
      const gl = (r as unknown as Record<string,number>).gain_loss
      if (gl != null && gl !== 0) return <span style={{ color: deltaColor(gl), fontWeight: 600 }}>{gl >= 0 ? '+' : ''}{fmt$(gl)}</span>
      if (r.account === 'fidelity_401k') return <span style={{ color: 'var(--text3)' }} title="401k gain/loss not tracked per-position — Fidelity reports only at account level via NetBenefits">—</span>
      return <span style={{ color: 'var(--text3)' }}>—</span>
    }},
    { key: 'yield_pct', label: 'Yield', width: 40, align: 'right' as const, render: (r: Holding) => (
      r.yield_pct ? <span style={{ color: 'var(--green)' }}>{r.yield_pct.toFixed(1)}%</span> : <span style={{ color: 'var(--text3)' }}>—</span>
    )},
    { key: 'pi_score', label: 'PI', width: 30, align: 'right' as const, sortKey: (r: Holding) => (r as unknown as Record<string,number>).pi_score ?? 0, render: (r: Holding) => {
      const s = (r as unknown as Record<string,number>).pi_score
      return s != null ? <span title={`Position Intelligence Score: ${s >= 65 ? 'Strong (≥65) — position well-supported by technicals/fundamentals' : s >= 40 ? 'Moderate (40-64) — mixed signals, monitor closely' : 'Weak (<40) — consider trimming or setting tighter stop'}`} style={{ fontWeight: 600, color: s >= 65 ? 'var(--green)' : s >= 40 ? 'var(--amber)' : 'var(--red)' }}>{s}</span> : <span style={{ color: 'var(--text3)' }} title="PI Score not computed — run enrichment pipeline">—</span>
    }},
    { key: 'rsi', label: 'RSI', width: 35, align: 'right' as const, render: (r: Holding) => (
      r.rsi != null ? <span style={{ color: r.rsi > 70 ? 'var(--red)' : r.rsi < 30 ? 'var(--green)' : 'var(--text1)' }}>{r.rsi.toFixed(0)}</span> : <span style={{ color: 'var(--text3)' }}>—</span>
    )},
    { key: 'sector', label: 'Sector', width: 70, render: (r: Holding) => <span style={{ fontSize: 9, color: 'var(--text3)' }}>{r.sector?.slice(0, 12) || '—'}</span> },
    { key: 'links', label: '', width: 50, sortable: false, render: (r: Holding) => (
      <div style={{ display: 'flex', gap: 3 }}>
        <a href={`https://finviz.com/quote.ashx?t=${r.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 8, color: 'var(--accent)', textDecoration: 'none' }}>Fvz</a>
        <a href={`https://finance.yahoo.com/quote/${r.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 8, color: 'var(--accent)', textDecoration: 'none' }}>Yho</a>
      </div>
    )},
  ]

  return (
    <>
      <PageHeader title="Portfolio" subtitle={`${positions.length} positions | ${fmt$(total)} | as of ${hd?.as_of || '...'}`} />

      {/* Active filter banner */}
      {(activeFilter || params.get('sector') || params.get('symbol')) && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 10, padding: '8px 12px', background: 'rgba(74,144,244,0.08)', border: '1px solid rgba(74,144,244,0.25)', borderRadius: 12, fontSize: 10 }}>
          <span style={{ color: 'var(--accent)', fontWeight: 600 }}>Filtered:</span>
          {activeFilter && <span style={{ color: 'var(--text1)' }}>{activeFilter}</span>}
          {params.get('sector') && <span style={{ color: 'var(--text1)' }}>sector: {params.get('sector')}</span>}
          {params.get('symbol') && <span style={{ color: 'var(--text1)' }}>symbol: {params.get('symbol')}</span>}
          <button onClick={() => navigate(-1 as any)} style={{ fontSize: 9, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Back</button>
          <button onClick={() => { setParams({}); setAcctFilter('all') }} style={{ fontSize: 9, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Clear filters</button>
        </div>
      )}

      {/* Period returns — clickable for attribution drill */}
      <Card title="Period Returns" subtitle={drillPeriod ? `Click ${drillPeriod} again to close` : 'Click a period to drill down'} compact>
        <PeriodReturnBars periods={periods} selectedPeriod={drillPeriod}
          onPeriodClick={k => setDrillPeriod(drillPeriod === k ? null : k)} />
      </Card>

      {/* Period attribution drill-down panel */}
      {drillPeriod && (
        <Card title={`${drillPeriod} Attribution`} subtitle={`${positions.length} positions`} compact>
          <div style={{ maxHeight: 250, overflowY: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
              <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '3px 6px', color: 'var(--text3)', fontSize: 9 }}>Ticker</th>
                <th style={{ textAlign: 'left', padding: '3px 6px', color: 'var(--text3)', fontSize: 9 }}>Account</th>
                <th style={{ textAlign: 'right', padding: '3px 6px', color: 'var(--text3)', fontSize: 9 }}>Value</th>
                <th style={{ textAlign: 'right', padding: '3px 6px', color: 'var(--text3)', fontSize: 9 }}>{drillPeriod} %</th>
                <th style={{ textAlign: 'right', padding: '3px 6px', color: 'var(--text3)', fontSize: 9 }}>{drillPeriod} $</th>
              </tr></thead>
              <tbody>
                {(() => {
                  const PERF_MAP: Record<string, string> = { '1D': 'day_change_pct', '1W': 'perf_week_pct' }
                  const field = PERF_MAP[drillPeriod]
                  // For 1D, use day_change directly; for others use enrichment perf fields
                  const rows = positions.map(p => {
                    let pct = 0
                    let dollar = 0
                    if (drillPeriod === '1D') {
                      pct = p.day_change_pct ?? 0
                      dollar = p.day_change ?? 0
                    } else if (field) {
                      pct = (p as unknown as Record<string, number>)[field.replace('_pct', '_pct')] ?? 0
                      dollar = p.market_value * (pct / 100)
                    }
                    return { ...p, _pct: pct, _dollar: dollar }
                  }).sort((a, b) => Math.abs(b._dollar) - Math.abs(a._dollar))

                  return rows.slice(0, 20).map(r => (
                    <tr key={r.symbol + r.account} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '3px 6px', fontWeight: 600, color: 'var(--text0)' }}>{r.symbol}</td>
                      <td style={{ padding: '3px 6px', color: 'var(--text3)', fontSize: 9 }}>{ACCT[r.account] || r.account}</td>
                      <td style={{ padding: '3px 6px', textAlign: 'right', color: 'var(--text1)' }}>{fmt$(r.market_value)}</td>
                      <td style={{ padding: '3px 6px', textAlign: 'right', color: deltaColor(r._pct) }}>{fmtPct(r._pct)}</td>
                      <td style={{ padding: '3px 6px', textAlign: 'right', color: deltaColor(r._dollar), fontWeight: 600 }}>{r._dollar >= 0 ? '+' : ''}{fmt$(r._dollar)}</td>
                    </tr>
                  ))
                })()}
              </tbody>
            </table>
          </div>
          {drillPeriod !== '1D' && (
            <div style={{ marginTop: 6, fontSize: 9, color: 'var(--text3)' }}>
              Note: {drillPeriod} attribution uses enrichment performance data. Exact per-ticker dollar contribution requires historical position tracking.
            </div>
          )}
        </Card>
      )}

      {/* Account filter */}
      <div style={{ display: 'flex', gap: 3, marginBottom: 8 }}>
        {accounts.map(a => (
          <button key={a} onClick={() => setAcctFilter(a)} style={{
            padding: '4px 12px', fontSize: 10, border: `1px solid ${acctFilter === a ? 'var(--accent)' : 'rgba(255,255,255,0.08)'}`, borderRadius: 9999,
            background: acctFilter === a ? 'var(--accent-dim)' : 'rgba(255,255,255,0.04)',
            color: acctFilter === a ? 'var(--accent)' : 'var(--text3)',
            cursor: 'pointer', fontFamily: 'var(--sans)', transition: 'all 100ms',
          }}>
            {ACCT[a] || (a === 'all' ? 'All' : a)}
          </button>
        ))}
      </div>

      {/* Account subtotals */}
      {acctFilter === 'all' && (hd?.holdings ?? []).length > 0 && (() => {
        const acctSums: Record<string, { value: number; count: number; gain: number; cash: number }> = {}
        for (const p of hd?.holdings ?? []) {
          const a = p.account || 'unknown'
          if (!acctSums[a]) acctSums[a] = { value: 0, count: 0, gain: 0, cash: 0 }
          acctSums[a].value += p.market_value
          acctSums[a].count += 1
          if (p.is_cash) acctSums[a].cash += p.market_value
          if ((p as unknown as Record<string,number>).gain_loss) acctSums[a].gain += (p as unknown as Record<string,number>).gain_loss
        }
        return (
          <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Object.keys(acctSums).length}, 1fr)`, gap: 6, marginBottom: 8 }}>
            {Object.entries(acctSums).map(([acct, s]) => (
              <div key={acct} onClick={() => setAcctFilter(acct)} style={{ padding: '6px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', cursor: 'pointer', border: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text0)', marginBottom: 2 }}>{ACCT[acct] || acct}{acct === 'fidelity_401k' ? ' \uD83C\uDFE6' : ''}</div>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{fmt$(s.value)}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                  {s.count} pos{s.cash > 0 ? ` · ${fmt$(s.cash)} cash` : ''}{s.gain !== 0 && acct !== 'fidelity_401k' ? ` · ${s.gain >= 0 ? '+' : ''}${fmt$(s.gain)}` : ''}
                </div>
              </div>
            ))}
          </div>
        )
      })()}

      {/* Holdings grid */}
      <DataGrid columns={columns} data={positions} rowKey={r => r.symbol + ':' + r.account}
        onRowClick={r => { const key = r.symbol + ':' + r.account; setSelected(key === selected ? null : key); setParams(prev => { const p = new URLSearchParams(prev); p.set('symbol', r.symbol); p.set('account', r.account); return p }, { replace: true }) }}
        selectedKey={selected || undefined} maxHeight={420} />

      {/* Holdings detail drawer — matches v1 openHoldingDrawer */}
      <DetailDrawer open={!!sel} onClose={() => setSelected(null)}
        title={sel?.symbol || ''} subtitle={`${sel?.company || sel?.name || ''} | ${ACCT[sel?.account || ''] || sel?.account || ''}`}>
        {sel && (
          <>
            <DrawerSection title="Position">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="Market Value" value={fmt$(sel.market_value)} />
                <DrawerStat label="Shares" value={fmtN(sel.shares, 2)} />
                <DrawerStat label="Price" value={fmt$(sel.price, 2)} />
                <DrawerStat label="Allocation" value={(sel.portfolio_pct ?? 0).toFixed(1) + '%'} color={(sel.portfolio_pct ?? 0) >= 12 ? 'var(--red)' : undefined} />
                <DrawerStat label="Day Change" value={`${(sel.day_change ?? 0) >= 0 ? '+' : ''}${fmt$(sel.day_change ?? 0)} (${sel.day_change_pct != null ? fmtPct(sel.day_change_pct) : '—'})`} color={deltaColor(sel.day_change_pct ?? 0)} />
                <DrawerStat label="Account" value={ACCT[sel.account] || sel.account} />
                {sel.signal && <DrawerStat label="Signal" value={sel.signal} color={SIG_COLOR[sel.signal]} />}
                {sel.yield_pct != null && <DrawerStat label="Dividend Yield" value={sel.yield_pct.toFixed(2) + '%'} color="var(--green)" />}
                {(sel as unknown as Record<string,number>).cost_basis > 0 && (
                  <>
                    <DrawerStat label="Cost Basis" value={fmt$((sel as unknown as Record<string,number>).cost_basis)} />
                    <DrawerStat label="Gain/Loss" value={`${(sel as unknown as Record<string,number>).gain_loss >= 0 ? '+' : ''}${fmt$((sel as unknown as Record<string,number>).gain_loss)}`} color={deltaColor((sel as unknown as Record<string,number>).gain_loss)} />
                  </>
                )}
              </div>
            </DrawerSection>

            <DrawerSection title="Technical">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="RSI" value={sel.rsi?.toFixed(1) ?? '—'} color={sel.rsi != null ? (sel.rsi > 70 ? 'var(--red)' : sel.rsi < 30 ? 'var(--green)' : undefined) : undefined} />
                <DrawerStat label="Beta" value={sel.beta?.toFixed(2) ?? '—'} />
                <DrawerStat label="SMA 20" value={sel.sma20_pct != null ? fmtPct(sel.sma20_pct) : '—'} color={sel.sma20_pct != null ? deltaColor(sel.sma20_pct) : undefined} />
                <DrawerStat label="SMA 50" value={sel.sma50_pct != null ? fmtPct(sel.sma50_pct) : '—'} color={sel.sma50_pct != null ? deltaColor(sel.sma50_pct) : undefined} />
                <DrawerStat label="SMA 200" value={sel.sma200_pct != null ? fmtPct(sel.sma200_pct) : '—'} color={sel.sma200_pct != null ? deltaColor(sel.sma200_pct) : undefined} />
                <DrawerStat label="ATR" value={sel.atr?.toFixed(2) ?? '—'} />
              </div>
            </DrawerSection>

            <DrawerSection title="Fundamentals">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="P/E" value={sel.pe?.toFixed(1) ?? '—'} />
                <DrawerStat label="Fwd P/E" value={sel.forward_pe?.toFixed(1) ?? '—'} />
                <DrawerStat label="EPS TTM" value={sel.eps_ttm != null ? fmt$(sel.eps_ttm, 2) : '—'} />
                <DrawerStat label="Mkt Cap" value={sel.market_cap_b ? fmtCompact(sel.market_cap_b * 1e9) : '—'} />
                <DrawerStat label="52W High" value={sel.week52_high_pct != null ? fmtPct(sel.week52_high_pct) : '—'} />
                <DrawerStat label="Short Float" value={sel.short_float_pct ? sel.short_float_pct.toFixed(1) + '%' : '—'} />
                <DrawerStat label="Sector" value={sel.sector || '—'} />
                <DrawerStat label="Industry" value={sel.industry?.slice(0, 25) || '—'} />
              </div>
            </DrawerSection>

            <DrawerSection title="Links & Drillthrough">
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <button onClick={() => navigate(`/research?symbol=${sel.symbol}`)} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer' }}>Open Research</button>
                <button onClick={() => navigate(`/technical?symbol=${sel.symbol}`)} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer' }}>Open Technical</button>
                <button onClick={() => navigate(`/risk?symbol=${sel.symbol}`)} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer' }}>Open Risk</button>
                <a href={`https://finviz.com/quote.ashx?t=${sel.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
                <a href={`https://finance.yahoo.com/quote/${sel.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Yahoo Finance</a>
                <a href={`https://www.tradingview.com/symbols/${sel.symbol}/`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>TradingView</a>
              </div>
            </DrawerSection>
          </>
        )}
      </DetailDrawer>

      {/* BLOCK 2: Equity curve */}
      {hd?.equity_curve && hd.equity_curve.length > 2 && (
        <>
          <SectionHeader title="Portfolio Value" count={hd.equity_curve.length} />
          <Card compact>
            <div style={{ height: 80 }}>
              <LineChart labels={hd.equity_curve.map(e => e.date.slice(5))} data={hd.equity_curve.map(e => e.value)} />
            </div>
          </Card>
        </>
      )}

      {/* Allocation + Sector charts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 14 }}>
        <div>
          <SectionHeader title="Top 10 Allocation" />
          <Card>
            <div style={{ height: 180 }}>
              <DoughnutChart labels={[...top10.map(p => p.symbol), 'Other']} data={[...top10.map(p => p.market_value), otherTotal > 0 ? otherTotal : 0]} />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
              {top10.map((p, i) => (
                <span key={p.symbol + p.account} style={{ fontSize: 9, color: 'var(--text2)' }}>
                  {p.symbol} {p.portfolio_pct.toFixed(1)}%{i < top10.length - 1 ? ' ·' : ''}
                </span>
              ))}
            </div>
          </Card>
        </div>
        <div>
          <SectionHeader title="Sector Exposure" />
          <Card>
            <div style={{ height: 180 }}>
              <BarChartJS labels={sectorEntries.map(([s]) => s.slice(0, 10))} data={sectorEntries.map(([, v]) => v)}
                colors={sectorEntries.map(() => '#4a90f4')} />
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}

function S({ label, value, color }: { label: string; value: string; color?: string }) {
  return <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.3px' }}>{label}</div><div style={{ fontSize: 11, fontWeight: 600, color: color || 'var(--text0)' }}>{value}</div></div>
}
