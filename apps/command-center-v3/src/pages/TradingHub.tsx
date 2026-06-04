import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionPanel from '../components/ProtectionPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trade AI', 'Open Trades', 'Proposals', 'Execution', 'Broker Recon', 'Scalp'] as const

// GO / WAIT / NO-GO decision color
const decisionColor = (d?: string) => d === 'GO' ? '#22c55e' : d === 'WAIT' ? '#f59e0b' : '#ef4444'

export default function TradingHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Trade AI')
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
            <div style={{ display: 'grid', gridTemplateColumns: '0.5fr 1fr 0.6fr 0.6fr 0.7fr 0.6fr 1.4fr 0.8fr', fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
              <span>Decision</span><span>Symbol</span><span>Score</span><span>RVOL</span><span>Price</span><span>Chg%</span><span>Catalyst</span><span>Critic</span>
            </div>
            {tickers.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 12 }}>No scan tickers in the latest run.</div> :
            tickers.slice(0, 60).map((t: any, i: number) => (
              <div key={`${t.symbol}-${i}`} onClick={() => onDrill({ title: t.symbol, subtitle: `${t.decision ?? ''} · score ${t.score ?? '—'} · ${t.sector ?? ''}`, endpoint: '/api/v2/trade-ai', rows: [t] })}
                style={{ display: 'grid', gridTemplateColumns: '0.5fr 1fr 0.6fr 0.6fr 0.7fr 0.6fr 1.4fr 0.8fr', padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center', borderLeft: `3px solid ${decisionColor(t.decision)}` }}>
                <span style={{ fontWeight: 700, fontSize: 9, color: decisionColor(t.decision) }}>{t.decision || 'NO-GO'}</span>
                <div>
                  <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</span>
                  {t.grade && <span style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 4 }}>{t.grade}</span>}
                  {t.decision_changed && <span title={`critic changed from ${t.original_decision}`} style={{ fontSize: 8, color: '#f59e0b', marginLeft: 4 }}>⟳</span>}
                </div>
                <span style={{ color: 'var(--text2)', fontWeight: 600 }}>{t.score ?? '—'}</span>
                <span style={{ color: (t.rvol ?? 0) >= 5 ? '#22c55e' : 'var(--text2)' }}>{t.rvol ? Number(t.rvol).toFixed(1) : '—'}</span>
                <span style={{ color: 'var(--text2)' }}>{t.price ? `$${Number(t.price).toFixed(2)}` : '—'}</span>
                <span style={{ color: parseFloat(t.change_pct) >= 0 ? '#22c55e' : '#ef4444' }}>{t.change_pct !== '' && t.change_pct != null ? `${t.change_pct}%` : '—'}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.catalyst}>{t.catalyst || '—'}</span>
                <span style={{ fontSize: 9, color: t.critic_verdict === 'GO' ? '#22c55e' : t.critic_verdict === 'AVOID' ? '#ef4444' : 'var(--text3)' }}>{t.critic_verdict ?? '—'}</span>
              </div>
            ))}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/trade-ai (orchestrator scan: screener → enrichment → scalp critic → GO/WAIT/NO-GO). Read-only. Click a row for full scan detail. Showing top {Math.min(60, tickers.length)} of {tickers.length} by score.</div>
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

      {tab === 'Proposals' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Proposals ({propList.length})</div>
          {propList.slice(0, 20).map((p: any) => {
            const adv = advMap[String(p.id)]
            return (
            <div key={p.id} onClick={() => onDrill({ title: `${p.symbol} #${p.id}`, subtitle: `${p.strategy_id} · ${p.status}`, endpoint: '/api/v2/paper-proposals', rows: [adv ? { ...p, setup_advisory: adv.note, setup_advisory_flag: adv.advisory_flag, setup_prior_score: adv.prior_score } : p] })}
              style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <div>
                <span style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace', marginRight: 8 }}>{p.symbol}</span>
                <span style={{ color: 'var(--text3)' }}>{p.strategy_id}</span>
                {adv && <span title={adv.note} style={{ marginLeft: 8, fontSize: 8, padding: '1px 6px', borderRadius: 3, background: 'var(--bg2)', color: advColor(adv.advisory_flag), border: `1px solid ${advColor(adv.advisory_flag)}33` }}>
                  {adv.advisory_flag === 'caution' ? '⚠ ' : ''}setup ~{adv.prior_score != null ? Number(adv.prior_score).toFixed(0) : '—'}
                </span>}
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <span style={{ color: 'var(--text2)' }}>{fmt$(p.proposed_entry, 2)} → {fmt$(p.proposed_target1, 2)}</span>
                <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 3,
                  background: p.status === 'PENDING' ? 'rgba(245,158,11,.1)' : p.status === 'APPROVED' ? 'rgba(34,197,94,.1)' : 'rgba(107,114,128,.1)',
                  color: p.status === 'PENDING' ? '#f59e0b' : p.status === 'APPROVED' ? '#22c55e' : 'var(--text3)',
                }}>{p.status}</span>
              </div>
            </div>
          )})}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/paper-proposals + /api/v2/atm/setup-advisory (setup-quality prior). Advisory-only — read-only, never gates execution.</div>
        </div>
      )}

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
