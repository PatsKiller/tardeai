import { useState, useEffect } from 'react'
import PageHeader from '../components/PageHeader'
import SectionHeader from '../components/SectionHeader'

const mono: React.CSSProperties = { fontFamily: 'monospace' }

function useFetch<T>(url: string): { data: T | null; loading: boolean; refetch: () => void } {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    setLoading(true)
    fetch(url).then(r => r.json()).then(d => { if (d.ok) setData(d.data) }).catch(() => {}).finally(() => setLoading(false))
  }, [url, tick])
  return { data, loading, refetch: () => setTick(t => t + 1) }
}

function Card({ title, status, children }: { title: string; status?: 'ok' | 'warn' | 'error' | 'info'; children: React.ReactNode }) {
  const border = status === 'error' ? '1px solid rgba(239,68,68,0.4)' : status === 'warn' ? '1px solid rgba(245,158,11,0.4)' : status === 'ok' ? '1px solid rgba(34,197,94,0.2)' : '1px solid var(--border)'
  const bg = status === 'error' ? 'rgba(239,68,68,0.05)' : status === 'warn' ? 'rgba(245,158,11,0.05)' : 'var(--bg1)'
  return (
    <div style={{ background: bg, border, borderRadius: 8, padding: 14, marginBottom: 10 }}>
      <SectionHeader title={title} />
      {children}
    </div>
  )
}

export default function MorningBriefBot() {
  const { data, loading, refetch } = useFetch<any>('/api/v2/morning-brief')

  if (loading) return <div style={{ padding: 40, color: 'var(--text3)' }}>Loading morning brief...</div>
  if (!data) return <div style={{ padding: 40, color: 'var(--red)' }}>Failed to load morning brief</div>

  const hg = data.holdings_guard || {}
  const pa = data.paper_account || {}
  const oa = data.overnight_activity || {}
  const sh = data.strategy_health || {}
  const ct = data.closed_trades_24h || []
  const al = data.alerts_24h || {}
  const items = data.action_items || []

  const netPnl = ct.reduce((s: number, t: any) => s + (Number(t.pnl) || 0), 0)

  return (
    <div>
      <PageHeader title="Bot Morning Brief" subtitle={`Generated ${data.generated_at?.slice(0, 16) || 'now'}`} />
      <div style={{ marginBottom: 10 }}>
        <button onClick={refetch} style={{ padding: '6px 14px', background: 'var(--blue)', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 11 }}>Refresh</button>
      </div>

      {/* 1. Holdings Guard */}
      <Card title="1. Holdings Guard" status={hg.ok ? 'ok' : 'error'}>
        <div style={{ fontSize: 14, fontWeight: 700, color: hg.ok ? '#4ADE80' : '#F87171', ...mono }}>
          {hg.ok ? 'INTACT' : 'BELOW THRESHOLD'} — ${(hg.portfolio_value || 0).toLocaleString()}
        </div>
      </Card>

      {/* 2. Paper Account */}
      <Card title="2. Paper Account" status="info">
        <div style={{ display: 'flex', gap: 20, fontSize: 12, ...mono }}>
          <span>Equity: ${(pa.equity || 0).toLocaleString()}</span>
          <span>Open: {pa.open_positions || 0}</span>
          <span>Cash: ${(pa.cash || 0).toLocaleString()}</span>
          <span style={{ color: pa.heat_pct > 0.045 ? '#F59E0B' : '#4ADE80' }}>
            Heat: {((pa.heat_pct || 0) * 100).toFixed(1)}%
          </span>
        </div>
      </Card>

      {/* 3. Overnight Activity */}
      <Card title="3. Overnight Activity" status={oa.trades_opened > 0 ? 'ok' : 'info'}>
        <div style={{ fontSize: 12, ...mono }}>
          {oa.proposals_created} proposals, {oa.proposals_approved} approved, {oa.trades_opened} trades opened, {oa.trades_closed} closed
        </div>
        {Object.keys(oa.risk_gate_blocks || {}).length > 0 && (
          <div style={{ fontSize: 11, color: '#F59E0B', marginTop: 4 }}>
            Risk gate blocks: {Object.entries(oa.risk_gate_blocks || {}).filter(([, v]) => v as number > 0).map(([k, v]) => `${k}:${v}`).join(', ')}
          </div>
        )}
      </Card>

      {/* 4. Strategy Health */}
      <Card title="4. Strategy Health" status={sh.stuck_strategies?.length > 0 ? 'warn' : 'ok'}>
        <div style={{ fontSize: 12, ...mono }}>
          {sh.total_active} active, {sh.newly_activated} newly activated
          {sh.stuck_strategies?.length > 0 && (
            <span style={{ color: '#F59E0B' }}>, {sh.stuck_strategies.length} stuck</span>
          )}
        </div>
        {sh.stuck_strategies?.length > 0 && (
          <div style={{ marginTop: 4, fontSize: 11, color: '#F59E0B' }}>
            Stuck: {sh.stuck_strategies.join(', ')}
          </div>
        )}
      </Card>

      {/* 5. Closed Trades 24h */}
      <Card title={`5. Closed Trades 24h (${ct.length})`} status={ct.length > 0 ? (netPnl >= 0 ? 'ok' : 'warn') : 'info'}>
        {ct.length > 0 ? (
          <>
            <div style={{ fontSize: 12, fontWeight: 600, color: netPnl >= 0 ? '#4ADE80' : '#F87171', ...mono, marginBottom: 6 }}>
              Net: ${netPnl >= 0 ? '+' : ''}{netPnl.toFixed(2)}
            </div>
            {ct.map((t: any, i: number) => (
              <div key={i} style={{ display: 'flex', gap: 10, padding: '3px 0', fontSize: 11, borderBottom: '1px solid var(--border)', ...mono }}>
                <span style={{ fontWeight: 600, minWidth: 50 }}>{t.symbol}</span>
                <span style={{ color: t.outcome_verdict === 'WIN' ? '#4ADE80' : '#F87171', minWidth: 40 }}>{t.outcome_verdict}</span>
                <span style={{ color: Number(t.pnl) >= 0 ? '#4ADE80' : '#F87171', minWidth: 60 }}>${Number(t.pnl || 0).toFixed(2)}</span>
                <span style={{ color: '#64748B', fontSize: 10 }}>{t.exit_reason}</span>
                {t.stop_too_tight && <span style={{ color: '#F59E0B', fontSize: 9, padding: '1px 4px', background: 'rgba(245,158,11,0.15)', borderRadius: 3 }}>stop tight</span>}
              </div>
            ))}
          </>
        ) : <div style={{ fontSize: 11, color: '#64748B' }}>No trades closed in last 24h</div>}
      </Card>

      {/* 6. Alerts */}
      <Card title="6. Alerts 24h" status={al.urgent > 0 ? 'error' : 'info'}>
        <div style={{ display: 'flex', gap: 16, fontSize: 12, ...mono }}>
          <span style={{ color: al.urgent > 0 ? '#F87171' : '#64748B' }}>Urgent: {al.urgent}</span>
          <span>Digest: {al.digest}</span>
          <span style={{ color: '#64748B' }}>Dashboard: {al.dashboard_only}</span>
        </div>
      </Card>

      {/* 7. Action Items */}
      <Card title={`7. Action Items (${items.length})`} status={items.some((i: any) => i.severity === 'warning') ? 'warn' : 'info'}>
        {items.length > 0 ? items.map((it: any, i: number) => (
          <div key={i} style={{ padding: '4px 0', fontSize: 11, borderBottom: i < items.length - 1 ? '1px solid var(--border)' : 'none', display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, fontWeight: 600,
              background: it.severity === 'warning' ? 'rgba(245,158,11,0.15)' : 'rgba(59,130,246,0.15)',
              color: it.severity === 'warning' ? '#F59E0B' : '#60A5FA' }}>
              {it.severity === 'warning' ? 'WARN' : 'INFO'}
            </span>
            <span style={{ color: '#E2E8F0' }}>{it.message}</span>
          </div>
        )) : <div style={{ fontSize: 11, color: '#4ADE80' }}>No action items</div>}
      </Card>
    </div>
  )
}
