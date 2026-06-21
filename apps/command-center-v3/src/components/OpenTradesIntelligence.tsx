import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from './DetailDrawer'
import { useProAnalystMap } from './ProAnalystPill'
import PositionDecisionCard from './PositionDecisionCard'

const panel = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 14 } as const
const sel = { fontSize: 11, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: '#f8fafc' } as const
const GREEN = '#22c55e', RED = '#ef4444', AMBER = '#f59e0b', BLUE = '#60a5fa', TEXT0 = '#f8fafc', TEXT2 = '#cbd5e1', MUTED = '#94a3b8'

export default function OpenTradesIntelligence({ onDrill, focusSymbol }: { onDrill: (c: DrillContext) => void; focusSymbol?: string }) {
  const { data, loading, error } = useApi<any>('/api/v2/open-trades/intelligence', 60_000)
  // Deep-link from a Reports stop action: ?symbol=XXX focuses JUST that position's decision card (with the
  // Stage 2c protective-stop ARM + Ignore-1-week controls), with a banner to clear back to all.
  const [focus, setFocus] = useState((focusSymbol || '').toUpperCase())
  const { data: llmCov } = useApi<any>('/api/v2/portfolio/llm-coverage', 300_000)
  const { data: scards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const paMap = useProAnalystMap()
  const coverage: Record<string, any[]> = (llmCov as any)?.coverage ?? {}
  const protection: Record<string, any> = (llmCov as any)?.protection ?? {}
  const cardMap: Record<string, any> = (scards as any)?.cards ?? {}
  const [f, setF] = useState<any>({ account: 'all', broker: 'all', strategy: 'all', sector: 'all', rsi: 'all', protection: 'all', pnl: 'all', sort: 'priority', quick: 'all' })
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const set = (k: string, v: string) => setF({ ...f, [k]: v })

  const positions: any[] = data?.positions ?? []
  const summary = data?.summary ?? {}
  const flt = data?.filters ?? {}
  const excluded: any[] = data?.excluded_items ?? []

  const visible = useMemo(() => {
    let v = positions.filter(p => {
      if (f.account !== 'all' && p.account !== f.account) return false
      if (f.broker !== 'all' && p.broker !== f.broker) return false
      if (f.strategy !== 'all' && p.strategy !== f.strategy) return false
      if (f.sector !== 'all' && p.sector_relative?.sector !== f.sector) return false
      if (f.rsi !== 'all' && p.technical?.rsi_bucket !== f.rsi) return false
      if (f.protection !== 'all' && !p.protection?.[f.protection]) return false
      if (f.pnl === 'winners' && !(p.unrealized_pnl > 0)) return false
      if (f.pnl === 'losers' && !(p.unrealized_pnl < 0)) return false
      if (f.pnl === 'below_entry' && !p.protection?.below_entry) return false
      const rf = p.risk_flags ?? [], of = p.opportunity_flags ?? []
      switch (f.quick) {
        case 'needs_protection': if (p.operator_decision !== 'Needs protection review' && !rf.includes('large_gain_unprotected') && p.protection_state === 'protected') return false; break
        case 'high_priority': if (!['critical', 'high'].includes(p.operator_priority)) return false; break
        case 'watchlist': if (!['watchlist', 'directive'].includes(p.watchlist_state)) return false; break
        case 'data_stale': if (p.data_freshness !== 'stale') return false; break
        case 'basis_issue': if (p.basis_quality !== 'unknown' && p.basis_quality !== 'owner_provided') return false; break
        case 'news_fresh': if (p.news_freshness !== 'fresh') return false; break
        case 'trailing': if (!of.includes('trailing_candidate')) return false; break
        case 'large_gain': if (!rf.includes('large_gain_unprotected') && (p.unrealized_pnl_pct ?? 0) < 25) return false; break
        case 'underperforming': if (!(p.sector_relative?.vs_sector_5d < -1) && !(p.unrealized_pnl_pct < 0)) return false; break
      }
      return true
    })
    const PRANK: any = { critical: 3, high: 2, medium: 1, low: 0 }
    const g = (p: any): number | string => {
      switch (f.sort) {
        case 'priority': return PRANK[p.operator_priority] ?? 0
        case 'risk': return (p.risk_flags ?? []).length
        case 'unprotected_gain': return (p.risk_flags ?? []).includes('large_gain_unprotected') ? (p.unrealized_pnl_pct ?? 0) : -1e9
        case 'pnl': return p.unrealized_pnl ?? -1e9
        case 'rmult': return p.r_multiple ?? -1e9
        case 'rsi': return p.technical?.rsi ?? -1
        case 'news': return -(p.latest_news_age_hours ?? 1e9)
        case 'mktval': return p.market_value ?? -1
        case 'today': return p.today_move_pct ?? -1e9
        case 'watchlist': return ({ directive: 2, watchlist: 1, none: 0 } as any)[p.watchlist_state] ?? 0
        case 'symbol': return p.symbol
        default: return 0
      }
    }
    return [...v].sort((a, b) => f.sort === 'symbol' ? String(g(a)).localeCompare(String(g(b))) : (Number(g(b)) - Number(g(a))))
  }, [positions, f])
  const focusMatch = focus && visible.some(p => String(p.symbol || '').toUpperCase() === focus)
  const shown = focusMatch ? visible.filter(p => String(p.symbol || '').toUpperCase() === focus) : visible

  if (loading && !data) return <div style={{ ...panel, color: TEXT2 }}>Loading position intelligence…</div>
  if (error) return <div style={{ ...panel, borderColor: RED, color: RED }}>Intelligence unavailable: {error}</div>

  const Dd = ({ label, v, onPick }: any) => <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>{label}<select style={sel} value={f[v]} onChange={e => onPick(e.target.value)}><option value="all">all</option>{(flt[label === 'RSI' ? 'technical_buckets' : label === 'Protection' ? 'protection_states' : label.toLowerCase() + 's'] ?? []).map((o: string) => <option key={o} value={o}>{o}</option>)}</select></label>

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
    <div style={{ ...panel, display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center' }}>
      <div><div style={{ fontSize: 22, fontWeight: 900, color: TEXT0 }}>{visible.length}<span style={{ fontSize: 12, color: MUTED }}> / {summary.total_positions} positions</span></div><div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase' }}>shown / total</div></div>
      <Stat label="Unrealized P&L" v={fmt$(summary.total_unrealized_pnl ?? 0)} c={(summary.total_unrealized_pnl ?? 0) >= 0 ? GREEN : RED} />
      <Stat label="Near stop" v={summary.risk_counts?.near_stop ?? 0} c={summary.risk_counts?.near_stop ? RED : TEXT2} />
      <Stat label="TP missing" v={summary.risk_counts?.tp_missing ?? 0} c={AMBER} />
      <Stat label="Below entry" v={summary.risk_counts?.below_entry ?? 0} c={AMBER} />
      <Stat label="Big gain unprot." v={summary.risk_counts?.large_gain_unprotected ?? 0} c={AMBER} />
      <Stat label="Hermes findings" v={summary.risk_counts?.hermes_findings ?? 0} c="#a855f7" />
      <div style={{ marginLeft: 'auto', fontSize: 9, color: MUTED, textAlign: 'right' }}>{Object.entries(summary.by_account ?? {}).map(([k, n]: any) => <div key={k}>{k}: {n}</div>)}<div style={{ marginTop: 3 }}>source: {summary.source_of_truth ?? '—'}</div></div>
    </div>

    {(summary.excluded_stale_trade_rows > 0 || summary.excluded_zero_share_rows > 0 || summary.excluded_non_ticker_rows > 0) && <details style={{ ...panel, padding: 9 }}><summary style={{ fontSize: 11, color: AMBER, cursor: 'pointer' }}>Excluded stale/invalid rows: {summary.excluded_stale_trade_rows ?? 0} · zero-share: {summary.excluded_zero_share_rows ?? 0} · non-ticker: {summary.excluded_non_ticker_rows ?? 0}</summary><div style={{ marginTop: 8, maxHeight: 220, overflow: 'auto' }}>{excluded.slice(0, 60).map((e: any, i: number) => <div key={i} style={{ fontSize: 10, color: TEXT2, padding: '2px 0' }}><span style={{ color: MUTED }}>{e.account ?? '—'}</span> · <b>{e.symbol ?? '—'}</b> · {e.reason}<span style={{ color: MUTED }}> · {e.source}</span></div>)}</div></details>}

    <div style={{ ...panel, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
      <Dd label="Account" v="account" onPick={(x: string) => set('account', x)} /><Dd label="Broker" v="broker" onPick={(x: string) => set('broker', x)} /><Dd label="Strategy" v="strategy" onPick={(x: string) => set('strategy', x)} /><Dd label="Sector" v="sector" onPick={(x: string) => set('sector', x)} /><Dd label="RSI" v="rsi" onPick={(x: string) => set('rsi', x)} /><Dd label="Protection" v="protection" onPick={(x: string) => set('protection', x)} />
      <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>P&L<select style={sel} value={f.pnl} onChange={e => set('pnl', e.target.value)}><option value="all">all</option><option value="winners">winners</option><option value="losers">losers</option><option value="below_entry">below entry</option></select></label>
      <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3, marginLeft: 'auto' }}>Sort<select style={sel} value={f.sort} onChange={e => set('sort', e.target.value)}><option value="priority">priority</option><option value="risk">risk flags</option><option value="unprotected_gain">unprotected gain</option><option value="pnl">P&L</option><option value="rmult">R-multiple</option><option value="news">news freshness</option><option value="mktval">market value</option><option value="today">today move</option><option value="watchlist">watchlist/directive</option><option value="rsi">RSI</option><option value="symbol">symbol</option></select></label>
    </div>

    <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', alignItems: 'center' }}><span style={{ fontSize: 10, color: MUTED }}>account:</span>{['all', ...(flt.accounts ?? [])].map((a: string) => { const paper = String(a).toLowerCase().includes('paper'), on = f.account === a; return <button key={a} onClick={() => set('account', a)} style={{ fontSize: 10, padding: '4px 11px', borderRadius: 6, cursor: 'pointer', border: '1px solid var(--border)', background: on ? (a === 'all' || paper ? 'rgba(96,165,250,.18)' : 'rgba(255,167,38,.18)') : 'var(--bg2)', color: on ? (a === 'all' || paper ? BLUE : '#ffa726') : MUTED, fontWeight: on ? 800 : 500 }}>{a === 'all' ? 'All accounts' : `${paper ? 'PAPER' : 'REAL'} ${a.replace(/_/g, ' ')}`}{a !== 'all' && summary.by_account?.[a] != null ? ` (${summary.by_account[a]})` : ''}</button> })}</div>
    <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>{[['all', 'All'], ['needs_protection', 'Needs protection'], ['high_priority', 'High priority'], ['watchlist', 'Watchlist/directive'], ['data_stale', 'Data stale'], ['basis_issue', 'Basis issue'], ['news_fresh', 'News fresh'], ['trailing', 'Trailing candidate'], ['large_gain', 'Large gain'], ['underperforming', 'Underperforming']].map(([k, lbl]) => <button key={k} onClick={() => set('quick', k)} style={{ fontSize: 10, padding: '4px 10px', borderRadius: 6, cursor: 'pointer', border: '1px solid var(--border)', background: f.quick === k ? 'rgba(96,165,250,.18)' : 'var(--bg2)', color: f.quick === k ? BLUE : MUTED, fontWeight: f.quick === k ? 800 : 500 }}>{lbl}</button>)}</div>

    {focus && (
      <div style={{ ...panel, padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 10, fontSize: 11.5, borderColor: 'rgba(96,165,250,.35)', background: 'rgba(96,165,250,.08)', color: '#93c5fd' }}>
        <span>Focused on <b style={{ fontFamily: 'monospace', color: TEXT0 }}>{focus}</b> — its protective-stop ARM + "Ignore 1 week" controls are below.{!focusMatch ? ' (no open position for this symbol)' : ''}</span>
        <button onClick={() => setFocus('')} style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, padding: '3px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }}>show all</button>
      </div>
    )}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,minmax(620px,1fr))', gap: 16 }}>
      {shown.map(p => { const key = `${p.account}:${p.symbol}:${p.trade_id}`; return <PositionDecisionCard key={key} p={p} paMap={paMap} expanded={expanded[key] !== false} llmCov={coverage[(p.symbol || '').toUpperCase()]} protectionRec={protection[(p.symbol || '').toUpperCase()]} symCard={cardMap[(p.symbol || '').toUpperCase()]} onToggle={() => setExpanded({ ...expanded, [key]: expanded[key] === false })} onDrill={onDrill} onAction={(a: string, pos: any) => onDrill({ title: `${pos.symbol} — ${a}`, subtitle: `${pos.operator_decision} · read-only review`, endpoint: '/api/v2/open-trades/intelligence', rows: [pos], subjectType: 'position', subjectKey: pos.symbol } as any)} /> })}
    </div>
    {shown.length === 0 && <div style={{ ...panel, color: MUTED, textAlign: 'center' }}>No positions match the current filters.</div>}
    <div style={{ fontSize: 9, color: MUTED }}>Source: /api/v2/open-trades/intelligence (read-only) · price {summary.last_price_update ?? '—'} · Hermes {summary.last_hermes_update ? String(summary.last_hermes_update).slice(0, 10) : '—'} · technicals {summary.last_technical_update ?? '—'}</div>
  </div>
}

function Stat({ label, v, c }: any) { return <div><div style={{ fontSize: 17, fontWeight: 900, color: c }}>{v}</div><div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase' }}>{label}</div></div> }
