import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from './DetailDrawer'
import { useProAnalystMap } from './ProAnalystPill'
import PositionDecisionCard from './PositionDecisionCard'

// v3 Open Trades — actionable position intelligence (READ-ONLY). Consumes the aggregate
// /api/v2/open-trades/intelligence endpoint (all accounts) with client-side filter/sort.

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }
const sel = { fontSize: 11, padding: '4px 7px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text0)' }
const chip = (bg: string, fg: string) => ({ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: bg, color: fg, whiteSpace: 'nowrap' as const })
const rsiColor = (b: string) => b === 'oversold' ? '#22c55e' : b === 'overbought' ? '#ef4444' : b === 'missing' ? 'var(--text3)' : '#60a5fa'
const lvlColor = (l: string) => l === 'alert' ? '#ef4444' : l === 'watch' ? '#f59e0b' : '#22c55e'
const num = (v: any, d = 2) => (v == null ? '—' : Number(v).toFixed(d))
const pct = (v: any) => (v == null ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`)
const srcBadge = (s: string) => {
  const m: any = { hermes: ['rgba(168,85,247,.15)', '#a855f7'], hermes_alert: ['rgba(239,68,68,.15)', '#ef4444'], tradeai: ['rgba(96,165,250,.15)', '#60a5fa'] }
  const [bg, fg] = m[s] || ['var(--bg2)', 'var(--text2)']
  return chip(bg, fg)
}

export default function OpenTradesIntelligence({ onDrill }: { onDrill: (c: DrillContext) => void }) {
  const { data, loading, error } = useApi<any>('/api/v2/open-trades/intelligence', 60_000)
  // LLM provenance + stop/trail advisories (operator 2026-06-12: badges belong HERE, where
  // protection gets reviewed — not only on Portfolio holdings)
  const { data: llmCov } = useApi<any>('/api/v2/portfolio/llm-coverage', 300_000)
  const coverage: Record<string, any[]> = (llmCov as any)?.coverage ?? {}
  const protection: Record<string, any> = (llmCov as any)?.protection ?? {}
  const paMap = useProAnalystMap()
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
      // quick action-item filters (use the enriched decision fields)
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
    const s = f.sort
    const g = (p: any): number | string => {
      switch (s) {
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
    v = [...v].sort((a, b) => s === 'symbol' ? String(g(a)).localeCompare(String(g(b))) : (Number(g(b)) - Number(g(a))))
    return v
  }, [positions, f])

  if (loading && !data) return <div style={{ ...card, color: 'var(--text2)' }}>Loading position intelligence…</div>
  if (error) return <div style={{ ...card, borderColor: '#ef4444', color: '#ef4444' }}>Intelligence unavailable: {error}</div>

  const Dd = ({ label, v, onPick }: any) => (
    <label style={{ fontSize: 10, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>{label}
      <select style={sel} value={f[v]} onChange={e => onPick(e.target.value)}>
        <option value="all">all</option>
        {(flt[label === 'RSI' ? 'technical_buckets' : label === 'Protection' ? 'protection_states' : label.toLowerCase() + 's'] ?? []).map((o: string) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* SUMMARY HEADER */}
      <div style={{ ...card, display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'center' }}>
        <div title="Positions shown (after filters) / total positions across all accounts (holdings + paper trades)." style={{ cursor: 'help' }}><div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{visible.length}<span style={{ fontSize: 11, color: 'var(--text3)' }}> / {summary.total_positions} positions ⓘ</span></div></div>
        <Stat label="Unrealized P&L" v={fmt$(summary.total_unrealized_pnl ?? 0)} c={(summary.total_unrealized_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444'} tip="Total mark-to-market gain/loss across the shown positions (current value − cost basis). Not yet realized." />
        <Stat label="Near stop" v={summary.risk_counts?.near_stop ?? 0} c={summary.risk_counts?.near_stop ? '#ef4444' : 'var(--text2)'} tip="Positions trading close to their stop-loss — at risk of being stopped out soon." />
        <Stat label="TP missing" v={summary.risk_counts?.tp_missing ?? 0} c="#f59e0b" tip="Open positions with no take-profit target set — gains aren't being locked in on the way up." />
        <Stat label="Below entry" v={summary.risk_counts?.below_entry ?? 0} c="#f59e0b" tip="Positions currently priced below their entry (sitting at an unrealized loss)." />
        <Stat label="Big gain unprot." v={summary.risk_counts?.large_gain_unprotected ?? 0} c="#f59e0b" tip="Positions up significantly but with no profit protection (stop still below entry) — the gain could give back." />
        <Stat label="Hermes findings" v={summary.risk_counts?.hermes_findings ?? 0} c="#a855f7" tip="Count of advisory research findings from the Hermes fleet relevant to these positions." />
        <div style={{ marginLeft: 'auto', fontSize: 8, color: 'var(--text3)', textAlign: 'right' }}>
          {Object.entries(summary.by_account ?? {}).map(([k, n]: any) => <div key={k}>{k}: {n}</div>)}
          <div style={{ marginTop: 3 }}>source: {summary.source_of_truth ?? '—'}</div>
        </div>
      </div>

      {/* DIAGNOSTICS — excluded stale/invalid rows (proves the false-positive fix) */}
      {(summary.excluded_stale_trade_rows > 0 || summary.excluded_zero_share_rows > 0 || summary.excluded_non_ticker_rows > 0) && (
        <details style={{ ...card, padding: 8 }}>
          <summary style={{ fontSize: 10, color: '#f59e0b', cursor: 'pointer' }}>
            ⚠ Excluded stale trade rows: {summary.excluded_stale_trade_rows ?? 0}
            {' · '}zero-share: {summary.excluded_zero_share_rows ?? 0}
            {' · '}non-ticker CUSIPs: {summary.excluded_non_ticker_rows ?? 0}
            {' · '}cash: {summary.excluded_cash_rows ?? 0}
          </summary>
          <div style={{ marginTop: 8, maxHeight: 220, overflow: 'auto' }}>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginBottom: 4 }}>Not displayed as positions (not in current holdings / invalid). Source-of-truth = current holdings + paper positions.</div>
            {excluded.slice(0, 60).map((e: any, i: number) => (
              <div key={i} style={{ fontSize: 9, color: 'var(--text2)', padding: '1px 0' }}>
                <span style={{ color: 'var(--text3)' }}>{e.account ?? '—'}</span> · <b>{e.symbol ?? '—'}</b> · {e.reason}
                {e.stale_trade_count ? ` (${e.stale_trade_count} stale lot${e.stale_trade_count > 1 ? 's' : ''})` : ''}
                <span style={{ color: 'var(--text3)' }}> · {e.source}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* FILTER / SORT TOOLBAR */}
      <div style={{ ...card, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <Dd label="Account" v="account" onPick={(x: string) => set('account', x)} />
        <Dd label="Broker" v="broker" onPick={(x: string) => set('broker', x)} />
        <Dd label="Strategy" v="strategy" onPick={(x: string) => set('strategy', x)} />
        <Dd label="Sector" v="sector" onPick={(x: string) => set('sector', x)} />
        <Dd label="RSI" v="rsi" onPick={(x: string) => set('rsi', x)} />
        <Dd label="Protection" v="protection" onPick={(x: string) => set('protection', x)} />
        <label style={{ fontSize: 10, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>P&L
          <select style={sel} value={f.pnl} onChange={e => set('pnl', e.target.value)}><option value="all">all</option><option value="winners">winners</option><option value="losers">losers</option><option value="below_entry">below entry</option></select>
        </label>
        <label style={{ fontSize: 10, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2, marginLeft: 'auto' }}>Sort
          <select style={sel} value={f.sort} onChange={e => set('sort', e.target.value)}>
            <option value="priority">priority</option><option value="risk">risk flags</option><option value="unprotected_gain">unprotected gain</option>
            <option value="pnl">P&L</option><option value="rmult">R-multiple</option><option value="news">news freshness</option>
            <option value="mktval">market value</option><option value="today">today move</option><option value="watchlist">watchlist/directive</option>
            <option value="rsi">RSI</option><option value="symbol">symbol</option>
          </select>
        </label>
      </div>

      {/* QUICK ACCOUNT PILLS — one-tap account filter (operator request 2026-06-12) */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 9, color: 'var(--text3)' }}>account:</span>
        {['all', ...(flt.accounts ?? [])].map((a: string) => {
          const paper = String(a).toLowerCase().includes('paper')
          const on = f.account === a
          return (
            <button key={a} onClick={() => set('account', a)}
              style={{ fontSize: 10, padding: '3px 10px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)',
                background: on ? (a === 'all' ? 'rgba(96,165,250,.18)' : paper ? 'rgba(96,165,250,.18)' : 'rgba(255,167,38,.18)') : 'var(--bg2)',
                color: on ? (a === 'all' || paper ? '#60a5fa' : '#ffa726') : 'var(--text3)', fontWeight: on ? 700 : 400 }}>
              {a === 'all' ? 'All accounts' : `${paper ? '📝' : '💰'} ${a.replace(/_/g, ' ')}`}
              {a !== 'all' && summary.by_account?.[a] != null ? ` (${summary.by_account[a]})` : ''}
            </button>
          )
        })}
      </div>

      {/* QUICK ACTION-ITEM FILTERS */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {[['all', 'All'], ['needs_protection', 'Needs protection'], ['high_priority', 'High priority'], ['watchlist', 'Watchlist/directive'], ['data_stale', 'Data stale'], ['basis_issue', 'Basis issue'], ['news_fresh', 'News fresh'], ['trailing', 'Trailing candidate'], ['large_gain', 'Large gain'], ['underperforming', 'Underperforming']].map(([k, lbl]) => (
          <button key={k} onClick={() => set('quick', k)}
            style={{ fontSize: 10, padding: '3px 9px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)',
              background: f.quick === k ? 'rgba(96,165,250,.18)' : 'var(--bg2)', color: f.quick === k ? '#60a5fa' : 'var(--text3)', fontWeight: f.quick === k ? 700 : 400 }}>{lbl}</button>
        ))}
      </div>

      {/* CARDS — actionable position decision cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(400px,1fr))', gap: 12 }}>
        {visible.map(p => {
          const key = `${p.account}:${p.symbol}:${p.trade_id}`
          return (
            <PositionDecisionCard key={key} p={p} paMap={paMap}
              /* operator 2026-06-12: cards default to FULL (expanded); 'less' collapses per card */
              expanded={expanded[key] !== false}
              llmCov={coverage[(p.symbol || '').toUpperCase()]}
              protectionRec={protection[(p.symbol || '').toUpperCase()]}
              onToggle={() => setExpanded({ ...expanded, [key]: expanded[key] === false })}
              onDrill={onDrill}
              onAction={(a: string, pos: any) => onDrill({ title: `${pos.symbol} — ${a}`, subtitle: `${pos.operator_decision} · read-only review`, endpoint: '/api/v2/open-trades/intelligence', rows: [pos], subjectType: 'position', subjectKey: pos.symbol } as any)} />
          )
        })}
      </div>
      {visible.length === 0 && <div style={{ ...card, color: 'var(--text3)', textAlign: 'center' }}>No positions match the current filters.</div>}
      <div style={{ fontSize: 8, color: 'var(--text3)' }}>
        Source: /api/v2/open-trades/intelligence (read-only) · price {summary.last_price_update ?? '—'} · Hermes {summary.last_hermes_update ? String(summary.last_hermes_update).slice(0, 10) : '—'} · technicals {summary.last_technical_update ?? '—'}
      </div>
    </div>
  )
}

function Stat({ label, v, c, tip }: any) {
  return <div title={tip} style={tip ? { cursor: 'help' } : undefined}><div style={{ fontSize: 14, fontWeight: 700, color: c }}>{v}</div><div style={{ fontSize: 8, color: 'var(--text3)' }}>{label}{tip ? ' ⓘ' : ''}</div></div>
}
