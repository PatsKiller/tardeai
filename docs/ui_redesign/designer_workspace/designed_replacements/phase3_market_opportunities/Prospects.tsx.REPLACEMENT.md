# Prospects.tsx Replacement

Status:      HISTORICAL
as_of:       2026-05-25T14:16:20-04:00
Measured at: efcc51365 / not measured

**Target repo path:** `apps/command-center-v2/src/pages/Prospects.tsx`

**Original SHA256:** `b2d6fd13148ad576ddfbc9d5af777fa28f3a3727de868c8ef36bf2b8bbdd8de4`

## Full Replacement

```tsx
import React, { useState, useEffect, useCallback } from 'react'
import { StatusBadge } from '../components/StatusBadge'
import { SeverityBadge } from '../components/SeverityBadge'
import { ActionButton } from '../components/ActionButton'
import { StateCard } from '../components/StateCard'

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

const fmt$ = (v: number | null | undefined) => v != null ? `$${v.toFixed(2)}` : '--'

/** Map decision strings to StatusBadge status values */
function decisionToStatus(decision: string): string {
  switch (decision) {
    case 'GO': return 'ready'
    case 'WAIT': return 'waiting'
    case 'AVOID': return 'blocked'
    default: return 'unknown'
  }
}

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

  const goCount = prospects.filter(p => p.decision === 'GO').length
  const waitCount = prospects.filter(p => p.decision === 'WAIT').length
  const avoidCount = prospects.filter(p => p.decision === 'AVOID').length
  const lastScan = prospects[0]?.scanned_at ? new Date(prospects[0].scanned_at).toLocaleString() : '--'

  return (
    <div style={{ padding: '24px', color: '#E2E8F0', maxWidth: '1600px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '22px', fontWeight: 800, color: '#F1F5F9', margin: 0 }}>Prospect Discovery</h1>
          <p style={{ color: '#64748B', fontSize: '12px', margin: '4px 0 0' }}>Filtered candidates, missing evidence, and graduation path</p>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <StatusBadge
            status={runHealth.is_stale ? 'stale' : runHealth.run_health_status === 'RUN_HEALTHY' ? 'fresh' : 'unknown'}
            label={[
              runHealth.run_label ? `Run ${runHealth.run_label}` : 'No run',
              runHealth.symbols_scanned != null ? `${runHealth.symbols_scanned} symbols` : '',
              runHealth.data_age_minutes != null ? `${runHealth.data_age_minutes}m ago` : '',
              runHealth.run_health_status || (runHealth.is_stale ? 'STALE' : ''),
            ].filter(Boolean).join(' | ')}
            size="md"
          />
          <span style={{ fontSize: '12px', fontWeight: 700, color: '#60A5FA', background: '#0D1A2F', padding: '4px 12px', borderRadius: '6px', border: '1px solid #1E3A5F' }}>
            {prospects.length} results
          </span>
        </div>
      </div>

      {/* Summary StateCards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8, marginBottom: 16 }}>
        <StateCard title="Total Prospects" value={prospects.length} status="fresh" compact />
        <StateCard title="GO" value={goCount} status={goCount > 0 ? 'ready' : 'unknown'} compact />
        <StateCard title="WAIT" value={waitCount} status={waitCount > 0 ? 'waiting' : 'unknown'} compact />
        <StateCard title="AVOID" value={avoidCount} status={avoidCount > 0 ? 'blocked' : 'unknown'} compact />
        <StateCard title="Last Scan" value={lastScan !== '--' ? lastScan.split(',')[0] : '--'} description={lastScan !== '--' ? lastScan.split(',')[1]?.trim() : undefined} status={runHealth.is_stale ? 'stale' : 'fresh'} compact />
        <StateCard title="Strategy" value={activeTab.toUpperCase()} description="Active filter" compact />
      </div>

      {/* Tab bar - using ActionButton */}
      <div style={{ display: 'flex', gap: '4px', marginBottom: '16px' }}>
        {(['scalp', 'swing', 'income', 'position', 'all'] as ProspectType[]).map(tab => (
          <ActionButton
            key={tab}
            variant={activeTab === tab ? 'primary' : 'secondary'}
            size="md"
            onClick={() => switchTab(tab)}
            style={{
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              ...(activeTab === tab ? { background: '#1E3A5F', borderColor: '#2E86D4', color: '#60A5FA' } : { background: '#0F172A', borderColor: '#1E293B', color: '#64748B' }),
            }}
          >
            {tab}
          </ActionButton>
        ))}
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '16px', padding: '10px 16px', background: '#0D1626', border: '1px solid #1E293B', borderRadius: '8px' }}>
        <span style={{ fontSize: '10px', color: '#64748B', fontWeight: 600 }}>FILTERS:</span>
        <label style={{ fontSize: '11px', color: '#94A3B8' }}>Price:
          <input value={minPrice} onChange={e => setMinPrice(e.target.value)} placeholder="min"
            style={{ width: '50px', marginLeft: '4px', background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0', padding: '4px 6px', borderRadius: '4px', fontSize: '11px' }} />
          <span style={{ margin: '0 4px', color: '#475569' }}>-</span>
          <input value={maxPrice} onChange={e => setMaxPrice(e.target.value)} placeholder="max"
            style={{ width: '50px', background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0', padding: '4px 6px', borderRadius: '4px', fontSize: '11px' }} />
        </label>
        <label style={{ fontSize: '11px', color: '#94A3B8' }}>Score:
          <input value={minScore} onChange={e => setMinScore(e.target.value)} placeholder="min"
            style={{ width: '40px', marginLeft: '4px', background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0', padding: '4px 6px', borderRadius: '4px', fontSize: '11px' }} />
          <span style={{ color: '#475569', marginLeft: '2px' }}>+</span>
        </label>
        <ActionButton
          variant="ghost"
          size="sm"
          onClick={() => { setMinPrice(''); setMaxPrice(''); setMinScore('') }}
          style={{ fontSize: '10px', color: '#64748B', border: '1px solid #334155' }}
        >
          Clear
        </ActionButton>
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
            <div style={{ color: '#64748B', fontSize: '13px', padding: '40px 20px', textAlign: 'center', background: '#0D1626', borderRadius: '8px', border: '1px solid #1E293B' }}>
              <div style={{ marginBottom: 8 }}>Loading prospects...</div>
              <div style={{ fontSize: 10, color: '#475569' }}>Fetching from /api/v2/prospects</div>
            </div>
          ) : prospects.length === 0 ? (
            <div style={{ color: '#64748B', fontSize: '13px', padding: '40px 20px', textAlign: 'center', background: '#0D1626', borderRadius: '8px', border: '1px solid #1E293B' }}>
              <div style={{ fontSize: 16, marginBottom: 8, color: '#94A3B8' }}>No prospects match current filters</div>
              <div style={{ fontSize: 11, color: '#475569', marginBottom: 12 }}>
                Try widening the price range, lowering the minimum score, or switching tabs.
              </div>
              <ActionButton variant="secondary" onClick={() => { setMinPrice(''); setMaxPrice(''); setMinScore('') }}>
                Clear All Filters
              </ActionButton>
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
                          <StatusBadge status={decisionToStatus(p.decision)} label={p.decision} />
                          {p.in_portfolio && <StatusBadge status="complete" label="HELD" />}
                          {incubatorMap[p.symbol] && (() => {
                            const inc = incubatorMap[p.symbol]
                            const st = inc.lifecycle_state || 'STAYED_ACTIVE'
                            const statusMap: Record<string, string> = {
                              ROLLED_ON: 'warning',
                              IMPROVED: 'fresh',
                              DEGRADED: 'blocked',
                              STAYED_ACTIVE: 'running',
                            }
                            const labelMap: Record<string, string> = {
                              ROLLED_ON: 'NEW',
                              STAYED_ACTIVE: 'TRACK',
                              IMPROVED: 'IMPROVED',
                              DEGRADED: 'DEGRADED',
                            }
                            return (
                              <StatusBadge
                                status={statusMap[st] || 'unknown'}
                                label={`${labelMap[st] || st.replace(/_/g, ' ')}${(inc.days_active || 0) > 0 ? ` ${inc.days_active}d` : ''}`}
                              />
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
                        {p.float_m ? `${p.float_m.toFixed(0)}M` : '--'}
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
                        ) : <span style={{ color: '#334155', fontSize: '10px' }}>--</span>}
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
                          <StatusBadge
                            status={p.catalyst_verified ? 'complete' : 'warning'}
                            label="CAT"
                            title={p.catalyst}
                          />
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
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: '20px', fontWeight: 800, color: '#F1F5F9' }}>{selected.symbol}</span>
                <StatusBadge status={decisionToStatus(selected.decision)} label={selected.decision} size="md" />
              </div>
              <ActionButton variant="ghost" onClick={() => setSelected(null)} style={{ width: '24px', height: '24px', padding: 0 }}>x</ActionButton>
            </div>
            <div style={{ fontSize: '11px', color: '#64748B', marginBottom: '16px' }}>
              {selected.sector} | Score {selected.score}/55 | RVOL {(selected.rvol || 0).toFixed(1)}x
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
                <div><span style={{ color: '#64748B' }}>R:R: </span><span style={{ color: '#E2E8F0', fontWeight: 600 }}>{selected.risk_reward ? `${selected.risk_reward.toFixed(1)}:1` : '--'}</span></div>
              </div>
            </div>

            {/* Confluence */}
            {selected.confluence_tier && (
              <div style={{ marginBottom: '16px' }}>
                <div style={{ fontSize: '10px', color: '#64748B', letterSpacing: '0.1em', fontWeight: 600, marginBottom: '8px' }}>CONFLUENCE</div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '6px' }}>
                  <SeverityBadge
                    severity={selected.confluence_tier === 'STRONG' ? 'low' : selected.confluence_tier === 'MODERATE' ? 'medium' : 'info'}
                    label={selected.confluence_tier}
                    size="md"
                  />
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
                {(selected.pipeline_sources || []).length === 0 && (
                  <div style={{ color: '#475569', fontSize: 10 }}>No pipeline sources recorded</div>
                )}
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

            {/* Actions - using ActionButton primitives */}
            <div>
              <div style={{ fontSize: '10px', color: '#64748B', letterSpacing: '0.1em', fontWeight: 600, marginBottom: '8px' }}>ACTIONS</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {addedSymbols.has(selected.symbol) ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                    <StatusBadge status="complete" label="Added to watchlist" size="md" />
                  </div>
                ) : (
                  <>
                    <ActionButton
                      variant="primary"
                      size="md"
                      onClick={() => addToWatchlist(selected.symbol, activeTab === 'all' ? 'scalp' : activeTab)}
                      style={{ width: '100%', background: '#1E3A5F', borderColor: '#2E86D4', color: '#60A5FA' }}
                    >
                      + Add to Watchlist as {(activeTab === 'all' ? 'SCALP' : activeTab).toUpperCase()}
                    </ActionButton>
                    {activeTab !== 'swing' && (
                      <ActionButton
                        variant="secondary"
                        size="md"
                        onClick={() => addToWatchlist(selected.symbol, 'swing')}
                        style={{ width: '100%', background: '#0F172A', borderColor: '#334155', color: '#94A3B8' }}
                      >
                        + Add as SWING
                      </ActionButton>
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

## Acceptance Checklist

- [ ] Title changed from "PROSPECTS" to "Prospect Discovery"
- [ ] Subtitle changed to "Filtered candidates, missing evidence, and graduation path"
- [ ] StateCard used for summary metrics (Total Prospects, GO, WAIT, AVOID, Last Scan, Strategy) with `title=` prop (NOT `label=`)
- [ ] StatusBadge used for run health display in header via `status=` prop
- [ ] StatusBadge used for decision badges per ticker in table (GO/WAIT/AVOID)
- [ ] StatusBadge used for HELD badge, incubator lifecycle state badges, catalyst indicator
- [ ] StatusBadge used for "Added to watchlist" confirmation
- [ ] SeverityBadge used for confluence tier display in side panel
- [ ] ActionButton uses children pattern (`<ActionButton>Text</ActionButton>`) -- NO `label=` prop anywhere
- [ ] ActionButton used for tab bar buttons (scalp/swing/income/position/all)
- [ ] ActionButton used for Clear filter button
- [ ] ActionButton used for Add to Watchlist buttons
- [ ] ActionButton used for close button on side panel
- [ ] ActionButton used for Clear All Filters in empty state
- [ ] All existing fetch() patterns preserved -- NOT converted to useApi
- [ ] fetch('/api/v2/prospects') with params preserved
- [ ] fetch('/api/v2/incubator') preserved
- [ ] fetch('/api/v2/prospects/add-to-watchlist') POST preserved
- [ ] All existing useState hooks preserved identically
- [ ] All existing useEffect hooks preserved
- [ ] useCallback for fetchProspects preserved
- [ ] switchTab function preserved
- [ ] addToWatchlist function preserved
- [ ] All existing filter/search logic preserved (minPrice, maxPrice, minScore)
- [ ] Incubator map side panel section preserved
- [ ] Trade setup section preserved
- [ ] Confluence section preserved
- [ ] Pipeline sources section preserved
- [ ] Prospect interface preserved identically
- [ ] PRICE_DEFAULTS, SOURCE_COLORS, TIER_COLORS, DECISION_COLORS preserved
- [ ] Empty states added for: loading (with endpoint info), no results (with clear filter action), no pipeline sources
- [ ] No `<AgentChip agent=` anywhere (correct: `name=`)
- [ ] No `<ActionButton label=` anywhere (correct: children)
- [ ] No `<StateCard label=` anywhere (correct: `title=`)
- [ ] All imports added for StatusBadge, SeverityBadge, ActionButton, StateCard
