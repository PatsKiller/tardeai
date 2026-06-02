import { useState, useEffect } from 'react'
import PageHeader from '../components/PageHeader'
import SectionHeader from '../components/SectionHeader'
import InlineDualOpinionPanel from '../components/InlineDualOpinionPanel'

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const thStyle: React.CSSProperties = { fontSize: 8, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.3px', padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid var(--border)' }
const tdStyle: React.CSSProperties = { fontSize: 11, padding: '5px 8px', borderBottom: '1px solid var(--border)', color: '#E2E8F0' }

const statusColor: Record<string, string> = {
  WORKING: '#4ADE80', TUNING: '#F59E0B', NOT_WORKING: '#F87171',
  TOO_FEW: '#60A5FA', INACTIVE: '#64748B',
}
const statusBg: Record<string, string> = {
  WORKING: 'rgba(34,197,94,0.15)', TUNING: 'rgba(245,158,11,0.15)', NOT_WORKING: 'rgba(239,68,68,0.15)',
  TOO_FEW: 'rgba(59,130,246,0.15)', INACTIVE: 'rgba(100,116,139,0.15)',
}
const pill = (status: string) => ({
  fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
  background: statusBg[status] || 'rgba(100,116,139,0.15)',
  color: statusColor[status] || '#94A3B8',
})

function useFetch<T>(url: string): { data: T | null; loading: boolean } {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    fetch(url).then(r => r.json()).then(d => { if (d.ok) setData(d.data) }).catch(() => {}).finally(() => setLoading(false))
  }, [url])
  return { data, loading }
}

function Panel({ title, children, loading }: { title: string; children: React.ReactNode; loading?: boolean }) {
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }}>
      <SectionHeader title={title} />
      {loading ? <div style={{ padding: 16, color: '#64748B', fontSize: 11 }}>Loading...</div> : children}
    </div>
  )
}

function ScoreboardPanel() {
  const { data, loading } = useFetch<any[]>('/api/v2/strategy-analytics/scoreboard')
  return (
    <Panel title="Strategy Scoreboard" loading={loading}>
      {data && data.length > 0 ? (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              {['Strategy', 'Trades', 'W', 'L', 'Win%', 'PF', 'Avg Hold', 'Avg R', 'Total P&L', 'Status'].map(h =>
                <th key={h} style={thStyle}>{h}</th>)}
            </tr></thead>
            <tbody>{data.map((s: any) => (
              <tr key={s.strategy_id}>
                <td style={{ ...tdStyle, fontWeight: 600, ...mono }}>{s.strategy_id}</td>
                <td style={{ ...tdStyle, ...mono, textAlign: 'center' }}>{s.trades}</td>
                <td style={{ ...tdStyle, ...mono, color: '#4ADE80', textAlign: 'center' }}>{s.wins}</td>
                <td style={{ ...tdStyle, ...mono, color: '#F87171', textAlign: 'center' }}>{s.losses}</td>
                <td style={{ ...tdStyle, ...mono, textAlign: 'center' }}>{s.win_rate != null ? `${(s.win_rate * 100).toFixed(0)}%` : '--'}</td>
                <td style={{ ...tdStyle, ...mono, textAlign: 'center' }}>{s.profit_factor != null ? s.profit_factor.toFixed(2) : '--'}</td>
                <td style={{ ...tdStyle, ...mono, textAlign: 'center' }}>{s.avg_hold_hours != null ? `${s.avg_hold_hours.toFixed(1)}h` : '--'}</td>
                <td style={{ ...tdStyle, ...mono, textAlign: 'center' }}>{s.avg_r != null ? `${s.avg_r.toFixed(2)}R` : '--'}</td>
                <td style={{ ...tdStyle, ...mono, fontWeight: 600, color: s.total_pnl > 0 ? '#4ADE80' : s.total_pnl < 0 ? '#F87171' : '#94A3B8' }}>
                  {s.total_pnl != null ? `$${s.total_pnl >= 0 ? '+' : ''}${s.total_pnl.toFixed(2)}` : '--'}
                </td>
                <td style={tdStyle}><span style={pill(s.status)}>{s.status}</span></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <div style={{ padding: 12, color: '#64748B', fontSize: 11 }}>No strategy data yet.</div>}
    </Panel>
  )
}

function HoldTimePanel() {
  const { data, loading } = useFetch<any[]>('/api/v2/strategy-analytics/hold-times')
  const verdictColor = (v: string) => v === 'APPROPRIATE' ? '#4ADE80' : v === 'TOO_SHORT' ? '#F87171' : v === 'TOO_LONG' ? '#F59E0B' : '#64748B'
  return (
    <Panel title="Hold Time Analysis" loading={loading}>
      {data && data.length > 0 ? (
        <div style={{ display: 'grid', gap: 8 }}>
          {data.map((s: any) => (
            <div key={s.strategy_id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '6px 12px', background: 'var(--bg0)', borderRadius: 6 }}>
              <span style={{ ...mono, fontWeight: 600, minWidth: 200, fontSize: 11 }}>{s.strategy_id}</span>
              <span style={{ ...mono, fontSize: 11, minWidth: 70 }}>Avg: {s.avg_hold_hours?.toFixed(1)}h</span>
              <span style={{ fontSize: 10, color: '#64748B', minWidth: 120 }}>Norm: {s.norms?.min}–{s.norms?.max}h</span>
              <span style={{ fontSize: 10, fontWeight: 600, color: verdictColor(s.verdict) }}>{s.verdict}</span>
              {/* Simple bar visualization */}
              <div style={{ flex: 1, height: 8, background: '#1E293B', borderRadius: 4, position: 'relative', overflow: 'hidden' }}>
                <div style={{
                  position: 'absolute', height: '100%', borderRadius: 4,
                  background: verdictColor(s.verdict),
                  width: `${Math.min(100, (s.avg_hold_hours / (s.norms?.max || 100)) * 100)}%`,
                  opacity: 0.6,
                }} />
              </div>
            </div>
          ))}
        </div>
      ) : <div style={{ padding: 12, color: '#64748B', fontSize: 11 }}>No hold time data yet.</div>}
    </Panel>
  )
}

function ExitReasonPanel() {
  const { data, loading } = useFetch<Record<string, any[]>>('/api/v2/strategy-analytics/exit-reasons')
  const reasonColor: Record<string, string> = {
    stop_hit: '#F87171', stop_hit_instant: '#F87171', target_hit: '#4ADE80',
    time_stop_intraday_1545: '#F59E0B', time_stop_max_0d: '#F59E0B',
    manual_stale_close: '#94A3B8', phantom_no_alpaca_position: '#FB923C',
    position_closed_in_alpaca: '#64748B', order_never_filled_on_alpaca: '#64748B',
  }
  return (
    <Panel title="Exit Reason Distribution" loading={loading}>
      {data && Object.keys(data).length > 0 ? (
        <div style={{ display: 'grid', gap: 8 }}>
          {Object.entries(data).map(([strat, reasons]) => (
            <div key={strat} style={{ padding: '6px 12px', background: 'var(--bg0)', borderRadius: 6 }}>
              <div style={{ ...mono, fontWeight: 600, fontSize: 11, marginBottom: 4 }}>{strat}</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {(reasons as any[]).map((r: any) => (
                  <span key={r.exit_reason} style={{
                    fontSize: 9, padding: '2px 6px', borderRadius: 4,
                    background: `${reasonColor[r.exit_reason] || '#64748B'}22`,
                    color: reasonColor[r.exit_reason] || '#64748B',
                    fontWeight: 600,
                  }}>{r.exit_reason}: {r.count}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : <div style={{ padding: 12, color: '#64748B', fontSize: 11 }}>No exit data yet.</div>}
    </Panel>
  )
}

function StopQualityPanel() {
  const { data, loading } = useFetch<any[]>('/api/v2/strategy-analytics/stop-quality')
  const pctColor = (v: number) => v >= 50 ? '#F87171' : v >= 25 ? '#F59E0B' : '#4ADE80'
  return (
    <Panel title="Stop Quality Patterns" loading={loading}>
      {data && data.length > 0 ? (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            {['Strategy', 'Trades', 'Stop Too Tight %', 'Would Have Recovered %', 'Held Too Short %'].map(h =>
              <th key={h} style={thStyle}>{h}</th>)}
          </tr></thead>
          <tbody>{data.map((s: any) => (
            <tr key={s.strategy_id}>
              <td style={{ ...tdStyle, fontWeight: 600, ...mono }}>{s.strategy_id}</td>
              <td style={{ ...tdStyle, ...mono, textAlign: 'center' }}>{s.analyzed_trades}</td>
              <td style={{ ...tdStyle, ...mono, textAlign: 'center', color: pctColor(s.pct_stop_too_tight), fontWeight: 600 }}>
                {s.pct_stop_too_tight.toFixed(0)}%
              </td>
              <td style={{ ...tdStyle, ...mono, textAlign: 'center', color: pctColor(s.pct_would_have_recovered), fontWeight: 600 }}>
                {s.pct_would_have_recovered.toFixed(0)}%
              </td>
              <td style={{ ...tdStyle, ...mono, textAlign: 'center', color: pctColor(s.pct_held_too_short), fontWeight: 600 }}>
                {s.pct_held_too_short.toFixed(0)}%
              </td>
            </tr>
          ))}</tbody>
        </table>
      ) : <div style={{ padding: 12, color: '#64748B', fontSize: 11 }}>No post-trade analysis data yet.</div>}
    </Panel>
  )
}

function FinvizHealthPanel() {
  const { data, loading } = useFetch<any>('/api/v2/strategy-analytics/finviz-health')
  return (
    <Panel title="Finviz Pipeline Health" loading={loading}>
      {data ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8, padding: '8px 0' }}>
          {[
            ['Total Scans', data.total_rows],
            ['Unique Symbols', data.unique_symbols],
            ['Days of History', data.days_of_history],
            ['Rows Today', data.rows_today],
            ['7-Day Avg', data.avg_rows_7d?.toFixed(0)],
          ].map(([label, value]) => (
            <div key={String(label)} style={{ padding: '8px 12px', background: 'var(--bg0)', borderRadius: 6 }}>
              <div style={{ fontSize: 8, color: '#64748B', textTransform: 'uppercase' }}>{label}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#E2E8F0', ...mono }}>{value ?? '--'}</div>
            </div>
          ))}
        </div>
      ) : <div style={{ padding: 12, color: '#64748B', fontSize: 11 }}>No Finviz data.</div>}
    </Panel>
  )
}

function InactiveStrategiesPanel() {
  const { data, loading } = useFetch<any[]>('/api/v2/strategy-analytics/inactive-strategies')
  return (
    <Panel title={`Inactive Strategies (${data?.length ?? 0} with zero trades)`} loading={loading}>
      {data && data.length > 0 ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 6 }}>
          {data.map((s: any) => (
            <div key={s.strategy_id} style={{ padding: '6px 10px', background: 'var(--bg0)', borderRadius: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ ...mono, fontSize: 11, color: '#94A3B8' }}>{s.strategy_id}</span>
              <span style={{ fontSize: 9, color: s.candidates_7d > 0 ? '#F59E0B' : '#475569' }}>
                {s.candidates_7d > 0 ? `${s.candidates_7d} candidates 7d` : 'no candidates'}
              </span>
            </div>
          ))}
        </div>
      ) : <div style={{ padding: 12, color: '#4ADE80', fontSize: 11 }}>All strategies have trades.</div>}
    </Panel>
  )
}

function LessonPatternsPanel() {
  const { data, loading } = useFetch<any>('/api/v2/strategy-analytics/lesson-patterns')
  return (
    <Panel title="Lesson Patterns" loading={loading}>
      {data ? (
        <>
          {/* Keyword counts */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
            {Object.entries(data.keyword_counts || {}).map(([kw, cnt]) => (
              <div key={kw} style={{ padding: '6px 10px', background: 'var(--bg0)', borderRadius: 6, textAlign: 'center' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: Number(cnt) > 0 ? '#F59E0B' : '#475569', ...mono }}>{String(cnt)}</div>
                <div style={{ fontSize: 8, color: '#64748B', textTransform: 'uppercase' }}>{kw}</div>
              </div>
            ))}
          </div>
          {/* Recent lessons */}
          {(data.recent_lessons || []).slice(0, 10).map((l: any, i: number) => (
            <div key={i} style={{ padding: '8px 12px', background: 'var(--bg0)', borderRadius: 6, marginBottom: 6, borderLeft: '3px solid #F59E0B' }}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
                <span style={{ ...mono, fontWeight: 600, fontSize: 10, color: '#60A5FA' }}>{l.symbol}</span>
                <span style={{ fontSize: 9, color: '#64748B' }}>{l.strategy_id}</span>
              </div>
              <div style={{ fontSize: 11, color: '#CBD5E1', lineHeight: 1.5, fontStyle: 'italic' }}>
                "{(l.lesson_text || '').slice(0, 250)}"
              </div>
            </div>
          ))}
          {(data.recent_lessons || []).length === 0 && (
            <div style={{ padding: 12, color: '#64748B', fontSize: 11 }}>No lessons generated yet.</div>
          )}
        </>
      ) : null}
    </Panel>
  )
}

export default function StrategyAnalytics() {
  return (
    <div>
      <PageHeader title="Strategy Analytics" subtitle="What's working, what isn't, and why" />
      <ScoreboardPanel />
      <HoldTimePanel />
      <ExitReasonPanel />
      <StopQualityPanel />
      <FinvizHealthPanel />
      <InactiveStrategiesPanel />
      <LessonPatternsPanel />
    </div>
  )
}
