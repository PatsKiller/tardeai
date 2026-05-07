import { useState, useMemo, useRef, useEffect } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import Tooltip from '../components/Tooltip'
import { useApi } from '../hooks/useApi'
import { timeAgo, fmtN } from '../lib/format'

interface WhiteboardItem { id: number; symbol: string; title: string; summary: string; source_type: string; quality_score: number; confidence: number; status: string; days_on_board: number; created_at: string; hygiene_status: string | null }
interface WhiteboardData { items: WhiteboardItem[]; stats: { total: number; by_source: Record<string, number>; by_status: Record<string, number> } }
interface RagStatus { total_rows: number; total_embedded: number; coverage_pct: number; by_source: Record<string, { total: number; embedded: number; pct: number }> }
interface ContentGap { category: string; news_30d: number; youtube_30d: number; thin: boolean }
interface ContentGapsData { gaps: ContentGap[] }

const sourceColor = (s: string) => s === 'youtube' ? '#f44' : s === 'news' ? 'var(--accent)' : s === 'sec_form4' ? 'var(--amber)' : s === 'earnings' ? 'var(--green)' : 'var(--text3)'

type SortKey = 'quality' | 'date' | 'symbol'

function useDebounce(value: string, ms: number) {
  const [debounced, setDebounced] = useState(value)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => {
    timer.current = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer.current)
  }, [value, ms])
  return debounced
}

export default function IntelligenceWhiteboard() {
  const { data, error } = useApi<WhiteboardData>('/api/v2/intelligence-whiteboard', 60000)
  const { data: ragData } = useApi<RagStatus>('/api/v2/rag/status', 60000)
  const { data: gapsData } = useApi<ContentGapsData>('/api/v2/iris/content-gaps', 60000)

  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [staleFilter, setStaleFilter] = useState<'active' | 'stale' | 'all'>('all')
  const [limit, setLimit] = useState(100)
  const [searchRaw, setSearchRaw] = useState('')
  const [symbolRaw, setSymbolRaw] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('quality')

  const search = useDebounce(searchRaw, 300)
  const symbolSearch = useDebounce(symbolRaw, 300)

  // Critical content gaps
  const criticalGaps = useMemo(() => {
    if (!gapsData?.gaps) return []
    return gapsData.gaps.filter(g => g.news_30d === 0 && g.youtube_30d === 0)
  }, [gapsData])

  // Filtered + sorted items
  const { filtered, sourceCounts } = useMemo(() => {
    if (!data) return { filtered: [], sourceCounts: {} as Record<string, number> }

    let items = data.items

    // Source filter
    if (sourceFilter !== 'all') items = items.filter(i => i.source_type === sourceFilter)

    // Stale filter
    if (staleFilter === 'active') items = items.filter(i => i.days_on_board <= 90)
    else if (staleFilter === 'stale') items = items.filter(i => i.days_on_board > 90)

    // Search filter
    const q = search.toLowerCase()
    if (q) items = items.filter(i => i.title.toLowerCase().includes(q) || i.symbol.toLowerCase().includes(q) || i.source_type.toLowerCase().includes(q))

    // Symbol filter
    const sym = symbolSearch.toUpperCase()
    if (sym) items = items.filter(i => i.symbol.toUpperCase().includes(sym))

    // Compute per-source counts after all filters
    const counts: Record<string, number> = {}
    for (const i of items) counts[i.source_type] = (counts[i.source_type] || 0) + 1

    // Sort
    const sorted = [...items]
    if (sortKey === 'quality') sorted.sort((a, b) => b.quality_score - a.quality_score)
    else if (sortKey === 'date') sorted.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    else if (sortKey === 'symbol') sorted.sort((a, b) => a.symbol.localeCompare(b.symbol))

    return { filtered: sorted, sourceCounts: counts }
  }, [data, sourceFilter, staleFilter, search, symbolSearch, sortKey])

  const hasActiveFilters = search !== '' || symbolSearch !== ''

  if (error) return <div style={{ color: 'var(--red)', padding: 40 }}>Error loading whiteboard: {error}</div>
  if (!data) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading intelligence whiteboard...</div>

  const sources = Object.entries(data.stats.by_source || {})

  const chipStyle = (active: boolean, color?: string): React.CSSProperties => ({
    fontSize: 9, padding: '3px 10px', border: `1px solid ${active ? (color || 'var(--accent)') : 'var(--border)'}`,
    borderRadius: 12, background: active ? (color ? `color-mix(in srgb, ${color} 10%, transparent)` : 'var(--accent-dim)') : 'var(--bg3)',
    color: active ? (color || 'var(--accent)') : 'var(--text2)', cursor: 'pointer', fontWeight: 600,
  })

  const sortBtnStyle = (active: boolean): React.CSSProperties => ({
    fontSize: 9, padding: '3px 10px', border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
    borderRadius: 4, background: active ? 'var(--accent-dim)' : 'var(--bg3)',
    color: active ? 'var(--accent)' : 'var(--text2)', cursor: 'pointer', fontWeight: 600,
  })

  const inputStyle: React.CSSProperties = {
    fontSize: 10, padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 4,
    background: 'var(--bg2)', color: 'var(--text1)', outline: 'none', fontFamily: 'inherit',
  }

  const clearBtnStyle: React.CSSProperties = {
    position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)',
    background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', fontSize: 11,
    lineHeight: 1, padding: '0 2px',
  }

  const now = new Date()
  const ragTime = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })

  return (
    <>
      {/* Header + RAG tile */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <PageHeader title="Intelligence Whiteboard" subtitle={`${data.stats.total} items across ${sources.length} source types`} />

        {/* A. RAG Coverage Mini-Tile */}
        {ragData && (
          <div style={{
            padding: '6px 14px', background: 'var(--bg2)', border: '1px solid var(--border-subtle)',
            borderRadius: 8, fontSize: 10, color: 'var(--text2)', display: 'flex', alignItems: 'center', gap: 8,
            whiteSpace: 'nowrap', marginTop: 4,
          }}>
            <span style={{ fontSize: 12 }}>&#x1F4CA;</span>
            <span style={{ fontWeight: 700, color: 'var(--text1)' }}>{fmtN(ragData.total_rows)}</span> items
            <span style={{ color: 'var(--border)' }}>·</span>
            <span style={{ fontWeight: 700, color: ragData.coverage_pct >= 95 ? 'var(--green)' : 'var(--amber)' }}>{ragData.coverage_pct.toFixed(1)}%</span> embedded
            <span style={{ color: 'var(--border)' }}>·</span>
            <span style={{ color: 'var(--text3)' }}>Updated {ragTime}</span>
          </div>
        )}
      </div>

      {/* B. Content Gap Alert Banner */}
      {criticalGaps.length > 0 && (
        <div style={{
          padding: '8px 14px', marginBottom: 14, background: 'color-mix(in srgb, var(--amber) 8%, transparent)',
          border: '1px solid color-mix(in srgb, var(--amber) 30%, transparent)', borderRadius: 8,
          fontSize: 10, color: 'var(--amber)', lineHeight: 1.6,
        }}>
          <div style={{ fontWeight: 700 }}>&#x26A0;&#xFE0F; {criticalGaps.length} content gap{criticalGaps.length !== 1 ? 's' : ''} detected by Iris:</div>
          <div style={{ color: 'var(--text2)' }}>
            {criticalGaps.map(g => `${g.category} (0 articles)`).join(', ')}
          </div>
          <div style={{ color: 'var(--text3)', fontSize: 9 }}>Agents in these areas have limited RAG context.</div>
        </div>
      )}

      {/* C + D. Search bar + Symbol filter */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ position: 'relative' }}>
          <input
            type="text" placeholder="Search by title, symbol, or source..."
            value={searchRaw} onChange={e => setSearchRaw(e.target.value)}
            style={{ ...inputStyle, width: 240, paddingRight: searchRaw ? 20 : 8 }}
          />
          {searchRaw && <button onClick={() => setSearchRaw('')} style={clearBtnStyle}>&times;</button>}
        </div>
        <div style={{ position: 'relative' }}>
          <input
            type="text" placeholder="Symbol..."
            value={symbolRaw} onChange={e => setSymbolRaw(e.target.value)}
            style={{ ...inputStyle, width: 100, paddingRight: symbolRaw ? 20 : 8 }}
          />
          {symbolRaw && <button onClick={() => setSymbolRaw('')} style={clearBtnStyle}>&times;</button>}
        </div>

        {/* F. Sort toggle buttons */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
          <button onClick={() => setSortKey('quality')} style={sortBtnStyle(sortKey === 'quality')}>Quality &#x25BC;</button>
          <button onClick={() => setSortKey('date')} style={sortBtnStyle(sortKey === 'date')}>Date &#x25BC;</button>
          <button onClick={() => setSortKey('symbol')} style={sortBtnStyle(sortKey === 'symbol')}>Symbol &#x25B2;</button>
        </div>
      </div>

      {/* Source filter chips + Stale filter chips */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        {/* Source chips with live counts */}
        <button onClick={() => setSourceFilter('all')} style={chipStyle(sourceFilter === 'all')}>
          All ({hasActiveFilters ? `${filtered.length} matching` : data.stats.total})
        </button>
        {sources.map(([src, cnt]) => {
          const matchCount = sourceCounts[src] || 0
          const label = hasActiveFilters ? `${src} (${matchCount} matching)` : `${src} (${cnt})`
          return (
            <button key={src} onClick={() => setSourceFilter(src)} style={chipStyle(sourceFilter === src, sourceColor(src))}>
              {label}
            </button>
          )
        })}

        <span style={{ width: 1, height: 16, background: 'var(--border)', margin: '0 4px' }} />

        {/* G. Stale filter chips */}
        <button onClick={() => setStaleFilter('all')} style={chipStyle(staleFilter === 'all')}>All Ages</button>
        <button onClick={() => setStaleFilter('active')} style={chipStyle(staleFilter === 'active', 'var(--green)')}>Active</button>
        <button onClick={() => setStaleFilter('stale')} style={chipStyle(staleFilter === 'stale', 'var(--amber)')}>Stale (&gt;90d)</button>
      </div>

      {/* Stats row */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        {sources.map(([src, cnt]) => (
          <div key={src} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', background: 'var(--bg2)', border: '1px solid var(--border-subtle)', borderRadius: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: 999, background: sourceColor(src) }} />
            <span style={{ fontSize: 10, color: 'var(--text2)' }}>{src}</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: sourceColor(src) }}>{cnt}</span>
          </div>
        ))}
      </div>

      {/* Whiteboard items */}
      <SectionHeader title="Active Intelligence" count={filtered.length} />
      <Card>
        <div style={{ overflow: 'auto', maxHeight: 600 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
            <thead>
              <tr style={{ background: 'var(--bg1)' }}>
                {['Symbol', 'Source', 'Title', 'Quality', 'Confidence', 'Days', 'Status', 'Added'].map(h => (
                  <th key={h} style={{ padding: '5px 8px', textAlign: 'left', color: 'var(--text3)', fontSize: 9, fontWeight: 600, borderBottom: '1px solid var(--border)', position: 'sticky', top: 0, background: 'var(--bg1)', zIndex: 1 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, limit).map(item => {
                const staleLevel = item.days_on_board > 180 ? 'very-stale' : item.days_on_board > 90 ? 'stale' : null
                const statusColor = item.status === 'active' ? 'var(--green)' : item.status === 'demoted' ? 'var(--amber)' : 'var(--text3)'
                return (
                  <tr key={item.id}>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text0)' }}>{item.symbol}</td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                      <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, color: sourceColor(item.source_type), background: `color-mix(in srgb, ${sourceColor(item.source_type)} 15%, transparent)` }}>{item.source_type}</span>
                    </td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text1)', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.summary}>{item.title}</td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: item.quality_score >= 80 ? 'var(--green)' : item.quality_score >= 60 ? 'var(--amber)' : 'var(--text2)', fontWeight: 600 }}>{item.quality_score}</td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text2)' }}>{item.confidence}%</td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: item.days_on_board > 7 ? 'var(--amber)' : 'var(--text3)' }}>{item.days_on_board}d</td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, color: statusColor, background: `color-mix(in srgb, ${statusColor} 15%, transparent)` }}>{item.hygiene_status || item.status}</span>
                      {/* G. Stale badges */}
                      {staleLevel === 'very-stale' && (
                        <Tooltip content={`${item.days_on_board} days on board - consider archiving`}>
                          <span style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 3, color: 'var(--red)', background: 'color-mix(in srgb, var(--red) 15%, transparent)' }}>VERY STALE</span>
                        </Tooltip>
                      )}
                      {staleLevel === 'stale' && (
                        <Tooltip content={`${item.days_on_board} days on board`}>
                          <span style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 3, color: 'var(--amber)', background: 'color-mix(in srgb, var(--amber) 15%, transparent)' }}>STALE</span>
                        </Tooltip>
                      )}
                    </td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text2)', fontSize: 9 }}>{timeAgo(item.created_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {filtered.length > limit && (
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            <button onClick={() => setLimit(l => l + 100)} style={{ fontSize: 9, padding: '4px 12px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg3)', color: 'var(--accent)', cursor: 'pointer' }}>Show more ({filtered.length - limit} remaining)</button>
          </div>
        )}
      </Card>
    </>
  )
}
