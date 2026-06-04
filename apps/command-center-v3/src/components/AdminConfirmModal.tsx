import { useEffect, useState } from 'react'
import { preview, confirm, type AdminPreview, type AdminResult } from '../lib/adminWrite'

export interface PendingAction { path: string; body: any; label: string }

// Two-step guarded-write modal: on open it PREVIEWS the exact old->new (no mutation); the operator
// must click Confirm to apply. Every confirmed write is recorded server-side in admin_audit_log.
export default function AdminConfirmModal({ action, onClose, onDone }: {
  action: PendingAction | null
  onClose: () => void
  onDone: (r: AdminResult) => void
}) {
  const [prev, setPrev] = useState<AdminPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!action) { setPrev(null); setErr(null); return }
    setBusy(true); setErr(null)
    preview(action.path, action.body)
      .then(p => { setPrev(p); setBusy(false); if (!p.ok && p.error) setErr(p.error) })
      .catch(e => { setErr(String(e)); setBusy(false) })
  }, [action])

  if (!action) return null
  const p = prev?.preview

  const doConfirm = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await confirm(action.path, action.body)
      setBusy(false)
      if (r.ok) { onDone(r); onClose() }
      else setErr(r.error || r.detail || 'write failed')
    } catch (e) { setErr(String(e)); setBusy(false) }
  }

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 20, width: 460, maxWidth: '92vw' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Confirm: {action.label}</div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>Guarded write — review the exact change, then confirm. Recorded in the admin audit log.</div>
        {busy && !p && <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading change preview…</div>}
        {p && (
          <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 12, fontSize: 11, fontFamily: 'var(--mono)', lineHeight: 1.7 }}>
            <div><span style={{ color: 'var(--text3)' }}>action&nbsp;</span> {p.action}</div>
            <div><span style={{ color: 'var(--text3)' }}>target&nbsp;</span> {p.target}</div>
            <div style={{ marginTop: 6 }}><span style={{ color: '#ef4444' }}>old&nbsp;</span> {JSON.stringify(p.old_value)}</div>
            <div><span style={{ color: '#22c55e' }}>new&nbsp;</span> {JSON.stringify(p.new_value)}</div>
          </div>
        )}
        {err && <div style={{ color: '#ef4444', fontSize: 11, marginTop: 10 }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
          <button onClick={onClose} style={{ background: 'var(--bg2)', color: 'var(--text2)', border: '1px solid var(--border)', borderRadius: 6, padding: '7px 14px', fontSize: 12, cursor: 'pointer' }}>Cancel</button>
          <button onClick={doConfirm} disabled={busy || !p} style={{ background: (busy || !p) ? 'var(--bg2)' : '#1d4ed8', color: '#fff', border: 0, borderRadius: 6, padding: '7px 16px', fontSize: 12, fontWeight: 600, cursor: (busy || !p) ? 'default' : 'pointer' }}>{busy ? 'Applying…' : 'Confirm change'}</button>
        </div>
      </div>
    </div>
  )
}
