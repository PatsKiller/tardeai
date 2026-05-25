# Source Export: Prospects.tsx

- **Original path:** apps/command-center-v2/src/pages/Prospects.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** b2d6fd13148ad576ddfbc9d5af777fa28f3a3727de868c8ef36df2b8bbdd8de4
- **File size:** 25499 bytes
- **Exists:** YES

```tsx
import React, { useState, useEffect, useCallback } from 'react'

type ProspectType = 'scalp' | 'swing' | 'income' | 'position' | 'all'

const PRICE_DEFAULTS: Record<ProspectType, {min: string, max: string}> = {
  scalp:    { min: '2',  max: '50'  },
  swing:    { min: '10', max: '200' },
  income:   { min: '',   max: ''    },
  position: { min: '10', max: '500' },
  all:      { min: '',   max: ''    },
}

const SOURCE_COLORS: Record<string, string> = {
  screener:  '#3B82F6',
  social:    '#F97316',
  agent:     '#22C55E',
  watchlist: '#EAB308',
}

const TIER_COLORS: Record<string, {text: string, bg: string}> = {
  STRONG:   { text: '#10B981', bg: '#10B98120' },
  MODERATE: { text: '#F59E0B', bg: '#F59E0B20' },
  WEAK:     { text: '#94A3B8', bg: '#94A3B820' },
}

const DECISION_COLORS: Record<string, {text: string, bg: string}> = {
  GO:    { text: '#4ADE80', bg: '#0D1F0D' },
  WAIT:  { text: '#F59E0B', bg: '#1F1800' },
  AVOID: { text: '#F87171', bg: '#1F0D0D' },
}

const fmt$ = (v: number | null | undefined) => v != null ? `$${v.toFixed(2)}` : '—'

interface Prospect {
  symbol: string
  score: number
  decision: string
  price: number
  rvol: number
  float_m: number
  gap_pct: number
  change_pct: number
  sector: string
  industry: string
  social_reddit: number
  social_stocktwits: number
  mention_count: number
  catalyst: string
  catalyst_verified: boolean
  scanned_at: string
  source: string
  screener_label: string
  pipeline_sources: string[]
  strategy_type: string
  ideal_entry: number
  stop_loss: number
  target_price: number
  risk_reward: number
  in_portfolio: boolean
  in_ai_watchlist: boolean
  confluence_tier: string
  confluence_score: number
  strategy_badges: string[]
  conf_stop: number
  conf_target: number
  entry_quality: string
  atr: number
  proposal_action: string
  proposal_agent: string
  proposal_confidence: number
}

export default function Prospects() {
  const [prospects, setProspects] = useState<Prospect[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<ProspectType>('scalp')
  const [minPrice, setMinPrice] = useState(PRICE_DEFAULTS.scalp.min)
  const [maxPrice, setMaxPrice] = useState(PRICE_DEFAULTS.scalp.max)
  const [minScore, setMinScore] = useState('')
  const [selected, setSelected] = useState<Prospect | null>(null)
  const [addedSymbols, setAddedSymbols] = useState<Set<string>>(new Set())
  const [incubatorMap, setIncubatorMap] = useState<Record<string, any>>({})
  const [runHealth, setRunHealth] = useState<{
    run_label?: string; latest_scan?: string; is_stale?: boolean; stale_reason?: string;
    symbols_scanned?: number; go_count?: number; wait_count?: number;
    run_health_status?: string; data_age_minutes?: number;
  }>({})

  const fetchProspects = useCallback(async () => {
    setLoading(true)
    const params = new URLSearchParams({ type: activeTab })
    if (minPrice) params.append('min_price', minPrice)
    if (maxPrice) params.append('max_price', maxPrice)
    if (minScore) params.append('min_score', minScore)
    try {
      const res = await fetch(`/api/v2/prospects?${params}`)
      const data = await res.json()
      if (data.ok) {
        setProspects(data.data || [])
        setRunHealth({
          run_label: data.run_label, latest_scan: data.latest_scan || data.last_scan,
          is_stale: data.is_stale, stale_reason: data.stale_reason,
          symbols_scanned: data.symbols_scanned, go_count: data.go_count,
          wait_count: data.wait_count, run_health_status: data.run_health_status,
          data_age_minutes: data.data_age_minutes,
        })
      }
    } catch { /* ignore */ }
    setLoading(false)
  }, [activeTab, minPrice, maxPrice, minScore])

  useEffect(() => { fetchProspects() }, [fetchProspects])

  useEffect(() => {
    fetch('/api/v2/incubator').then(r => r.json()).then(d => {
      const items = (d.data || d).universe || []
      const map: Record<string, any> = {}
      items.forEach((i: any) => { map[i.symbol] = i })
      setIncubatorMap(map)
    }).catch(() => {})
  }, [])

  const switchTab = (tab: ProspectType) => {
    setActiveTab(tab)
    setMinPrice(PRICE_DEFAULTS[tab].min)
    setMaxPrice(PRICE_DEFAULTS[tab].max)
    setSelected(null)
  }

  const addToWatchlist = async (symbol: string, strategyType: string) => {
    const res = await fetch('/api/v2/prospects/add-to-watchlist', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, strategy_type: strategyType, source: 'prospects' }),
    })
    const data = await res.json()
    if (data.ok) setAddedSymbols(prev => new Set(prev).add(symbol))
  }

  const tabCounts = {
    scalp: prospects.length,
    swing: 0, income: 0, position: 0, all: 0,
  }

  const lastScan = prospects[0]?.scanned_at ? new Date(prospects[0].scanned_at).toLocaleString() : '—'

  return (
    <div style={{ padding: '24px', color: '#E2E8F0', maxWidth: '1600px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '22px', fontWeight: 800, color: '#F1F5F9', margin: 0 }}>PROSPECTS</h1>
          <p style={{ color: '#64748B', fontSize: '12px', margin: '4px 0 0' }}>Pre-trade candidate discovery</p>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <span style={{
            fontSize: '10px', padding: '4px 10px', borderRadius: '4px',
            color: runHealth.is_stale ? '#FBBF24' : runHealth.run_health_status === 'RUN_HEALTHY' ? '#4ADE80' : '#94A3B8',
            background: runHealth.is_stale ? '#1F1800' : runHealth.run_health_status === 'RUN_HEALTHY' ? '#0D1F0D' : '#0F172A',
            border: `1px solid ${runHealth.is_stale ? '#92400E' : runHealth.run_health_status === 'RUN_HEALTHY' ? '#166534' : '#1E293B'}`,
          }}>
            {runHealth.run_label ? `Run ${runHealth.run_label}` : 'No run'} {' '}
            {runHealth.symbols_scanned != null ? `${runHealth.symbols_scanned} symbols` : ''} {' '}
            {runHealth.data_age_minutes != null ? `${runHealth.data_age_minutes}m ago` : ''} {' '}
            {runHealth.run_health_status || (runHealth.is_stale ? 'STALE' : '')}
          </span>
          <span style={{ fontSize: '12px', fontWeight: 700, color: '#60A5FA', background: '#0D1A2F', padding: '4px 12px', borderRadius: '6px', border: '1px solid #1E3A5F' }}>
            {prospects.length} results
          </span>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: '4px', marginBottom: '16px' }}>
        {(['scalp', 'swing', 'income', 'position', 'all'] as ProspectType[]).map(tab => (
          <button key={tab} onClick={() => switchTab(tab)}
            style={{
              padding: '8px 20px', borderRadius: '6px', fontSize: '12px', fontWeight: 700,
              cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.05em',
              background: activeTab === tab ? '#1E3A5F' : '#0F172A',
              border: `1px solid ${activeTab === tab ? '#2E86D4' : '#1E293B'}`,
              color: activeTab === tab ? '#60A5FA' : '#64748B',
            }}>
            {tab}
          </button>
        ))}
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '16px', padding: '10px 16px', background: '#0D1626', border: '1px solid #1E293B', borderRadius: '8px' }}>
        <span style={{ fontSize: '10px', color: '#64748B', fontWeight: 600 }}>FILTERS:</span>
        <label style={{ fontSize: '11px', color: '#94A3B8' }}>Price:
          <input value={minPrice} onChange={e => setMinPrice(e.target.value)} placeholder="min"
            style={{ width: '50px', marginLeft: '4px', background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0', padding: '4px 6px', borderRadius: '4px', fontSize: '11px' }} />
          <span style={{ margin: '0 4px', color: '#475569' }}>–</span>
          <input value={maxPrice} onChange={e => setMaxPrice(e.target.value)} placeholder="max"
            style={{ width: '50px', background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0', padding: '4px 6px', borderRadius: '4px', fontSize: '11px' }} />
        </label>
        <label style={{ fontSize: '11px', color: '#94A3B8' }}>Score:
          <input value={minScore} onChange={e => setMinScore(e.target.value)} placeholder="min"
            style={{ width: '40px', marginLeft: '4px', background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0', padding: '4px 6px', borderRadius: '4px', fontSize: '11px' }} />
          <span style={{ color: '#475569', marginLeft: '2px' }}>+</span>
        </label>
        <button onClick={() => { setMinPrice(''); setMaxPrice(''); setMinScore('') }}
          style={{ fontSize: '10px', color: '#64748B', background: 'none', border: '1px solid #334155', padding: '3px 10px', borderRadius: '4px', cursor: 'pointer' }}>
          Clear
        </button>
        {/* Source legend */}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '10px', fontSize: '10px', color: '#64748B' }}>
          {Object.entries(SOURCE_COLORS).map(([src, color]) => (
            <span key={src} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: color, display: 'inline-block' }} />
              {src}
            </span>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: '16px' }}>
        {/* Results table */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {loading ? (
            <div style={{ color: '#64748B', fontSize: '13px', padding: '20px' }}>Loading prospects...</div>
          ) : prospects.length === 0 ? (
            <div style={{ color: '#64748B', fontSize: '13px', padding: '20px', textAlign: 'center', background: '#0D1626', borderRadius: '8px', border: '1px solid #1E293B' }}>
              No prospects match current filters. Try widening price range or switching tabs.
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1E293B' }}>
                  {['Symbol', 'Price', 'Chg%', 'Score', 'RVOL', 'Float', 'Confluence', 'Sources', ''].map(h =>
                    <th key={h} style={{ textAlign: 'left', padding: '8px', color: '#475569', fontSize: '10px', fontFamily: 'monospace', letterSpacing: '0.05em' }}>{h}</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {prospects.map((p, i) => {
                  const dc = DECISION_COLORS[p.decision] || { text: '#94A3B8', bg: '#1E293B' }
                  const isSelected = selected?.symbol === p.symbol
                  return (
                    <tr key={`${p.symbol}-${i}`}
                      onClick={() => setSelected(isSelected ? null : p)}
                      style={{
                        borderBottom: '1px solid #0F172A', cursor: 'pointer',
                        background: isSelected ? '#0D1A2F' : i % 2 === 0 ? 'transparent' : '#08101E',
                      }}>
                      <td style={{ padding: '8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ fontWeight: 700, color: '#60A5FA', fontFamily: 'monospace' }}>{p.symbol}</span>
                          <span style={{ fontSize: '9px', fontWeight: 700, padding: '1px 6px', borderRadius: '3px', background: dc.bg, color: dc.text }}>{p.decision}</span>
                          {p.in_portfolio && <span style={{ fontSize: '8px', color: '#4ADE80', background: '#0D1F0D', padding: '1px 4px', borderRadius: '2px' }}>HELD</span>}
                          {incubatorMap[p.symbol] && (() => {
                            const inc = incubatorMap[p.symbol]
                            const st = inc.lifecycle_state || 'STAYED_ACTIVE'
                            const stColors: Record<string, { bg: string; text: string }> = {
                              ROLLED_ON: { bg: '#422006', text: '#F59E0B' },
                              IMPROVED: { bg: '#052E16', text: '#10B981' },
                              DEGRADED: { bg: '#450A0A', text: '#EF4444' },
                              STAYED_ACTIVE: { bg: '#0F2235', text: '#60A5FA' },
                            }
                            const c = stColors[st] || stColors.STAYED_ACTIVE
                            return (
                              <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: c.bg, color: c.text, fontFamily: 'monospace' }}>
                                {st === 'ROLLED_ON' ? 'NEW' : st === 'STAYED_ACTIVE' ? 'TRACK' : st.replace(/_/g, ' ')}
                                {(inc.days_active || 0) > 0 ? ` ${inc.days_active}d` : ''}
                              </span>
                            )
                          })()}
                        </div>
                      </td>
                      <td style={{ padding: '8px', fontFamily: 'monospace', color: '#E2E8F0' }}>${p.price?.toFixed(2)}</td>
                      <td style={{ padding: '8px', fontFamily: 'monospace', fontWeight: 600, color: (p.change_pct || 0) >= 0 ? '#4ADE80' : '#F87171' }}>
                        {(p.change_pct || 0) >= 0 ? '+' : ''}{(p.change_pct || 0).toFixed(1)}%
                      </td>
                      <td style={{ padding: '8px' }}>
                        <span style={{ fontWeight: 700, fontSize: '13px', color: p.score >= 40 ? '#4ADE80' : p.score >= 30 ? '#F59E0B' : '#94A3B8' }}>
                          {p.score}
                        </span>
                      </td>
                      <td style={{ padding: '8px', fontFamily: 'monospace', color: (p.rvol || 0) >= 3 ? '#4ADE80' : '#94A3B8' }}>
                        {(p.rvol || 0).toFixed(1)}x
                      </td>
                      <td style={{ padding: '8px', fontFamily: 'monospace', color: '#94A3B8', fontSize: '11px' }}>
                        {p.float_m ? `${p.float_m.toFixed(0)}M` : '—'}
                      </td>
                      <td style={{ padding: '8px' }}>
                        {p.confluence_tier && p.confluence_tier !== 'NONE' ? (
                          <span style={{
                            fontSize: '9px', fontWeight: 700, padding: '2px 8px', borderRadius: '4px',
                            background: (TIER_COLORS[p.confluence_tier] || TIER_COLORS.WEAK).bg,
                            color: (TIER_COLORS[p.confluence_tier] || TIER_COLORS.WEAK).text,
                          }}>
                            {p.confluence_tier} {p.confluence_score || ''}
                          </span>
                        ) : <span style={{ color: '#334155', fontSize: '10px' }}>—</span>}
                      </td>
                      <td style={{ padding: '8px' }}>
                        <div style={{ display: 'flex', gap: '3px', alignItems: 'center' }}>
                          {(p.pipeline_sources || []).map(src => (
                            <div key={src} title={src} style={{
                              width: 8, height: 8, borderRadius: '50%',
                              backgroundColor: SOURCE_COLORS[src] || '#475569',
                            }} />
                          ))}
                        </div>
                      </td>
                      <td style={{ padding: '8px' }}>
                        {p.catalyst && (
                          <span title={p.catalyst} style={{ fontSize: '9px', color: p.catalyst_verified ? '#4ADE80' : '#F59E0B', background: p.catalyst_verified ? '#0D1F0D' : '#1F1800', padding: '1px 6px', borderRadius: '3px' }}>
                            CAT
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Side panel */}
        {selected && (
          <div style={{ width: '340px', flexShrink: 0, background: '#0D1626', border: '1px solid #1E293B', borderRadius: '8px', padding: '20px', alignSelf: 'flex-start', position: 'sticky', top: '80px' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <div>
                <span style={{ fontSize: '20px', fontWeight: 800, color: '#F1F5F9' }}>{selected.symbol}</span>
                <span style={{ fontSize: '11px', marginLeft: '8px', padding: '2px 8px', borderRadius: '4px',
                  background: (DECISION_COLORS[selected.decision] || {bg:'#1E293B'}).bg,
                  color: (DECISION_COLORS[selected.decision] || {text:'#94A3B8'}).text,
                  fontWeight: 700 }}>{selected.decision}</span>
              </div>
              <button onClick={() => setSelected(null)} style={{ background: 'none', border: '1px solid #334155', color: '#94A3B8', width: '24px', height: '24px', borderRadius: '4px', cursor: 'pointer', fontSize: '14px' }}>×</button>
            </div>
            <div style={{ fontSize: '11px', color: '#64748B', marginBottom: '16px' }}>
              {selected.sector} · Score {selected.score}/55 · RVOL {(selected.rvol || 0).toFixed(1)}x
            </div>

            {/* Trade Setup */}
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '10px', color: '#64748B', letterSpacing: '0.1em', fontWeight: 600, marginBottom: '8px' }}>TRADE SETUP</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
                <div><span style={{ color: '#64748B' }}>Entry: </span><span style={{ color: '#E2E8F0', fontWeight: 600 }}>{fmt$(selected.ideal_entry || selected.price)}</span></div>
                <div><span style={{ color: '#64748B' }}>Stop: </span><span style={{ color: '#F87171', fontWeight: 600 }}>{(() => {
                  const entry = selected.ideal_entry || selected.price || 0
                  const stop = selected.stop_loss || selected.conf_stop
                  if (stop && stop >= entry) return <><span style={{ color: '#F59E0B' }}>{fmt$(stop)} (inverted)</span></>
                  return fmt$(stop)
                })()}</span></div>
                <div><span style={{ color: '#64748B' }}>Target: </span><span style={{ color: '#4ADE80', fontWeight: 600 }}>{fmt$(selected.target_price || selected.conf_target)}</span></div>
                <div><span style={{ color: '#64748B' }}>R:R: </span><span style={{ color: '#E2E8F0', fontWeight: 600 }}>{selected.risk_reward ? `${selected.risk_reward.toFixed(1)}:1` : '—'}</span></div>
              </div>
            </div>

            {/* Confluence */}
            {selected.confluence_tier && (
              <div style={{ marginBottom: '16px' }}>
                <div style={{ fontSize: '10px', color: '#64748B', letterSpacing: '0.1em', fontWeight: 600, marginBottom: '8px' }}>CONFLUENCE</div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '6px' }}>
                  <span style={{
                    fontSize: '11px', fontWeight: 700, padding: '3px 10px', borderRadius: '4px',
                    background: (TIER_COLORS[selected.confluence_tier] || TIER_COLORS.WEAK).bg,
                    color: (TIER_COLORS[selected.confluence_tier] || TIER_COLORS.WEAK).text,
                  }}>{selected.confluence_tier}</span>
                  <span style={{ fontSize: '12px', color: '#E2E8F0', fontWeight: 600 }}>{selected.confluence_score}</span>
                  {selected.entry_quality && <span style={{ fontSize: '10px', color: '#94A3B8' }}>({selected.entry_quality})</span>}
                </div>
                {(selected.strategy_badges || []).length > 0 && (
                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                    {selected.strategy_badges.map(b => (
                      <span key={b} style={{ fontSize: '9px', padding: '2px 6px', borderRadius: '3px', background: '#1E293B', color: '#94A3B8' }}>{b}</span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Pipeline Sources */}
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '10px', color: '#64748B', letterSpacing: '0.1em', fontWeight: 600, marginBottom: '8px' }}>PIPELINE SOURCES</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11px' }}>
                {(selected.pipeline_sources || []).map(src => (
                  <div key={src} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: SOURCE_COLORS[src] || '#475569' }} />
                    <span style={{ color: '#E2E8F0', textTransform: 'capitalize' }}>{src}</span>
                    {src === 'social' && selected.mention_count > 0 && (
                      <span style={{ color: '#64748B' }}>
                        ({selected.social_reddit || 0} reddit, {selected.social_stocktwits || 0} stocktwits)
                      </span>
                    )}
                    {src === 'agent' && selected.proposal_agent && (
                      <span style={{ color: '#64748B' }}>by {selected.proposal_agent} ({selected.proposal_confidence}%)</span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Incubator Track Record */}
            {incubatorMap[selected.symbol] && (() => {
              const inc = incubatorMap[selected.symbol]
              return (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 10, color: '#64748B', letterSpacing: '0.1em', fontWeight: 600, marginBottom: 8 }}>INCUBATOR</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6 }}>
                    {[
                      { label: 'Baseline', val: inc.baseline_score?.toFixed(0) || '-' },
                      { label: 'Latest', val: inc.latest_score?.toFixed(0) || '-' },
                      { label: 'Best', val: inc.best_score?.toFixed(0) || '-' },
                      { label: 'Days', val: inc.days_active || 0 },
                      { label: 'Delta', val: (inc.score_delta || 0) >= 0 ? `+${(inc.score_delta || 0).toFixed(0)}` : (inc.score_delta || 0).toFixed(0) },
                      { label: 'State', val: (inc.lifecycle_state || 'ACTIVE').replace(/_/g, ' ') },
                    ].map(({ label, val }) => (
                      <div key={label} style={{ background: '#0A1628', borderRadius: 4, padding: '5px 7px' }}>
                        <div style={{ color: '#475569', fontSize: 9 }}>{label}</div>
                        <div style={{ color: '#CBD5E1', fontSize: 12, fontWeight: 600, fontFamily: 'monospace' }}>{val}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })()}

            {/* Actions */}
            <div>
              <div style={{ fontSize: '10px', color: '#64748B', letterSpacing: '0.1em', fontWeight: 600, marginBottom: '8px' }}>ACTIONS</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {addedSymbols.has(selected.symbol) ? (
                  <div style={{ fontSize: '11px', color: '#4ADE80', textAlign: 'center', padding: '8px', background: '#0D1F0D', borderRadius: '6px', border: '1px solid #166534' }}>
                    Added to watchlist
                  </div>
                ) : (
                  <>
                    <button onClick={() => addToWatchlist(selected.symbol, activeTab === 'all' ? 'scalp' : activeTab)}
                      style={{ width: '100%', padding: '8px', borderRadius: '6px', fontSize: '11px', fontWeight: 600, cursor: 'pointer', background: '#1E3A5F', border: '1px solid #2E86D4', color: '#60A5FA' }}>
                      + Add to Watchlist as {(activeTab === 'all' ? 'SCALP' : activeTab).toUpperCase()}
                    </button>
                    {activeTab !== 'swing' && (
                      <button onClick={() => addToWatchlist(selected.symbol, 'swing')}
                        style={{ width: '100%', padding: '8px', borderRadius: '6px', fontSize: '11px', fontWeight: 600, cursor: 'pointer', background: '#0F172A', border: '1px solid #334155', color: '#94A3B8' }}>
                        + Add as SWING
                      </button>
                    )}
                  </>
                )}
                <a href={`/v2/watchlist/${selected.symbol}`} target="_blank" rel="noreferrer"
                  style={{ display: 'block', textAlign: 'center', padding: '8px', borderRadius: '6px', fontSize: '11px', fontWeight: 600, background: '#0F172A', border: '1px solid #334155', color: '#94A3B8', textDecoration: 'none' }}>
                  View Full Research
                </a>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
```
