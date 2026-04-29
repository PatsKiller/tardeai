import { useState, useCallback } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import DataGrid from '../components/DataGrid'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import { useApi } from '../hooks/useApi'
import { useFetch } from '../hooks/useFetch'
import { fmt$, fmtPct, deltaColor } from '../lib/format'
import type { Enrichment, NewsData, Catalyst } from '../lib/types'

interface WlItem { symbol: string; source: string; status: string; company: string; rsi: number | null; perf_week_pct: number | null; confidence: number | null; expires_at: string | null; upside_pct: number | null; notes?: string | null }
interface WlData { count: number; items: WlItem[] }

const srcColor: Record<string, string> = { user: 'var(--accent)', analyst_curated: 'var(--amber)', ai_generated: 'var(--green)' }
const srcLabel: Record<string, string> = { user: 'User', analyst_curated: 'Analyst', ai_generated: 'AI' }

export default function Watchlist() {
  const { data: wl } = useApi<WlData>('/api/v2/watchlist')
  const { data: news } = useFetch<NewsData>('/data/portfolios/state/portfolio_news.json')
  const [showAdd, setShowAdd] = useState(false)
  const [selectedItem, setSelectedItem] = useState<WlItem | null>(null)
  const [addSym, setAddSym] = useState('')
  const [addIntent, setAddIntent] = useState('growth')
  const [addThesis, setAddThesis] = useState('')
  const [addStatus, setAddStatus] = useState<string | null>(null)

  const items = wl?.items ?? []
  const allArticles = news?.all_scored || news?.catalysts || []
  const articleCount = (sym: string) => allArticles.filter((a: Catalyst) => a.portfolio_symbol === sym).length

  const handleAdd = useCallback(async () => {
    if (!addSym.trim()) return
    setAddStatus('Adding...')
    try {
      const resp = await fetch('/api/watchlist/write', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'add', symbol: addSym.trim().toUpperCase(), source_type: 'user', intent: addIntent, thesis: addThesis }) })
      const d = await resp.json()
      setAddStatus(d.ok ? 'Added' : d.error || 'Failed')
      if (d.ok) { setAddSym(''); setTimeout(() => { setAddStatus(null); window.location.reload() }, 800) }
    } catch { setAddStatus('Failed') }
  }, [addSym])

  const handleRemove = useCallback(async (sym: string, source: string) => {
    try {
      await fetch('/api/watchlist/write', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'remove', symbol: sym, source_type: source }) })
      window.location.reload()
    } catch {}
  }, [])

  const columns = [
    { key: 'symbol', label: 'Symbol', width: 55, render: (r: WlItem) => <span style={{ fontWeight: 700 }}>{r.symbol}</span> },
    { key: 'source', label: 'Source', width: 55, render: (r: WlItem) => (
      <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: `color-mix(in srgb, ${srcColor[r.source] || 'var(--text3)'} 15%, transparent)`, color: srcColor[r.source] || 'var(--text3)' }}>
        {srcLabel[r.source] || r.source}
      </span>
    )},
    { key: 'company', label: 'Company', width: 120, render: (r: WlItem) => <span style={{ fontSize: 10, color: 'var(--text2)' }}>{r.company?.slice(0, 20) || '—'}</span> },
    { key: 'confidence', label: 'Conf', width: 40, align: 'right' as const, render: (r: WlItem) => r.confidence ? <span style={{ color: r.confidence >= 0.8 ? 'var(--green)' : 'var(--text2)' }}>{(r.confidence * 100).toFixed(0)}%</span> : <span style={{ color: 'var(--text3)' }}>—</span> },
    { key: 'upside', label: 'Upside', width: 50, align: 'right' as const, render: (r: WlItem) => r.upside_pct ? <span style={{ color: 'var(--green)' }}>+{r.upside_pct.toFixed(0)}%</span> : <span style={{ color: 'var(--text3)' }}>—</span> },
    { key: 'rsi', label: 'RSI', width: 35, align: 'right' as const, render: (r: WlItem) => r.rsi != null ? <span style={{ color: r.rsi > 70 ? 'var(--red)' : r.rsi < 30 ? 'var(--green)' : 'var(--text1)' }}>{r.rsi.toFixed(0)}</span> : <span style={{ color: 'var(--text3)' }}>—</span> },
    { key: 'perf', label: '1W', width: 50, align: 'right' as const, render: (r: WlItem) => r.perf_week_pct != null ? <span style={{ color: deltaColor(r.perf_week_pct) }}>{fmtPct(r.perf_week_pct)}</span> : <span style={{ color: 'var(--text3)' }}>—</span> },
    { key: 'articles', label: 'News', width: 35, align: 'right' as const, render: (r: WlItem) => { const c = articleCount(r.symbol); return c > 0 ? <span style={{ color: 'var(--accent)' }}>{c}</span> : <span style={{ color: 'var(--text3)' }}>0</span> }},
    { key: 'expires', label: 'Expires', width: 65, render: (r: WlItem) => r.expires_at ? <span style={{ fontSize: 9, color: 'var(--text3)' }}>{r.expires_at}</span> : <span style={{ color: 'var(--text3)' }}>—</span> },
    { key: 'remove', label: '', width: 25, sortable: false, render: (r: WlItem) => (
      <button onClick={e => { e.stopPropagation(); handleRemove(r.symbol, r.source) }} style={{ fontSize: 9, color: 'var(--text3)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--mono)' }} title="Remove">x</button>
    )},
  ]

  return (
    <>
      <PageHeader title="Watchlist" subtitle={`${items.length} items`} actions={
        <button onClick={() => setShowAdd(!showAdd)} style={{ padding: '3px 10px', fontSize: 10, border: '1px solid var(--accent)', borderRadius: 'var(--radius)', background: 'var(--accent-dim)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>
          + Add
        </button>
      } />

      {/* Add form */}
      {showAdd && (
        <Card compact>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input value={addSym} onChange={e => setAddSym(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleAdd()} placeholder="SYMBOL" style={{ padding: '4px 8px', fontSize: 11, width: 80, background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text0)', fontFamily: 'var(--mono)', outline: 'none' }} />
              <select value={addIntent} onChange={e => setAddIntent(e.target.value)} style={{ padding: '4px 6px', fontSize: 10, background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text1)', fontFamily: 'var(--mono)' }}>
                {['growth', 'income', 'defense', 'speculative', 'swing', 'long_term_hold', 'etf_broad'].map(i => (
                  <option key={i} value={i}>{i.replace(/_/g, ' ')}</option>
                ))}
              </select>
              <button onClick={handleAdd} style={{ padding: '4px 10px', fontSize: 10, border: '1px solid var(--green)', borderRadius: 'var(--radius)', background: 'var(--green-dim)', color: 'var(--green)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Add</button>
              <button onClick={() => setShowAdd(false)} style={{ padding: '4px 10px', fontSize: 10, border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text3)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Cancel</button>
              {addStatus && <span style={{ fontSize: 10, color: addStatus === 'Added' ? 'var(--green)' : 'var(--text2)' }}>{addStatus}</span>}
            </div>
            <textarea value={addThesis} onChange={e => setAddThesis(e.target.value)} placeholder="Thesis / notes (optional)" rows={2} style={{ padding: '4px 8px', fontSize: 10, background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text1)', fontFamily: 'var(--mono)', outline: 'none', resize: 'vertical' }} />
          </div>
        </Card>
      )}

      {/* Source summary */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 10, marginTop: 8 }}>
        {Object.entries(srcLabel).map(([key, label]) => {
          const count = items.filter(i => i.source === key).length
          return count > 0 ? (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: srcColor[key] }} />
              <span style={{ color: 'var(--text2)' }}>{label}</span>
              <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{count}</span>
            </div>
          ) : null
        })}
      </div>

      <DataGrid columns={columns} data={items} rowKey={r => r.symbol + ':' + r.source} maxHeight={400}
        onRowClick={r => setSelectedItem(r)} />

      {/* Watchlist detail drawer */}
      <DetailDrawer open={!!selectedItem} onClose={() => setSelectedItem(null)}
        title={selectedItem?.symbol || ''} subtitle={`${srcLabel[selectedItem?.source || 'user']} watchlist item`}>
        {selectedItem && (
          <>
            <DrawerSection title="Details">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="Symbol" value={selectedItem.symbol} />
                <DrawerStat label="Source" value={srcLabel[selectedItem.source] || selectedItem.source} />
                <DrawerStat label="Company" value={selectedItem.company || '—'} />
                <DrawerStat label="Status" value={selectedItem.status} />
                {selectedItem.rsi != null && <DrawerStat label="RSI" value={selectedItem.rsi.toFixed(0)} color={selectedItem.rsi > 70 ? 'var(--red)' : selectedItem.rsi < 30 ? 'var(--green)' : undefined} />}
                {selectedItem.perf_week_pct != null && <DrawerStat label="1W Perf" value={fmtPct(selectedItem.perf_week_pct)} color={deltaColor(selectedItem.perf_week_pct)} />}
                {selectedItem.confidence != null && <DrawerStat label="Confidence" value={`${(selectedItem.confidence * 100).toFixed(0)}%`} color={selectedItem.confidence >= 0.8 ? 'var(--green)' : 'var(--text2)'} />}
                {selectedItem.upside_pct != null && <DrawerStat label="Upside" value={`+${selectedItem.upside_pct}%`} color="var(--green)" />}
                {selectedItem.expires_at && <DrawerStat label="Expires" value={selectedItem.expires_at} />}
              </div>
            </DrawerSection>
            <DrawerSection title="Links">
              <div style={{ display: 'flex', gap: 6 }}>
                <a href={`https://finviz.com/quote.ashx?t=${selectedItem.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
                <a href={`https://finance.yahoo.com/quote/${selectedItem.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Yahoo</a>
              </div>
            </DrawerSection>
          </>
        )}
      </DetailDrawer>

      {/* AI detail cards */}
      {items.filter(i => i.source === 'ai_generated').length > 0 && (
        <>
          <SectionHeader title="AI-Generated Detail" count={items.filter(i => i.source === 'ai_generated').length} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8 }}>
            {items.filter(i => i.source === 'ai_generated').map(r => (
              <Card key={r.symbol} title={r.symbol} subtitle={r.company?.slice(0, 18)} compact>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3, fontSize: 10 }}>
                  {r.upside_pct != null && <div><span style={{ color: 'var(--text3)', fontSize: 8 }}>UPSIDE</span><div style={{ color: 'var(--green)', fontWeight: 600 }}>+{r.upside_pct}%</div></div>}
                  {r.confidence != null && <div><span style={{ color: 'var(--text3)', fontSize: 8 }}>CONFIDENCE</span><div style={{ fontWeight: 600 }}>{(r.confidence * 100).toFixed(0)}%</div></div>}
                  {r.expires_at && <div><span style={{ color: 'var(--text3)', fontSize: 8 }}>EXPIRES</span><div>{r.expires_at}</div></div>}
                  <div><span style={{ color: 'var(--text3)', fontSize: 8 }}>ARTICLES</span><div>{articleCount(r.symbol)}</div></div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </>
  )
}
