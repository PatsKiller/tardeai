import { useEffect, useState } from 'react'
import { preview, confirm, getToken, setToken, type AdminPreview, type AdminResult } from '../lib/adminWrite'
import { RADIUS } from '../lib/designTokens'

export interface PendingAction { path: string; body: any; label: string; explain?: string }

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
  const [tok, setTok] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    if (!action) { setPrev(null); setErr(null); return }
    setBusy(true); setErr(null)
    preview(action.path, action.body)
      .then(p => { setPrev(p); setBusy(false); if (!p.ok && p.error) setErr(p.error) })
      .catch(e => { setErr(String(e)); setBusy(false) })
  }, [action, retry])

  if (!action) return null
  const p = prev?.preview
  // 2026-10-19: a browser with no saved operator token got a silent 403 ("the buttons do nothing"). Ask for it here.
  const denied = !!err && /access denied/i.test(err)
  const saveToken = () => { setToken(tok.trim()); setTok(''); setRetry((n) => n + 1) }

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
        {action.explain && <div style={{ fontSize: 13, color: 'var(--text0)', lineHeight: 1.45, margin: '6px 0 10px' }}>{action.explain}</div>}
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
        {err && !denied && <div style={{ color: '#ef4444', fontSize: 11, marginTop: 10 }}>{err}</div>}
        {denied && (
          <div style={{ marginTop: 10, padding: 10, border: '1px solid var(--warning-color)', borderRadius: RADIUS.md, fontSize: 12, color: 'var(--text0)' }}>
            <div style={{ marginBottom: 6 }}>{getToken() ? 'The saved operator token was rejected.' : 'This browser has no operator write token saved yet.'} Enter it once (it is kept in this browser only):</div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input type="password" value={tok} onChange={(e) => setTok(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && tok.trim()) saveToken() }} placeholder="ADMIN_WRITE_TOKEN" autoFocus
                style={{ flex: 1, fontSize: 12, padding: '5px 8px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: RADIUS.sm, color: 'var(--text0)' }} />
              <button type="button" disabled={!tok.trim()} onClick={saveToken} style={{ fontSize: 12, padding: '5px 12px', borderRadius: RADIUS.sm, border: 0, background: 'var(--info-color)', color: 'var(--text0)', cursor: tok.trim() ? 'pointer' : 'default' }}>Save &amp; retry</button>
            </div>
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
          <button onClick={onClose} style={{ background: 'var(--bg2)', color: 'var(--text2)', border: '1px solid var(--border)', borderRadius: 6, padding: '7px 14px', fontSize: 12, cursor: 'pointer' }}>Cancel</button>
          <button onClick={doConfirm} disabled={busy || !p} style={{ background: (busy || !p) ? 'var(--bg2)' : '#1d4ed8', color: '#fff', border: 0, borderRadius: 6, padding: '7px 16px', fontSize: 12, fontWeight: 600, cursor: (busy || !p) ? 'default' : 'pointer' }}>{busy ? 'Applying…' : 'Confirm change'}</button>
        </div>
      </div>
    </div>
  )
}
