import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import { useApi } from '../hooks/useApi'

interface Service {
  name: string
  url: string | null
  health_url?: string
  category: string
  health: string | null
  note?: string
  install_path?: string
  hermes_home?: string
}

interface AccessData {
  tailscale: { fqdn: string; ip: string; ssh: string }
  services: Service[]
  drive: { folder_id: string; folder_name: string }
  hermes_reports: string[]
}

const healthColor: Record<string, string> = {
  healthy: 'var(--green)', warning: 'var(--amber)', down: 'var(--red)', unknown: 'var(--text3)',
}

function CopyBtn({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
      style={{ fontSize: 10, padding: '3px 8px', border: '1px solid var(--border)', borderRadius: 4, background: copied ? 'rgba(14,203,129,.15)' : 'var(--bg2)', color: copied ? 'var(--green)' : 'var(--text2)', cursor: 'pointer' }}
    >{copied ? 'Copied' : (label || 'Copy')}</button>
  )
}

function ServiceRow({ s }: { s: Service }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ width: 8, height: 8, borderRadius: '50%', background: healthColor[s.health || 'unknown'] || 'var(--text3)', flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{s.name}</div>
        {s.url && <div style={{ fontSize: 10, color: 'var(--text3)', wordBreak: 'break-all' }}>{s.url}</div>}
        {(s as any).localhost_url && <div style={{ fontSize: 10, color: 'var(--text3)', wordBreak: 'break-all', opacity: 0.6 }}>localhost: {(s as any).localhost_url}</div>}
        {s.note && <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 2 }}>{s.note}</div>}
        {s.install_path && <div style={{ fontSize: 10, color: 'var(--text3)' }}>Path: {s.install_path}</div>}
        {s.hermes_home && <div style={{ fontSize: 10, color: 'var(--text3)' }}>HERMES_HOME: {s.hermes_home}</div>}
      </div>
      <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
        {s.url && (
          <>
            <a href={s.url} target="_blank" rel="noopener noreferrer"
              style={{ fontSize: 10, padding: '3px 8px', border: '1px solid var(--accent)', borderRadius: 4, color: 'var(--accent)', textDecoration: 'none' }}>Open</a>
            <CopyBtn text={s.url} label="Copy URL" />
          </>
        )}
        {s.health_url && <CopyBtn text={`curl -s ${s.health_url} | head -c 200`} label="Copy curl" />}
      </div>
    </div>
  )
}

export default function SystemAccess() {
  const [rk, setRk] = useState(0)
  const { data, loading, error } = useApi<AccessData>(`/api/v2/system/access-links?_r=${rk}`)

  if (loading && !data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>
  if (error) return <div style={{ padding: 24, color: 'var(--red)' }}>Error: {error}</div>
  if (!data) return null

  const byCategory = (cat: string) => data.services.filter(s => s.category === cat)

  return (
    <>
      <PageHeader title="System Access Links" subtitle="Endpoints, services, and access paths" actions={
        <button onClick={() => setRk(k => k + 1)} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>Refresh</button>
      } />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 12, padding: '0 0 16px' }}>
        {/* Tailscale */}
        <Card title="Tailscale Access">
          <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 8 }}>
            <div>FQDN: <span style={{ color: 'var(--text0)' }}>{data.tailscale.fqdn}</span></div>
            <div>IP: <span style={{ color: 'var(--text0)' }}>{data.tailscale.ip}</span></div>
          </div>
          <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
            <CopyBtn text={data.tailscale.ssh} label="Copy SSH" />
            <CopyBtn text={data.tailscale.fqdn} label="Copy FQDN" />
          </div>
          {byCategory('tailscale').map((s, i) => <ServiceRow key={i} s={s} />)}
        </Card>

        {/* Localhost */}
        <Card title="Local Services">
          {byCategory('localhost').map((s, i) => <ServiceRow key={i} s={s} />)}
        </Card>

        {/* Drive & Reports */}
        <Card title="Documentation & Drive">
          <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 8 }}>
            <div>Drive folder: <span style={{ color: 'var(--text0)' }}>{data.drive.folder_name}</span></div>
          </div>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text1)', marginTop: 12, marginBottom: 6 }}>Hermes Reports</div>
          {data.hermes_reports.map((r, i) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--text3)', padding: '3px 0' }}>{r.split('/').pop()}</div>
          ))}
        </Card>
      </div>
    </>
  )
}
