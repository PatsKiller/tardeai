// SnapTradeCredsModal — paste the SnapTrade API keys (clientId + consumerKey from the dashboard
// "API Keys" page) and save them into config/broker_credentials.env via the server. Write-only: the
// consumer key is never read back, only a masked client id + "saved" booleans. This stores the APP keys
// only — linking a brokerage (the per-user connect flow) is a separate, later step.
import { useEffect, useState } from 'react'

type Status = {
  client_id_set?: boolean; consumer_key_set?: boolean; client_id_masked?: string | null
  ready?: boolean; connected?: boolean; error?: string
}

export default function SnapTradeCredsModal({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [clientId, setClientId] = useState('')
  const [consumerKey, setConsumerKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  const loadStatus = () =>
    fetch('/api/v2/snaptrade/status').then(r => r.json())
      .then(d => setStatus((d?.data ?? d) as Status)).catch(() => setStatus({ error: 'status unavailable' }))
  useEffect(() => { loadStatus() }, [])

  const save = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await fetch('/api/v2/snaptrade/credentials', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: clientId.trim(), consumer_key: consumerKey.trim() }),
      })
      const d = await r.json()
      if (d?.ok) {
        setMsg({ kind: 'ok', text: 'Saved to broker_credentials.env (chmod 600).' })
        setClientId(''); setConsumerKey(''); setStatus(d.status as Status)
      } else {
        setMsg({ kind: 'err', text: d?.error || 'save failed' })
      }
    } catch (e: any) {
      setMsg({ kind: 'err', text: String(e?.message || e) })
    } finally { setBusy(false) }
  }

  const lbl = { fontSize: 10, color: '#8a8a8a', fontWeight: 700, display: 'block', marginBottom: 3 } as const
  const inp = { width: '100%', boxSizing: 'border-box' as const, fontSize: 12, padding: '7px 9px', borderRadius: 6,
    border: '1px solid #2c2c2c', background: '#0e0e0e', color: '#e0e0e0', fontFamily: 'monospace' as const }
  const ready = !!status?.ready

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.62)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 520, maxWidth: '100%', background: '#141414',
        border: '1px solid #2c2c2c', borderRadius: 12, padding: 18, boxShadow: '0 18px 50px rgba(0,0,0,.5)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 900, color: '#e0e0e0' }}>Connect SnapTrade — API keys</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#8a8a8a', fontSize: 18, cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ fontSize: 10.5, color: '#bdbdbd', lineHeight: 1.5, marginBottom: 12 }}>
          Paste the <b>Client ID</b> and <b>Consumer Key</b> from your SnapTrade dashboard → API Keys. They’re
          written to <code style={{ color: '#64b5f6' }}>.env</code> (chmod 600, gitignored) — the same store as
          the System → API Keys &amp; Secrets page, where they also appear as slots. This saves the <b>app keys
          only</b> — next, link a brokerage (<code style={{ color: '#64b5f6' }}>snaptrade_connect.py</code>), then
          run the read-only sync.
        </div>

        {/* current status */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
          {[['Client ID', status?.client_id_set, status?.client_id_masked],
            ['Consumer Key', status?.consumer_key_set, status?.consumer_key_set ? 'saved' : null],
            ['Brokerage', status?.connected, status?.connected ? 'linked' : 'not linked yet']].map(([k, on, extra]: any) => (
            <span key={k} style={{ fontSize: 9.5, fontWeight: 700, padding: '3px 9px', borderRadius: 5,
              border: `1px solid ${on ? 'rgba(76,175,80,.5)' : '#2c2c2c'}`,
              background: on ? 'rgba(76,175,80,.12)' : '#1b1b1b', color: on ? '#81c784' : '#8a8a8a' }}>
              {k}: {on ? '✓' : '—'}{extra ? ` ${extra}` : ''}
            </span>
          ))}
        </div>

        <div style={{ marginBottom: 10 }}>
          <label style={lbl}>Client ID</label>
          <input value={clientId} onChange={e => setClientId(e.target.value)} placeholder="SNAPTRADE-XXXX…" style={inp} autoComplete="off" spellCheck={false} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label style={lbl}>Consumer Key</label>
          <input value={consumerKey} onChange={e => setConsumerKey(e.target.value)} placeholder="paste consumer key (write-only)" type="password" style={inp} autoComplete="off" spellCheck={false} />
        </div>

        {msg && <div style={{ fontSize: 10.5, fontWeight: 700, marginBottom: 10,
          color: msg.kind === 'ok' ? '#81c784' : '#e57373' }}>{msg.kind === 'ok' ? '✓ ' : '⚠ '}{msg.text}</div>}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', alignItems: 'center' }}>
          <span style={{ flex: 1, fontSize: 9, color: '#616161' }}>
            {ready ? 'Keys present — connect a brokerage next.' : 'Both keys required.'}
          </span>
          <button onClick={onClose} style={{ fontSize: 11, padding: '6px 14px', borderRadius: 6, border: '1px solid #2c2c2c', background: '#1b1b1b', color: '#bdbdbd', cursor: 'pointer' }}>Close</button>
          <button onClick={save} disabled={busy || !clientId.trim() || !consumerKey.trim()}
            style={{ fontSize: 11, fontWeight: 800, padding: '6px 16px', borderRadius: 6, border: '1px solid #1d4ed8',
              background: (busy || !clientId.trim() || !consumerKey.trim()) ? '#1b1b1b' : '#1d4ed8',
              color: (busy || !clientId.trim() || !consumerKey.trim()) ? '#616161' : '#fff',
              cursor: (busy || !clientId.trim() || !consumerKey.trim()) ? 'not-allowed' : 'pointer' }}>
            {busy ? 'saving…' : 'Save keys'}
          </button>
        </div>
      </div>
    </div>
  )
}
