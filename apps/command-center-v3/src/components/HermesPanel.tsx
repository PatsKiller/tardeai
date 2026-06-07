import { useState } from 'react'
import { useApi } from '../hooks/useApi'

// Hermes global-profile management panel (Command Center → System → Hermes).
// Read-only status + safe SOUL/identity editing. Never enables the retired sidecar gateway.

const PROFILE_LABELS: Record<string, string> = {
  default: 'Global Hermes Identity',
  tradeai: 'Trade AI Advisory Identity',
  tradeai12b: 'Experimental 12B Trade AI Identity',
  dev: 'Development / Codex Identity',
  serverops: 'ServerOps Identity',
}

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200) }}
      style={{ marginLeft: 8, fontSize: 10, padding: '1px 6px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>
      {done ? '✓' : 'copy'}
    </button>
  )
}

function SoulEditor({ profile, onClose }: { profile: string; onClose: () => void }) {
  const { data, loading } = useApi<any>(`/api/v2/hermes/soul?profile=${profile}`, 0)
  const [text, setText] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const content = text ?? data?.content ?? ''

  async function save() {
    setSaving(true); setMsg(null)
    try {
      const r = await fetch('/api/v2/hermes/soul', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile, content }),
      })
      const d = await r.json()
      if (r.ok && d.ok) setMsg({ ok: true, text: `Saved. Backup: ${d.backup || '(new file)'}` })
      else setMsg({ ok: false, text: (d.errors ? d.errors.join(' · ') : d.error) || 'save failed' })
    } catch (e: any) { setMsg({ ok: false, text: String(e) }) }
    setSaving(false)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 20, width: 'min(820px,92vw)', maxHeight: '88vh', overflow: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Hermes Identity Editor — {PROFILE_LABELS[profile] || profile}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', fontSize: 20, cursor: 'pointer' }}>×</button>
        </div>
        <p style={{ fontSize: 11, color: 'var(--text3)', marginTop: 0 }}>{data?.path} — saves create a timestamped backup first; safety-validated before write.</p>
        {(profile === 'tradeai' || profile === 'tradeai12b') && (
          <div style={{ fontSize: 10, color: '#f59e0b', marginBottom: 8 }}>
            Trade AI profile: must keep boundary lines (no trades/orders/stops/proposals; do not read raw secrets). Unsafe enabling language is rejected.
          </div>
        )}
        {loading && text === null ? <p style={{ color: 'var(--text3)' }}>Loading…</p> : (
          <textarea value={content} onChange={e => setText(e.target.value)} spellCheck={false}
            style={{ width: '100%', minHeight: 360, fontFamily: 'monospace', fontSize: 12, padding: 10, background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 6, resize: 'vertical' }} />
        )}
        {msg && <div style={{ marginTop: 8, fontSize: 12, color: msg.ok ? '#22c55e' : '#ef4444' }}>{msg.text}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 12, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '6px 14px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>Cancel</button>
          <button onClick={save} disabled={saving} style={{ padding: '6px 14px', border: 'none', borderRadius: 6, background: '#60a5fa', color: '#fff', fontWeight: 600, cursor: saving ? 'wait' : 'pointer' }}>{saving ? 'Saving…' : 'Save SOUL'}</button>
        </div>
      </div>
    </div>
  )
}

export default function HermesPanel() {
  const { data: st } = useApi<any>('/api/v2/hermes/profiles-status', 60_000)
  const { data: tc } = useApi<any>('/api/v2/hermes/terminal-commands', 300_000)
  const { data: codex } = useApi<any>('/api/v2/hermes/codex-dev-status', 120_000)
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {st?.tools_note && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>ℹ {st.tools_note}</div>}
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
