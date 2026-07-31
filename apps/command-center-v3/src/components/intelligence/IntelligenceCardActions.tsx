import { useState } from 'react'
import AdminConfirmModal, { type PendingAction } from '../AdminConfirmModal'
import type { IntelligenceItemType } from '../../lib/intelligenceItemId'

const btn: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  padding: '5px 11px',
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'var(--bg2)',
  color: 'var(--text1)',
  cursor: 'pointer',
}

interface Props {
  itemId: string
  itemType: IntelligenceItemType
  symbol?: string
  onDone?: () => void
}

/** Dismiss / Mark reviewed (guarded admin write) + Promote to watchlist (existing submit API). */
export default function IntelligenceCardActions({ itemId, itemType, symbol, onDone }: Props) {
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const setStatus = (status: 'dismissed' | 'reviewed', label: string) => {
    setPending({
      path: '/api/v2/admin/intelligence-item/set-status',
      label: `${label} intelligence item`,
      body: { item_id: itemId, item_type: itemType, status, note: '' },
    })
  }

  const promote = async () => {
    if (!symbol || !/^[A-Z]{1,5}$/.test(symbol)) {
      setMsg('No valid ticker to promote')
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      const r = await fetch('/api/v2/watchlist/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols: [symbol],
          agent: 'maria',
          request_type: 'research',
          note: `Promoted from Intelligence (${itemType})`,
        }),
      })
      const j = await r.json()
      if (j.ok !== false) {
        setMsg(`Queued ${symbol} for watchlist research`)
        onDone?.()
      } else setMsg(j.error || 'Promote failed')
    } catch (e) {
      setMsg(String(e))
    }
    setBusy(false)
  }

  return (
    <>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }} onClick={e => e.stopPropagation()}>
        <button type="button" style={btn} onClick={() => setStatus('reviewed', 'Mark reviewed')}>Mark reviewed</button>
        <button type="button" style={{ ...btn, color: 'var(--amber)', borderColor: 'rgba(245,158,11,.35)' }} onClick={() => setStatus('dismissed', 'Dismiss')}>Dismiss</button>
        {symbol && /^[A-Z]{1,5}$/.test(symbol) && (
          <button type="button" disabled={busy} style={{ ...btn, color: 'var(--blue)', borderColor: 'rgba(96,165,250,.35)' }} onClick={promote}>
            {busy ? 'Queuing…' : 'Promote to watchlist'}
          </button>
        )}
        {msg && <span style={{ fontSize: 10, color: 'var(--text3)' }}>{msg}</span>}
      </div>
      <AdminConfirmModal
        action={pending}
        onClose={() => setPending(null)}
        onDone={() => { setPending(null); onDone?.() }}
      />
    </>
  )
}
