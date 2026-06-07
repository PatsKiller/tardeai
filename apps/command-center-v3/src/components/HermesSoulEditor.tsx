import { useState } from 'react'
import { useApi } from '../hooks/useApi'

// Shared Hermes identity/SOUL editor modal — used by System → Hermes (HermesPanel) and the
// /v3/hermes research graph (HermesHub). Read current SOUL, edit, save (backup-first + safety-validated
// server-side). Never enables tools/gateway; tradeai/tradeai12b boundary lines are enforced on save.

export const PROFILE_LABELS: Record<string, string> = {
  default: 'Global Hermes Identity',
  tradeai: 'Trade AI Advisory Identity',
  tradeai12b: 'Experimental 12B Trade AI Identity',
  dev: 'Development / Codex Identity',
  serverops: 'ServerOps Identity',
}

export default function HermesSoulEditor({ profile, onClose }: { profile: string; onClose: () => void }) {
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
