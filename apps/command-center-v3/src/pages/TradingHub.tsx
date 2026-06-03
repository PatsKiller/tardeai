import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionPanel from '../components/ProtectionPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trade AI', 'Open Trades', 'Proposals', 'Execution', 'Scalp'] as const

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
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Open Positions ({trades.length})</div>
            {trades.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No open paper trades</div> :
            trades.map((t: any) => {
              const adv = advBySym[t.symbol]
              return (
              <div key={t.id} onClick={() => onDrill({ title: t.symbol, subtitle: `${t.strategy_id} · R=${t.r_multiple?.toFixed(2)}`, endpoint: '/api/v2/open-trades', rows: [adv ? { ...t, setup_advisory: adv.note, setup_advisory_flag: adv.advisory_flag, setup_prior_score: adv.prior_score, entry_rsi_band: adv.band } : t] })}
                style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr', padding: '8px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                <div>
                  <div style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>{t.strategy_id}</div>
                </div>
                <span style={{ color: 'var(--text2)' }}>{t.shares} @ {fmt$(t.entry_price, 2)}</span>
                <span style={{ color: (t.pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmt$(t.pnl, 2)}</span>
                <span style={{ color: 'var(--text2)' }}>R: {t.r_multiple?.toFixed(2) ?? '—'}</span>
                {adv
                  ? <span title={adv.note} style={{ fontSize: 8, padding: '1px 6px', borderRadius: 3, alignSelf: 'center', justifySelf: 'start', background: 'var(--bg2)', color: advColor(adv.advisory_flag), border: `1px solid ${advColor(adv.advisory_flag)}33` }}>
                      {adv.advisory_flag === 'caution' ? '⚠ ' : adv.advisory_flag === 'favorable' ? '✓ ' : ''}entry setup ~{adv.prior_score != null ? Number(adv.prior_score).toFixed(0) : '—'}
                    </span>
                  : <span style={{ fontSize: 9, color: t.risk_flags?.length ? '#f59e0b' : 'var(--text3)' }}>
                      {t.trail_recommendation?.replace(/_/g, ' ') ?? '—'}
                    </span>}
              </div>
            )})}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/open-trades + /api/v2/atm/setup-advisory (entry-setup quality prior, matched by symbol — advisory-only, never gates). Open trades have no exit grade yet; entry-setup rating reflects the RSI-band prior at proposal time.</div>
          </div>
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
