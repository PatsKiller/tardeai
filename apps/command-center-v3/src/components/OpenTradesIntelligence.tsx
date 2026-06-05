import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from './DetailDrawer'

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
  const [f, setF] = useState<any>({ account: 'all', broker: 'all', strategy: 'all', sector: 'all', rsi: 'all', protection: 'all', pnl: 'all', sort: 'risk' })
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
      return true
    })
    const s = f.sort
    const g = (p: any): number | string => {
      switch (s) {
        case 'risk': return ({ alert: 2, watch: 1, ok: 0 } as any)[p.action_state?.level] ?? 0
        case 'pnl': return p.unrealized_pnl ?? -1e9
        case 'rmult': return p.r_multiple ?? -1e9
        case 'rsi': return p.technical?.rsi ?? -1
        case 'news': return -(p.news?.[0]?.age_hours ?? 1e9)
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
        <div><div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{visible.length}<span style={{ fontSize: 11, color: 'var(--text3)' }}> / {summary.total_positions} positions</span></div></div>
        <Stat label="Unrealized P&L" v={fmt$(summary.total_unrealized_pnl ?? 0)} c={(summary.total_unrealized_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444'} />
        <Stat label="Near stop" v={summary.risk_counts?.near_stop ?? 0} c={summary.risk_counts?.near_stop ? '#ef4444' : 'var(--text2)'} />
        <Stat label="TP missing" v={summary.risk_counts?.tp_missing ?? 0} c="#f59e0b" />
        <Stat label="Below entry" v={summary.risk_counts?.below_entry ?? 0} c="#f59e0b" />
        <Stat label="Big gain unprot." v={summary.risk_counts?.large_gain_unprotected ?? 0} c="#f59e0b" />
        <Stat label="Hermes findings" v={summary.risk_counts?.hermes_findings ?? 0} c="#a855f7" />
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
          <select style={sel} value={f.sort} onChange={e => set('sort', e.target.value)}><option value="risk">risk</option><option value="pnl">P&L</option><option value="rmult">R-multiple</option><option value="rsi">RSI</option><option value="news">news recency</option><option value="symbol">symbol</option></select>
        </label>
      </div>

      {/* CARDS */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(380px,1fr))', gap: 12 }}>
        {visible.map(p => {
          const t = p.technical || {}, sr = p.sector_relative || {}, pr = p.protection || {}, as_ = p.action_state || {}
          const key = `${p.account}:${p.symbol}:${p.trade_id}`
          const exp = expanded[key]
          return (
            <div key={key} style={{ ...card, borderLeft: `3px solid ${lvlColor(as_.level)}` }}>
              {/* header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)' }}>{p.symbol}</span>
                  <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 6 }}>{p.shares} sh · {p.hold_duration ?? '—'}</span>
                </div>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                  <span style={chip('var(--bg2)', 'var(--text2)')}>{p.account}</span>
                  <span style={chip('var(--bg2)', 'var(--text3)')}>{p.broker}/{p.environment}</span>
                </div>
              </div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{p.strategy ?? '—'}</div>

              {/* P&L + plan */}
              <div style={{ display: 'flex', gap: 12, marginTop: 8, alignItems: 'baseline' }}>
                {p.unrealized_pnl != null ? (
                  <>
                    <span style={{ fontSize: 16, fontWeight: 700, color: p.unrealized_pnl >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(p.unrealized_pnl)}</span>
                    <span style={{ fontSize: 12, color: (p.unrealized_pnl_pct ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{pct(p.unrealized_pnl_pct)}</span>
                  </>
                ) : (
                  <>
                    <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{fmt$(p.market_value ?? 0)}</span>
                    <span style={{ fontSize: 9, color: '#f59e0b' }}>{p.basis_warning === 'no_cost_basis' ? 'no cost basis' : 'basis unverified'}</span>
                  </>
                )}
                {p.today_move_pct != null && <span style={{ fontSize: 10, color: 'var(--text3)' }}>today {pct(p.today_move_pct)}</span>}
                {p.r_multiple != null && <span style={{ fontSize: 10, color: 'var(--text3)' }}>{num(p.r_multiple, 1)}R</span>}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 6, fontFamily: 'monospace' }}>
                {p.basis_kind === 'avg_cost' ? 'avg cost' : 'entry'} {p.basis_reliable ? num(p.entry_price) : 'n/a'} · now {num(p.current_price)}
                {p.stop_price != null ? ` · stop ${num(p.stop_price)}` : ''}
                {p.target_price ? ` · tgt ${num(p.target_price)}` : ''}
                {p.basis_reliable && p.cost_basis != null ? ` · basis ${fmt$(p.cost_basis)}` : ''}
              </div>

              {/* technical + protection chips */}
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 8 }}>
                <span style={chip('var(--bg2)', rsiColor(t.rsi_bucket))}>RSI {t.rsi != null ? num(t.rsi, 0) : '—'} {t.rsi_bucket}</span>
                <span style={chip('var(--bg2)', t.trend_label === 'bullish' ? '#22c55e' : t.trend_label === 'bearish' ? '#ef4444' : 'var(--text2)')}>{t.trend_label}</span>
                {t.stale && <span style={chip('rgba(245,158,11,.15)', '#f59e0b')}>technicals stale</span>}
                {pr.tp_missing && p.basis_kind !== 'avg_cost' && <span style={chip('rgba(245,158,11,.15)', '#f59e0b')}>TP missing</span>}
                {pr.below_entry && <span style={chip('rgba(245,158,11,.15)', '#f59e0b')}>{p.basis_kind === 'avg_cost' ? 'below cost' : 'below entry'}</span>}
                {pr.stop_near && <span style={chip('rgba(239,68,68,.15)', '#ef4444')}>stop near</span>}
                {pr.trailing_candidate && <span style={chip('rgba(96,165,250,.15)', '#60a5fa')}>trailing candidate</span>}
                {p.hermes?.alert_count_24h > 0 && <span style={chip('rgba(239,68,68,.15)', '#ef4444')}>Hermes alert</span>}
                {p.hermes?.disagreement && <span style={chip('rgba(168,85,247,.15)', '#a855f7')}>Hermes disagree</span>}
              </div>

              {/* action + inline protection */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
                <span style={{ fontSize: 10, fontWeight: 600, color: lvlColor(as_.level) }}>▸ {as_.label}</span>
                <div style={{ display: 'flex', gap: 8 }}>
                  {pr.option_count > 0 && <span style={{ fontSize: 9, color: '#60a5fa' }}>{pr.option_count} protection opt</span>}
                  <span onClick={() => setExpanded({ ...expanded, [key]: !exp })} style={{ fontSize: 9, color: 'var(--text3)', cursor: 'pointer', textDecoration: 'underline' }}>{exp ? 'less' : 'more intelligence'}</span>
                  <span onClick={() => onDrill({ title: `${p.symbol} — ${p.account}`, subtitle: `${p.strategy ?? ''} · ${p.broker}/${p.environment}`, endpoint: '/api/v2/open-trades/intelligence', rows: [p] } as any)} style={{ fontSize: 9, color: '#60a5fa', cursor: 'pointer', textDecoration: 'underline' }}>drill</span>
                </div>
              </div>

              {/* expanded: news + sector */}
              {exp && (
                <div style={{ marginTop: 8, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text2)', marginBottom: 4 }}>News & Research</div>
                  {(p.news ?? []).length === 0 && <div style={{ fontSize: 9, color: 'var(--text3)' }}>No recent research surfaced.</div>}
                  {(p.news ?? []).slice(0, 4).map((n: any, i: number) => (
                    <div key={i} style={{ fontSize: 9, marginBottom: 4, display: 'flex', gap: 5, alignItems: 'baseline' }}>
                      <span style={srcBadge(n.source)}>{n.source}</span>
                      {n.url ? <a href={n.url} target="_blank" rel="noopener noreferrer" style={{ color: '#60a5fa', textDecoration: 'none', flex: 1 }}>{(n.title || '').slice(0, 70)}</a> : <span style={{ color: 'var(--text2)', flex: 1 }}>{(n.title || '').slice(0, 70)}</span>}
                      {n.age_hours != null && <span style={{ color: 'var(--text3)' }}>{Math.round(n.age_hours)}h</span>}
                    </div>
                  ))}
                  <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text2)', margin: '8px 0 4px' }}>Sector-relative</div>
                  {sr.sector ? (
                    <div style={{ fontSize: 9, color: 'var(--text2)' }}>{sr.sector} ({sr.sector_etf ?? '—'}) · {sr.label} · 5d {pct(sr.symbol_perf_5d)} vs sector {sr.vs_sector_5d != null ? pct(sr.vs_sector_5d) : '—'} vs SPY {sr.vs_spy_5d != null ? pct(sr.vs_spy_5d) : '—'}</div>
                  ) : <div style={{ fontSize: 9, color: 'var(--text3)' }}>sector data unavailable</div>}
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>
                    SMA50 {t.sma50_pct != null ? pct(t.sma50_pct) : '—'} · SMA200 {t.sma200_pct != null ? pct(t.sma200_pct) : '—'} · RVOL {t.rvol ?? '—'} · {t.adx_regime ?? ''}
                    {p.hermes?.latest_research_at && ` · Hermes ${String(p.hermes.latest_research_at).slice(0, 10)}`}
                  </div>
                </div>
              )}
            </div>
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

function Stat({ label, v, c }: any) {
  return <div><div style={{ fontSize: 14, fontWeight: 700, color: c }}>{v}</div><div style={{ fontSize: 8, color: 'var(--text3)' }}>{label}</div></div>
}
