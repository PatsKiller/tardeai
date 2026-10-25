import { useEffect, useRef, useState } from 'react'
import { RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import { reviewPresentation } from '../../lib/watchConflictPresentation'
import type {ConflictRecord} from '../conflicts/ConflictSheet'

/** Watch reuses the existing request action; the shared sheet alone reads ledger status. */
export default function WatchReviewRequest({symbol, securityGuid, record, onRefresh}: {
  symbol: string; securityGuid?: string | null; record: ConflictRecord | null; onRefresh?: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const alive = useRef(true)
  const epoch = useRef(0)
  useEffect(() => {
    alive.current = true; epoch.current += 1
    setAcknowledged(false); setMessage(''); setBusy(false)
    return () => { alive.current = false; epoch.current += 1 }
  }, [symbol, securityGuid, record?.key])
  const presentation = reviewPresentation(record)
  const requestable = record?.action === 'queue_review'
    && !['CLEARED', 'SUPERSEDED'].includes(record.state)
  const identityMatches = Boolean(securityGuid) && record?.subject.kind === 'security' && record.subject.id === securityGuid
  async function ask() {
    if (!record || !identityMatches || busy || acknowledged || presentation.pending) return
    const requestedEpoch = epoch.current
    setBusy(true); setMessage('Requesting a CIO review…')
    try {
      const response = await fetch(`/api/v3/opportunities/${encodeURIComponent(symbol)}/review-request`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({note: `Watch conflict: ${record.summary}`.slice(0, 240)}),
      })
      const raw = await response.json()
      const result = raw?.data ?? raw
      if (!response.ok || !(raw?.ok === true || result?.ok === true) || result?.ok === false) throw new Error(result?.error || raw?.error || `Request failed (${response.status})`)
      if (result.symbol !== symbol) throw new Error('Review response did not identify this security')
      if (!alive.current || epoch.current !== requestedEpoch) return
      setAcknowledged(true)
      setMessage(result.already_open ? 'An existing review request was reported. Waiting for the saved review history.' : 'Review request submitted. Waiting for the saved review history.')
      onRefresh?.()
    } catch (error: any) {
      if (alive.current && epoch.current === requestedEpoch) setMessage(`Could not queue the review: ${error?.message || 'request failed'}`)
    } finally { if (alive.current && epoch.current === requestedEpoch) setBusy(false) }
  }
  if (!requestable) return null
  if (!identityMatches) return <p role="status">CIO review unavailable: this finding could not be joined to the security’s durable identity.</p>
  return <section data-testid="watch-review-request" aria-label="CIO review" style={{display: 'grid', gap: 12, color: TOKENS.text[1], fontSize: TYPE.base}}>
    {message && <div role="status" data-testid="watch-review-message">{acknowledged && presentation.pending ? 'Review request is recorded in the saved history.' : message}</div>}
    {presentation.state !== 'decided' && <footer className="watch-conflict-actions" style={{position: 'sticky', bottom: 0, display: 'grid', gap: 8, padding: '10px 0', background: TOKENS.bg[1]}}>
      <button type="button" data-testid="watch-ask-cio" onClick={ask} disabled={busy || acknowledged || presentation.pending}
        style={{minHeight: 44, width: '100%', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.warning}`, background: TOKENS.bg[2], color: TOKENS.warning, cursor: busy || acknowledged || presentation.pending ? 'default' : 'pointer'}}>
        {busy ? 'Requesting…' : presentation.pending ? 'CIO review in progress' : acknowledged ? 'Review requested · awaiting saved status' : 'Ask the CIO to review'}
      </button>
    </footer>}
  </section>
}
