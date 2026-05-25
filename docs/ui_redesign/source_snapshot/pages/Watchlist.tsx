import { useState, useCallback, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import WatchlistSymbolPanel from '../components/WatchlistSymbolPanel'
import { ConfluenceBadge } from '../components/ConfluenceBadge'
import { useApi } from '../hooks/useApi'
import { useToast } from '../components/ToastProvider'

/*
  Watchlist Agent Workbench — Phase 12/13: Symbol Master + Account Holdings
  - Default: one row per symbol (deduped via watchlist_symbol_master)
  - Source detail toggle for audit
  - Account-level holdings in drawer
  - Maturity ladder + full narratives + synthesis
*/

// ── Types ──

interface SymbolRow {
  symbol: string; sources: string[]; in_portfolio: boolean; in_ai_discovered: boolean
  in_ai_watchlist: boolean; in_personal_watchlist: boolean
  asset_type: string | null; score: number | null; updated_at: string
  strategy_type: string | null; latest_price: number | null; support: number | null
  resistance: number | null; stop_loss: number | null; target_price: number | null
  risk_reward: number | null; account_fit: string | null; technical_summary: string | null
  analysis_stage: string | null; maria_status: string | null; steph_status: string | null
  risk_status: string | null; tax_status: string | null; full_chain_status: string | null
  final_synthesis_status: string | null; required_agents: string[] | null
  completed_agents: string[] | null; maturity_needs_iteration: boolean | null
  latest_recommendation: string | null; research_confidence: number | null
  synthesis_recommendation: string | null; synthesis_confidence: number | null
  decision_quality_status: string | null; decision_actionable: boolean | null
  // Runtime fields from API
  last_recommendation: string | null; last_confidence: number | null
  last_agent: string | null; is_curated: boolean | null; days_watched: number | null
  added_by: string | null; why_added: string | null; all_sources: string[] | null
  // Holdings
  account_holdings: AccountHolding[]; total_shares: number; total_market_value: number
  portfolio_weight: number
  // LLM health
  holdings_llm_health?: string; holdings_llm_action?: string
  holdings_llm_confidence?: number; holdings_llm_at?: string
}

interface AccountHolding {
  account_id: string; account_name: string; account_type: string
  shares: number; market_value: number; cost_basis: number | null
  gain_loss: number | null; gain_loss_pct: number | null; weight_in_account?: number
}

interface WlSummary {
  total_active: number; by_source: Record<string, number>
  by_status: Record<string, number>; jobs: Record<string, number>
  research_cards: number; needs_iteration: number
}

interface AgentResult {
  agent: string; summary: string; full_narrative?: string; recommendation: string
  confidence: number; reason_codes?: string[]; model_used?: string; created_at: string
}

interface MaturitySummary {
  analysis_stage: string; escalation_policy?: string
  required_agents: string[]; completed_agents: string[]; missing_agents: string[]
  agent_statuses: Record<string, string>
  final_synthesis_status: string; needs_iteration: boolean; iteration_reason?: string
}

interface Synthesis {
  recommendation: string; confidence: number; action: string
  reason_codes?: string[]; conflicts?: string[]; unresolved?: string[]
  synthesis_narrative?: string; next_review_date?: string
  decision_safety?: string; safety_overrides?: Record<string, string>
  safety_reasons?: { rule: string; detail: string }[]
}

interface StrategyCard {
  strategy_type: string; latest_price: number; support: number; resistance: number
  ideal_entry: number; stop_loss: number; target_price: number; risk_reward: number
  account_fit: string; thesis: string; technical_summary: string
  confidence: number; needs_iteration: boolean
}

interface DrawerData {
  symbol: string
  card: { latest_summary: string; latest_recommendation: string; confidence: number } | null
  strategy: StrategyCard | null
  maturity: MaturitySummary | null
  synthesis: Synthesis | null
  holdings: { accounts: AccountHolding[]; total_shares: number; total_market_value: number; portfolio_weight: number } | null
  items: { source: string; bucket: string; status: string; score: number }[]
  results: AgentResult[]
  events: { event_type: string; status: string; message: string; created_at: string }[]
  alerts?: { alert_type: string; severity: string; raw_text: string; price?: number; stop_price?: number; data_quality_status: string; created_at: string }[]
  data_quality_warned?: boolean
  data_quality_issues?: { alert_type: string; data_quality_status: string; raw_text: string }[]
  decision_qa?: {
    status: string; actionable: boolean; human_review_required: boolean
    conflicts: { type: string; description: string }[]
    gating_reasons: string[]; missing_agents: string[]
  }
}

// ── Main Component ──

export default function Watchlist() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [, setParams] = useSearchParams()

  const [source, setSource] = useState('candidates')
  const [stageFilter, setStageFilter] = useState('')
  const [strategyFilter, setStrategyFilter] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('updated')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [submitAgent, setSubmitAgent] = useState('maria')
  const [submitType, setSubmitType] = useState('research')
  const [submitNote, setSubmitNote] = useState('')
  const [submitStatus, setSubmitStatus] = useState('')
  const [drawerSymbol, setDrawerSymbol] = useState<string | null>(null)
  const [drawerData, setDrawerData] = useState<DrawerData | null>(null)
  const [expandedNarrative, setExpandedNarrative] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [confluenceData, setConfluenceData] = useState<Record<string, any>>({})

  // Default: symbol master (deduped)
  const queryStr = [source && `source=${source}`, stageFilter && `stage=${stageFilter}`, strategyFilter && `strategy=${strategyFilter}`, sort && `sort=${sort}`].filter(Boolean).join('&')
  const { data: summary } = useApi<WlSummary>(`/api/v2/watchlist/summary?_r=${refreshKey}`)
  const { data: symbolsResp } = useApi<{ count: number; symbols: SymbolRow[] }>(`/api/v2/watchlist/symbols?${queryStr}&_r=${refreshKey}`)

  const symbols = (symbolsResp?.symbols || []).filter(i => !search || i.symbol.toLowerCase().includes(search.toLowerCase()))

  // Load confluence data for visible symbols (non-fatal)
  useEffect(() => {
    const syms = (symbolsResp?.symbols || []).map(s => s.symbol).slice(0, 20)
    if (syms.length === 0) return
    fetch('/api/v2/indicators/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: syms, profile: 'swing' })
    })
      .then(r => r.json())
      .then(d => { if (d.ok && d.results) setConfluenceData(d.results) })
      .catch(() => {})
  }, [symbolsResp])

  const filterBySource = (s: string) => { setSource(prev => prev === s ? '' : s); setRefreshKey(k => k + 1) }

  const openDrawer = useCallback((sym: string) => {
    setDrawerSymbol(sym)
    setExpandedNarrative(null)
    // Data loading is handled by WatchlistSymbolPanel component
  }, [])

  const handleSubmit = useCallback(async () => {
    const syms = [...selected]
    if (!syms.length) { showToast('Select symbols first', 'error'); return }
    setSubmitStatus('Submitting...')
    try {
      const r = await fetch('/api/v2/watchlist/submit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbols: syms, agent: submitAgent, request_type: submitType, note: submitNote }) })
      const d = await r.json()
      setSubmitStatus(d.ok ? `Queued ${d.created_jobs?.length || syms.length} jobs` : `Error: ${d.error}`)
      if (d.ok) { setSelected(new Set()); showToast(`Submitted ${syms.length} to ${submitAgent}`, 'success'); setTimeout(() => setRefreshKey(k => k + 1), 1000) }
    } catch { setSubmitStatus('Network error') }
  }, [selected, submitAgent, submitType, submitNote, showToast])

  const toggleSel = (sym: string, on: boolean) => setSelected(s => { const n = new Set(s); on ? n.add(sym) : n.delete(sym); return n })
  const toggleAll = (on: boolean) => setSelected(on ? new Set(symbols.map(i => i.symbol)) : new Set())

  // Stats
  const held = symbols.filter(s => s.in_portfolio).length
  const synthesized = symbols.filter(s => s.analysis_stage === 'final_synthesis_complete').length
  const totalValue = symbols.reduce((sum, s) => sum + (s.total_market_value || 0), 0)

  return (
    <>
      <PageHeader title="Watchlist Workbench" subtitle={`${symbols.length} active candidates${held > 0 ? ` · ${held} also in portfolio` : ' · not currently held'} · ${synthesized} synthesized · $${(totalValue / 1000).toFixed(0)}K tracked · Pipeline: Raw → Strategy → Agent Review → Synthesized → Approval`} actions={
        <button onClick={() => setRefreshKey(k => k + 1)} style={{ padding: '4px 12px', fontSize: 10, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, background: 'rgba(255,255,255,0.04)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--sans)' }}>⟳ Refresh</button>
      } />

      {/* Summary tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 10, marginBottom: 14 }}>
        <MetricTile label="Unique Symbols" value={String(symbolsResp?.count || 0)} onClick={() => { setSource('candidates'); setStageFilter(''); setRefreshKey(k => k + 1) }} />
        <MetricTile label="Portfolio" value={String(summary?.by_source?.portfolio || 0)} deltaColor={source === 'portfolio' ? 'var(--green)' : undefined} onClick={() => filterBySource('portfolio')} />
        <MetricTile label="AI Discovered" value={String(summary?.by_source?.ai_discovered || 0)} deltaColor={source === 'ai_discovered' ? 'var(--purple)' : undefined} onClick={() => filterBySource('ai_discovered')} />
        <MetricTile label="AI Watchlist" value={String(summary?.by_source?.ai_watchlist || 0)} deltaColor={source === 'ai_watchlist' ? 'var(--accent)' : undefined} onClick={() => filterBySource('ai_watchlist')} />
        <MetricTile label="Personal" value={String(summary?.by_source?.personal_watchlist || 0)} deltaColor={source === 'personal_watchlist' ? 'var(--amber)' : undefined} onClick={() => filterBySource('personal_watchlist')} />
        <MetricTile label="Synthesized" value={String(synthesized)} deltaColor="var(--green)" />
      </div>

      {/* Submit bar */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '10px 14px', background: 'rgba(16,20,28,0.92)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)' }}>Submit →</span>
        <select value={submitAgent} onChange={e => setSubmitAgent(e.target.value)} style={selStyle}>
          <option value="maria">Maria</option><option value="steph">Steph</option>
          <option value="risk_agent">Risk</option><option value="tax_agent">Tax</option>
          <option value="full_chain">Full Chain</option>
        </select>
        <select value={submitType} onChange={e => setSubmitType(e.target.value)} style={selStyle}>
          <option value="research">Research</option><option value="trade_plan">Trade Plan</option>
          <option value="allocation">Allocation</option>
        </select>
        <input value={submitNote} onChange={e => setSubmitNote(e.target.value)} placeholder="note" style={{ ...selStyle, width: 160 }} />
        <button onClick={handleSubmit} style={btnAccent}>Submit ({selected.size})</button>
        {submitStatus && <span style={{ fontSize: 10, color: 'var(--text2)' }}>{submitStatus}</span>}
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search symbol..." style={{ ...selStyle, width: 130 }} />
        <select value={source} onChange={e => setSource(e.target.value)} style={selStyle}>
          <option value="candidates">Candidates (not held)</option>
          <option value="ai_watchlist">AI Watchlist</option>
          <option value="personal_watchlist">Personal</option>
          <option value="curated">All Curated (incl. held)</option>
          <option value="ai_discovered">AI Discovered</option>
          <option value="">All Sources</option>
        </select>
        <select value={stageFilter} onChange={e => setStageFilter(e.target.value)} style={selStyle}>
          <option value="">All stages</option>
          <option value="raw_data_only">Raw only</option>
          <option value="strategy_card_ready">Strategy ready</option>
          <option value="specialist_review_partial">Partial review</option>
          <option value="specialist_review_complete">Full review</option>
          <option value="final_synthesis_complete">Synthesized</option>
        </select>
        <select value={strategyFilter} onChange={e => setStrategyFilter(e.target.value)} style={selStyle}>
          <option value="">All strategies</option>
          <option value="income">Income</option>
          <option value="defense_thesis">Defense</option>
          <option value="core_holding">Core Holding</option>
          <option value="growth_etf">Growth ETF</option>
          <option value="speculative_growth">Speculative</option>
        </select>
        <select value={sort} onChange={e => setSort(e.target.value)} style={selStyle}>
          <option value="updated">Recent</option><option value="score">Score</option>
          <option value="symbol">A-Z</option><option value="price">Price</option>
          <option value="rr">R:R</option>
        </select>
        {(source !== 'candidates' || stageFilter || strategyFilter) && (
          <button onClick={() => { setSource('candidates'); setStageFilter(''); setStrategyFilter(''); setRefreshKey(k => k + 1) }}
            style={{ padding: '3px 10px', fontSize: 9, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, background: 'rgba(255,255,255,0.04)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--sans)' }}>
            Clear
          </button>
        )}
        <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 'auto' }}>{symbols.length} symbols</span>
      </div>

      {/* Symbol master table */}
      <Card>
        <div style={{ maxHeight: '55vh', overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th style={th}><input type="checkbox" onChange={e => toggleAll(e.target.checked)} /></th>
                <th style={th}>Symbol</th>
                <th style={th}>Agent / Source</th>
                <th style={th}>Days</th>
                <th style={th}>Strategy</th>
                <th style={{ ...th, textAlign: 'right' }}>Price</th>
                <th style={{ ...th, textAlign: 'right' }}>Value</th>
                <th style={{ ...th, textAlign: 'right' }}>Weight</th>
                <th style={{ ...th, textAlign: 'center' }}>R:R</th>
                <th style={th}>Stage</th>
                <th style={th}>Confluence</th>
                <th style={th}>Analysts</th>
                <th style={th}>Decision</th>
              </tr>
            </thead>
            <tbody>
              {symbols.map(item => {
                const rr = item.risk_reward
                const rrColor = rr ? (rr >= 2 ? 'var(--green)' : rr >= 1 ? 'var(--amber)' : 'var(--red)') : 'var(--text3)'
                const rec = item.synthesis_recommendation || item.latest_recommendation
                return (
                  <tr key={item.symbol}
                    style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}
                    onClick={() => openDrawer(item.symbol)}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.02)' }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = '' }}>
                    <td style={td} onClick={e => e.stopPropagation()}>
                      <input type="checkbox" checked={selected.has(item.symbol)} onChange={e => toggleSel(item.symbol, e.target.checked)} />
                    </td>
                    <td style={td}>
                      <span style={{ color: 'var(--accent)', fontWeight: 800, fontSize: 13, cursor: 'pointer' }}
                        onClick={e => { e.stopPropagation(); navigate(`/research?symbol=${item.symbol}`) }}
                        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.textDecoration = 'underline' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.textDecoration = '' }}>
                        {item.symbol}
                      </span>
                      {item.last_recommendation && (
                        <div style={{ fontSize: 8, fontWeight: 700, marginTop: 2,
                          color: item.last_recommendation === 'BUY' || item.last_recommendation === 'ADD' ? '#0ecb81' :
                                 item.last_recommendation === 'SELL' || item.last_recommendation === 'TRIM' ? '#f6465d' :
                                 item.last_recommendation === 'HOLD' ? '#f0b90b' : 'var(--text3)' }}>
                          {item.last_recommendation} {item.last_confidence ? `${(item.last_confidence * 100).toFixed(0)}%` : ''}
                        </div>
                      )}
                    </td>
                    <td style={td}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {item.last_agent && (
                          <span style={{ fontSize: 9, fontWeight: 700, color: item.last_agent === 'maria' ? '#4a90f4' : item.last_agent === 'steph' ? '#0ecb81' : item.last_agent === 'risk_agent' ? '#f6465d' : '#f0b90b' }}>
                            {item.last_agent.replace('_agent', '')}
                          </span>
                        )}
                        <SourceBadges sources={item.sources || []} onFilter={filterBySource} />
                        {item.is_curated && <span style={{ fontSize: 7, fontWeight: 700, color: '#0ecb81', background: '#0ecb8118', padding: '1px 4px', borderRadius: 3, width: 'fit-content' }}>CURATED</span>}
                        {item.added_by && (() => {
                          const cfg: Record<string, { icon: string; color: string; label: string }> = {
                            portfolio: { icon: '\uD83D\uDCBC', color: '#6366f1', label: 'Portfolio' },
                            personal_watchlist: { icon: '\uD83D\uDC64', color: '#6366f1', label: 'Personal' },
                            ai_discovered: { icon: '\uD83E\uDD16', color: '#059669', label: 'AI Discover' },
                            ai_watchlist: { icon: '\uD83D\uDD0D', color: '#059669', label: 'AI Watch' },
                            screener: { icon: '\uD83D\uDCCA', color: '#0891b2', label: 'Screener' },
                          }
                          const c = cfg[item.added_by!] || { icon: '\u2022', color: '#6b7280', label: item.added_by }
                          return <span style={{ fontSize: 7, fontWeight: 600, padding: '1px 4px', borderRadius: 3, border: `1px solid ${c.color}40`, color: c.color, whiteSpace: 'nowrap' }}>{c.icon} {c.label}</span>
                        })()}
                        {item.in_portfolio && item.portfolio_weight > 0 && <span style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: 'rgba(220,38,38,.12)', color: '#DC2626', border: '1px solid rgba(220,38,38,.3)', whiteSpace: 'nowrap' }}>{'\u26a0\ufe0f'} HELD {item.portfolio_weight.toFixed(1)}%</span>}
                        {item.holdings_llm_health && (
                          <span style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 3, whiteSpace: 'nowrap',
                            background: item.holdings_llm_health === 'STRONG' ? 'rgba(34,197,94,.12)' : item.holdings_llm_health === 'STABLE' ? 'rgba(59,130,246,.12)' : item.holdings_llm_health === 'WATCH' ? 'rgba(245,158,11,.12)' : 'rgba(239,68,68,.12)',
                            color: item.holdings_llm_health === 'STRONG' ? '#22C55E' : item.holdings_llm_health === 'STABLE' ? '#3B82F6' : item.holdings_llm_health === 'WATCH' ? '#F59E0B' : '#EF4444',
                            border: `1px solid ${item.holdings_llm_health === 'STRONG' ? 'rgba(34,197,94,.3)' : item.holdings_llm_health === 'STABLE' ? 'rgba(59,130,246,.3)' : item.holdings_llm_health === 'WATCH' ? 'rgba(245,158,11,.3)' : 'rgba(239,68,68,.3)'}`,
                          }}>AI: {item.holdings_llm_health} {item.holdings_llm_action && item.holdings_llm_action !== 'HOLD' ? `→${item.holdings_llm_action}` : ''}</span>
                        )}
                      </div>
                    </td>
                    <td style={{ ...td, textAlign: 'center' }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: (item.days_watched ?? 0) >= 3 ? 'var(--green)' : (item.days_watched ?? 0) >= 1 ? 'var(--text1)' : 'var(--text3)' }}>
                        {item.days_watched ?? 0}d
                      </span>
                    </td>
                    <td style={td}><StrategyPill type={item.strategy_type} /></td>
                    <td style={{ ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                      {item.latest_price ? `$${item.latest_price.toFixed(2)}` : <span title="No price data — agents may have insufficient data for technical analysis. Check after 7 PM pipeline run." style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'rgba(240,185,11,.1)', color: 'var(--amber)' }}>NO DATA</span>}
                    </td>
                    <td style={{ ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: item.total_market_value ? 'var(--text1)' : 'var(--text3)' }}>
                      {item.total_market_value ? `$${(item.total_market_value / 1000).toFixed(1)}K` : '—'}
                    </td>
                    <td style={{ ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--text2)' }}>
                      {item.portfolio_weight ? `${item.portfolio_weight.toFixed(1)}%` : '—'}
                    </td>
                    <td style={{ ...td, textAlign: 'center' }}>
                      {rr ? <span style={{ fontSize: 11, fontWeight: 700, color: rrColor, padding: '1px 6px', borderRadius: 6, background: `color-mix(in srgb, ${rrColor} 10%, transparent)` }}>{rr.toFixed(1)}</span> : <span style={{ color: 'var(--text3)' }}>—</span>}
                    </td>
                    <td style={td}><StageBadge stage={item.analysis_stage} /></td>
                    <td style={td}>
                      {confluenceData[item.symbol]?.confluence_tier ? (
                        <ConfluenceBadge
                          tier={confluenceData[item.symbol].confluence_tier}
                          bullishCount={confluenceData[item.symbol].signals_bullish || 0}
                          badges={confluenceData[item.symbol].strategy_badges || []}
                          compact
                        />
                      ) : <span style={{ color: 'var(--text3)', fontSize: 9 }}>--</span>}
                    </td>
                    <td style={td}>
                      <AgentBadges maria={item.maria_status} steph={item.steph_status}
                        risk={item.risk_status} tax={item.tax_status} synthesis={item.final_synthesis_status} />
                    </td>
                    <td style={td}><DecisionBadge rec={rec} qaStatus={item.decision_quality_status} actionable={item.decision_actionable} /></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {symbols.length === 0 && <div style={{ padding: 30, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>No symbols match current filters.</div>}
        </div>
      </Card>

      {/* ═══ SYMBOL CONTEXT PANEL ═══ */}
      <WatchlistSymbolPanel symbol={drawerSymbol} onClose={() => setDrawerSymbol(null)} />

      {/* Legacy drawer hidden — replaced by WatchlistSymbolPanel */}
      {false && drawerSymbol && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 1100, display: 'flex', justifyContent: 'flex-end' }} onClick={() => setDrawerSymbol(null)}>
          <div style={{ width: 620, height: '100vh', background: 'var(--bg0)', borderLeft: '1px solid var(--border)', padding: 20, overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--accent)', fontFamily: 'var(--sans)' }}>{drawerSymbol}</div>
                <div style={{ display: 'flex', gap: 6, marginTop: 4, alignItems: 'center' }}>
                  {drawerData?.strategy?.strategy_type && <StrategyPill type={drawerData.strategy.strategy_type} />}
                  {drawerData?.maturity && <StageBadge stage={drawerData.maturity.analysis_stage} />}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <a href={`https://finviz.com/quote.ashx?t=${drawerSymbol}`} target="_blank" rel="noreferrer" style={{ padding: '3px 10px', fontSize: 9, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, background: 'rgba(255,255,255,0.04)', color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
                <button onClick={() => setDrawerSymbol(null)} style={{ fontSize: 20, color: 'var(--text3)', background: 'none', border: 'none', cursor: 'pointer' }}>×</button>
              </div>
            </div>

            {/* 0. DECISION QA STATUS */}
            {drawerData?.decision_qa && (
              <div style={{ padding: 12, background: drawerData.decision_qa.actionable ? 'rgba(14,203,129,0.04)' : 'rgba(240,185,11,0.04)', border: `1px solid ${drawerData.decision_qa.actionable ? 'rgba(14,203,129,0.12)' : 'rgba(240,185,11,0.12)'}`, borderRadius: 10, marginBottom: 14 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                  <QaStatusBadge status={drawerData.decision_qa.status} />
                  {drawerData.decision_qa.actionable
                    ? <span style={{ fontSize: 10, color: 'var(--green)', fontWeight: 700 }}>ACTIONABLE</span>
                    : <span style={{ fontSize: 10, color: 'var(--amber)', fontWeight: 700 }}>NOT ACTIONABLE</span>}
                  {drawerData.decision_qa.human_review_required && (
                    <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 99, background: 'rgba(246,70,93,0.1)', color: 'var(--red)', fontWeight: 700 }}>NEEDS HUMAN REVIEW</span>
                  )}
                </div>
                {drawerData.decision_qa.missing_agents.length > 0 && (
                  <div style={{ fontSize: 10, color: 'var(--amber)', marginBottom: 4 }}>
                    Missing required: {drawerData.decision_qa.missing_agents.join(', ')}
                  </div>
                )}
                {drawerData.decision_qa.conflicts.length > 0 && (
                  <div style={{ marginBottom: 4 }}>
                    {drawerData.decision_qa.conflicts.map((c, i) => (
                      <div key={i} style={{ fontSize: 9, color: 'var(--red)', padding: '2px 0' }}>
                        CONFLICT: {c.description}
                      </div>
                    ))}
                  </div>
                )}
                {drawerData.decision_qa.gating_reasons.length > 0 && (
                  <div>
                    {drawerData.decision_qa.gating_reasons.map((r, i) => (
                      <div key={i} style={{ fontSize: 9, color: 'var(--text3)', padding: '1px 0' }}>{r}</div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* 0b. SYNTHESIS SAFETY OVERRIDE */}
            {drawerData?.synthesis?.decision_safety && drawerData.synthesis.decision_safety !== 'safe' && drawerData.synthesis.decision_safety !== 'pending' && (
              <div style={{ padding: 12, background: 'rgba(246,70,93,0.06)', border: '1px solid rgba(246,70,93,0.15)', borderRadius: 10, marginBottom: 14 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                  <SafetyBadge safety={drawerData.synthesis.decision_safety} />
                  {drawerData.synthesis.safety_overrides && Object.keys(drawerData.synthesis.safety_overrides).length > 0 && (
                    <span style={{ fontSize: 10, color: 'var(--red)' }}>
                      Override: {Object.values(drawerData.synthesis.safety_overrides as Record<string, string>).join(', ')}
                    </span>
                  )}
                </div>
                {(drawerData.synthesis.safety_reasons || []).map((r: any, i: number) => (
                  <div key={i} style={{ fontSize: 9, color: 'var(--text2)', padding: '2px 0' }}>
                    <b style={{ color: 'var(--red)' }}>{r.rule}:</b> {r.detail}
                  </div>
                ))}
              </div>
            )}

            {/* 1. ACCOUNT HOLDINGS */}
            {drawerData?.holdings && drawerData.holdings.accounts.length > 0 && (
              <div style={{ padding: 14, background: 'rgba(14,203,129,0.04)', border: '1px solid rgba(14,203,129,0.1)', borderRadius: 10, marginBottom: 14 }}>
                <div style={{ fontSize: 9, color: 'var(--green)', textTransform: 'uppercase', fontWeight: 700, marginBottom: 8 }}>
                  Account Holdings — {drawerData.holdings.portfolio_weight.toFixed(1)}% of portfolio
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      <th style={{ ...th, padding: '3px 6px' }}>Account</th>
                      <th style={{ ...th, padding: '3px 6px' }}>Type</th>
                      <th style={{ ...th, padding: '3px 6px', textAlign: 'right' }}>Shares</th>
                      <th style={{ ...th, padding: '3px 6px', textAlign: 'right' }}>Value</th>
                      <th style={{ ...th, padding: '3px 6px', textAlign: 'right' }}>Gain/Loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {drawerData.holdings.accounts.map((a, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <td style={{ padding: '4px 6px', fontSize: 10, color: 'var(--text1)' }}>{a.account_name}</td>
                        <td style={{ padding: '4px 6px', fontSize: 9, color: 'var(--text2)' }}>{a.account_type}</td>
                        <td style={{ padding: '4px 6px', fontSize: 10, color: 'var(--text1)', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{a.shares.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                        <td style={{ padding: '4px 6px', fontSize: 10, color: 'var(--text1)', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>${a.market_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                        <td style={{ padding: '4px 6px', fontSize: 10, textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: (a.gain_loss ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>
                          {a.gain_loss != null ? `${a.gain_loss >= 0 ? '+' : ''}$${a.gain_loss.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—'}
                          {a.gain_loss_pct != null && <span style={{ fontSize: 8, marginLeft: 4 }}>({a.gain_loss_pct >= 0 ? '+' : ''}{a.gain_loss_pct.toFixed(1)}%)</span>}
                        </td>
                      </tr>
                    ))}
                    <tr style={{ borderTop: '2px solid var(--border)' }}>
                      <td colSpan={2} style={{ padding: '4px 6px', fontSize: 10, fontWeight: 700, color: 'var(--text0)' }}>Total</td>
                      <td style={{ padding: '4px 6px', fontSize: 10, fontWeight: 700, color: 'var(--text0)', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{drawerData.holdings.total_shares.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                      <td style={{ padding: '4px 6px', fontSize: 10, fontWeight: 700, color: 'var(--text0)', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>${drawerData.holdings.total_market_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                      <td />
                    </tr>
                  </tbody>
                </table>
              </div>
            )}

            {/* 2. MATURITY LADDER */}
            {drawerData?.maturity && (
              <div style={{ padding: 14, background: 'rgba(74,144,244,0.04)', border: '1px solid rgba(74,144,244,0.12)', borderRadius: 10, marginBottom: 14 }}>
                <div style={{ fontSize: 9, color: 'var(--accent)', textTransform: 'uppercase', fontWeight: 700, marginBottom: 10 }}>
                  Analysis Maturity — {drawerData.maturity.escalation_policy || 'default'} policy
                </div>
                <MaturityLadder maturity={drawerData.maturity} />
                {drawerData.maturity.needs_iteration && drawerData.maturity.iteration_reason && (
                  <div style={{ fontSize: 9, color: 'var(--amber)', marginTop: 8, padding: '4px 8px', background: 'rgba(240,185,11,0.06)', borderRadius: 6 }}>{drawerData.maturity.iteration_reason}</div>
                )}
              </div>
            )}

            {/* 3. FINAL SYNTHESIS */}
            {drawerData?.synthesis && (
              <div style={{ padding: 14, background: 'rgba(14,203,129,0.06)', border: '1px solid rgba(14,203,129,0.15)', borderRadius: 10, marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 9, color: 'var(--green)', textTransform: 'uppercase', fontWeight: 700 }}>Final Synthesis</span>
                  <span style={{ fontSize: 18, fontWeight: 800, color: recColor(drawerData.synthesis.recommendation) }}>{drawerData.synthesis.recommendation}</span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 6 }}>
                  Confidence: {drawerData.synthesis.confidence ? `${(drawerData.synthesis.confidence * 100).toFixed(0)}%` : '—'}
                  {drawerData.synthesis.action && <> · <b style={{ color: 'var(--text1)' }}>{drawerData.synthesis.action}</b></>}
                </div>
                {drawerData.synthesis.synthesis_narrative && (
                  <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.7, marginBottom: 8, whiteSpace: 'pre-wrap' }}>{drawerData.synthesis.synthesis_narrative}</div>
                )}
                {drawerData.synthesis.reason_codes?.length ? (
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
                    {drawerData.synthesis.reason_codes.map((c, i) => <span key={i} style={{ fontSize: 8, padding: '2px 6px', borderRadius: 99, background: 'rgba(14,203,129,0.1)', color: 'var(--green)' }}>{c}</span>)}
                  </div>
                ) : null}
                {drawerData.synthesis.conflicts?.length ? (
                  <div style={{ marginTop: 6 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--amber)', marginBottom: 2 }}>Conflicts:</div>
                    {drawerData.synthesis.conflicts.map((c, i) => <div key={i} style={{ fontSize: 10, color: 'var(--amber)', padding: '2px 0' }}>{c}</div>)}
                  </div>
                ) : null}
                {drawerData.synthesis.unresolved?.length ? (
                  <div style={{ marginTop: 6 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--red)', marginBottom: 2 }}>Unresolved:</div>
                    {drawerData.synthesis.unresolved.map((u, i) => <div key={i} style={{ fontSize: 10, color: 'var(--red)', padding: '2px 0' }}>{u}</div>)}
                  </div>
                ) : null}
                {drawerData.synthesis.next_review_date && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>Next review: {drawerData.synthesis.next_review_date}</div>}
              </div>
            )}

            {/* 3b. INCOME PROFILE */}
            {(drawerData as any)?.income && (
              <div style={{ padding: 14, background: 'rgba(240,185,11,0.04)', border: '1px solid rgba(240,185,11,0.1)', borderRadius: 10, marginBottom: 14 }}>
                <div style={{ fontSize: 9, color: 'var(--amber)', textTransform: 'uppercase', fontWeight: 700, marginBottom: 8 }}>
                  Income Profile — {(drawerData as any).income.layer?.replace(/_/g, ' ')}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 8 }}>
                  <MiniMetric label="Annual Income" value={`$${((drawerData as any).income.annual_income || 0).toLocaleString()}`} color="var(--green)" />
                  <MiniMetric label="Yield" value={`${(drawerData as any).income.yield_pct || 0}%`} />
                  <MiniMetric label="Fwd Yield" value={`${(drawerData as any).income.forward_yield_pct || 0}%`} />
                  <MiniMetric label="Yield on Cost" value={(drawerData as any).income.yield_on_cost_pct ? `${(drawerData as any).income.yield_on_cost_pct}%` : '—'} color={(drawerData as any).income.yield_on_cost_pct > 5 ? 'var(--green)' : undefined} />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                  <MiniMetric label="Div Growth 5yr" value={(drawerData as any).income.dividend_growth_5yr_pct ? `${(drawerData as any).income.dividend_growth_5yr_pct}%` : 'N/A'} />
                  <MiniMetric label="Payout Safety" value={(drawerData as any).income.payout_safety || '?'} color={(drawerData as any).income.payout_safety === 'safe' ? 'var(--green)' : (drawerData as any).income.payout_safety === 'at_risk' ? 'var(--red)' : 'var(--amber)'} />
                  <MiniMetric label="Reliability" value={(drawerData as any).income.income_reliability || '?'} />
                  <MiniMetric label="% of Target" value={`${(drawerData as any).income.income_goal_contribution_pct || 0}%`} color="var(--accent)" />
                </div>
                {(drawerData as any).income.preferred_account && (
                  <div style={{ fontSize: 9, color: 'var(--text2)', marginTop: 6, padding: '4px 0', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                    Preferred account: <b style={{ color: 'var(--text1)' }}>{(drawerData as any).income.preferred_account}</b>
                    {(drawerData as any).income.expense_ratio_pct != null && <> · Expense ratio: {(drawerData as any).income.expense_ratio_pct}%</>}
                  </div>
                )}
              </div>
            )}

            {/* 4. STRATEGY CARD */}
            {drawerData?.strategy && (
              <div style={{ padding: 14, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10, marginBottom: 14 }}>
                <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', fontWeight: 700, marginBottom: 8 }}>Strategy Card (System-Generated)</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 10 }}>
                  <MiniMetric label="Price" value={drawerData.strategy.latest_price ? `$${Number(drawerData.strategy.latest_price).toFixed(2)}` : '—'} />
                  <MiniMetric label="Support" value={drawerData.strategy.support ? `$${Number(drawerData.strategy.support).toFixed(2)}` : '—'} color="var(--green)" />
                  <MiniMetric label="Resistance" value={drawerData.strategy.resistance ? `$${Number(drawerData.strategy.resistance).toFixed(2)}` : '—'} color="var(--red)" />
                  <MiniMetric label="Stop" value={drawerData.strategy.stop_loss ? `$${Number(drawerData.strategy.stop_loss).toFixed(2)}` : '—'} color="var(--amber)" />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                  <MiniMetric label="Entry" value={drawerData.strategy.ideal_entry ? `$${Number(drawerData.strategy.ideal_entry).toFixed(2)}` : '—'} />
                  <MiniMetric label="Target" value={drawerData.strategy.target_price ? `$${Number(drawerData.strategy.target_price).toFixed(2)}` : '—'} color="var(--green)" />
                  <MiniMetric label="R:R" value={drawerData.strategy.risk_reward ? String(Number(drawerData.strategy.risk_reward).toFixed(1)) : '—'}
                    color={Number(drawerData.strategy.risk_reward) >= 2 ? 'var(--green)' : Number(drawerData.strategy.risk_reward) >= 1 ? 'var(--amber)' : 'var(--red)'} />
                  <MiniMetric label="Account Fit" value={drawerData.strategy.account_fit || '—'} />
                </div>
                {drawerData.strategy.technical_summary && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 8, padding: '4px 0', borderTop: '1px solid rgba(255,255,255,0.05)' }}>{drawerData.strategy.technical_summary}</div>}
              </div>
            )}

            {/* 5. ANALYST NARRATIVES */}
            {(drawerData?.results?.length ?? 0) > 0 && (
              <>
                <SectionHeader title="Analyst Narratives" count={drawerData?.results?.length} />
                {drawerData!.results.map((r, i) => (
                  <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                      <AgentBadge agent={r.agent} status="completed" />
                      <RecBadge rec={r.recommendation} />
                      <span style={{ fontSize: 9, color: 'var(--text3)' }}>{r.confidence ? `${(r.confidence * 100).toFixed(0)}%` : ''}</span>
                      <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>{r.created_at?.slice(0, 16)}</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5, marginBottom: 4 }}>{r.summary}</div>
                    {r.reason_codes?.length ? (
                      <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginBottom: 4 }}>
                        {r.reason_codes.map((c, j) => <span key={j} style={{ fontSize: 7, padding: '1px 5px', borderRadius: 99, background: 'rgba(74,144,244,0.1)', color: 'var(--accent)' }}>{c}</span>)}
                      </div>
                    ) : null}
                    {r.full_narrative && r.full_narrative !== r.summary && (
                      <>
                        <button onClick={() => setExpandedNarrative(expandedNarrative === `${r.agent}-${i}` ? null : `${r.agent}-${i}`)}
                          style={{ fontSize: 9, color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 0', fontFamily: 'var(--sans)' }}>
                          {expandedNarrative === `${r.agent}-${i}` ? 'Collapse' : 'View full narrative'}
                        </button>
                        {expandedNarrative === `${r.agent}-${i}` && (
                          <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.7, marginTop: 6, padding: 10, background: 'rgba(255,255,255,0.02)', borderRadius: 8, whiteSpace: 'pre-wrap' }}>{r.full_narrative}</div>
                        )}
                      </>
                    )}
                  </div>
                ))}
              </>
            )}

            {/* 6. SOURCE MEMBERSHIP */}
            <SectionHeader title="Source Membership" count={drawerData?.items?.length} />
            {(drawerData?.items || []).map((i, idx) => (
              <div key={idx} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
                <SourcePill source={i.source} />
                <span style={{ color: 'var(--text2)' }}>{i.bucket || '—'}</span>
                <StatusPill status={i.status} />
                <span style={{ color: 'var(--text2)', marginLeft: 'auto' }}>score: {i.score || '—'}</span>
              </div>
            ))}

            {/* 6b. DATA QUALITY WARNING */}
            {drawerData?.data_quality_warned && (
              <div style={{ padding: 12, background: 'rgba(240,185,11,0.06)', border: '1px solid rgba(240,185,11,0.15)', borderRadius: 10, marginBottom: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--amber)', marginBottom: 6 }}>DATA QUALITY WARNING</div>
                <div style={{ fontSize: 10, color: 'var(--amber)' }}>Data quality issues detected — synthesis confidence reduced.</div>
                {(drawerData.data_quality_issues || []).map((dq, i) => (
                  <div key={i} style={{ fontSize: 9, color: 'var(--text2)', padding: '3px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                    {dq.data_quality_status}: {dq.alert_type} — {(dq.raw_text || '').slice(0, 100)}
                  </div>
                ))}
              </div>
            )}

            {/* 6c. ALERT TIMELINE */}
            {(drawerData?.alerts?.length ?? 0) > 0 && (
              <>
                <SectionHeader title="Alert Timeline" count={drawerData?.alerts?.length} />
                <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                  {drawerData!.alerts.map((a, i) => {
                    const sevColor = a.severity === 'critical' ? 'var(--red)' : a.severity === 'urgent' ? 'var(--red)' : a.severity === 'warning' ? 'var(--amber)' : 'var(--text3)'
                    const dqBad = a.data_quality_status !== 'valid' && a.data_quality_status !== 'unknown'
                    return (
                      <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 9 }}>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <span style={{ fontWeight: 700, color: sevColor, minWidth: 50 }}>{a.severity?.toUpperCase()}</span>
                          <span style={{ color: 'var(--text2)' }}>{a.alert_type.replace(/_/g, ' ')}</span>
                          {a.price ? <span style={{ color: 'var(--text1)' }}>${a.price}</span> : null}
                          {a.stop_price ? <span style={{ color: 'var(--amber)' }}>stop ${a.stop_price}</span> : null}
                          {dqBad && <span style={{ color: 'var(--red)', fontWeight: 700 }}>{a.data_quality_status.replace(/_/g, ' ')}</span>}
                          <span style={{ color: 'var(--text3)', marginLeft: 'auto', whiteSpace: 'nowrap' }}>{a.created_at?.slice(0, 16)}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </>
            )}

            {/* 7. EVENT LOG */}
            {(drawerData?.events?.length ?? 0) > 0 && (
              <>
                <SectionHeader title="Event Log" count={drawerData?.events?.length} />
                <div style={{ maxHeight: 160, overflowY: 'auto' }}>
                  {drawerData!.events.map((e, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, fontSize: 9, color: 'var(--text3)', padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                      <span style={{ fontWeight: 600, minWidth: 80 }}>{e.event_type}</span>
                      <span style={{ color: 'var(--text2)', flex: 1 }}>{e.message || ''}</span>
                      <span style={{ whiteSpace: 'nowrap' }}>{e.created_at?.slice(0, 16)}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Quick submit */}
            <div style={{ marginTop: 16, display: 'flex', gap: 6 }}>
              <button onClick={() => { setSelected(new Set([drawerSymbol])); setSubmitAgent('maria'); setTimeout(handleSubmit, 50) }} style={{ ...btnAccent, fontSize: 10 }}>Maria</button>
              <button onClick={() => { setSelected(new Set([drawerSymbol])); setSubmitAgent('steph'); setTimeout(handleSubmit, 50) }} style={{ ...btnAccent, fontSize: 10 }}>Steph</button>
              <button onClick={() => { setSelected(new Set([drawerSymbol])); setSubmitAgent('risk_agent'); setTimeout(handleSubmit, 50) }} style={{ ...btnAccent, fontSize: 10 }}>Risk</button>
              <button onClick={() => { setSelected(new Set([drawerSymbol])); setSubmitAgent('full_chain'); setTimeout(handleSubmit, 50) }} style={{ ...btnGreen, fontSize: 10 }}>Full Chain</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ── Sub-components ──

function MaturityLadder({ maturity }: { maturity: MaturitySummary }) {
  const stages = [
    { key: 'raw_data_only', label: 'Raw' },
    { key: 'strategy_card_ready', label: 'Strategy' },
    { key: 'routed', label: 'Routed' },
    { key: 'specialist_review_partial', label: 'Partial' },
    { key: 'specialist_review_complete', label: 'Reviewed' },
    { key: 'final_synthesis_complete', label: 'Synthesis' },
  ]
  const currentIdx = stages.findIndex(s => s.key === maturity.analysis_stage)
  const isFailed = maturity.analysis_stage === 'failed'

  return (
    <div>
      <div style={{ display: 'flex', gap: 2, marginBottom: 10 }}>
        {stages.map((s, i) => {
          const done = i <= currentIdx && !isFailed
          const current = i === currentIdx && !isFailed
          return (
            <div key={s.key} style={{ flex: 1, textAlign: 'center' }}>
              <div style={{ height: 4, borderRadius: 2, background: done ? 'var(--green)' : isFailed && i <= 0 ? 'var(--red)' : 'rgba(255,255,255,0.06)' }} />
              <div style={{ fontSize: 7, marginTop: 3, color: current ? 'var(--green)' : done ? 'var(--text2)' : 'var(--text3)', fontWeight: current ? 700 : 400 }}>{s.label}</div>
            </div>
          )
        })}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {(['maria', 'steph', 'risk', 'tax'] as const).map(agent => {
          const st = maturity.agent_statuses[agent] || 'not_required'
          if (st === 'not_required') return null
          return <AgentBadge key={agent} agent={agent} status={st} />
        })}
        <AgentBadge agent="synthesis" status={maturity.final_synthesis_status} />
      </div>
    </div>
  )
}

function AgentBadge({ agent, status }: { agent: string; status: string }) {
  const colors: Record<string, [string, string]> = {
    completed: ['rgba(14,203,129,0.12)', 'var(--green)'],
    processing: ['rgba(74,144,244,0.12)', 'var(--accent)'],
    queued: ['rgba(240,185,11,0.1)', 'var(--amber)'],
    required: ['rgba(255,255,255,0.04)', 'var(--text3)'],
    failed: ['rgba(246,70,93,0.12)', 'var(--red)'],
    pending: ['rgba(255,255,255,0.04)', 'var(--text3)'],
    not_required: ['transparent', 'var(--text3)'],
  }
  const [bg, color] = colors[status] || colors.not_required
  const icon = status === 'completed' ? '\u2713' : status === 'failed' ? '\u2717' : status === 'processing' ? '\u25CF' : ''
  const label = agent === 'risk_agent' ? 'risk' : agent === 'tax_agent' ? 'tax' : agent
  return <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 6px', borderRadius: 99, background: bg, color, textTransform: 'uppercase' }}>{icon} {label}</span>
}

function AgentBadges({ maria, steph, risk, tax, synthesis }: { maria?: string | null; steph?: string | null; risk?: string | null; tax?: string | null; synthesis?: string | null }) {
  const badges = [
    { agent: 'M', status: maria },
    { agent: 'S', status: steph },
    { agent: 'R', status: risk },
    { agent: 'T', status: tax },
    { agent: '\u03A3', status: synthesis },
  ].filter(b => b.status && b.status !== 'not_required' && b.status !== 'pending')

  if (!badges.length) return <span style={{ color: 'var(--text3)', fontSize: 9 }}>—</span>

  return (
    <div style={{ display: 'flex', gap: 2 }}>
      {badges.map((b, i) => {
        const color = b.status === 'completed' ? 'var(--green)' : b.status === 'failed' ? 'var(--red)' : b.status === 'processing' ? 'var(--accent)' : b.status === 'queued' ? 'var(--amber)' : 'var(--text3)'
        return (
          <span key={i} title={`${b.agent}: ${b.status}`}
            style={{ fontSize: 8, fontWeight: 700, width: 16, height: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4, background: `color-mix(in srgb, ${color} 12%, transparent)`, color }}>
            {b.agent}
          </span>
        )
      })}
    </div>
  )
}

function SourceBadges({ sources, onFilter }: { sources: string[]; onFilter: (s: string) => void }) {
  const map: Record<string, [string, string, string]> = {
    portfolio: ['P', 'rgba(14,203,129,0.12)', 'var(--green)'],
    ai_discovered: ['D', 'rgba(167,139,250,0.12)', 'var(--purple)'],
    ai_watchlist: ['W', 'rgba(74,144,244,0.12)', 'var(--accent)'],
    personal_watchlist: ['*', 'rgba(240,185,11,0.12)', 'var(--amber)'],
  }
  return (
    <div style={{ display: 'flex', gap: 2 }} onClick={e => e.stopPropagation()}>
      {sources.map(s => {
        const [label, bg, color] = map[s] || ['?', 'rgba(255,255,255,0.06)', 'var(--text3)']
        return (
          <span key={s} title={s.replace(/_/g, ' ')} onClick={() => onFilter(s)}
            style={{ fontSize: 8, fontWeight: 700, width: 16, height: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4, background: bg, color, cursor: 'pointer' }}>
            {label}
          </span>
        )
      })}
    </div>
  )
}

function StageBadge({ stage }: { stage?: string | null }) {
  if (!stage) return <span style={{ color: 'var(--text3)', fontSize: 9 }}>—</span>
  const labels: Record<string, [string, string]> = {
    raw_data_only: ['RAW', 'var(--text3)'],
    strategy_card_ready: ['STRATEGY', 'var(--text2)'],
    routed: ['ROUTED', 'var(--amber)'],
    specialist_review_partial: ['PARTIAL', 'var(--amber)'],
    specialist_review_complete: ['REVIEWED', 'var(--accent)'],
    full_chain_complete: ['FULL CHAIN', 'var(--accent)'],
    final_synthesis_complete: ['SYNTHESIZED', 'var(--green)'],
    needs_iteration: ['NEEDS WORK', 'var(--amber)'],
    failed: ['FAILED', 'var(--red)'],
  }
  const [label, color] = labels[stage] || ['?', 'var(--text3)']
  return <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 6px', borderRadius: 99, background: `color-mix(in srgb, ${color} 10%, transparent)`, color, textTransform: 'uppercase', letterSpacing: '.03em' }}>{label}</span>
}

function SourcePill({ source }: { source: string }) {
  const colors: Record<string, [string, string]> = {
    portfolio: ['rgba(14,203,129,0.1)', 'var(--green)'],
    ai_discovered: ['rgba(167,139,250,0.1)', 'var(--purple)'],
    ai_watchlist: ['rgba(74,144,244,0.1)', 'var(--accent)'],
    personal_watchlist: ['rgba(240,185,11,0.1)', 'var(--amber)'],
  }
  const [bg, color] = colors[source] || ['rgba(255,255,255,0.06)', 'var(--text2)']
  return <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 99, background: bg, color }}>{source?.replace(/_/g, ' ')}</span>
}

function StatusPill({ status }: { status: string }) {
  const color = status === 'researched' ? 'var(--green)' : status === 'queued' ? 'var(--amber)' : status === 'removed' ? 'var(--red)' : 'var(--text2)'
  return <span style={{ fontSize: 9, fontWeight: 600, padding: '2px 6px', borderRadius: 99, background: `color-mix(in srgb, ${color} 12%, transparent)`, color }}>{status}</span>
}

function StrategyPill({ type }: { type?: string | null }) {
  if (!type) return <span style={{ color: 'var(--text3)', fontSize: 9 }}>—</span>
  const colors: Record<string, string> = { income: 'var(--green)', defense_thesis: 'var(--amber)', speculative_growth: 'var(--red)', growth_etf: 'var(--accent)', core_holding: 'var(--text1)' }
  const c = colors[type] || 'var(--text2)'
  return <span style={{ fontSize: 9, fontWeight: 600, padding: '2px 6px', borderRadius: 99, background: `color-mix(in srgb, ${c} 10%, transparent)`, color: c }}>{type.replace(/_/g, ' ')}</span>
}

function RecBadge({ rec }: { rec?: string | null }) {
  if (!rec) return <span style={{ color: 'var(--text3)', fontSize: 9 }}>—</span>
  return <span style={{ fontSize: 9, fontWeight: 700, color: recColor(rec), padding: '1px 6px', borderRadius: 99, background: `color-mix(in srgb, ${recColor(rec)} 10%, transparent)` }}>{rec}</span>
}

function DecisionBadge({ rec, qaStatus, actionable }: { rec?: string | null; qaStatus?: string | null; actionable?: boolean | null }) {
  if (actionable && rec) {
    return <RecBadge rec={rec} />
  }
  // Not actionable — show QA status instead of recommendation
  const labels: Record<string, [string, string]> = {
    partial_review: ['PARTIAL', 'var(--amber)'],
    conflicting_agents: ['CONFLICT', 'var(--red)'],
    missing_required_agent: ['MISSING', 'var(--text3)'],
    data_quality_warning: ['DQ WARN', 'var(--amber)'],
    data_quality_blocked: ['DQ BLOCK', 'var(--red)'],
    tiny_position_low_priority: ['LOW PRI', 'var(--text3)'],
    stale_analysis: ['STALE', 'var(--text3)'],
    needs_human_review: ['REVIEW', 'var(--red)'],
    pending: ['PENDING', 'var(--text3)'],
  }
  const [label, color] = labels[qaStatus || 'pending'] || ['—', 'var(--text3)']
  return <span style={{ fontSize: 8, fontWeight: 700, color, padding: '1px 6px', borderRadius: 99, background: `color-mix(in srgb, ${color} 10%, transparent)`, textTransform: 'uppercase' }}>{label}</span>
}

function SafetyBadge({ safety }: { safety: string }) {
  const m: Record<string, [string, string]> = {
    safe: ['SAFE', 'var(--green)'],
    unsafe: ['UNSAFE', 'var(--red)'],
    blocked: ['BLOCKED', 'var(--red)'],
    pending: ['PENDING', 'var(--text3)'],
  }
  const [label, color] = m[safety] || [safety, 'var(--text3)']
  return <span style={{ fontSize: 10, fontWeight: 800, color, padding: '2px 10px', borderRadius: 99, background: `color-mix(in srgb, ${color} 12%, transparent)`, textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</span>
}

function QaStatusBadge({ status }: { status: string }) {
  const labels: Record<string, [string, string]> = {
    actionable: ['ACTIONABLE', 'var(--green)'],
    partial_review: ['PARTIAL REVIEW', 'var(--amber)'],
    conflicting_agents: ['CONFLICTING AGENTS', 'var(--red)'],
    missing_required_agent: ['MISSING REQUIRED AGENT', 'var(--amber)'],
    data_quality_warning: ['DATA QUALITY WARNING', 'var(--amber)'],
    data_quality_blocked: ['DATA QUALITY BLOCKED', 'var(--red)'],
    tiny_position_low_priority: ['TINY POSITION LOW PRIORITY', 'var(--text3)'],
    stale_analysis: ['STALE ANALYSIS', 'var(--text3)'],
    needs_human_review: ['NEEDS HUMAN REVIEW', 'var(--red)'],
    unsafe: ['UNSAFE', 'var(--red)'],
    blocked: ['BLOCKED', 'var(--red)'],
    pending: ['PENDING', 'var(--text3)'],
  }
  const [label, color] = labels[status] || [status, 'var(--text3)']
  return <span style={{ fontSize: 9, fontWeight: 700, color, padding: '2px 8px', borderRadius: 99, background: `color-mix(in srgb, ${color} 10%, transparent)`, textTransform: 'uppercase', letterSpacing: '.03em' }}>{label}</span>
}

function MiniMetric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color: color || 'var(--text0)', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

function recColor(rec?: string | null): string {
  if (!rec) return 'var(--text3)'
  const r = rec.toUpperCase()
  if (r.includes('BUY') || r.includes('ADD') || r.includes('STRONG')) return 'var(--green)'
  if (r.includes('HOLD') || r.includes('NEUTRAL')) return 'var(--amber)'
  if (r.includes('SELL') || r.includes('AVOID') || r.includes('TRIM')) return 'var(--red)'
  return 'var(--text2)'
}

const th: React.CSSProperties = { padding: '6px 8px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', textAlign: 'left', whiteSpace: 'nowrap' }
const td: React.CSSProperties = { padding: '7px 8px', fontSize: 11, color: 'var(--text1)' }
const selStyle: React.CSSProperties = { padding: '5px 10px', fontSize: 10, background: 'var(--bg1)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, color: 'var(--text1)', fontFamily: 'var(--sans)' }
const btnAccent: React.CSSProperties = { padding: '6px 16px', fontSize: 10, fontWeight: 700, border: '1px solid var(--accent)', borderRadius: 8, background: 'rgba(74,144,244,0.08)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'var(--sans)' }
const btnGreen: React.CSSProperties = { padding: '6px 16px', fontSize: 10, fontWeight: 700, border: '1px solid var(--green)', borderRadius: 8, background: 'rgba(14,203,129,0.08)', color: 'var(--green)', cursor: 'pointer', fontFamily: 'var(--sans)' }
