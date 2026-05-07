import { useState, useEffect } from 'react'

interface Entity {
  entity_id: string
  entity_type: 'market' | 'subject'
  entity_subtype: string | null
  display_name: string | null
  intelligence_score: number | null
  intelligence_grade: string | null
  iris_freshness: string | null
  iris_coverage: string | null
  iris_notes: string | null
  iris_action_needed: string | null
  signal_count: number | null
  pipeline_sources: string[] | null
  current_price: number | null
  rvol: number | null
  confluence_tier: string | null
  confluence_score: number | null
  screener_decision: string | null
  screener_score: number | null
  social_mentions: number | null
  last_enriched: string | null
  last_agent_analysis: string | null
  last_agent_verdict: string | null
  rag_item_count: number | null
  john_risk_level: string | null
  john_impact: string | null
  john_action_needed: string | null
  thresholds_updated: string | null
  strategy_type: string | null
  sector: string | null
}

interface Stats {
  total: number
  market: number
  subject: number
  critical: number
  stale: number
  thin: number
  avg_score: number | null
}

const FRESHNESS_COLOR: Record<string, string> = {
  FRESH: '#00ff88',
  AGING: '#ffcc00',
  STALE: '#ff8800',
  CRITICAL: '#ff3344',
  UNKNOWN: '#555',
}

const RISK_COLOR: Record<string, string> = {
  critical: '#ff3344',
  high: '#ff8800',
  medium: '#ffcc00',
  low: '#00ff88',
}

export default function IntelligenceEntities() {
  const [entities, setEntities] = useState<Entity[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'market' | 'subject'>('all')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Entity | null>(null)

  useEffect(() => {
    fetch('/api/v2/intelligence-entities')
      .then(r => r.json())
      .then(d => {
        if (d.ok && d.data) {
          setEntities(d.data.entities || [])
          setStats(d.data.stats || null)
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = entities.filter(e => {
    if (filter !== 'all' && e.entity_type !== filter) return false
    if (search && !e.entity_id.toLowerCase().includes(search.toLowerCase()) &&
        !(e.display_name || '').toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const subjects = filtered.filter(e => e.entity_type === 'subject')
  const markets = filtered.filter(e => e.entity_type === 'market')

  if (loading) return <div style={{ padding: 40, color: '#ccc' }}>Loading intelligence entities...</div>

  return (
    <div style={{ padding: '20px 30px', color: '#e0e0e0', fontFamily: 'monospace' }}>
      <h1 style={{ margin: 0, fontSize: 22, color: '#fff' }}>INTELLIGENCE ENTITIES</h1>
      <p style={{ color: '#888', margin: '4px 0 16px' }}>Canonical entity registry — all pipelines write, all agents read</p>

      {/* Stats tiles */}
      {stats && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
          <Tile label="Total" value={stats.total} />
          <Tile label="Market" value={stats.market} color="#4499ff" />
          <Tile label="Subject" value={stats.subject} color="#aa55ff" />
          <Tile label="Critical" value={stats.critical} color="#ff3344" />
          <Tile label="Stale" value={stats.stale} color="#ff8800" />
          <Tile label="Avg Score" value={stats.avg_score ?? 0} color="#00ff88" />
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
        <select value={filter} onChange={e => setFilter(e.target.value as any)}
          style={{ background: '#1a1a2e', color: '#ccc', border: '1px solid #333', padding: '6px 10px', borderRadius: 4 }}>
          <option value="all">All Types</option>
          <option value="market">Market</option>
          <option value="subject">Subject</option>
        </select>
        <input placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)}
          style={{ background: '#1a1a2e', color: '#ccc', border: '1px solid #333', padding: '6px 10px', borderRadius: 4, width: 200 }} />
        <span style={{ color: '#666', fontSize: 12 }}>{filtered.length} entities shown</span>
      </div>

      {/* Subject entities section */}
      {subjects.length > 0 && (
        <>
          <h2 style={{ fontSize: 14, color: '#aa55ff', margin: '20px 0 8px', textTransform: 'uppercase', letterSpacing: 1 }}>
            Subject Entities ({subjects.length})
          </h2>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #333' }}>
                  <th style={th}>Entity</th>
                  <th style={th}>Risk</th>
                  <th style={th}>John Impact</th>
                  <th style={th}>Fresh</th>
                  <th style={th}>Score</th>
                  <th style={th}>RAG</th>
                </tr>
              </thead>
              <tbody>
                {subjects.map(e => (
                  <tr key={e.entity_id} onClick={() => setSelected(e)}
                    style={{ borderBottom: '1px solid #222', cursor: 'pointer' }}
                    onMouseEnter={ev => (ev.currentTarget.style.background = '#1a1a2e')}
                    onMouseLeave={ev => (ev.currentTarget.style.background = 'transparent')}>
                    <td style={td}><strong>{e.entity_id}</strong></td>
                    <td style={td}>
                      <span style={{ color: RISK_COLOR[e.john_risk_level || ''] || '#888' }}>
                        {(e.john_risk_level || '?').toUpperCase()}
                      </span>
                    </td>
                    <td style={{ ...td, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {e.john_impact || '—'}
                    </td>
                    <td style={td}>
                      <FreshBadge value={e.iris_freshness} />
                    </td>
                    <td style={td}>
                      {e.intelligence_score ?? '—'} ({e.intelligence_grade || '?'})
                    </td>
                    <td style={td}>{e.rag_item_count || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Market entities section */}
      {markets.length > 0 && (
        <>
          <h2 style={{ fontSize: 14, color: '#4499ff', margin: '24px 0 8px', textTransform: 'uppercase', letterSpacing: 1 }}>
            Market Entities ({markets.length})
          </h2>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #333' }}>
                  <th style={th}>Symbol</th>
                  <th style={th}>Price</th>
                  <th style={th}>Score</th>
                  <th style={th}>Confluence</th>
                  <th style={th}>Sources</th>
                  <th style={th}>Fresh</th>
                  <th style={th}>Grade</th>
                  <th style={th}>RAG</th>
                </tr>
              </thead>
              <tbody>
                {markets.map(e => (
                  <tr key={e.entity_id} onClick={() => setSelected(e)}
                    style={{ borderBottom: '1px solid #222', cursor: 'pointer' }}
                    onMouseEnter={ev => (ev.currentTarget.style.background = '#1a1a2e')}
                    onMouseLeave={ev => (ev.currentTarget.style.background = 'transparent')}>
                    <td style={td}><strong>{e.entity_id}</strong></td>
                    <td style={td}>{e.current_price ? `$${Number(e.current_price).toFixed(2)}` : '—'}</td>
                    <td style={td}>
                      {e.screener_decision && <span>{e.screener_decision} ({e.screener_score})</span>}
                    </td>
                    <td style={td}>
                      <span style={{ color: e.confluence_tier === 'STRONG' ? '#00ff88' : e.confluence_tier === 'MODERATE' ? '#ffcc00' : '#888' }}>
                        {e.confluence_tier || '—'}
                      </span>
                    </td>
                    <td style={td}>
                      {(e.pipeline_sources || []).join(', ') || '—'}
                    </td>
                    <td style={td}>
                      <FreshBadge value={e.iris_freshness} />
                    </td>
                    <td style={td}>
                      {e.intelligence_score ?? '—'} ({e.intelligence_grade || '?'})
                    </td>
                    <td style={td}>{e.rag_item_count || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Detail panel */}
      {selected && (
        <div style={{ position: 'fixed', top: 0, right: 0, width: 420, height: '100vh',
          background: '#0d0d1a', borderLeft: '1px solid #333', padding: 20, overflowY: 'auto', zIndex: 100 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, color: '#fff' }}>{selected.entity_id}</h3>
            <button onClick={() => setSelected(null)}
              style={{ background: 'none', border: 'none', color: '#888', fontSize: 20, cursor: 'pointer' }}>x</button>
          </div>
          <p style={{ color: '#888', fontSize: 12 }}>{selected.display_name}</p>
          <p style={{ fontSize: 12 }}>
            Type: {selected.entity_type} / {selected.entity_subtype} | Grade: {selected.intelligence_grade} ({selected.intelligence_score}/100)
          </p>
          <p style={{ fontSize: 12 }}>Freshness: <FreshBadge value={selected.iris_freshness} /> | Coverage: {selected.iris_coverage || '?'}</p>

          {selected.entity_type === 'subject' && (
            <div style={{ marginTop: 12 }}>
              <Detail label="Risk Level" value={(selected.john_risk_level || '').toUpperCase()} />
              <Detail label="John Impact" value={selected.john_impact} />
              <Detail label="Action Needed" value={selected.john_action_needed} />
              <Detail label="Thresholds Updated" value={selected.thresholds_updated ? new Date(selected.thresholds_updated).toLocaleDateString() : 'never'} />
            </div>
          )}

          {selected.entity_type === 'market' && (
            <div style={{ marginTop: 12 }}>
              <Detail label="Price" value={selected.current_price ? `$${Number(selected.current_price).toFixed(2)}` : '—'} />
              <Detail label="RVOL" value={selected.rvol ? `${Number(selected.rvol).toFixed(1)}x` : '—'} />
              <Detail label="Confluence" value={`${selected.confluence_tier || 'NONE'} (${selected.confluence_score || 0})`} />
              <Detail label="Screener" value={selected.screener_decision ? `${selected.screener_decision} (${selected.screener_score})` : '—'} />
              <Detail label="Social" value={selected.social_mentions ? `${selected.social_mentions} mentions` : '—'} />
              <Detail label="Sector" value={selected.sector || '—'} />
              <Detail label="Strategy" value={selected.strategy_type || '—'} />
            </div>
          )}

          <div style={{ marginTop: 12 }}>
            <Detail label="Last Agent" value={selected.last_agent_verdict} />
            <Detail label="RAG Items" value={String(selected.rag_item_count || 0)} />
            <Detail label="Pipelines" value={(selected.pipeline_sources || []).join(', ') || 'none'} />
            <Detail label="Signals Today" value={String(selected.signal_count || 0)} />
          </div>

          {selected.iris_notes && (
            <div style={{ marginTop: 12, padding: 8, background: '#1a1a2e', borderRadius: 4, fontSize: 11, color: '#ffaa00' }}>
              Iris: {selected.iris_notes}
            </div>
          )}
          {selected.iris_action_needed && (
            <div style={{ marginTop: 8, padding: 8, background: '#2a1a1a', borderRadius: 4, fontSize: 11, color: '#ff6644' }}>
              Action: {selected.iris_action_needed}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Tile({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div style={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 6, padding: '8px 14px', minWidth: 80 }}>
      <div style={{ fontSize: 11, color: '#888', textTransform: 'uppercase' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: color || '#fff' }}>{value}</div>
    </div>
  )
}

function FreshBadge({ value }: { value: string | null }) {
  const v = value || 'UNKNOWN'
  return <span style={{ color: FRESHNESS_COLOR[v] || '#555', fontSize: 12 }}>{v}</span>
}

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null
  return (
    <div style={{ marginBottom: 6, fontSize: 12 }}>
      <span style={{ color: '#888' }}>{label}: </span>
      <span style={{ color: '#ccc' }}>{value}</span>
    </div>
  )
}

const th: React.CSSProperties = { textAlign: 'left', padding: '6px 10px', color: '#888', fontWeight: 500, fontSize: 11, textTransform: 'uppercase' }
const td: React.CSSProperties = { padding: '6px 10px', color: '#ccc' }
