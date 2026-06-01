import { useState, useMemo } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface AppInfo {
  name: string
  category: string
  installed: string | null
  latest: string | null
  path: string | null
  version_cmd: string
  update_cmd: string
  note?: string
  drift: { status: string; detail: string }
}

interface AppsData {
  applications: AppInfo[]
  summary: { total: number; current: number; behind: number; unknown: number; not_installed: number }
  versions_checked_at?: string
}

const statusColors: Record<string, string> = {
  current: 'var(--green)', patch_behind: 'var(--amber)', minor_behind: '#e67e22',
  major_behind: 'var(--red)', unknown: 'var(--text3)', not_installed: 'var(--text3)',
}

const statusLabels: Record<string, string> = {
  current: 'Current', patch_behind: 'Patch Behind', minor_behind: 'Minor Behind',
  major_behind: 'Major Behind', unknown: 'Unknown', not_installed: 'Not Installed',
}

const categoryLabels: Record<string, string> = {
  core: 'Core', agent: 'AI / Agent', model: 'Ollama Models',
  integration: 'Integrations', frontend: 'Frontend',
}

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
      title={text}
      style={{ fontSize: 9, padding: '2px 6px', border: '1px solid var(--border)', borderRadius: 3, background: copied ? 'rgba(14,203,129,.15)' : 'var(--bg2)', color: copied ? 'var(--green)' : 'var(--text3)', cursor: 'pointer' }}
    >{copied ? 'Copied' : 'Copy'}</button>
  )
}

function DetailModal({ app, onClose }: { app: AppInfo; onClose: () => void }) {
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 20, maxWidth: 520, width: '90%' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>{app.name}</div>
        <div style={{ display: 'grid', gap: 8, fontSize: 11 }}>
          <Row label="Category" value={categoryLabels[app.category] || app.category} />
          <Row label="Installed" value={app.installed || 'Unknown'} />
          <Row label="Latest" value={app.latest || 'Unknown'} />
          <Row label="Status" value={statusLabels[app.drift.status] || app.drift.status} />
          {app.drift.detail && <Row label="Drift" value={app.drift.detail} />}
          <Row label="Path" value={app.path || 'N/A'} />
          <div style={{ marginTop: 8 }}>
            <div style={{ color: 'var(--text2)', marginBottom: 4 }}>Version command:</div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <code style={{ fontSize: 10, color: 'var(--text1)', background: 'var(--bg2)', padding: '4px 8px', borderRadius: 4, flex: 1, wordBreak: 'break-all' }}>{app.version_cmd}</code>
              <CopyBtn text={app.version_cmd} />
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text2)', marginBottom: 4 }}>Update command:</div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <code style={{ fontSize: 10, color: 'var(--amber)', background: 'var(--bg2)', padding: '4px 8px', borderRadius: 4, flex: 1, wordBreak: 'break-all' }}>{app.update_cmd}</code>
              <CopyBtn text={app.update_cmd} />
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Commands are copy-only. They are not executed from this page.</div>
          </div>
          {app.note && <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 4, padding: '6px 8px', background: 'rgba(246,190,0,.08)', borderRadius: 4 }}>{app.note}</div>}
        </div>
        <button onClick={onClose} style={{ marginTop: 16, fontSize: 11, padding: '6px 16px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>Close</button>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <span style={{ color: 'var(--text3)', minWidth: 80 }}>{label}:</span>
      <span style={{ color: 'var(--text1)' }}>{value}</span>
    </div>
  )
}

export default function SystemApplications() {
  const [rk, setRk] = useState(0)
  const [search, setSearch] = useState('')
  const [catFilter, setCatFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [detail, setDetail] = useState<AppInfo | null>(null)
  const { data, loading, error } = useApi<AppsData>(`/api/v2/system/applications?_r=${rk}`)
  const { data: sjData } = useApi<{ timers: { total: number; hermes: Array<{ name: string; status: string }>; tradeai: Array<{ name: string; status: string }>; other_count: number }; cron: { active: number; migrated: number }; health: { last_observation: string | null; last_backlog_health: string | null } }>(`/api/v2/system/scheduled-jobs?_r=${rk}`)

  const filtered = useMemo(() => {
    if (!data) return []
    return data.applications.filter(a => {
      if (search && !a.name.toLowerCase().includes(search.toLowerCase())) return false
      if (catFilter !== 'all' && a.category !== catFilter) return false
      if (statusFilter === 'behind' && !a.drift.status.includes('behind')) return false
      if (statusFilter === 'unknown' && a.drift.status !== 'unknown') return false
      if (statusFilter !== 'all' && statusFilter !== 'behind' && statusFilter !== 'unknown' && a.drift.status !== statusFilter) return false
      return true
    })
  }, [data, search, catFilter, statusFilter])

  if (loading && !data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>
  if (error) return <div style={{ padding: 24, color: 'var(--red)' }}>Error: {error}</div>
  if (!data) return null

  const s = data.summary
  const categories = [...new Set(data.applications.map(a => a.category))]

  return (
    <>
      <PageHeader title="System Applications" subtitle={`Installed software inventory and version drift${data.versions_checked_at ? ` — last checked ${new Date(data.versions_checked_at).toLocaleDateString()}` : ''}`} actions={
        <button onClick={() => setRk(k => k + 1)} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>Refresh</button>
      } />

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        {[
          { label: 'Total', value: s.total, color: 'var(--text0)' },
          { label: 'Current', value: s.current, color: 'var(--green)' },
          { label: 'Behind', value: s.behind, color: 'var(--amber)' },
          { label: 'Unknown', value: s.unknown, color: 'var(--text3)' },
        ].map((m, i) => (
          <div key={i} style={{ padding: '8px 16px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, textAlign: 'center' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: m.color }}>{m.value}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>{m.label}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search..."
          style={{ fontSize: 11, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', width: 160 }} />
        <select value={catFilter} onChange={e => setCatFilter(e.target.value)}
          style={{ fontSize: 11, padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)' }}>
          <option value="all">All Categories</option>
          {categories.map(c => <option key={c} value={c}>{categoryLabels[c] || c}</option>)}
        </select>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          style={{ fontSize: 11, padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)' }}>
          <option value="all">All Status</option>
          <option value="behind">Behind Only</option>
          <option value="unknown">Unknown Only</option>
          <option value="current">Current Only</option>
        </select>
      </div>

      {/* Table */}
      <Card>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Application', 'Category', 'Installed', 'Latest', 'Status', 'Actions'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)', fontWeight: 600, fontSize: 10 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((app, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '6px 8px', color: 'var(--text0)', fontWeight: 500 }}>{app.name}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text3)' }}>{categoryLabels[app.category] || app.category}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text1)', fontFamily: 'monospace', fontSize: 10 }}>{app.installed || '—'}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text3)', fontFamily: 'monospace', fontSize: 10 }}>{app.latest || '—'}</td>
                <td style={{ padding: '6px 8px' }}>
                  <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: `${statusColors[app.drift.status] || 'var(--text3)'}22`, color: statusColors[app.drift.status] || 'var(--text3)' }}>
                    {statusLabels[app.drift.status] || app.drift.status}
                  </span>
                </td>
                <td style={{ padding: '6px 8px' }}>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <CopyBtn text={app.version_cmd} />
                    <button onClick={() => setDetail(app)} style={{ fontSize: 9, padding: '2px 6px', border: '1px solid var(--accent)', borderRadius: 3, background: 'transparent', color: 'var(--accent)', cursor: 'pointer' }}>Details</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <div style={{ padding: 16, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>No applications match filters</div>}
      </Card>

      {detail && <DetailModal app={detail} onClose={() => setDetail(null)} />}

      {/* Scheduled Jobs Health */}
      {sjData && (
        <Card title="Scheduled Jobs">
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
            {[
              { label: 'Systemd Timers', value: sjData.timers.total, color: 'var(--accent)' },
              { label: 'Active Cron', value: sjData.cron.active, color: 'var(--text0)' },
              { label: 'Migrated', value: sjData.cron.migrated, color: 'var(--green)' },
            ].map((m, i) => (
              <div key={i} style={{ padding: '6px 12px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, textAlign: 'center' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: m.color }}>{m.value}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{m.label}</div>
              </div>
            ))}
          </div>
          {sjData.timers.hermes.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 4, fontWeight: 600 }}>Hermes Timers</div>
              {sjData.timers.hermes.map((t, i) => (
                <div key={i} style={{ fontSize: 11, display: 'flex', gap: 6, alignItems: 'center', padding: '2px 0' }}>
                  <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: t.status === 'active' ? 'rgba(14,203,129,.15)' : 'rgba(234,57,67,.15)', color: t.status === 'active' ? 'var(--green)' : 'var(--red)' }}>{t.status}</span>
                  <span style={{ color: 'var(--text1)' }}>{t.name.replace(/-/g, ' ')}</span>
                </div>
              ))}
            </div>
          )}
          {sjData.timers.tradeai.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 4, fontWeight: 600 }}>Trade AI Timers</div>
              {sjData.timers.tradeai.map((t, i) => (
                <div key={i} style={{ fontSize: 11, display: 'flex', gap: 6, alignItems: 'center', padding: '2px 0' }}>
                  <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: t.status === 'active' ? 'rgba(14,203,129,.15)' : 'rgba(234,57,67,.15)', color: t.status === 'active' ? 'var(--green)' : 'var(--red)' }}>{t.status}</span>
                  <span style={{ color: 'var(--text1)' }}>{t.name.replace(/-/g, ' ')}</span>
                </div>
              ))}
            </div>
          )}
          {sjData.health.last_observation && (
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>
              Last observation: {new Date(sjData.health.last_observation).toLocaleString()} | Last backlog health: {sjData.health.last_backlog_health ? new Date(sjData.health.last_backlog_health).toLocaleString() : 'N/A'}
            </div>
          )}
        </Card>
      )}
    </>
  )
}
