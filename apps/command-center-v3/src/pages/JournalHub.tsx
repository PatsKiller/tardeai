import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionOutcomesPanel from '../components/ProtectionOutcomesPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trades', 'Analytics', 'Lessons', 'Protection'] as const

export default function JournalHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Trades')
  const { data: journal } = useApi<any>('/api/v2/automated-trade-journal', 60_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: lessonsData } = useApi<any>('/api/v2/journal/closed-trades/lessons', 120_000)

  const trades = journal?.trades ?? []
  const openTrades = trades.filter((t: any) => t.status === 'open')
  const closedTrades = trades.filter((t: any) => t.status === 'closed')
  const summary = journal?.summary ?? {}
  const warnings = journal?.integrity_warnings ?? []
  const jc = readiness?.journal_completeness ?? {}

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Journal</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{trades.length} trades · {openTrades.length} open · {closedTrades.length} closed</div>
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

      {/* Integrity warnings */}
      {warnings.length > 0 && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.15)', borderRadius: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#f59e0b', marginBottom: 4 }}>Integrity Warnings ({warnings.length})</div>
          {warnings.slice(0, 5).map((w: any, i: number) => (
            <div key={i} style={{ fontSize: 9, color: '#fbbf24', padding: '1px 0' }}>{typeof w === 'string' ? w : JSON.stringify(w)}</div>
          ))}
        </div>
      )}

      {tab === 'Trades' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, maxHeight: 500, overflowY: 'auto' }}>
          {trades.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No journal trades</div> :
          trades.map((t: any) => (
            <div key={t.id} onClick={() => onDrill({ title: `${t.symbol} #${t.id}`, subtitle: `${t.strategy_id} · ${t.status}`, endpoint: '/api/v2/automated-trade-journal', rows: [t] })}
              style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr', padding: '8px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <div>
                <div style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</div>
                <div style={{ fontSize: 8, color: 'var(--text3)' }}>{t.strategy_id}</div>
              </div>
              <span style={{ color: 'var(--text2)' }}>{t.shares} @ {fmt$(t.entry_price, 2)}</span>
              <span style={{ color: t.status === 'open' ? '#60a5fa' : (t.pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>
                {t.status === 'open' ? 'OPEN' : fmt$(t.pnl, 2)}
              </span>
              <span style={{ color: 'var(--text2)' }}>{t.exit_reason ?? '—'}</span>
              <span style={{ color: 'var(--text3)', fontSize: 9 }}>{t.hold_time_min ? `${Math.round(t.hold_time_min / 60)}h` : '—'}</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/automated-trade-journal. Read-only.</div>
        </div>
      )}

      {tab === 'Analytics' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Journal Field Completeness</div>
          {Object.keys(jc).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No completeness data — run paper_trade_statistics.py</div> :
          Object.entries(jc).sort(([, a]: [string, any], [, b]: [string, any]) => b - a).map(([field, pct]: [string, any]) => (
            <div key={field} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
              <span style={{ width: 120, fontSize: 10, color: 'var(--text2)' }}>{field}</span>
              <div style={{ flex: 1, height: 12, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: pct >= 95 ? '#22c55e' : pct >= 80 ? '#f59e0b' : '#ef4444', borderRadius: 3 }} />
              </div>
              <span style={{ fontSize: 10, color: pct >= 95 ? '#22c55e' : pct >= 80 ? '#f59e0b' : '#ef4444', width: 40, textAlign: 'right' }}>{pct}%</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/paper-trade-readiness → journal_completeness</div>
        </div>
      )}

      {tab === 'Lessons' && lessonsData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Trade Lessons ({lessonsData.count ?? 0})</div>
          {(lessonsData.lessons ?? []).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No lessons recorded yet</div> :
          (lessonsData.lessons ?? []).slice(0, 15).map((l: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: l.lesson_category ?? `Lesson ${i}`, subtitle: l.strategy_id ?? '', endpoint: '/api/v2/journal/closed-trades/lessons', rows: [l] })}
              style={{ padding: '8px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{l.lesson_category ?? l.lesson_type ?? '—'}</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{(l.lesson_text ?? l.summary ?? JSON.stringify(l)).slice(0, 120)}</div>
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>{l.strategy_id ?? ''} · {l.symbol ?? ''}</div>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/journal/closed-trades/lessons</div>
        </div>
      )}

      {tab === 'Protection' && <ProtectionOutcomesPanel onDrill={onDrill} />}
    </div>
  )
}
