import { useState } from 'react'
import { useApi } from '../hooks/useApi'

// Secrets / API-key manager. Write-only: the UI never shows or receives a full secret value — only a
// masked '••••1234' hint + presence. Used to rotate keys (e.g. ANTHROPIC_API_KEY) after a leak.
export default function SecretsManager() {
  const { data, refetch } = useApi<any>('/api/v2/admin/secrets', 60_000)
  const secrets: any[] = data?.secrets ?? []
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [val, setVal] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const save = async () => {
    if (!key.trim() || val.trim().length < 4 || busy) return
    setBusy(true); setMsg('')
    try {
      const r = await fetch('/api/v2/admin/secrets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: key.trim(), value: val }) })
      const j = await r.json()
      if (j?.data?.ok) { setMsg(`✓ ${j.data.key} ${j.data.rotated ? 'rotated' : 'set'} (${j.data.masked}). ${j.data.note}`); setVal(''); setKey(''); setTimeout(() => { refetch(); setOpen(false) }, 1800) }
      else setMsg(`✗ ${j?.error || j?.data?.error || 'failed'}`)
    } catch { setMsg('✗ request failed') }
    setBusy(false)
  }

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>API Keys & Secrets</div>
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>write-only · values are masked & never displayed · stored in .env (0600, gitignored, never synced)</div>
        </div>
        <button onClick={() => { setOpen(true); setMsg('') }} style={{ padding: '8px 14px', fontSize: 12, fontWeight: 700, borderRadius: 7, border: 'none', cursor: 'pointer', background: '#a855f7', color: '#fff' }}>+ Add / Rotate Secret</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 6, marginTop: 12 }}>
        {secrets.map((s: any) => (
          <div key={s.key} onClick={() => { setKey(s.key); setOpen(true); setMsg('') }} title="rotate this secret"
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 10px', borderRadius: 7, cursor: 'pointer', background: 'var(--bg2)', border: '1px solid var(--border)' }}>
            <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text1)' }}>{s.key}</span>
            <span style={{ fontSize: 10, color: s.present ? '#22c55e' : '#ef4444' }}>{s.present ? s.masked : 'not set'}</span>
          </div>
        ))}
      </div>

      {open && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.5)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setOpen(false)}>
          <div onClick={e => e.stopPropagation()} style={{ width: 460, maxWidth: '92vw', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Add / Rotate Secret</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 14 }}>The value is write-only — it is stored in .env and never displayed, returned, logged, or synced to git/Drive.</div>
            <label style={{ fontSize: 10, color: 'var(--text3)' }}>Key name (UPPER_SNAKE_CASE, ends with _KEY/_TOKEN/_SECRET/_PASSWORD)</label>
            <input list="secret-keys" value={key} onChange={e => setKey(e.target.value.toUpperCase())} placeholder="ANTHROPIC_API_KEY"
              style={{ width: '100%', padding: '8px 12px', fontSize: 12, fontFamily: 'monospace', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)', margin: '4px 0 12px' }} />
            <datalist id="secret-keys">{secrets.map((s: any) => <option key={s.key} value={s.key} />)}</datalist>
            <label style={{ fontSize: 10, color: 'var(--text3)' }}>New value</label>
            <input type="password" value={val} onChange={e => setVal(e.target.value)} placeholder="paste the new key/secret" autoComplete="new-password"
              style={{ width: '100%', padding: '8px 12px', fontSize: 12, fontFamily: 'monospace', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)', margin: '4px 0 14px' }} />
            {msg && <div style={{ fontSize: 11, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444', marginBottom: 12 }}>{msg}</div>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setOpen(false)} style={{ padding: '8px 14px', fontSize: 12, borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>Cancel</button>
              <button onClick={save} disabled={busy || !key.trim() || val.trim().length < 4} style={{ padding: '8px 16px', fontSize: 12, fontWeight: 700, borderRadius: 7, border: 'none', cursor: 'pointer', background: '#22c55e', color: '#fff', opacity: busy || !key.trim() || val.trim().length < 4 ? 0.5 : 1 }}>{busy ? 'Saving…' : 'Save secret'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
