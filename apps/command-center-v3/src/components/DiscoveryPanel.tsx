import { useState } from 'react'
import { laneLabel } from '../lib/laneLabels'

// Discovery & Watchlist Builder — type a sector/theme/company/supply-chain query, Hermes (free Grok/
// ChatGPT OAuth) discovers relevant tickers with relevance + relationship + reason, then add to the
// watchlist where enrichment + Hermes scoring take over.
const EXAMPLES = ['companies that supply NVIDIA', 'SpaceX suppliers', 'AI data center growth', 'defense drones', 'stocks exposed to uranium demand']
const relColor = (r?: string) => (({ supplier: '#0ea5e9', customer: '#a855f7', partner: '#22c55e', competitor: '#ef4444', ecosystem: '#f59e0b', enabling: '#14b8a6', 'direct exposure': '#3b82f6', indirect: '#94a3b8' } as any)[r || ''] || 'var(--text3)')
const expColor = (e?: string) => (({ high: '#22c55e', medium: '#f59e0b', low: '#94a3b8' } as any)[e || ''] || 'var(--text3)')

export default function DiscoveryPanel({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [lane, setLane] = useState<'grok' | 'chatgpt'>('grok')
  const [running, setRunning] = useState(false)
  const [res, setRes] = useState<any>(null)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [adding, setAdding] = useState(false)
  const [msg, setMsg] = useState('')

  const discover = async () => {
    if (!query.trim() || running) return
    setRunning(true); setRes(null); setSel(new Set()); setMsg('')
    try {
      const r = await fetch('/api/v2/discovery/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: query.trim(), lane }) })
      const j = await r.json()
      if (j?.data?.results?.length) setRes(j.data)
      else setMsg(j?.data?.error || j?.error || 'No companies found — try rephrasing.')
    } catch { setMsg('Discovery failed.') }
    setRunning(false)
  }
  const add = async (tickers?: string[], topN?: number) => {
    if (!res?.query_id || adding) return
    setAdding(true)
    try {
      const r = await fetch('/api/v2/discovery/add-to-watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query_id: res.query_id, tickers, top_n: topN }) })
      const j = await r.json()
      setMsg(`Added ${j.count} to the watchlist — scoring kicked off.`)
      setTimeout(onAdded, 2500)
    } catch { setMsg('Add failed.') }
    setAdding(false)
  }
  const toggle = (t: string) => { const n = new Set(sel); n.has(t) ? n.delete(t) : n.add(t); setSel(n) }

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
      <div onClick={() => setOpen(!open)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
        <div>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>🔍 Discovery & Watchlist Builder</span>
          <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 8 }}>sector · theme · company · supply chain → ranked tickers → watchlist</span>
        </div>
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>{open ? '▾' : '▸'}</span>
      </div>

      {open && (<div style={{ marginTop: 12 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && discover()}
            placeholder='e.g. "companies that supply NVIDIA"  ·  "AI data center growth"  ·  "defense drones"'
            style={{ flex: '1 1 360px', padding: '8px 12px', fontSize: 12, borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
          <select value={lane} onChange={e => setLane(e.target.value as any)} style={{ padding: '8px 10px', fontSize: 11, borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)' }}>
            <option value="deepseek-flash">DeepSeek Flash (primary)</option>
            <option value="deepseek-v4">DeepSeek v4</option>
            <option value="grok">{laneLabel('grok')}</option>
            <option value="chatgpt">{laneLabel('chatgpt')}</option>
          </select>
          <button onClick={discover} disabled={running || !query.trim()} style={{ padding: '8px 16px', fontSize: 12, fontWeight: 700, borderRadius: 7, border: 'none', cursor: running ? 'default' : 'pointer', background: '#3b82f6', color: '#fff', opacity: running || !query.trim() ? 0.6 : 1 }}>
            {running ? 'Discovering…' : 'Discover'}
          </button>
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
          {EXAMPLES.map(ex => <span key={ex} onClick={() => setQuery(ex)} style={{ fontSize: 9, color: 'var(--text3)', cursor: 'pointer', padding: '2px 8px', borderRadius: 10, background: 'var(--bg2)', border: '1px solid var(--border)' }}>{ex}</span>)}
        </div>
        {msg && <div style={{ fontSize: 11, color: '#3b82f6', marginTop: 10 }}>{msg}</div>}

        {res?.results?.length > 0 && (<div style={{ marginTop: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: 'var(--text2)' }}>{res.count} companies · mode {res.mode} · via {res.lane}</span>
            <span style={{ display: 'flex', gap: 6 }}>
              <button onClick={() => add(Array.from(sel))} disabled={adding || !sel.size} style={{ padding: '5px 12px', fontSize: 11, fontWeight: 700, borderRadius: 6, border: '1px solid #22c55e', background: 'rgba(34,197,94,.12)', color: '#22c55e', cursor: sel.size ? 'pointer' : 'default', opacity: sel.size ? 1 : 0.5 }}>Add selected ({sel.size})</button>
              <button onClick={() => add(undefined, 10)} disabled={adding} style={{ padding: '5px 12px', fontSize: 11, fontWeight: 700, borderRadius: 6, border: 'none', background: '#a855f7', color: '#fff', cursor: 'pointer' }}>Add top 10</button>
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {res.results.map((r: any) => (
              <div key={r.ticker} onClick={() => toggle(r.ticker)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px', borderRadius: 7, cursor: 'pointer', background: sel.has(r.ticker) ? 'rgba(59,130,246,.12)' : 'var(--bg2)', border: `1px solid ${sel.has(r.ticker) ? '#3b82f6' : 'var(--border)'}` }}>
                <input type="checkbox" readOnly checked={sel.has(r.ticker)} style={{ accentColor: '#3b82f6' }} />
                <span style={{ flex: '0 0 56px', fontFamily: 'monospace', fontWeight: 700, color: 'var(--text0)', fontSize: 12 }}>{r.ticker}{r.added_to_watchlist && <span title="already on watchlist" style={{ color: '#22c55e', fontSize: 10 }}> ✓</span>}</span>
                <span style={{ flex: '0 0 44px', textAlign: 'center' }}><span style={{ fontSize: 13, fontWeight: 800, color: r.relevance_score >= 80 ? '#22c55e' : r.relevance_score >= 60 ? '#f59e0b' : 'var(--text3)' }}>{Math.round(r.relevance_score)}</span></span>
                <span style={{ flex: '0 0 110px', fontSize: 9, fontWeight: 700, color: relColor(r.relationship_type) }}>{r.relationship_type}</span>
                <span style={{ flex: '0 0 54px', fontSize: 9, fontWeight: 600, color: expColor(r.exposure_strength) }}>{r.exposure_strength}</span>
                {!r.verified && <span title="ticker not yet in our universe — verify before trading" style={{ flex: '0 0 16px', color: '#f59e0b', fontSize: 11 }}>⚠</span>}
                <span style={{ flex: '1 1 auto', fontSize: 10, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={`${r.company_name} — ${r.reason}`}>{r.reason}</span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Discovered via free {res.lane} OAuth — advisory. relevance = strength + directness of the link to your query. Added names get full enrichment + Hermes composite scoring. ⚠ = ticker not yet verified in our universe.</div>
        </div>)}
      </div>)}
    </div>
  )
}
