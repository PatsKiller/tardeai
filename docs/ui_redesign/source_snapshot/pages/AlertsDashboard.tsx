import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'

type VolumeStats = { sent: number; suppressed: number; queued: number; dashboard_only: number; total: number }
type TierRow = { tier: string; action_taken: string; count: number }
type SuppressedRow = { alert_type: string; symbol: string | null; suppressed_count: number; last_attempt: string }
type DigestRow = { digest_slot: string; queued: number }
type UrgentRow = { alert_type: string; symbol: string | null; message: string; created_at: string; action_taken: string }

type SystemAlert = { id: string; alert_type: string; severity: string; raw_text: string; created_at: string; parsed_payload?: Record<string, unknown> }

type AlertsData = {
  volume_stats: VolumeStats & { system?: number }
  by_tier: TierRow[]
  suppressed: SuppressedRow[]
  digest_pending: DigestRow[]
  urgent_recent: UrgentRow[]
  system_alerts?: SystemAlert[]
  system_alert_count?: number
}

const btn: React.CSSProperties = { fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg1)', color: 'var(--text1)', cursor: 'pointer' }
const th: React.CSSProperties = { padding: '6px 8px', textAlign: 'left', color: '#848e9c', fontSize: 10, fontWeight: 600, borderBottom: '1px solid var(--border)' }
const td: React.CSSProperties = { padding: '6px 8px', fontSize: 11, borderBottom: '1px solid rgba(255,255,255,0.03)' }

export default function AlertsDashboard() {
  const [rk, setRk] = useState(0)
  const { data, loading, error } = useApi<AlertsData>(`/api/v2/alerts-dashboard?_r=${rk}`)

  if (loading && !data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading alerts...</div>
  if (error) return <div style={{ padding: 24, color: 'var(--red)' }}>Error: {error}</div>
  if (!data) return <div style={{ padding: 24, color: 'var(--text3)' }}>No data</div>

  const v = data.volume_stats || { sent: 0, suppressed: 0, queued: 0, dashboard_only: 0, total: 0 }
  const reduction = v.total > 0 ? Math.round(((v.suppressed + v.dashboard_only) / v.total) * 100) : 0

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1200 }}>
      <PageHeader title="Alert Dashboard" subtitle="Three-tier alert architecture"
        actions={<button onClick={() => setRk(k => k + 1)} style={btn}>Refresh</button>} />

      {/* Volume stats */}
      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 13 }}>
          <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>SYSTEM</span><br /><span style={{ color: '#f6465d', fontWeight: 700 }}>{v.system ?? data.system_alert_count ?? 0}</span></div>
          <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>SENT</span><br /><span style={{ color: '#0ecb81', fontWeight: 700 }}>{v.sent}</span></div>
          <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>SUPPRESSED</span><br /><span style={{ color: '#f0b90b', fontWeight: 700 }}>{v.suppressed}</span></div>
          <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>QUEUED</span><br /><span style={{ color: '#4a90f4', fontWeight: 700 }}>{v.queued}</span></div>
          <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>DISPATCHED</span><br /><span style={{ color: 'var(--text2)', fontWeight: 700 }}>{v.dashboard_only}</span></div>
          <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>TOTAL</span><br /><span style={{ fontWeight: 700 }}>{v.total}</span></div>
        </div>
      </Card>

      {/* Digest pending */}
      {data.digest_pending.length > 0 && (
        <Card title="Digest Queue" subtitle="Pending next brief" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 16 }}>
            {data.digest_pending.map((d, i) => (
              <div key={i} style={{ fontSize: 11 }}>
                <span style={{ color: '#4a90f4', fontWeight: 600 }}>{d.digest_slot}</span>: {d.queued} queued
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Recent urgent */}
      {data.urgent_recent.length > 0 && (
        <Card title="Recent Urgent Alerts" subtitle="Last 24h" style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Type</th><th style={th}>Symbol</th><th style={th}>Action</th><th style={th}>Time</th>
            </tr></thead>
            <tbody>
              {data.urgent_recent.map((u, i) => (
                <tr key={i}>
                  <td style={{ ...td, color: 'var(--text2)' }}>{u.alert_type.replace(/_/g, ' ')}</td>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{u.symbol || '-'}</td>
                  <td style={{ ...td, color: u.action_taken === 'sent_telegram' ? '#0ecb81' : u.action_taken === 'suppressed_dedup' ? '#f0b90b' : 'var(--text3)' }}>
                    {u.action_taken?.replace(/_/g, ' ')}
                  </td>
                  <td style={{ ...td, color: 'var(--text3)' }}>{timeAgo(u.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Suppressed */}
      {data.suppressed.length > 0 && (
        <Card title="Suppressed Alerts" subtitle="Would have been spam" style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Type</th><th style={th}>Symbol</th><th style={th}>Suppressed</th><th style={th}>Last Attempt</th>
            </tr></thead>
            <tbody>
              {data.suppressed.map((s, i) => (
                <tr key={i}>
                  <td style={{ ...td, color: 'var(--text2)' }}>{s.alert_type?.replace(/_/g, ' ')}</td>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{s.symbol || '-'}</td>
                  <td style={{ ...td, color: '#f0b90b' }}>{s.suppressed_count}x</td>
                  <td style={{ ...td, color: 'var(--text3)' }}>{timeAgo(s.last_attempt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* By tier breakdown */}
      {data.by_tier.length > 0 && (
        <Card title="By Tier" subtitle="24h classification" style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Tier</th><th style={th}>Action</th><th style={th}>Count</th>
            </tr></thead>
            <tbody>
              {data.by_tier.map((t, i) => (
                <tr key={i}>
                  <td style={{ ...td, color: t.tier === 'URGENT' ? '#f6465d' : t.tier === 'DIGEST' ? '#4a90f4' : 'var(--text3)', fontWeight: 600 }}>{t.tier}</td>
                  <td style={{ ...td, color: 'var(--text2)' }}>{t.action_taken?.replace(/_/g, ' ')}</td>
                  <td style={td}>{t.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* System / data-product alerts */}
      {(data.system_alerts?.length ?? 0) > 0 && (
        <Card title={`System Alerts (${data.system_alerts?.length})`} style={{ marginTop: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th style={th}>Type</th><th style={th}>Severity</th><th style={th}>Detail</th><th style={th}>Time</th></tr></thead>
            <tbody>
              {data.system_alerts?.map((a, i) => {
                const sevColor = a.severity === 'urgent' ? '#f6465d' : a.severity === 'warning' ? '#f0b90b' : '#848e9c'
                return (
                  <tr key={i}>
                    <td style={td}><span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, background: 'rgba(255,255,255,0.04)', fontFamily: 'monospace' }}>{a.alert_type}</span></td>
                    <td style={{ ...td, color: sevColor, fontWeight: 600 }}>{a.severity}</td>
                    <td style={td}>{a.raw_text}</td>
                    <td style={{ ...td, fontSize: 10, color: '#848e9c' }}>{a.created_at ? timeAgo(a.created_at) : ''}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Card>
      )}

      {v.total === 0 && (!data.system_alerts || data.system_alerts.length === 0) && (
        <Card style={{ marginTop: 20 }}>
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--text3)' }}>
            <div style={{ fontSize: 14, marginBottom: 8 }}>No alerts classified in the last 24 hours</div>
            <div style={{ fontSize: 11 }}>The three-tier system will classify alerts as they fire</div>
          </div>
        </Card>
      )}
    </div>
  )
}
