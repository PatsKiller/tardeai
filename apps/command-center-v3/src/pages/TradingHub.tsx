import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionPanel from '../components/ProtectionPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Open Trades', 'Proposals', 'Execution', 'Scalp'] as const

export default function TradingHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Open Trades')
  const { data: openTrades } = useApi<any>('/api/v2/open-trades', 30_000)
  const { data: proposals } = useApi<any>('/api/v2/paper-proposals', 60_000)
  const { data: paperStatus } = useApi<any>('/api/v2/paper-status', 30_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: execQual } = useApi<any>('/api/v2/execution-quality', 120_000)
  const { data: scalpData } = useApi<any>('/api/v2/scalp/live', 120_000)

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

      {tab === 'Open Trades' && (
        <>
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Open Positions ({trades.length})</div>
            {trades.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No open paper trades</div> :
            trades.map((t: any) => (
              <div key={t.id} onClick={() => onDrill({ title: t.symbol, subtitle: `${t.strategy_id} · R=${t.r_multiple?.toFixed(2)}`, endpoint: '/api/v2/open-trades', rows: [t] })}
                style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr', padding: '8px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                <div>
                  <div style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>{t.strategy_id}</div>
                </div>
                <span style={{ color: 'var(--text2)' }}>{t.shares} @ {fmt$(t.entry_price, 2)}</span>
                <span style={{ color: (t.pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmt$(t.pnl, 2)}</span>
                <span style={{ color: 'var(--text2)' }}>R: {t.r_multiple?.toFixed(2) ?? '—'}</span>
                <span style={{ fontSize: 9, color: t.risk_flags?.length ? '#f59e0b' : 'var(--text3)' }}>
                  {t.trail_recommendation?.replace(/_/g, ' ') ?? '—'}
                </span>
              </div>
            ))}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/open-trades. Read-only — no trade controls.</div>
          </div>
          <ProtectionPanel onDrill={onDrill} />
        </>
      )}

      {tab === 'Proposals' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Proposals ({propList.length})</div>
          {propList.slice(0, 20).map((p: any) => (
            <div key={p.id} onClick={() => onDrill({ title: `${p.symbol} #${p.id}`, subtitle: `${p.strategy_id} · ${p.status}`, endpoint: '/api/v2/paper-proposals', rows: [p] })}
              style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <div>
                <span style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace', marginRight: 8 }}>{p.symbol}</span>
                <span style={{ color: 'var(--text3)' }}>{p.strategy_id}</span>
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <span style={{ color: 'var(--text2)' }}>{fmt$(p.proposed_entry, 2)} → {fmt$(p.proposed_target1, 2)}</span>
                <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 3,
                  background: p.status === 'PENDING' ? 'rgba(245,158,11,.1)' : p.status === 'APPROVED' ? 'rgba(34,197,94,.1)' : 'rgba(107,114,128,.1)',
                  color: p.status === 'PENDING' ? '#f59e0b' : p.status === 'APPROVED' ? '#22c55e' : 'var(--text3)',
                }}>{p.status}</span>
              </div>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/paper-proposals. Read-only — no approval controls.</div>
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
