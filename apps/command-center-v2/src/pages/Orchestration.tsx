import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'

interface Timer { name: string; next: string; last: string; schedule: string; activates: string; status: string; last_start?: string; last_end?: string; result?: string }
interface Service { name: string; status: string; description: string }
interface Skill { name: string; path: string; type: string }
interface Script { name: string; purpose: string }
interface EnvCheck { name: string; ok: boolean; detail: string; fix: string }
interface OrchData { timers: Timer[]; services: Service[]; skills: Skill[]; scripts: Script[]; env_checks: EnvCheck[]; health: string; failed_timers: number; failed_env: number }

const statusColor = (s: string) => s === 'active' || s === 'running' ? 'var(--green)' : s === 'waiting' ? 'var(--accent)' : s === 'failed' ? 'var(--red)' : 'var(--text3)'

export default function Orchestration() {
  const navigate = useNavigate()
  const { data } = useApi<OrchData>('/api/v2/orchestration')

  if (!data) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading orchestration data...</div>

  return (
    <>
      <PageHeader title="Orchestration" subtitle={`${data.timers.length} timers · ${data.services.length} services · ${data.skills.length} skills — for API keys & DB state see System Health`} />

      {/* Quick nav */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {(['morning-brief', 'actions', 'ops', 'system-health'] as const).map(p => (
          <button key={p} onClick={() => navigate(`/${p}`)} style={{ fontSize: 9, padding: '3px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>{p === 'morning-brief' ? 'Morning Brief' : p === 'actions' ? 'Actions' : p === 'system-health' ? 'System Health' : 'Ops'}</button>
        ))}
      </div>

      {/* System health banner */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, alignItems: 'center' }}>
        <div style={{ width: 40, height: 40, borderRadius: 999, display: 'grid', placeItems: 'center', fontWeight: 800, fontSize: 11, border: `3px solid ${data.health === 'healthy' ? 'var(--green)' : data.health === 'degraded' ? 'var(--amber)' : 'var(--red)'}`, color: data.health === 'healthy' ? 'var(--green)' : data.health === 'degraded' ? 'var(--amber)' : 'var(--red)' }}>
          {data.health === 'healthy' ? '\u2713' : data.health === 'degraded' ? '\u26a0' : '\u2717'}
        </div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: data.health === 'healthy' ? 'var(--green)' : data.health === 'degraded' ? 'var(--amber)' : 'var(--red)', textTransform: 'uppercase' }}>{data.health}</div>
          <div style={{ fontSize: 9, color: 'var(--text3)' }}>
            {data.failed_timers > 0 && `${data.failed_timers} failed timer${data.failed_timers !== 1 ? 's' : ''} `}
            {data.failed_env > 0 && `${data.failed_env} env issue${data.failed_env !== 1 ? 's' : ''}`}
            {data.failed_timers === 0 && data.failed_env === 0 && 'All systems operational'}
          </div>
        </div>
      </div>

      {/* Environment readiness */}
      <SectionHeader title="Environment Readiness" count={data.env_checks.length} />
      <Card compact>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 6 }}>
          {data.env_checks.map(e => (
            <div key={e.name} style={{ display: 'flex', gap: 6, padding: '4px 8px', borderRadius: 'var(--radius)', background: e.ok ? 'var(--bg3)' : 'var(--red-dim)', border: `1px solid ${e.ok ? 'var(--border-subtle)' : 'var(--red)'}`, alignItems: 'center' }}>
              <span style={{ fontSize: 10, color: e.ok ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>{e.ok ? '\u2713' : '\u2717'}</span>
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text0)' }}>{e.name}</div>
                <div style={{ fontSize: 8, color: e.ok ? 'var(--text3)' : 'var(--red)' }}>
                  {e.ok ? e.detail : e.fix || e.detail}
                  {!e.ok && <span style={{ display: 'block', fontSize: 7, color: 'var(--amber)', marginTop: 1 }}>Pipeline will not run if this check fails</span>}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Scheduled Jobs */}
      <SectionHeader title="Scheduled Jobs (systemd timers)" count={data.timers.length} />
      <Card>
        <div style={{ overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
            <thead>
              <tr style={{ background: 'var(--bg1)' }}>
                {['Timer', 'Schedule', 'Next Run', 'Last Run', 'Duration', 'Result'].map(h => (
                  <th key={h} style={{ padding: '5px 8px', textAlign: 'left', color: 'var(--text3)', fontSize: 9, fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.timers.map(t => (
                <tr key={t.name}>
                  <td style={{ padding: '5px 8px', borderBottom: '1px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text0)' }}>{t.name.replace('.timer', '')}</td>
                  <td style={{ padding: '5px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text2)', fontFamily: 'var(--mono)', fontSize: 9 }}>{t.schedule}</td>
                  <td style={{ padding: '5px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--accent)', fontSize: 9 }}>{t.next ? t.next.slice(0, 25) : '—'}</td>
                  <td style={{ padding: '5px 8px', borderBottom: '1px solid var(--border-subtle)', fontSize: 9 }}>
                    {t.last_start ? (() => {
                      const ago = timeAgo(t.last_start)
                      const msAgo = Date.now() - new Date(t.last_start).getTime()
                      const overdue = msAgo > 48 * 3600000
                      return <span style={{ color: overdue ? 'var(--amber)' : 'var(--text2)' }}>{ago}{overdue ? ' ⚠️' : ''}</span>
                    })() : <span style={{ color: 'var(--text3)' }}>—</span>}
                  </td>
                  <td style={{ padding: '5px 8px', borderBottom: '1px solid var(--border-subtle)', fontSize: 9 }}>{t.last_start && t.last_end ? (() => { try { const ms = new Date(t.last_end!).getTime() - new Date(t.last_start!).getTime(); const dur = ms > 60000 ? `${(ms/60000).toFixed(0)}m` : `${(ms/1000).toFixed(0)}s`; const long = ms > 60 * 60000; return <span style={{ color: long ? 'var(--amber)' : 'var(--text3)' }}>{dur}{long ? ' (long)' : ''}</span> } catch { return '—' } })() : '—'}</td>
                  <td style={{ padding: '5px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                    <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, color: t.result === 'success' ? 'var(--green)' : t.result === 'failed' ? 'var(--red)' : statusColor(t.status), background: `color-mix(in srgb, ${t.result === 'success' ? 'var(--green)' : t.result === 'failed' ? 'var(--red)' : statusColor(t.status)} 15%, transparent)` }}>{t.result || t.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Active Services */}
      <SectionHeader title="Active Services" count={data.services.length} />
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {data.services.map(s => (
            <div key={s.name} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, color: statusColor(s.status), background: `color-mix(in srgb, ${statusColor(s.status)} 15%, transparent)` }}>{s.status}</span>
              <span style={{ fontWeight: 600, color: 'var(--text0)', width: 180 }}>{s.name.replace('.service', '')}</span>
              <span style={{ color: 'var(--text2)' }}>{s.description}</span>
            </div>
          ))}
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* Skills / Agents */}
        <div>
          <SectionHeader title="Skills & Agents" count={data.skills.length} />
          <Card>
            {data.skills.map(s => (
              <div key={s.name} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
                <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: s.type === 'agent' ? 'var(--accent-dim)' : 'var(--green-dim)', color: s.type === 'agent' ? 'var(--accent)' : 'var(--green)' }}>{s.type}</span>
                <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{s.name}</span>
              </div>
            ))}
          </Card>
        </div>

        {/* Automation Scripts */}
        <div>
          <SectionHeader title="Automation Scripts" count={data.scripts.length} />
          <Card>
            {data.scripts.map(s => (
              <div key={s.name} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
                <span style={{ fontWeight: 600, color: 'var(--text1)', fontFamily: 'var(--mono)' }}>{s.name}</span>
                <span style={{ color: 'var(--text3)' }}>{s.purpose}</span>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </>
  )
}
