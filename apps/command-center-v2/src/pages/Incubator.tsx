import React, { useState, useEffect } from 'react'

const STATE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  ROLLED_ON:             { bg: '#422006', text: '#F59E0B', border: '#92400E' },
  STAYED_ACTIVE:         { bg: '#0F2235', text: '#60A5FA', border: '#1E3A5F' },
  IMPROVED:              { bg: '#052E16', text: '#10B981', border: '#065F46' },
  DEGRADED:              { bg: '#450A0A', text: '#EF4444', border: '#991B1B' },
  PROMOTED_TO_SIGNAL:    { bg: '#1E1B4B', text: '#818CF8', border: '#3730A3' },
  PROMOTED_TO_PROPOSAL:  { bg: '#1E1B4B', text: '#A78BFA', border: '#3730A3' },
  ROLLED_OFF:            { bg: '#1C1917', text: '#78716C', border: '#44403C' },
}

const EVENT_COLORS: Record<string, string> = {
  ROLLED_ON: '#F59E0B', STAYED_ACTIVE: '#60A5FA', IMPROVED: '#10B981',
  DEGRADED: '#EF4444', ROLLED_OFF: '#78716C', PROMOTED_TO_SIGNAL: '#818CF8',
}

type FilterState = 'ALL' | 'ACTIVE' | 'IMPROVING' | 'DEGRADED' | 'PROMOTED'

export default function Incubator() {
  const [items, setItems] = useState<any[]>([])
  const [events, setEvents] = useState<any[]>([])
  const [health, setHealth] = useState<any>({})
  const [filter, setFilter] = useState<FilterState>('ALL')
  const [minScore, setMinScore] = useState('')
  const [minDays, setMinDays] = useState('')
  const [stratFilter, setStratFilter] = useState('all')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch('/api/v2/incubator').then(r => r.json()),
      fetch('/api/v2/incubator-events').then(r => r.json()),
      fetch('/api/v2/incubator-health').then(r => r.json()),
    ]).then(([inc, ev, h]) => {
      setItems((inc.data || inc).universe || [])
      setEvents((ev.data || ev).events || [])
      setHealth((h.data || h))
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  const strategies = Array.from(new Set(items.map(i => i.strategy_id).filter(Boolean))).sort()

  const filtered = items.filter(item => {
    if (filter === 'ACTIVE' && item.status !== 'ACTIVE') return false
    if (filter === 'IMPROVING' && (item.score_delta || 0) <= 0) return false
    if (filter === 'DEGRADED' && (item.score_delta || 0) >= 0) return false
    if (filter === 'PROMOTED' && !item.promoted_to_signal_at) return false
    if (minScore && (item.latest_score || 0) < Number(minScore)) return false
    if (minDays && (item.days_active || 0) < Number(minDays)) return false
    if (stratFilter !== 'all' && item.strategy_id !== stratFilter) return false
    return true
  })

  const tabs: { key: FilterState; label: string; count: number }[] = [
    { key: 'ALL', label: 'All', count: items.length },
    { key: 'ACTIVE', label: 'Active', count: items.filter(i => i.status === 'ACTIVE').length },
    { key: 'IMPROVING', label: 'Improving', count: items.filter(i => (i.score_delta || 0) > 0).length },
    { key: 'DEGRADED', label: 'Degraded', count: items.filter(i => (i.score_delta || 0) < 0).length },
    { key: 'PROMOTED', label: 'Promoted', count: items.filter(i => !!i.promoted_to_signal_at).length },
  ]

  return (
    <div style={{ padding: 24, color: '#E2E8F0', maxWidth: 1600, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: '#F1F5F9', margin: 0 }}>INCUBATOR UNIVERSE</h1>
          <p style={{ color: '#64748B', fontSize: 12, margin: '4px 0 0' }}>
            {health.active || 0} active
            {health.today_events?.ROLLED_ON ? ` · ${health.today_events.ROLLED_ON} rolled on today` : ''}
            {health.today_events?.IMPROVED ? ` · ${health.today_events.IMPROVED} improved` : ''}
            {health.today_events?.DEGRADED ? ` · ${health.today_events.DEGRADED} degraded` : ''}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {health.last_weekly_build && (
            <span style={{ fontSize: 10, color: '#475569' }}>
              Last build: {new Date(health.last_weekly_build).toLocaleDateString()}
            </span>
          )}
          <span style={{ fontSize: 12, fontWeight: 700, color: '#60A5FA', background: '#0D1A2F', padding: '4px 12px', borderRadius: 6, border: '1px solid #1E3A5F' }}>
            {filtered.length} shown
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setFilter(t.key)}
            style={{
              padding: '8px 16px', borderRadius: 6, fontSize: 12, fontWeight: 700,
              cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.05em',
              background: filter === t.key ? '#1E3A5F' : '#0F172A',
              border: `1px solid ${filter === t.key ? '#2E86D4' : '#1E293B'}`,
              color: filter === t.key ? '#60A5FA' : '#64748B',
            }}>
            {t.label} <span style={{ fontSize: 10, opacity: 0.7 }}>({t.count})</span>
          </button>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, padding: '8px 16px', background: '#0D1626', border: '1px solid #1E293B', borderRadius: 8 }}>
        <span style={{ fontSize: 10, color: '#64748B', fontWeight: 600 }}>FILTERS:</span>
        <label style={{ fontSize: 11, color: '#94A3B8' }}>Score:
          <input value={minScore} onChange={e => setMinScore(e.target.value)} placeholder="min"
            style={{ width: 40, marginLeft: 4, background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0', padding: '4px 6px', borderRadius: 4, fontSize: 11 }} />
        </label>
        <label style={{ fontSize: 11, color: '#94A3B8' }}>Days:
          <input value={minDays} onChange={e => setMinDays(e.target.value)} placeholder="min"
            style={{ width: 40, marginLeft: 4, background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0', padding: '4px 6px', borderRadius: 4, fontSize: 11 }} />
        </label>
        <label style={{ fontSize: 11, color: '#94A3B8' }}>Strategy:
          <select value={stratFilter} onChange={e => setStratFilter(e.target.value)}
            style={{ marginLeft: 4, background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0', padding: '4px 6px', borderRadius: 4, fontSize: 11 }}>
            <option value="all">All</option>
            {strategies.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <button onClick={() => { setMinScore(''); setMinDays(''); setStratFilter('all'); setFilter('ALL') }}
          style={{ fontSize: 10, color: '#64748B', background: 'none', border: '1px solid #334155', padding: '3px 10px', borderRadius: 4, cursor: 'pointer' }}>
          Clear
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ color: '#64748B', fontSize: 13, padding: 20 }}>Loading incubator...</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, marginBottom: 24 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #1E293B' }}>
              {['Symbol', 'Strategy', 'Days', 'Baseline', 'Latest', 'Best', 'Delta', 'State', 'RVOL', 'Catalyst'].map(h =>
                <th key={h} style={{ textAlign: 'left', padding: '8px 6px', color: '#475569', fontSize: 10, fontFamily: 'monospace', letterSpacing: '0.05em' }}>{h}</th>
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.map((item, i) => {
              const sc = STATE_COLORS[item.lifecycle_state] || STATE_COLORS.STAYED_ACTIVE
              const delta = item.score_delta || 0
              return (
                <tr key={item.id} style={{ borderBottom: '1px solid #0F172A', background: i % 2 === 0 ? 'transparent' : '#08101E' }}>
                  <td style={{ padding: '7px 6px' }}>
                    <a href={`/v2/watchlist/${item.symbol}`} style={{ fontWeight: 700, color: '#60A5FA', fontFamily: 'monospace', textDecoration: 'none' }}>{item.symbol}</a>
                  </td>
                  <td style={{ padding: '7px 6px', fontSize: 10, color: '#94A3B8' }}>{item.strategy_id}</td>
                  <td style={{ padding: '7px 6px', fontFamily: 'monospace', color: '#E2E8F0' }}>{item.days_active || 0}d</td>
                  <td style={{ padding: '7px 6px', fontFamily: 'monospace', color: '#94A3B8' }}>{item.baseline_score?.toFixed(0) ?? '-'}</td>
                  <td style={{ padding: '7px 6px', fontFamily: 'monospace', fontWeight: 600, color: '#E2E8F0' }}>{item.latest_score?.toFixed(0) ?? '-'}</td>
                  <td style={{ padding: '7px 6px', fontFamily: 'monospace', color: '#4ADE80' }}>{item.best_score?.toFixed(0) ?? '-'}</td>
                  <td style={{ padding: '7px 6px', fontFamily: 'monospace', fontWeight: 600, color: delta > 0 ? '#4ADE80' : delta < 0 ? '#F87171' : '#475569' }}>
                    {delta > 0 ? '+' : ''}{delta.toFixed(0)}
                  </td>
                  <td style={{ padding: '7px 6px' }}>
                    <span style={{
                      fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3,
                      background: sc.bg, color: sc.text, border: `1px solid ${sc.border}`,
                      fontFamily: 'monospace',
                    }}>
                      {item.lifecycle_state?.replace(/_/g, ' ') || 'ACTIVE'}
                    </span>
                  </td>
                  <td style={{ padding: '7px 6px', fontFamily: 'monospace', color: (item.rvol_latest || 0) >= 5 ? '#4ADE80' : '#94A3B8' }}>
                    {(item.rvol_latest || 0).toFixed(1)}x
                  </td>
                  <td style={{ padding: '7px 6px', fontSize: 10, color: '#94A3B8', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.catalyst_verified && <span style={{ color: '#4ADE80', marginRight: 4 }}>&#10003;</span>}
                    {item.catalyst ? item.catalyst.substring(0, 60) : '-'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {/* Events log */}
      {events.length > 0 && (
        <div>
          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#94A3B8', marginBottom: 12, letterSpacing: '0.05em' }}>RECENT EVENTS</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {events.slice(0, 20).map(ev => (
              <div key={ev.id} style={{
                display: 'flex', gap: 12, alignItems: 'center', padding: '6px 12px',
                background: '#0D1626', borderRadius: 4, fontSize: 11,
              }}>
                <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#60A5FA', minWidth: 50 }}>{ev.symbol}</span>
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3, minWidth: 80, textAlign: 'center',
                  color: EVENT_COLORS[ev.event_type] || '#94A3B8',
                  background: `${EVENT_COLORS[ev.event_type] || '#94A3B8'}15`,
                }}>
                  {ev.event_type?.replace(/_/g, ' ')}
                </span>
                {ev.old_score != null && ev.new_score != null && (
                  <span style={{ fontFamily: 'monospace', color: '#94A3B8', fontSize: 10 }}>
                    {Number(ev.old_score).toFixed(0)} → {Number(ev.new_score).toFixed(0)}
                  </span>
                )}
                <span style={{ fontSize: 10, color: '#475569', marginLeft: 'auto' }}>
                  {ev.created_at ? new Date(ev.created_at).toLocaleString() : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
