import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface QueueData {
  timestamp: string; timers_total: number; cron_count: number
  categories: Record<string, number>
  category_details: Record<string, Array<{ timer: string; activates: string }>>
  system_services: string[]; ollama_loaded: string[]
  all_timers: Array<{ timer: string; activates: string }>
}

const catLabels: Record<string, { label: string; color: string; icon: string }> = {
  '24x7_services': { label: '24/7 Services', color: '#22c55e', icon: '🟢' },
  tonight_overnight: { label: 'Tonight / Overnight', color: '#8b5cf6', icon: '🌙' },
  market_morning: { label: 'Market Morning', color: '#f59e0b', icon: '☀️' },
  hermes_research: { label: 'Hermes Research', color: '#3b82f6', icon: '🔬' },
  hermes_advisory: { label: 'Hermes Advisory', color: '#06b6d4', icon: '🤖' },
  governance: { label: 'Governance', color: '#6b7280', icon: '📋' },
  portfolio: { label: 'Portfolio', color: '#10b981', icon: '💼' },
  other: { label: 'Other', color: '#94a3b8', icon: '⚙️' },
}

export default function QueueControlTower() {
  const { data } = useApi<QueueData>('/api/v2/system/queue-control-tower', 30_000)

  if (!data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading queue data...</div>

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>
      <PageHeader title="Queue Control Tower" subtitle={`${data.timers_total} timers · ${data.cron_count} cron jobs · Read-only`} />

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 16 }}>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 16px', textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text0)' }}>{data.timers_total}</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>Timers</div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 16px', textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text0)' }}>{data.cron_count}</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>Cron Jobs</div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 16px', textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: '#22c55e' }}>{data.system_services.length}</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>Running Services</div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 16px', textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: '#3b82f6' }}>{data.ollama_loaded.length}</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>LLM Models Loaded</div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 16px', textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{data.ollama_loaded.join(', ') || 'none'}</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>Active Model</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Categories */}
        {Object.entries(data.category_details).map(([cat, jobs]) => {
          const cfg = catLabels[cat] || { label: cat, color: '#888', icon: '?' }
          return (
            <Card key={cat} title={`${cfg.icon} ${cfg.label} (${jobs.length})`}>
              {jobs.length === 0 ? (
                <div style={{ fontSize: 11, color: 'var(--text3)', padding: 8 }}>No jobs in this category</div>
              ) : (
                jobs.map((j, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                    <span style={{ color: cfg.color, fontWeight: 600, fontFamily: 'monospace' }}>{j.timer.replace('.timer', '')}</span>
                    <span style={{ color: 'var(--text3)' }}>{j.activates.replace('.service', '')}</span>
                  </div>
                ))
              )}
            </Card>
          )
        })}
      </div>

      {/* System services */}
      <div style={{ marginTop: 16 }}>
        <Card title={`🟢 System Services (${data.system_services.length})`}>
          {data.system_services.map(s => (
            <div key={s} style={{ padding: '4px 8px', fontSize: 11, color: '#22c55e', fontFamily: 'monospace' }}>{s}</div>
          ))}
        </Card>
      </div>

      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 12, textAlign: 'center' }}>
        Read-only · No action controls · Updated {new Date(data.timestamp).toLocaleString()}
      </div>
    </div>
  )
}
