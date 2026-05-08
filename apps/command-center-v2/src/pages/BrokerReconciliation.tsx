import React, { useState } from 'react'
import PageHeader from '../components/PageHeader'
import { useApi } from '../hooks/useApi'

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }
const pill = (color: string): React.CSSProperties => ({
  fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
  background: color === 'green' ? 'rgba(34,197,94,0.15)' : color === 'red' ? 'rgba(239,68,68,0.15)' : color === 'blue' ? 'rgba(59,130,246,0.15)' : 'rgba(251,191,36,0.15)',
  color: color === 'green' ? 'var(--green)' : color === 'red' ? 'var(--red)' : color === 'blue' ? '#60A5FA' : 'var(--amber)',
})
const kv = (label: string, value: any, color?: string) => (
  <div key={label}>
    <div style={lbl}>{label}</div>
    <div style={{ fontSize: 11, color: color || 'var(--text0)', fontWeight: 600, ...mono }}>{value ?? '--'}</div>
  </div>
)
const stateColor = (s: string) => s === 'MATCHED' || s === 'CLOSED_OK' ? 'green' : s === 'UNKNOWN' ? 'amber' : 'red'

export default function BrokerReconciliation() {
  const { data, loading } = useApi<any>('/api/v2/broker-reconciliation', 30000)
  const [running, setRunning] = useState(false)

  const runRecon = async () => {
    setRunning(true)
    try {
      await fetch('/api/v2/paper-reconciliation/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      window.location.reload()
    } catch { alert('Failed') }
    setRunning(false)
  }

  const runs = data?.runs || []
  const items = data?.items || []
  const latestRun = runs[0] || {}
  const issueItems = items.filter((i: any) => i.reconciliation_state && !['MATCHED', 'CLOSED_OK'].includes(i.reconciliation_state))

  return (
    <>
      <PageHeader title="Broker Reconciliation" subtitle="Alpaca paper trading position and order reconciliation" />
      <div style={{ padding: '0 24px 24px' }}>
        {loading && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading...</div>}

        {/* Latest Run Summary */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 16, padding: 16, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)' }}>
          {kv('Run Status', latestRun.run_status || 'No runs yet', latestRun.run_status === 'completed' ? 'var(--green)' : undefined)}
          {kv('Orders Seen', latestRun.orders_seen ?? '--')}
          {kv('Positions Seen', latestRun.positions_seen ?? '--')}
          {kv('Matched', latestRun.trades_matched ?? '--', 'var(--green)')}
          {kv('Unmatched Broker', latestRun.unmatched_broker_orders ?? '--', (latestRun.unmatched_broker_orders || 0) > 0 ? 'var(--red)' : undefined)}
          {kv('Unmatched Local', latestRun.unmatched_local_trades ?? '--', (latestRun.unmatched_local_trades || 0) > 0 ? 'var(--red)' : undefined)}
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button onClick={runRecon} disabled={running}
            style={{ padding: '6px 14px', fontSize: 11, fontWeight: 600, border: 'none', borderRadius: 5, cursor: 'pointer', color: '#60A5FA', background: 'rgba(59,130,246,0.15)' }}>
            {running ? 'Running...' : 'Run Reconciliation'}
          </button>
        </div>

        {/* Issues */}
        {issueItems.length > 0 && (
          <div style={{ marginBottom: 16, padding: 12, background: 'rgba(239,68,68,0.05)', borderRadius: 8, border: '1px solid rgba(239,68,68,0.2)' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--red)', marginBottom: 8 }}>Reconciliation Issues ({issueItems.length})</div>
            {issueItems.map((i: any) => (
              <div key={i.id} style={{ fontSize: 10, color: 'var(--text1)', padding: '4px 0', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={pill(stateColor(i.reconciliation_state))}>{i.reconciliation_state}</span>
                <span style={{ fontWeight: 600, ...mono }}>{i.symbol}</span>
                <span style={{ color: 'var(--text3)' }}>{i.issue_code || ''}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>{i.broker_order_id || ''}</span>
              </div>
            ))}
          </div>
        )}

        {/* Run History */}
        <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Run History</h3>
        <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--border)' }}>
                {['Run ID', 'Broker', 'Status', 'Orders', 'Positions', 'Matched', 'Unmatched Broker', 'Unmatched Local', 'Started'].map(h => (
                  <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 && (
                <tr><td colSpan={9} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No reconciliation runs yet.</td></tr>
              )}
              {runs.map((r: any) => (
                <tr key={r.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 10px' }}>#{r.id}</td>
                  <td style={{ padding: '6px 10px' }}>{r.broker}</td>
                  <td style={{ padding: '6px 10px' }}><span style={pill(r.run_status === 'completed' ? 'green' : 'amber')}>{r.run_status}</span></td>
                  <td style={{ padding: '6px 10px' }}>{r.orders_seen ?? 0}</td>
                  <td style={{ padding: '6px 10px' }}>{r.positions_seen ?? 0}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--green)' }}>{r.trades_matched ?? 0}</td>
                  <td style={{ padding: '6px 10px', color: (r.unmatched_broker_orders || 0) > 0 ? 'var(--red)' : 'var(--text2)' }}>{r.unmatched_broker_orders ?? 0}</td>
                  <td style={{ padding: '6px 10px', color: (r.unmatched_local_trades || 0) > 0 ? 'var(--red)' : 'var(--text2)' }}>{r.unmatched_local_trades ?? 0}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text3)', fontSize: 9 }}>{r.started_at ? new Date(r.started_at).toLocaleString() : '--'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* All Items */}
        {items.length > 0 && (
          <>
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginTop: 24, marginBottom: 8 }}>Reconciliation Items</h3>
            <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)' }}>
                    {['Symbol', 'State', 'Issue', 'Broker Order', 'Client Order', 'Paper Trade', 'Date'].map(h => (
                      <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((i: any) => (
                    <tr key={i.id} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 10px', fontWeight: 700 }}>{i.symbol || '--'}</td>
                      <td style={{ padding: '6px 10px' }}><span style={pill(stateColor(i.reconciliation_state))}>{i.reconciliation_state}</span></td>
                      <td style={{ padding: '6px 10px', color: 'var(--text2)' }}>{i.issue_code || '--'}</td>
                      <td style={{ padding: '6px 10px', color: 'var(--text3)', fontSize: 9 }}>{i.broker_order_id || '--'}</td>
                      <td style={{ padding: '6px 10px', color: 'var(--text3)', fontSize: 9 }}>{i.client_order_id || '--'}</td>
                      <td style={{ padding: '6px 10px' }}>{i.paper_trade_id || '--'}</td>
                      <td style={{ padding: '6px 10px', color: 'var(--text3)', fontSize: 9 }}>{i.created_at ? new Date(i.created_at).toLocaleString() : '--'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </>
  )
}
