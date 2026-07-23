import { useEffect, useMemo, useState } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'
import { HelpTip } from './ReEntryHelpGuide'

const MANDATE_KEY = 'portfolio.reentry.mandates.v4'
const ROTATION_KEY = 'portfolio.reentry.rotation-links.v1'

function useJson(url: string) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    fetch(url, { cache: 'no-store', signal: controller.signal }).then(async response => {
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.ok === false) throw new Error(payload?.error || String(response.status))
      setData(payload?.data && typeof payload.data === 'object' ? payload.data : payload)
    }).catch(value => { if (value?.name !== 'AbortError') setError(String(value?.message || value)) })
    return () => controller.abort()
  }, [url, tick])
  return { data, error, refetch: () => setTick(value => value + 1) }
}
function unwrap(value: any): any { let result = value; for (let i = 0; i < 3 && result?.data && typeof result.data === 'object'; i += 1) result = result.data; return result ?? {} }
function prefMap(value: any): Record<string, any> { const result = unwrap(value)?.value; return result && typeof result === 'object' && !Array.isArray(result) ? result : {} }
function text(...values: any[]): string { for (const value of values) if (value !== null && value !== undefined && String(value).trim()) return String(value).trim(); return '' }
function finite(...values: any[]): number | null { for (const value of values) if (value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))) return Number(value); return null }
function target(value: number | null): string { return value === null ? '—' : `$${value.toFixed(2)}` }
function changeOf(a: any, p: any) {
  const raw = text(a?.latest_action, a?.rating_change, a?.analyst_action, a?.change_type, a?.catalyst, p?.latest_action, p?.rating_change)
  const upper = raw.toUpperCase()
  const direction = /UPGRADE|RAISE|INITIAT.*BUY|RESUME.*BUY/.test(upper) ? 'UPGRADED' : /DOWNGRADE|LOWER|CUT|INITIAT.*SELL|RESUME.*SELL/.test(upper) ? 'DOWNGRADED' : raw ? upper : 'NO RECENT CHANGE IN FEED'
  return { direction, from: text(a?.from_rating, a?.prior_rating, a?.rating_from), to: text(a?.to_rating, a?.new_rating, a?.rating_to), firm: text(a?.firm, a?.analyst_firm, a?.provider), date: text(a?.action_date, a?.change_date, a?.updated_at, a?.as_of) }
}

export default function ReEntryAnalystEvidence() {
  const professional = useJson('/api/v2/pro-analyst/pills?map=1')
  const detail = useJson('/api/v2/analyst-detail?map=1')
  const history = useJson('/api/v2/redeploy/history?days=365')
  const mandates = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`)
  const rotations = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(ROTATION_KEY)}`)
  const [query, setQuery] = useState('')
  const [showAll, setShowAll] = useState(false)
  const pMap: Record<string, any> = unwrap(professional.data)?.map ?? {}
  const dMap: Record<string, any> = unwrap(detail.data)?.map ?? {}
  const mandateMap = prefMap(mandates.data)
  const rotationMap = prefMap(rotations.data)
  const historyRows: any[] = unwrap(history.data)?.rows ?? []
  const source = new Set<string>(); const destination = new Set<string>()
  for (const link of Object.values(rotationMap) as any[]) { if (link?.sourceSymbol) source.add(String(link.sourceSymbol).toUpperCase()); if (link?.destinationSymbol) destination.add(String(link.destinationSymbol).toUpperCase()) }
  const symbols = useMemo(() => [...new Set([...historyRows.map(row => text(row.symbol).toUpperCase()), ...Object.keys(mandateMap), ...source, ...destination].filter(Boolean))].sort(), [history.data, mandates.data, rotations.data])
  const rows = symbols.map(symbol => {
    const p = pMap[symbol] ?? {}; const a = dMap[symbol] ?? {}; const dist = a.dist ?? {}
    return { symbol, p, a, change: changeOf(a, p), rec: text(p.rec, a.rec, p.recommendation, a.recommendation_key), n: finite(p.n, a.n), mean: finite(a.target_mean, p.target, a.target_mean_price), median: finite(a.target_median, a.target_median_price), high: finite(a.target_high, a.target_high_price), low: finite(a.target_low, a.target_low_price), upside: finite(a.upside, p.upside), dist: [['strong_buy', 'SB'], ['buy', 'B'], ['hold', 'H'], ['sell', 'S'], ['strong_sell', 'SS']].filter(([key]) => dist[key] != null).map(([key, label]) => `${label} ${dist[key]}`).join(' · '), asOf: text(a.as_of, a.dist_period, p.as_of), role: source.has(symbol) ? 'ROTATION SOURCE' : destination.has(symbol) ? 'ROTATION DESTINATION' : 'RE-ENTRY CANDIDATE' }
  }).filter(row => !query.trim() || row.symbol.includes(query.trim().toUpperCase()))
  const shown = rows.slice(0, showAll ? rows.length : 50)
  return <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><div style={{ fontSize: 13, fontWeight: 900 }}>DETAILED ANALYST EVIDENCE <HelpTip text="The same professional-consensus and analyst-detail maps used by Watch. Informational only; they do not bypass the six return gates." /></div><div style={{ fontSize: 10, color: BB.text3 }}>Buy/hold/sell consensus · upgrade/downgrade evidence · rating distribution · mean/median/high/low targets · source and as-of</div></div><button onClick={() => { professional.refetch(); detail.refetch(); history.refetch() }} style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)' }}>REFRESH</button></div>
    <div style={{ marginTop: 7, padding: '7px 9px', border: `1px solid ${BB.blue}`, borderRadius: 5, fontSize: 10.5 }}><b style={{ color: BB.blue }}>MEMORIALIZED USE:</b> this evidence is saved with the persistent ticker context and used for thesis, priority and target-weight review. It cannot by itself mark a re-entry ready or trigger a rotation-back alert.</div>
    {[professional.error, detail.error].filter(Boolean).map(error => <div key={error} style={{ fontSize: 10, color: BB.red, marginTop: 5 }}>{error}</div>)}
    <div style={{ display: 'flex', gap: 7, marginTop: 8 }}><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Filter symbol…" style={{ minWidth: 230, fontSize: 11, padding: '5px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} /><button onClick={() => setShowAll(value => !value)} style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${showAll ? BB.blue : 'var(--border)'}`, background: showAll ? BB.blueDim : 'var(--bg2)', color: showAll ? BB.blue : 'var(--text2)' }}>{showAll ? 'SHOW FIRST 50' : `SHOW ALL ${rows.length}`}</button></div>
    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1440 }}><div style={{ display: 'grid', gridTemplateColumns: '75px 210px 245px 310px 175px 1fr', gap: 8, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Symbol</span><span>Consensus</span><span>Upgrade / downgrade</span><span>Targets / distribution</span><span>Role</span><span>How used</span></div>{shown.map(row => {
      const recKey = row.rec.toLowerCase(); const recColor = ['strong_buy', 'strong buy', 'buy'].includes(recKey) ? BB.green : ['sell', 'strong_sell', 'strong sell', 'underperform'].includes(recKey) ? BB.red : row.rec ? BB.amber : BB.text3
      const changeColor = row.change.direction === 'UPGRADED' ? BB.green : row.change.direction === 'DOWNGRADED' ? BB.red : BB.text3
      return <div key={row.symbol} style={{ display: 'grid', gridTemplateColumns: '75px 210px 245px 310px 175px 1fr', gap: 8, padding: '8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5 }}><b style={{ fontSize: 12 }}>{row.symbol}</b><div><b style={{ color: recColor }}>{row.rec ? row.rec.replace(/_/g, ' ').toUpperCase() : 'UNAVAILABLE'}</b><br /><span style={{ color: BB.text3 }}>{row.n ?? '—'} analysts · {row.upside === null ? 'target upside unavailable' : `${row.upside >= 0 ? '+' : ''}${row.upside.toFixed(1)}% to mean`}</span></div><div><b style={{ color: changeColor }}>{row.change.direction}</b><br /><span style={{ color: BB.text3 }}>{row.change.from || row.change.to ? `${row.change.from || '—'} → ${row.change.to || '—'}` : 'No from/to rating in feed'}{row.change.firm ? ` · ${row.change.firm}` : ''}{row.change.date ? ` · ${row.change.date.slice(0, 10)}` : ''}</span></div><div><b>Mean {target(row.mean)} · Median {target(row.median)}</b><br /><span style={{ color: BB.green }}>High {target(row.high)}</span> · <span style={{ color: BB.red }}>Low {target(row.low)}</span><br /><span style={{ color: BB.text3 }}>{row.dist || 'Rating distribution unavailable'} · as of {row.asOf || 'unavailable'}</span></div><b style={{ color: row.role === 'ROTATION SOURCE' ? BB.amber : row.role === 'ROTATION DESTINATION' ? BB.blue : BB.text3 }}>{row.role}</b><span style={{ color: BB.text3 }}>{row.role === 'ROTATION SOURCE' ? 'Analyst changes update the return thesis; the technical/regime/tax gates still control the alert.' : row.role === 'ROTATION DESTINATION' ? 'Watch for deterioration while capital is parked; no automatic switch occurs.' : 'Use with entry zone, resistance hold, trend, regime and account constraints.'}</span></div>
    })}</div></div>
  </div>
}
