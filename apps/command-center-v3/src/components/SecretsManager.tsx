import { useState, useEffect } from 'react'
import { useApi } from '../hooks/useApi'

// Secrets / API-key manager. Write-only: the UI never shows or receives a full secret value — only a
// masked '••••1234' hint + presence. Used to rotate keys (e.g. ANTHROPIC_API_KEY) after a leak.
// Live-validation chip colors. "set" ≠ "works" — a dead ANTHROPIC key sat green for weeks (2026-06-12).
const VSTATUS: Record<string, { c: string; label: string }> = {
  valid: { c: '#22c55e', label: 'VERIFIED ✓' },
  INVALID: { c: '#ef4444', label: 'INVALID ✗' },
  quota_or_billing: { c: '#f59e0b', label: 'QUOTA/BILLING ⚠' },
  not_set: { c: 'var(--text3)', label: 'not set' },
  not_validatable: { c: '#60a5fa', label: 'n/a' },
  check_failed: { c: '#f59e0b', label: 'check failed' },
  unknown_key: { c: 'var(--text3)', label: '—' },
}

export default function SecretsManager() {
  const { data, refetch } = useApi<any>('/api/v2/admin/secrets', 60_000)
  const secrets: any[] = data?.secrets ?? []
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [val, setVal] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [vres, setVres] = useState<Record<string, any>>({})
  const [vbusy, setVbusy] = useState(false)
  const selectedConfig = !!secrets.find((s: any) => s.key === key)?.is_config  // config value (not a masked secret)
  const isCookieKey = key.endsWith('_COOKIE')

  const validateAll = async () => {
    setVbusy(true)
    try {
      const r = await fetch('/api/v2/admin/validate-secret', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
      const j = await r.json(); const d = j?.data ?? j
      const m: Record<string, any> = {}
      for (const x of (d.results ?? [])) m[x.name] = x
      setVres(m)
    } catch { /* chips just stay absent */ }
    setVbusy(false)
  }

  const validateOne = async (name: string) => {
    try {
      const r = await fetch('/api/v2/admin/validate-secret', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) })
      const j = await r.json(); const d = j?.data ?? j
      if (d.result) setVres(v => ({ ...v, [name]: d.result }))
      return d.result
    } catch { return null }
  }

  // Auto-validate FINVIZ_COOKIE on mount so an expired Elite cookie surfaces without a click
  // (stale-data RCA / AGENTS.md §13.6 — screener + social scalp go empty silently otherwise).
  useEffect(() => {
    const row = secrets.find((s: any) => s.key === 'FINVIZ_COOKIE')
    if (!row?.present) return
    if (vres.FINVIZ_COOKIE) return
    void validateOne('FINVIZ_COOKIE')
    // secrets list identity changes when /admin/secrets loads; do not re-fire once we have a result
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secrets.length, data])

  const save = async () => {
    if (!key.trim() || val.trim().length < 4 || busy) return
    setBusy(true); setMsg('')
    try {
      const r = await fetch('/api/v2/admin/secrets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: key.trim(), value: val }) })
      const j = await r.json()
      if (j?.data?.ok) {
        // validate-on-save: ask the PROVIDER immediately so a dead key can never sit "green"
        const vr = await validateOne(j.data.key)
        const vtxt = vr ? ` · provider check: ${VSTATUS[vr.status]?.label ?? vr.status} (${vr.detail})` : ''
        setMsg(`✓ ${j.data.key} ${j.data.rotated ? 'rotated' : 'set'} (${j.data.masked}).${vtxt}`)
        setVal(''); setKey(''); setTimeout(() => { refetch(); setOpen(false) }, vr ? 3200 : 1800)
      }
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
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={validateAll} disabled={vbusy} title="Live-checks every key against its provider (cheap authenticated pings; Brave costs 1 search credit)"
            style={{ padding: '8px 14px', fontSize: 12, fontWeight: 700, borderRadius: 7, border: '1px solid var(--border)', cursor: 'pointer', background: 'var(--bg2)', color: '#60a5fa' }}>
            {vbusy ? 'Validating…' : '✓ Validate all keys'}</button>
          <button onClick={() => { setOpen(true); setMsg('') }} style={{ padding: '8px 14px', fontSize: 12, fontWeight: 700, borderRadius: 7, border: 'none', cursor: 'pointer', background: '#a855f7', color: '#fff' }}>+ Add / Rotate Secret</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 6, marginTop: 12 }}>
        {secrets.map((s: any) => {
          const v = vres[s.key]
          const vs = v ? VSTATUS[v.status] : null
          const ro = !!s.read_only
          return (
            <div key={s.key} onClick={ro ? undefined : () => { setKey(s.key); setOpen(true); setMsg('') }}
              title={ro ? 'read-only — managed by the SnapTrade connect flow (snaptrade_connect.py)' : v ? `${v.status}: ${v.detail}` : 'rotate this secret'}
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 10px', borderRadius: 7, cursor: ro ? 'default' : 'pointer', background: 'var(--bg2)', opacity: ro ? 0.78 : 1,
                border: `1px solid ${v?.status === 'INVALID' ? '#ef4444' : v?.status === 'valid' ? '#22c55e44' : 'var(--border)'}` }}>
              <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text1)' }}>{s.key}
                  {s.is_config && <span style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 4, padding: '0 3px', border: '1px solid var(--border)', borderRadius: 3 }}>cfg</span>}
                  {ro && <span title="read-only · connect-flow managed" style={{ fontSize: 8, color: '#90caf9', marginLeft: 4, padding: '0 3px', border: '1px solid #1d4ed8', borderRadius: 3 }}>🔒 ro</span>}
                </span>
                {s.label && <span style={{ fontSize: 10, color: 'var(--text3)' }}>{s.label}</span>}
                {s.badge && (
                  <span style={{
                    fontSize: 10, fontWeight: 700,
                    color: 'var(--text2)',
                    width: 'fit-content', padding: '1px 4px', borderRadius: 3,
                    border: '1px solid var(--border)',
                  }}>{s.badge}</span>
                )}
              </span>
              <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0 }}>
                {vs && <span style={{ fontSize: 8.5, fontWeight: 800, color: vs.c }}>{vs.label}</span>}
                <span style={{ fontSize: 10, color: s.present ? '#22c55e' : '#ef4444' }}>{s.present ? (s.masked || 'set') : 'not set'}</span>
              </span>
            </div>
          )
        })}
      </div>
      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 6 }}>
        "set" only means written to .env — <b>Validate</b> asks each PROVIDER (models/getMe/quote pings). New saves auto-validate. n/a = no harmless ping exists (Schwab OAuth, SMTP, …) — those prove themselves in their own flows.
      </div>

      {open && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.5)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setOpen(false)}>
          <div onClick={e => e.stopPropagation()} style={{ width: 460, maxWidth: '92vw', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Add / Rotate Secret</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 14 }}>The value is write-only — it is stored in .env and never displayed, returned, logged, or synced to git/Drive.</div>
            <label style={{ fontSize: 10, color: 'var(--text3)' }}>Key name (UPPER_SNAKE_CASE, ends with _KEY/_TOKEN/_SECRET/_PASSWORD)</label>
            <input list="secret-keys" value={key} onChange={e => setKey(e.target.value.toUpperCase())} placeholder="ANTHROPIC_API_KEY"
              style={{ width: '100%', padding: '8px 12px', fontSize: 12, fontFamily: 'monospace', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)', margin: '4px 0 12px' }} />
            <datalist id="secret-keys">{secrets.filter((s: any) => !s.read_only).map((s: any) => <option key={s.key} value={s.key} />)}</datalist>
            <label style={{ fontSize: 10, color: 'var(--text3)' }}>{selectedConfig ? 'Value (config — not masked)' : isCookieKey ? 'Cookie string (full browser Cookie header)' : 'New value'}</label>
            {isCookieKey ? (
              <textarea value={val} onChange={e => setVal(e.target.value)} placeholder="Paste the full Cookie header from elite.finviz.com (DevTools → Network → any request → Cookie). Must include .ASPXAUTH and .AspNetCore.Session."
                autoComplete="off" rows={5}
                style={{ width: '100%', padding: '8px 12px', fontSize: 11, fontFamily: 'monospace', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)', margin: '4px 0 14px', resize: 'vertical' }} />
            ) : (
              <input type={selectedConfig ? 'text' : 'password'} value={val} onChange={e => setVal(e.target.value)} placeholder={selectedConfig ? 'https://…/oauth/callback' : 'paste the new key/secret'} autoComplete="new-password"
                style={{ width: '100%', padding: '8px 12px', fontSize: 12, fontFamily: 'monospace', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)', margin: '4px 0 14px' }} />
            )}
            {isCookieKey && <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: -10, marginBottom: 12 }}>Save auto-runs a live Finviz export test. Semicolons/parentheses are OK — stored quoted in .env.</div>}
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
