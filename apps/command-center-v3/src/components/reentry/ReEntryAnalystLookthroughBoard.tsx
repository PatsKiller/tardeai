import { useEffect, useMemo, useState } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'

const MANDATE_KEY = 'portfolio.reentry.mandates.v4'
const ROTATION_KEY = 'portfolio.reentry.rotation-links.v1'

function useJson(url: string) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    fetch(url, { cache: 'no-store', signal: controller.signal })
      .then(async response => {
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.ok === false) throw new Error(payload?.error || String(response.status))
        setData(payload?.data && typeof payload.data === 'object' ? payload.data : payload)
      })
      .catch(value => { if (value?.name !== 'AbortError') setError(String(value?.message || value)) })
    return () => controller.abort()
  }, [url, tick])
  return { data, error, refetch: () => setTick(value => value + 1) }
}
function unwrap(value: any): any {
  let result = value
  for (let index = 0; index < 3 && result?.data && typeof result.data === 'object'; index += 1) result = result.data
  return result ?? {}
}
function prefMap(value: any): Record<string, any> {
  const result = unwrap(value)?.value
  return result && typeof result === 'object' && !Array.isArray(result) ? result : {}
}
function finite(...values: any[]): number | null {
  for (const value of values) if (value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))) return Number(value)
  return null
}
function text(...values: any[]): string {
  for (const value of values) if (value !== null && value !== undefined && String(value).trim()) return String(value).trim()
  return ''
}
function fundDetail(lookthrough: any, symbol: string): any {
  const payload = unwrap(lookthrough)
  const maps = [payload?.funds, payload?.etfs, payload?.by_fund, payload?.fund_lookthrough, payload?.funds_detail]
  for (const map of maps) if (map?.[symbol]) return map[symbol]
  return null
}
function list(value: any): any[] { return Array.isArray(value) ? value : [] }
function weightStatus(current: number, target: number | null, source: boolean, destination: boolean) {
  if (target !== null) {
    const delta = current - target
    if (Math.abs(delta) <= 0.25) return { label: 'AT TARGET', delta, color: BB.green }
    if (delta > 0) return { label: 'OVERWEIGHT', delta, color: BB.amber }
    return { label: 'UNDERWEIGHT', delta, color: BB.red }
  }
  if (source) return { label: 'REDUCED SOURCE', delta: null, color: BB.amber }
  if (destination) return { label: 'INCREASED DESTINATION', delta: null, color: BB.blue }
  return { label: 'NO TARGET', delta: null, color: BB.text3 }
}

export default function ReEntryAnalystLookthroughBoard() {
  const analyst = useJson('/api/v2/pro-analyst/pills?map=1')
  const lookthrough = useJson('/api/v2/portfolio/lookthrough')
  const holdings = useJson('/api/v2/portfolio/holdings')
  const history = useJson('/api/v2/redeploy/history?days=365')
  const mandatePref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`)
  const rotationPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(ROTATION_KEY)}`)
  const [query, setQuery] = useState('')
  const [showAll, setShowAll] = useState(false)

  const analystMap: Record<string, any> = unwrap(analyst.data)?.map ?? {}
  const mandates = prefMap(mandatePref.data)
  const rotations = prefMap(rotationPref.data)
  const holdingRows: any[] = unwrap(holdings.data)?.holdings ?? []
  const historyRows: any[] = unwrap(history.data)?.rows ?? []
  const valueBySymbol: Record<string, number> = {}
  let portfolioTotal = 0
  for (const row of holdingRows) {
    const symbol = text(row.symbol).toUpperCase()
    const value = finite(row.market_value, row.value) ?? 0
    if (symbol) valueBySymbol[symbol] = (valueBySymbol[symbol] ?? 0) + value
    portfolioTotal += value
  }
  const sourceSymbols = new Set<string>()
  const destinationSymbols = new Set<string>()
  for (const link of Object.values(rotations) as any[]) {
    if (!link || typeof link !== 'object') continue
    if (link.sourceSymbol) sourceSymbols.add(String(link.sourceSymbol).toUpperCase())
    if (link.destinationSymbol) destinationSymbols.add(String(link.destinationSymbol).toUpperCase())
  }
  const symbols = useMemo(() => [...new Set([
    ...Object.keys(mandates),
    ...historyRows.map(row => text(row.symbol).toUpperCase()),
    ...sourceSymbols,
    ...destinationSymbols,
  ].filter(Boolean))].sort(), [mandatePref.data, history.data, rotationPref.data])

  const rows = symbols.map(symbol => {
    const professional = analystMap[symbol] ?? null
    const fund = fundDetail(lookthrough.data, symbol)
    const currentWeight = portfolioTotal > 0 ? (valueBySymbol[symbol] ?? 0) / portfolioTotal * 100 : 0
    const targetWeight = finite(mandates[symbol]?.targetWeightPct, mandates[symbol]?.target_weight_pct)
    const status = weightStatus(currentWeight, targetWeight, sourceSymbols.has(symbol), destinationSymbols.has(symbol))
    const sectors = list(fund?.sectors ?? fund?.sector_weights).slice(0, 3)
    const topHoldings = list(fund?.top_holdings ?? fund?.holdings).slice(0, 5)
    const lookthroughAnalyst = finite(fund?.analyst_look_through_pct, fund?.look_through_analyst_pct)
    return { symbol, professional, fund, currentWeight, targetWeight, status, sectors, topHoldings, lookthroughAnalyst }
  }).filter(row => !query.trim() || row.symbol.includes(query.trim().toUpperCase()))
    .sort((a, b) => {
      const ar = a.status.label === 'UNDERWEIGHT' ? 0 : a.status.label === 'REDUCED SOURCE' ? 1 : 2
      const br = b.status.label === 'UNDERWEIGHT' ? 0 : b.status.label === 'REDUCED SOURCE' ? 1 : 2
      return ar - br || a.symbol.localeCompare(b.symbol)
    })
  const shown = rows.slice(0, showAll ? rows.length : 40)
  const errors = [analyst.error && `Analyst: ${analyst.error}`, lookthrough.error && `Look-through: ${lookthrough.error}`, holdings.error && `Holdings: ${holdings.error}`].filter(Boolean)

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div><div style={{ fontSize: 13, fontWeight: 900 }}>ANALYST / ETF LOOK-THROUGH / WEIGHT BOARD</div><div style={{ fontSize: 10, color: BB.text3 }}>Real Street consensus · ETF fields labeled look-through · current versus target weight · rotation source/destination status</div></div>
        <button onClick={() => { analyst.refetch(); lookthrough.refetch(); holdings.refetch(); history.refetch() }} style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)' }}>REFRESH</button>
      </div>
      {errors.map(error => <div key={String(error)} style={{ fontSize: 10, color: BB.red, marginTop: 5 }}>{error}</div>)}
      <div style={{ display: 'flex', gap: 7, marginTop: 8 }}><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Filter analyst / ETF symbols…" style={{ minWidth: 240, fontSize: 11, padding: '5px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} /><button onClick={() => setShowAll(value => !value)} style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${showAll ? BB.blue : 'var(--border)'}`, background: showAll ? BB.blueDim : 'var(--bg2)', color: showAll ? BB.blue : 'var(--text2)' }}>{showAll ? 'SHOW FIRST 40' : `SHOW ALL ${rows.length}`}</button></div>
      <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1250 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '75px 250px 190px 210px 235px 250px', gap: 8, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Symbol</span><span>Professional analyst consensus</span><span>Weight</span><span>Weight status</span><span>ETF look-through</span><span>Top exposure evidence</span></div>
        {shown.map(row => {
          const p = row.professional
          const rec = p?.has ? text(p.rec, 'targets only').replace(/_/g, ' ').toUpperCase() : 'NO PROFESSIONAL COVERAGE'
          const analystColor = !p?.has ? BB.text3 : ['strong_buy', 'buy'].includes(String(p.rec).toLowerCase()) ? BB.green : String(p.rec).toLowerCase() === 'sell' ? BB.red : BB.amber
          const sectorText = row.sectors.map((item: any) => `${text(item.name, item.sector, item.label)} ${finite(item.pct, item.weight_pct) ?? '—'}%`).join(' · ')
          const holdingText = row.topHoldings.map((item: any) => `${text(item.symbol, item.ticker, item.name)} ${finite(item.pct, item.weight_pct) ?? '—'}%`).join(' · ')
          const isFund = Boolean(row.fund)
          return <div key={row.symbol} style={{ display: 'grid', gridTemplateColumns: '75px 250px 190px 210px 235px 250px', gap: 8, padding: '7px 8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5 }}>
            <b style={{ fontSize: 12 }}>{row.symbol}</b>
            <div><b style={{ color: analystColor }}>{rec}</b>{p?.has && <><br /><span style={{ color: BB.text3 }}>{p.n ?? '—'} analysts · mean target {p.target == null ? '—' : `$${p.target}`} · {p.upside == null ? '—' : `${p.upside >= 0 ? '+' : ''}${p.upside}%`} upside</span>{p.divergence === 'divergent' && <span style={{ color: BB.red }}> · ≠ Street</span>}{p.stale && <span style={{ color: BB.amber }}> · STALE</span>}</>}</div>
            <div><b>{row.currentWeight.toFixed(2)}% current</b><br /><span style={{ color: BB.text3 }}>{row.targetWeight === null ? 'target not assigned' : `${row.targetWeight.toFixed(2)}% target`}</span></div>
            <div><b style={{ color: row.status.color }}>{row.status.label}</b><br /><span style={{ color: BB.text3 }}>{row.status.delta === null ? sourceSymbols.has(row.symbol) ? 'capital moved out / awaiting return plan' : destinationSymbols.has(row.symbol) ? 'capital moved in as destination' : 'assign a target weight' : `${row.status.delta >= 0 ? '+' : ''}${row.status.delta.toFixed(2)} percentage points vs target`}</span></div>
            <div>{isFund ? <><b style={{ color: BB.blue }}>ETF/FUND LOOK-THROUGH</b><br /><span style={{ color: BB.text3 }}>analyst look-through {row.lookthroughAnalyst === null ? 'unavailable' : `${row.lookthroughAnalyst.toFixed(0)}%`} · expense {finite(row.fund?.expense_ratio) === null ? '—' : `${finite(row.fund?.expense_ratio)!.toFixed(2)}%`} · yield {finite(row.fund?.distribution_yield, row.fund?.yield_pct) === null ? '—' : `${finite(row.fund?.distribution_yield, row.fund?.yield_pct)!.toFixed(2)}%`}</span></> : <span style={{ color: BB.text3 }}>Direct security — Street consensus shown at left.</span>}</div>
            <div style={{ color: BB.text3 }}>{isFund ? sectorText || holdingText || 'Fund-specific holdings unavailable; portfolio-wide look-through is not relabeled as fund-specific.' : 'n/a'}{sectorText && holdingText ? <><br />{holdingText}</> : null}</div>
          </div>
        })}
      </div></div>
      {!shown.length && <div style={{ padding: 12, color: BB.text3, fontSize: 10 }}>No symbols match the current filter.</div>}
    </div>
  )
}
