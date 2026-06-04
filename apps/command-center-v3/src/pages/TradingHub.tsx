import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionPanel from '../components/ProtectionPanel'
import ProposalsRich from '../components/ProposalsRich'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trade AI', 'Open Trades', 'Proposals', 'Execution', 'Broker Recon', 'Scalp'] as const

// GO / WAIT / NO-GO decision color
const decisionColor = (d?: string) => d === 'GO' ? '#22c55e' : d === 'WAIT' ? '#f59e0b' : '#ef4444'

export default function TradingHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Trade AI')
  const [tradeFilter, setTradeFilter] = useState<'ALL' | 'GO' | 'WAIT'>('ALL')
  const [copied, setCopied] = useState<string | null>(null)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai', 60_000)
  const { data: openTrades } = useApi<any>('/api/v2/open-trades', 30_000)
  const { data: proposals } = useApi<any>('/api/v2/paper-proposals', 60_000)
  const { data: paperStatus } = useApi<any>('/api/v2/paper-status', 30_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: execQual } = useApi<any>('/api/v2/execution-quality', 120_000)
  const { data: scalpData } = useApi<any>('/api/v2/scalp/live', 120_000)
  const { data: setupAdvisory } = useApi<any>('/api/v2/atm/setup-advisory', 120_000)
  const { data: recon } = useApi<any>('/api/v2/broker-reconciliation', 120_000)

  const advMap: Record<string, any> = {}
  const advBySym: Record<string, any> = {}
  for (const a of (setupAdvisory?.advisories ?? [])) {
    advMap[String(a.proposal_id)] = a
    // Map advisory to symbol for open-position enrichment; prefer non-expired / higher-confidence
    const prev = advBySym[a.symbol]
    if (!prev || (prev.status === 'EXPIRED' && a.status !== 'EXPIRED')) advBySym[a.symbol] = a
  }
  const advColor = (f?: string) => f === 'caution' ? '#ef4444' : f === 'favorable' ? '#22c55e' : 'var(--text3)'

  const trades = openTrades?.trades ?? []
  const execList: any[] = Array.isArray(execQual) ? execQual : []
  const propList = proposals?.proposals ?? []
  const pending = propList.filter((p: any) => p.status === 'PENDING' || p.status === 'APPROVED')
  const alpaca = paperStatus?.alpaca ?? {}

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Trading</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            {trades.length} open · {pending.length} pending proposals · Alpaca {alpaca.account_status ?? '—'}
            {readiness && <span> · P-level: {readiness.level?.replace(/_/g, ' ')}</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {/* Readiness bar */}
      {readiness && (
        <div style={{ marginBottom: 14, padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, display: 'flex', gap: 20, alignItems: 'center', fontSize: 10 }}>
          <span style={{ color: 'var(--text3)' }}>Paper Readiness:</span>
          <span style={{ fontWeight: 700, color: '#f59e0b' }}>{readiness.level?.replace(/_/g, ' ')}</span>
          <span style={{ color: 'var(--text3)' }}>{readiness.closed_usable}/{readiness.target_2000} trades</span>
          <div style={{ flex: 1, height: 4, background: 'var(--bg2)', borderRadius: 2 }}>
            <div style={{ width: `${Math.min(100, readiness.pct_to_2000 ?? 0)}%`, height: '100%', background: '#f59e0b', borderRadius: 2, minWidth: 2 }} />
          </div>
          <span style={{ color: '#ef4444', fontWeight: 700, fontSize: 9 }}>LIVE BLOCKED</span>
        </div>
      )}

      {tab === 'Trade AI' && (() => {
        const tickers: any[] = (tradeAi?.tickers ?? []).slice().sort((a: any, b: any) => (b.score ?? 0) - (a.score ?? 0))
        const filtered = tradeFilter === 'ALL' ? tickers : tickers.filter((t: any) => t.decision === tradeFilter)
        const copyBoxes = (['GO', 'WAIT', 'ALL'] as const).map(type => {
          const syms = (type === 'ALL' ? tickers : tickers.filter((t: any) => t.decision === type)).map((t: any) => t.symbol)
          return { type, label: type === 'ALL' ? 'Universe' : type, syms, text: syms.join(','), color: type === 'GO' ? '#22c55e' : type === 'WAIT' ? '#f59e0b' : 'var(--text2)' }
        })
        const doCopy = (type: string, text: string) => {
          const done = () => { setCopied(type); setTimeout(() => setCopied(null), 1500) }
          if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(done)
          else { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done() }
        }
        // Source badge config (parity with v2 Source column)
        const srcCfg: Record<string, { icon: string; color: string; label: string }> = {
          social: { icon: '💬', color: '#d97706', label: 'Social' },
          portfolio: { icon: '💼', color: '#6366f1', label: 'Portfolio' },
          personal_watchlist: { icon: '👤', color: '#6366f1', label: 'Personal' },
          ai_discovered: { icon: '🤖', color: '#059669', label: 'AI' },
          ai_watchlist: { icon: '🔍', color: '#059669', label: 'AI Watch' },
          screener: { icon: '📊', color: '#0891b2', label: 'Finviz' },
        }
        const srcBadge = (t: any) => {
          const c = srcCfg[t.source || 'screener'] || srcCfg.screener
          return { ...c, label: t.source === 'social' && t.source_detail ? `Social ${t.source_detail}` : c.label }
        }
        const pctColor = (v: any) => { const n = parseFloat(v); return isNaN(n) ? 'var(--text3)' : n >= 0 ? '#22c55e' : '#ef4444' }
        const pctText = (v: any) => (v === '' || v == null) ? '—' : `${v}%`
        // Richer ticker table layout
        const gridCols = '52px 72px 1fr 60px 30px 48px 64px 58px 58px 50px 1.3fr 1fr 1.6fr'
        const runHistory: any[] = tradeAi?.run_history ?? []
        const sectors: Record<string, number> = tradeAi?.sectors ?? {}
        const sectorEntries = Object.entries(sectors).sort((a, b) => (b[1] as number) - (a[1] as number))
        const sectorMax = sectorEntries.length ? Math.max(...sectorEntries.map(e => e[1] as number)) : 1
        const runGoMax = runHistory.length ? Math.max(1, ...runHistory.map((r: any) => r.go ?? 0)) : 1
        const kpis = [
          { label: 'GO', value: tradeAi?.go_count ?? 0, color: '#22c55e' },
          { label: 'WAIT', value: tradeAi?.wait_count ?? 0, color: '#f59e0b' },
          { label: 'NO-GO', value: tradeAi?.avoid_count ?? 0, color: '#ef4444' },
          { label: 'Scanned', value: tradeAi?.ticker_count ?? tickers.length, color: 'var(--text0)' },
          { label: 'VIX', value: tradeAi?.vix != null ? Number(tradeAi.vix).toFixed(1) : '—', color: '#60a5fa' },
          { label: 'Regime', value: tradeAi?.market_regime ?? '—', color: '#a855f7' },
        ]
        return (
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Market Opportunities Scanner</div>
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                {tradeAi?.latest_run_label || tradeAi?.run_label || 'no run'}
                {tradeAi?.latest_run_timestamp && ` · ${new Date(tradeAi.latest_run_timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`}
                {tradeAi?.run_health_status && <span style={{ marginLeft: 6, color: tradeAi.run_health_status === 'healthy' ? '#22c55e' : '#f59e0b' }}>· {tradeAi.run_health_status}</span>}
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 8, margin: '10px 0 14px' }}>
              {kpis.map(k => (
                <div key={k.label} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 6px', textAlign: 'center' }}>
                  <div style={{ fontSize: 17, fontWeight: 700, color: k.color }}>{k.value}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{k.label}</div>
                </div>
              ))}
            </div>

            {/* Copy lists (GO / WAIT / Universe) — paste into broker watchlist / ToS */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              {copyBoxes.map(b => (
                <div key={b.type} style={{ flex: 1, padding: '6px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                    <span style={{ fontSize: 8, color: b.color, fontWeight: 700 }}>{b.label} ({b.syms.length})</span>
                    {b.syms.length > 0 && (
                      <button onClick={() => doCopy(b.type, b.text)} style={{
                        fontSize: 8, padding: '2px 8px', borderRadius: 4, cursor: 'pointer', fontWeight: 600,
                        border: `1px solid ${copied === b.type ? '#22c55e' : 'var(--border)'}`,
                        background: copied === b.type ? 'rgba(34,197,94,.12)' : 'var(--bg1)',
                        color: copied === b.type ? '#22c55e' : 'var(--text2)',
                      }}>{copied === b.type ? '✓ Copied' : 'Copy'}</button>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text0)', fontFamily: 'monospace', wordBreak: 'break-all', userSelect: 'all', cursor: 'text', minHeight: 16, maxHeight: 54, overflowY: 'auto' }}>
                    {b.text || '—'}
                  </div>
                </div>
              ))}
            </div>

            {/* Decision filter */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
              {(['ALL', 'GO', 'WAIT'] as const).map(f => {
                const active = tradeFilter === f
                const fc = f === 'GO' ? '#22c55e' : f === 'WAIT' ? '#f59e0b' : '#60a5fa'
                const count = f === 'ALL' ? tickers.length : tickers.filter((t: any) => t.decision === f).length
                return (
                  <button key={f} onClick={() => setTradeFilter(f)} style={{
                    padding: '4px 12px', fontSize: 10, borderRadius: 5, cursor: 'pointer', fontWeight: active ? 700 : 500,
                    border: `1px solid ${active ? fc : 'var(--border)'}`,
                    background: active ? `${fc}22` : 'var(--bg2)', color: active ? fc : 'var(--text3)', fontFamily: 'monospace',
                  }}>{f === 'ALL' ? 'Universe' : f} ({count})</button>
                )
              })}
            </div>

            <div style={{ overflowX: 'auto' }}>
            <div style={{ minWidth: 1080 }}>
            <div style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 6, fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
              <span>Decision</span><span>Source</span><span>Symbol</span><span>Score</span><span>Grd</span><span>RVOL</span><span>Price</span><span>Chg%</span><span>Gap%</span><span>Float</span><span>Sector</span><span>Social</span><span>Catalyst</span>
            </div>
            {filtered.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 12 }}>No {tradeFilter === 'ALL' ? '' : tradeFilter + ' '}tickers in the latest run.</div> :
            filtered.slice(0, 60).map((t: any, i: number) => {
              const sb = srcBadge(t)
              const country = t.country || ''
              const flag = (!country || country === '🇺🇸' || country === 'United States') ? '' : country
              const social = t.social_sentiment || ''
              const socialColor = social.includes('Very Bullish') ? '#4ade80' : social.includes('Bullish') ? '#86efac' : social.includes('Bearish') ? '#f87171' : 'var(--text3)'
              const score = t.score ?? 0
              return (
              <div key={`${t.symbol}-${i}`} onClick={() => onDrill({ title: t.symbol, subtitle: `${t.decision ?? ''} · score ${t.score ?? '—'} · ${t.sector ?? ''}`, endpoint: '/api/v2/trade-ai', rows: [t] })}
                style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 6, padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center', borderLeft: `3px solid ${decisionColor(t.decision)}` }}>
                <span style={{ fontWeight: 700, fontSize: 9, color: decisionColor(t.decision) }}>{t.decision || 'NO-GO'}</span>
                <span title={sb.label} style={{ fontSize: 8, fontWeight: 600, padding: '1px 4px', borderRadius: 3, border: `1px solid ${sb.color}40`, color: sb.color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sb.icon} {sb.label}</span>
                <div style={{ overflow: 'hidden' }}>
                  <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</span>
                  {t.decision_changed && <span title={`critic changed from ${t.original_decision}`} style={{ fontSize: 8, color: '#f59e0b', marginLeft: 4 }}>⟳</span>}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div style={{ width: 24, height: 4, background: 'var(--bg3)', borderRadius: 2, overflow: 'hidden', flexShrink: 0 }}>
                    <div style={{ width: `${Math.min(score, 50) * 2}%`, height: '100%', background: score >= 40 ? '#22c55e' : score >= 30 ? '#f59e0b' : 'var(--text3)' }} />
                  </div>
                  <span style={{ fontWeight: 600, color: score >= 40 ? '#22c55e' : score >= 30 ? '#f59e0b' : 'var(--text2)' }}>{t.score ?? '—'}</span>
                </div>
                <span style={{ fontWeight: 600, color: t.grade === 'A' ? '#22c55e' : 'var(--text2)' }}>{t.grade || '—'}</span>
                <span style={{ color: (t.rvol ?? 0) >= 5 ? '#22c55e' : 'var(--text2)' }}>{t.rvol ? Number(t.rvol).toFixed(1) + 'x' : '—'}</span>
                <span style={{ color: 'var(--text2)' }}>{t.price ? `$${Number(t.price).toFixed(2)}` : '—'}</span>
                <span style={{ color: pctColor(t.change_pct), fontWeight: 600 }}>{pctText(t.change_pct)}</span>
                <span style={{ color: pctColor(t.gap_pct) }}>{pctText(t.gap_pct)}</span>
                <span style={{ color: 'var(--text2)' }}>{t.float_m != null && t.float_m !== '' ? `${t.float_m}M` : '—'}</span>
                <span style={{ fontSize: 9, display: 'flex', flexDirection: 'column', gap: 1, overflow: 'hidden' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text1)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{flag}{flag ? ' ' : ''}{t.sector || '—'}</span>
                  {t.vs_sector_pct != null && <span style={{ fontSize: 8, color: t.vs_sector_pct >= 0 ? '#4ade80' : '#f87171' }}>vs {t.sector_etf || 'sector'}: {t.vs_sector_pct >= 0 ? '+' : ''}{t.vs_sector_pct}%</span>}
                </span>
                {social ? (
                  <span style={{ fontSize: 9, display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <span style={{ fontWeight: 600, color: socialColor }}>{social}</span>
                    {(t.social_reddit || t.social_stocktwits) ? <span style={{ fontSize: 8, color: 'var(--text3)' }}>R:{t.social_reddit || 0} ST:{t.social_stocktwits || 0}{t.social_bullish_pct != null ? ` (${Math.round(t.social_bullish_pct)}% bull)` : ''}</span> : null}
                  </span>
                ) : <span style={{ fontSize: 9, color: 'var(--text3)' }}>—</span>}
                <span style={{ fontSize: 9, color: t.disqualified ? '#fca5a5' : t.catalyst_verified === false ? '#f59e0b' : 'var(--text3)', display: 'flex', alignItems: 'center', gap: 4, overflow: 'hidden' }} title={t.catalyst}>
                  {t.disqualified && <span style={{ fontSize: 7, background: '#7f1d1d', color: '#fca5a5', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>DQ</span>}
                  {!t.disqualified && t.catalyst_verified === false && <span style={{ fontSize: 7, background: '#78350f', color: '#fcd34d', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>?</span>}
                  {!t.disqualified && t.catalyst_verified === true && <span style={{ fontSize: 7, background: '#052e16', color: '#86efac', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>V</span>}
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.catalyst || '—'}</span>
                </span>
              </div>
            )})}
            </div>
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/trade-ai (orchestrator scan: screener → enrichment → scalp critic → GO/WAIT/NO-GO). Click a row for full scan detail. Showing top {Math.min(60, filtered.length)} of {filtered.length}{tradeFilter !== 'ALL' ? ` ${tradeFilter}` : ''} by score{tradeFilter !== 'ALL' ? ` (${tickers.length} universe)` : ''}.</div>

            {/* Run History + Sector Distribution */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14 }}>
              <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Run History <span style={{ color: 'var(--text3)', fontWeight: 400 }}>({runHistory.length})</span></div>
                {runHistory.length <= 1 ? <div style={{ color: 'var(--text3)', fontSize: 10 }}>Single run only</div> : (
                  <>
                    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 60 }}>
                      {runHistory.slice().reverse().map((r: any, i: number) => (
                        <div key={i} title={`${r.label} · GO ${r.go} · WAIT ${r.wait}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
                          <div style={{ width: '100%', height: `${((r.go ?? 0) / runGoMax) * 100}%`, minHeight: (r.go ?? 0) > 0 ? 3 : 0, background: (r.go ?? 0) > 0 ? '#22c55e' : 'var(--border)', borderRadius: '2px 2px 0 0' }} />
                          <span style={{ fontSize: 7, color: 'var(--text3)', marginTop: 2, whiteSpace: 'nowrap' }}>{r.label}</span>
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                      {runHistory.map((r: any, i: number) => (
                        <div key={i} style={{ fontSize: 9, color: 'var(--text3)' }}><span style={{ fontWeight: 600, color: 'var(--text2)' }}>{r.label}</span> GO:{r.go} W:{r.wait}</div>
                      ))}
                    </div>
                  </>
                )}
              </div>
              <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Sector Distribution <span style={{ color: 'var(--text3)', fontWeight: 400 }}>({sectorEntries.length})</span></div>
                {sectorEntries.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 10 }}>No sector data available</div> : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
                    {sectorEntries.map(([sec, count]) => (
                      <div key={sec} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ width: 110, fontSize: 9, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sec}</span>
                        <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{ width: `${((count as number) / sectorMax) * 100}%`, height: '100%', background: '#60a5fa', opacity: 0.7, borderRadius: 3 }} />
                        </div>
                        <span style={{ width: 28, fontSize: 9, color: 'var(--text1)', textAlign: 'right', fontWeight: 600 }}>{count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })()}

      {tab === 'Open Trades' && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Automated Positions ({trades.length})</div>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>Unrealized {fmt$(openTrades?.data?.total_unrealized_pnl ?? openTrades?.total_unrealized_pnl, 2)} · prices {openTrades?.data?.last_updated_at ? new Date(openTrades.data.last_updated_at).toLocaleString() : '—'}</div>
          </div>
          {trades.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No open paper trades</div> :
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12, marginBottom: 12 }}>
            {trades.map((t: any) => {
              const adv = advBySym[t.symbol]
              const pnlPos = (t.pnl ?? 0) >= 0
              const entry = t.entry_price, cur = t.current_price, stop = t.stop_loss, tgt = t.target_1
              const lo = Math.min(stop || cur, entry, cur), hi = Math.max(tgt || cur, entry, cur)
              const zpos = (x: number) => hi > lo ? Math.max(0, Math.min(100, ((x - lo) / (hi - lo)) * 100)) : 50
              const heldMs = t.opened_at ? Date.now() - Date.parse(t.opened_at) : 0
              const heldStr = heldMs > 0 ? `${Math.floor(heldMs / 86400000)}d ${Math.floor((heldMs % 86400000) / 3600000)}h` : '—'
              const rsiColor = t.rsi_status === 'oversold' ? '#22c55e' : t.rsi_status === 'overbought' ? '#ef4444' : 'var(--text2)'
              return (
                <div key={t.id} onClick={() => onDrill({ title: t.symbol, subtitle: `${t.strategy_id} · R=${t.r_multiple?.toFixed(2)}`, endpoint: '/api/v2/open-trades', rows: [adv ? { ...t, setup_advisory: adv.note, setup_advisory_flag: adv.advisory_flag, setup_prior_score: adv.prior_score } : t] })}
                  style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, cursor: 'pointer' }}>
                  {/* header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                    <div>
                      <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace', fontSize: 14 }}>{t.symbol}</span>
                      <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 6 }}>{t.strategy_id} · {t.shares} sh</span>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ color: pnlPos ? '#22c55e' : '#ef4444', fontWeight: 700, fontSize: 14 }}>{fmt$(t.pnl, 2)}</div>
                      <div style={{ fontSize: 9, color: pnlPos ? '#22c55e' : '#ef4444' }}>{t.pnl_pct >= 0 ? '+' : ''}{t.pnl_pct}% · {t.r_multiple >= 0 ? '+' : ''}{t.r_multiple?.toFixed(2)}R</div>
                    </div>
                  </div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', marginBottom: 8 }}>Held {heldStr}{t.catalyst ? ` · ${t.catalyst}` : ''}</div>
                  {/* stop / now / target */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'monospace', marginBottom: 4 }}>
                    <span style={{ color: '#ef4444' }}>Stop {fmt$(stop, 2)}</span>
                    <span style={{ color: 'var(--text0)', fontWeight: 700 }}>Now {fmt$(cur, 3)}</span>
                    <span style={{ color: '#22c55e' }}>Target {tgt ? fmt$(tgt, 2) : '—'}</span>
                  </div>
                  {/* zone bar */}
                  <div style={{ position: 'relative', height: 6, background: 'linear-gradient(90deg, rgba(239,68,68,.4), rgba(120,120,120,.2), rgba(34,197,94,.4))', borderRadius: 3, margin: '6px 0 4px' }}>
                    <div title="entry" style={{ position: 'absolute', left: `${zpos(entry)}%`, top: -2, width: 2, height: 10, background: 'var(--text3)' }} />
                    <div title="current" style={{ position: 'absolute', left: `${zpos(cur)}%`, top: -3, width: 8, height: 8, marginLeft: -4, borderRadius: '50%', background: '#60a5fa', border: '1px solid var(--bg0)' }} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: 'var(--text3)', marginBottom: 8 }}>
                    <span>Stop dist {t.dist_to_stop_pct != null ? `${t.dist_to_stop_pct}%` : '—'}</span>
                    <span>Target dist {t.dist_to_target_pct != null ? `${t.dist_to_target_pct}%` : '—'}</span>
                  </div>
                  {/* technicals */}
                  <div style={{ display: 'flex', gap: 12, fontSize: 9, marginBottom: 6, flexWrap: 'wrap' }}>
                    <span style={{ color: 'var(--text3)' }}>RSI <b style={{ color: rsiColor }}>{t.rsi_status ?? '—'}{t.rsi != null ? ` ${Math.round(t.rsi)}` : ''}</b></span>
                    {t.fib?.nearest && <span style={{ color: 'var(--text3)' }}>Fib <b style={{ color: 'var(--text2)' }}>{t.fib.nearest}</b></span>}
                    {t.pct_52w_high != null && <span style={{ color: 'var(--text3)' }}>52w hi <b style={{ color: 'var(--text2)' }}>{t.pct_52w_high}%</b></span>}
                  </div>
                  {/* trail advisory + flags */}
                  <div style={{ fontSize: 8, color: 'var(--text3)', borderTop: '1px solid var(--border)', paddingTop: 6 }}>
                    <span style={{ color: t.trail_recommendation?.startsWith('use_trail') ? '#f59e0b' : 'var(--text3)' }}>Trail: {t.trail_advice}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
                    {adv && <span title={adv.note} style={{ fontSize: 8, padding: '1px 6px', borderRadius: 3, background: 'var(--bg2)', color: advColor(adv.advisory_flag) }}>{adv.advisory_flag === 'caution' ? '⚠ ' : adv.advisory_flag === 'favorable' ? '✓ ' : ''}entry ~{adv.prior_score != null ? Number(adv.prior_score).toFixed(0) : '—'}</span>}
                    {(t.risk_flags ?? []).map((f: string) => (
                      <span key={f} style={{ fontSize: 8, padding: '1px 6px', borderRadius: 3, background: 'var(--bg2)', color: f === 'consider_partial_exit' ? '#22c55e' : '#f59e0b' }}>{f.replace(/_/g, ' ')}</span>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>}
          <div style={{ fontSize: 8, color: 'var(--text3)', margin: '0 0 12px' }}>Source: /api/v2/open-trades (entry/stop/target, R-multiple, trail advisory, RSI/fib technicals) + /api/v2/atm/setup-advisory. Prices update every 2 min during market hours (position monitor) + hourly broker sync.</div>
          <ProtectionPanel onDrill={onDrill} />
        </>
      )}

      {tab === 'Proposals' && <ProposalsRich />}

      {tab === 'Execution' && execQual && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Execution Quality ({execList.length} records)</div>
          {execList.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No execution quality data</div> :
          execList.slice(0, 15).map((e: any) => (
            <div key={e.id} onClick={() => onDrill({ title: `${e.symbol} TCA`, subtitle: `fill_quality: ${e.fill_quality ?? '—'}`, endpoint: '/api/v2/execution-quality', rows: [e] })}
              style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <span style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{e.symbol}</span>
              <span style={{ color: 'var(--text2)' }}>slip: {e.slippage_pct != null ? `${e.slippage_pct.toFixed(2)}%` : '—'}</span>
              <span style={{ color: 'var(--text2)' }}>fill: {e.fill_quality ?? '—'}</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>{e.market_session ?? '—'}</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/execution-quality</div>
        </div>
      )}

      {tab === 'Broker Recon' && (() => {
        const r = recon?.data ?? recon ?? {}
        const runs = r.runs ?? []
        const items = r.items ?? []
        const latest = runs[0] ?? {}
        const stClr = (s: string) => /ok|matched|clean/i.test(s || '') ? '#22c55e' : /unmatched|mismatch|orphan|issue/i.test(s || '') ? '#ef4444' : 'var(--text3)'
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
              {[
                { k: 'Orders seen', v: latest.orders_seen ?? '—', c: 'var(--text0)' },
                { k: 'Trades matched', v: latest.trades_matched ?? '—', c: '#22c55e' },
                { k: 'Unmatched broker', v: latest.unmatched_broker_orders ?? 0, c: (latest.unmatched_broker_orders ?? 0) > 0 ? '#ef4444' : 'var(--text3)' },
                { k: 'Unmatched local', v: latest.unmatched_local_trades ?? 0, c: (latest.unmatched_local_trades ?? 0) > 0 ? '#ef4444' : 'var(--text3)' },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 8px', textAlign: 'center' }}>
                  <div style={{ fontSize: 17, fontWeight: 700, color: s.c }}>{s.v}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
                </div>
              ))}
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Reconciliation items ({items.length})</div>
              {items.length === 0 ? <div style={{ color: '#22c55e', fontSize: 11 }}>No unmatched items — broker and local in sync.</div> :
              items.slice(0, 20).map((it: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: it.symbol ?? it.broker_order_id, subtitle: it.reconciliation_state, endpoint: '/api/v2/broker-reconciliation', rows: [it] })}
                  style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr 1fr', gap: 8, padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
                  <span style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--text0)' }}>{it.symbol ?? '—'}</span>
                  <span style={{ color: stClr(it.reconciliation_state), fontSize: 9 }}>{it.reconciliation_state ?? ''}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 9 }}>{it.issue_code ?? it.broker ?? ''}</span>
                </div>
              ))}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/broker-reconciliation — DB vs Alpaca. Latest run: {latest.broker ?? ''} {latest.run_status ?? ''} {latest.started_at ? new Date(latest.started_at).toLocaleString() : ''}</div>
            </div>
          </div>
        )
      })()}

      {tab === 'Scalp' && scalpData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Scalp Live ({scalpData.count ?? 0} signals)</div>
          {(scalpData.signals ?? []).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No live scalp signals</div> :
          (scalpData.signals ?? []).slice(0, 10).map((s: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: s.symbol ?? `Signal ${i}`, subtitle: 'Scalp', endpoint: '/api/v2/scalp/live', rows: [s] })}
              style={{ padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, color: 'var(--text2)' }}>
              {s.symbol ?? JSON.stringify(s).slice(0, 80)}
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/scalp/live</div>
        </div>
      )}
    </div>
  )
}
