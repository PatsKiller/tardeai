import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import SoulEditor from './HermesSoulEditor'

// Hermes global-profile management panel (Command Center → System → Hermes).
// Read-only status + safe SOUL/identity editing (shared HermesSoulEditor). Never enables the sidecar gateway.

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200) }}
      style={{ marginLeft: 8, fontSize: 10, padding: '1px 6px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>
      {done ? '✓' : 'copy'}
    </button>
  )
}

export default function HermesPanel() {
  const { data: st } = useApi<any>('/api/v2/hermes/profiles-status', 60_000)
  const { data: tc } = useApi<any>('/api/v2/hermes/terminal-commands', 300_000)
  const { data: codex } = useApi<any>('/api/v2/hermes/codex-dev-status', 120_000)
  const { data: legacy } = useApi<any>('/api/v2/hermes/legacy-agents', 300_000)
  const [editProfile, setEditProfile] = useState<string | null>(null)

  const card: React.CSSProperties = { background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }
  const kv: React.CSSProperties = { fontSize: 12, color: 'var(--text3)' }
  const gwActive = (st?.gateway_service_active || '').toLowerCase()
  const gwOk = gwActive !== 'active'

  return (
    <div>
      {editProfile && <SoulEditor profile={editProfile} onClose={() => setEditProfile(null)} />}

      {/* Status card */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Hermes Global Profiles</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 6 }}>
          <div style={kv}>Version: <b style={{ color: 'var(--text1)' }}>{st?.version || '…'}</b></div>
          <div style={kv}>CLI: <code>{st?.cli_path}</code></div>
          <div style={kv}>venv: <code>{st?.venv_path}</code></div>
          <div style={kv}>home: <code>{st?.home_path}</code></div>
          <div style={kv}>Old sidecar: <span style={{ color: '#f59e0b' }}>{st?.sidecar_status}</span></div>
          <div style={kv}>Gateway service: <b style={{ color: gwOk ? '#22c55e' : '#ef4444' }}>{st?.gateway_service_active} / {st?.gateway_service_enabled}</b></div>
        </div>
        {st?.sidecar_retired_dirs?.length > 0 && <div style={{ ...kv, marginTop: 6 }}>Retired dirs: {st.sidecar_retired_dirs.join(', ')}</div>}
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 6 }}>⚠ {st?.gateway_note}</div>
      </div>

      {/* Profile matrix */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Profiles</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
            {['Profile', 'Model', 'Tools', 'Status', 'Purpose', 'Actions'].map(h => <th key={h} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
          </tr></thead>
          <tbody>
            {(st?.profiles || []).map((p: any) => (
              <tr key={p.profile} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '6px 8px', fontWeight: 600 }}>{p.profile}</td>
                <td style={{ padding: '6px 8px' }}><code>{p.model}</code></td>
                <td style={{ padding: '6px 8px', color: /enabled:/.test(p.tools) ? '#f59e0b' : p.tools === 'disabled' ? '#22c55e' : 'var(--text3)' }}>{p.tools}</td>
                <td style={{ padding: '6px 8px' }}>{p.status}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text3)' }}>{p.purpose}</td>
                <td style={{ padding: '6px 8px' }}>
                  <button onClick={() => setEditProfile(p.profile)} style={{ fontSize: 11, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg1)', color: '#60a5fa', cursor: 'pointer' }}>View/Edit SOUL</button>
                  {p.soul_hash && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }} title={p.soul_mtime ? `modified ${new Date(p.soul_mtime * 1000).toLocaleString()}` : ''}>SOUL {p.soul_hash}{p.soul_mtime ? ` · ${new Date(p.soul_mtime * 1000).toLocaleDateString()}` : ''}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {st?.tools_note && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>ℹ {st.tools_note}</div>}
      </div>

      {/* Legacy / Retired Agents — read-only audit (Phase 206) */}
      <div style={{ ...card, border: '1px solid rgba(239,68,68,.3)', background: 'rgba(239,68,68,.05)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Legacy / Retired Agents — Read Only</div>
          <span style={{ fontSize: 9, color: 'var(--text3)' }}>
            {(legacy?.total ?? 0)} items · gateway {legacy?.gateway_service_active}/{legacy?.gateway_service_enabled} · scanned {legacy?.scanned_at ? new Date(legacy.scanned_at).toLocaleString() : '—'}
          </span>
        </div>
        <div style={{ fontSize: 10, color: '#ef4444', marginBottom: 8, fontWeight: 600 }}>
          ⚠ Retired sidecar artifacts are shown for audit only. Do not enable the retired gateway or execute retired wrappers.
        </div>
        {!legacy ? <div style={{ fontSize: 11, color: 'var(--text3)' }}>Loading legacy inventory…</div> :
         (legacy.items || []).filter((i: any) => i.status !== 'ACTIVE_PROFILE').length === 0 ?
         <div style={{ fontSize: 11, color: 'var(--text3)' }}>No retired agent artifacts found.</div> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
              {['Name', 'Source', 'Classification', 'Model', 'Tools', 'Purpose / Safety', 'Modified', 'Recommendation'].map(h =>
                <th key={h} style={{ padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {(legacy.items || []).filter((i: any) => i.status !== 'ACTIVE_PROFILE').map((i: any, idx: number) => {
                const danger = i.status === 'RETIRED_WRAPPER' || i.status === 'UNSAFE_RUNTIME_ARTIFACT'
                const tools = i.tools && (i.tools.toolsets || i.tools.disabled_toolsets)
                  ? `ts:${JSON.stringify(i.tools.toolsets ?? [])}` : '—'
                return (
                  <tr key={idx} style={{ borderBottom: '1px solid var(--border)', opacity: 0.92 }}>
                    <td style={{ padding: '5px 6px', fontFamily: 'monospace' }}>{i.name}</td>
                    <td style={{ padding: '5px 6px', color: 'var(--text3)', fontSize: 9 }}>{i.source_dir}</td>
                    <td style={{ padding: '5px 6px', color: danger ? '#ef4444' : '#f59e0b', fontWeight: 600 }}>{i.status}</td>
                    <td style={{ padding: '5px 6px' }}>{i.model ? <code>{i.model}</code> : '—'}</td>
                    <td style={{ padding: '5px 6px', color: 'var(--text3)' }}>{tools}</td>
                    <td style={{ padding: '5px 6px', color: 'var(--text3)' }}>{i.purpose || i.safety_note}</td>
                    <td style={{ padding: '5px 6px', color: 'var(--text3)', fontSize: 9 }}>{i.last_modified ? new Date(i.last_modified).toLocaleDateString() : '—'}</td>
                    <td style={{ padding: '5px 6px', color: danger ? '#ef4444' : 'var(--text2)' }}>{i.migration_recommendation}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>
          Source: /api/v2/hermes/legacy-agents · read-only · no enable/run/edit · secrets redacted · runtime-state contents not exposed.
        </div>
      </div>

      {/* Terminal commands */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>How to call Hermes from terminal</div>
        {(tc?.chat || []).map((c: string) => (
          <div key={c} style={{ fontFamily: 'monospace', fontSize: 12, marginBottom: 3 }}>{c}<Copy text={c} /></div>
        ))}
        <div style={{ fontWeight: 600, fontSize: 11, color: 'var(--text3)', margin: '8px 0 4px' }}>Diagnostics</div>
        {(tc?.diagnostics || []).map((c: string) => (
          <div key={c} style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text3)', marginBottom: 2 }}>{c}<Copy text={c} /></div>
        ))}
        <div style={{ fontSize: 10, color: '#ef4444', marginTop: 8 }}>⚠ {tc?.warning}</div>
      </div>

      {/* Codex dev */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>ChatGPT / Codex Dev Profile</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 6, marginBottom: 8 }}>
          <div style={kv}>dev profile exists: <b>{String(codex?.dev_profile_exists)}</b></div>
          <div style={kv}>dev SOUL exists: <b>{String(codex?.dev_soul_exists)}</b></div>
          <div style={kv}>dev model configured: <b>{String(codex?.dev_model_configured)}</b></div>
          <div style={kv}>Codex auth: <b>{codex?.codex_auth_configured}</b></div>
          <div style={kv}>Codex runtime enabled: <b style={{ color: '#22c55e' }}>{String(codex?.codex_runtime_enabled)}</b></div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, padding: 10 }}>
          {(codex?.terminal_instructions || []).map((l: string, i: number) => (
            <div key={i} style={{ fontFamily: 'monospace', fontSize: 11, color: l.startsWith('#') ? 'var(--text3)' : 'var(--text1)' }}>{l}</div>
          ))}
        </div>
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 8 }}>ℹ {codex?.note}</div>
      </div>
    </div>
  )
}
