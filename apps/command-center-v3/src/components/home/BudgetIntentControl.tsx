// Operator-only budget intent, inside the existing Home v7 context card.
//
// The control appears ONLY when the payload says a decision is available to the operator and the row names its canonical
// scope. It never submits on its own: preview is a `dry_run:true` POST against a freshly read basis, and the real write
// needs a second, explicit confirm with the same request id and the same source binding. Nothing measured is sent —
// actor, actual, limit and breach stay server-side.

import { useState } from 'react'
import { RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import type { BudgetRow } from '../../lib/homeV007'
import {
  BUDGET_DECIDE_PATH, basisUrl, currentBasis, futureUtcZ, historyRecords, humanError, intentBody, networkOutcomeUnknown,
  presentationCall, reconcile, refusedText, requestId,
  type DecisionRecord, type IntentBody,
} from '../../lib/budgetIntent'

const small = { fontSize: TYPE.sm, color: TOKENS.text[2] } as const
const box = { display: 'grid', gap: 6, padding: '8px 10px', border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, background: TOKENS.bg[2], marginTop: 6 } as const
const field = { fontSize: TYPE.sm, padding: '6px 8px', minHeight: 44, background: TOKENS.bg[1], color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, fontFamily: 'inherit' } as const
const button = { fontSize: TYPE.sm, padding: '6px 12px', minHeight: 44, minWidth: 44, background: TOKENS.bg[1], color: TOKENS.info, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, cursor: 'pointer', fontFamily: 'inherit' } as const
const primary = { ...button, color: TOKENS.bg[0], background: TOKENS.info, fontWeight: 700 } as const

function defaultUntilLocal(): string {
  const at = new Date(Date.now() + 7 * 24 * 3600 * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(at.getHours())}:${pad(at.getMinutes())}`
}

type Preview = { body: IntentBody; storeApproved: boolean; wouldReplay: boolean; basisAsOf: string | null }

export default function BudgetIntentControl({ row, onRecorded }: { row: BudgetRow; onRecorded?: () => void }) {
  const [open, setOpen] = useState(false)
  const [until, setUntil] = useState(defaultUntilLocal)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  // The history is a fact in its own right: it survives a source that cannot be read right now, and it is how an
  // uncertain write is resolved after the fact.
  const [history, setHistory] = useState<DecisionRecord[]>([])
  const [basisUnavailable, setBasisUnavailable] = useState(false)
  const [done, setDone] = useState<{ actor: string | null; until: string | null; receipt: string | null } | null>(null)

  // A decision can only be offered when the backend says so AND the row names the canonical scope it is scoped to.
  if (row.operatorDecision !== 'available' || !row.scopeId || !row.key || row.key === '?') return null

  const reset = () => { setPreview(null); setError(''); setDone(null) }
  const close = () => { setOpen(false); reset() }

  /**
   * Read the basis AND its history. A 503 is not an error for the history: the decisions the server still holds are
   * shown, and the write controls are turned off because there is no current measurement to bind to.
   */
  async function readBasis() {
    const reply = await presentationCall(basisUrl(String(row.scopeId), row.key))
    if (reply.outcome === 'unknown') throw new Error(networkOutcomeUnknown('Failed to fetch'))
    setHistory(historyRecords(reply.data))
    if (!reply.ok) {
      if (reply.status === 503 || reply.code === 'SOURCE_UNAVAILABLE') {
        setBasisUnavailable(true)
        return { binding: null, breached: null, asOf: null, available: false }
      }
      throw new Error(humanError(reply))
    }
    setBasisUnavailable(false)
    const basis = currentBasis(reply.data)
    if (!basis.binding) throw new Error('The basis did not carry a canonical binding. Nothing was sent.')
    if (basis.breached !== true) throw new Error('This budget is no longer breached, so there is nothing to record intent for.')
    return { ...basis, available: true }
  }

  /** After a refused or uncertain write: did the pending request already land? Identity is the id AND the payload. */
  async function resolvePending(pending: IntentBody) {
    try {
      const reply = await presentationCall(basisUrl(String(row.scopeId), row.key))
      const records = historyRecords(reply.data)
      setHistory(records)
      setBasisUnavailable(!reply.ok && (reply.status === 503 || reply.code === 'SOURCE_UNAVAILABLE'))
      const found = reconcile(records, pending)
      if (found) {
        setDone({ actor: 'an earlier request', until: found.intentionalUntil, receipt: found.receipt ? found.receipt.slice(0, 12) : null })
        setPreview(null)
        onRecorded?.()
        return true
      }
    } catch {
      /* the read itself failed: the outcome stays unknown, and the pending request id is kept for the retry */
    }
    return false
  }

  async function onPreview() {
    setBusy(true); setError(''); setPreview(null)
    try {
      const untilUtc = futureUtcZ(until)
      if (!untilUtc) throw new Error('Choose an expiry in the future.')
      const basis = await readBasis()
      if (!basis.available) throw new Error('The canonical source is unavailable right now, so there is no basis to record against. Its earlier decisions are listed below.')
      const body = intentBody({ scopeId: row.scopeId, budget: row.key, binding: basis.binding, untilUtc, requestId: requestId(), comment, dryRun: true })
      const reply = await presentationCall(BUDGET_DECIDE_PATH, body)
      if (!reply.ok) throw new Error(humanError(reply))
      const data = (reply.data || {}) as Record<string, unknown>
      if (data.written !== false) throw new Error('The preview did not confirm that nothing would be written; not continuing.')
      setPreview({ body, storeApproved: data.store_approved === true, wouldReplay: data.would_replay === true, basisAsOf: basis.asOf })
    } catch (e) {
      setError((e as Error)?.name === 'TypeError' || /fetch|network|load failed/i.test(String((e as Error)?.message || ''))
        ? networkOutcomeUnknown(e)
        : String((e as Error)?.message || e))
    } finally { setBusy(false) }
  }

  async function onConfirm() {
    if (!preview) return
    setBusy(true); setError('')
    try {
      // Re-read the basis in the same breath as the write: a changed measurement is refused by the server (409).
      const basis = await readBasis()
      if (!basis.available) throw new Error('The canonical source is unavailable right now, so this cannot be recorded. The pending request is kept.')
      if (basis.binding?.sha256 !== preview.body.source_binding.sha256 || basis.binding?.as_of !== preview.body.source_binding.as_of) {
        setPreview(null)
        throw new Error('The measurement changed while you were reviewing. Nothing was written — preview again.')
      }
      const pending = preview.body
      const { dry_run: _drop, ...real } = pending
      const reply = await presentationCall(BUDGET_DECIDE_PATH, real as IntentBody)
      if (!reply.ok) {
        // Never infer the outcome from the code or the status: the append may have happened before the error.
        if (await resolvePending(pending)) return
        if (reply.outcome === 'refused') throw new Error(refusedText(reply.code))
        throw new Error(networkOutcomeUnknown('Failed to fetch'))
      }
      const data = (reply.data || {}) as Record<string, unknown>
      setDone({
        actor: typeof data.actor === 'string' ? data.actor : null,
        until: typeof data.intentional_until === 'string' ? data.intentional_until : preview.body.intentional_until,
        receipt: typeof data.hash_self === 'string' ? data.hash_self.slice(0, 12) : null,
      })
      setPreview(null)
      onRecorded?.()
    } catch (e) {
      const text = String((e as Error)?.message || '')
      // A dropped reply is not proof that nothing was written. Keep the preview so the retry carries the SAME
      // request id, which the ledger replays instead of appending a second decision.
      const lost = (e as Error)?.name === 'TypeError' || /fetch|network|load failed/i.test(text)
      const shown = lost ? networkOutcomeUnknown(e) : text
      setError(shown)
      // An uncertain outcome keeps the preview, so the retry is the same request; a local refusal (changed basis,
      // past expiry) already cleared it deliberately.
      if (/outcome is unknown/i.test(shown) && preview) void resolvePending(preview.body)
    } finally { setBusy(false) }
  }

  if (done) {
    return <div style={box} data-testid="v7-intent-done">
      <div style={small}>intent recorded · {done.actor ?? 'operator'}{done.until ? ` · until ${done.until}` : ''}{done.receipt ? ` · receipt ${done.receipt}` : ''}</div>
      <div style={small}>Presentation only — the measurement, the limit and the breach are unchanged.</div>
      <button type="button" style={button} onClick={close}>Close</button>
    </div>
  }

  if (!open) {
    return <div style={{ marginTop: 4 }}>
      <button type="button" style={button} data-testid="v7-intent-open" onClick={() => { setOpen(true); reset() }}>
        Record intent…
      </button>
    </div>
  }

  return <div style={box} data-testid="v7-intent-form">
    <div style={small}>Operator session only. Nothing measured is sent, and the breach is not cleared.</div>
    <label style={small}>Intent ends (your local time)
      <input type="datetime-local" style={field} value={until} data-testid="v7-intent-until"
        onChange={e => { setUntil(e.target.value); setPreview(null); setError('') }} />
    </label>
    <label style={small}>Comment (optional)
      <input type="text" style={field} value={comment} maxLength={400} data-testid="v7-intent-comment"
        onChange={e => { setComment(e.target.value); setPreview(null); setError('') }} />
    </label>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      <button type="button" style={primary} disabled={busy} data-testid="v7-intent-preview" onClick={onPreview}>
        {busy ? 'Reading…' : 'Preview (writes nothing)'}
      </button>
      <button type="button" style={button} disabled={busy} onClick={close}>Cancel</button>
    </div>
    {error ? <div role="alert" style={{ ...small, color: TOKENS.danger }} data-testid="v7-intent-error">{error}</div> : null}
    {basisUnavailable ? <div style={small} data-testid="v7-intent-source-unavailable">
      The canonical source cannot be read right now. {history.length} earlier decision{history.length === 1 ? ' is' : 's are'} still listed; recording is off until it answers.
    </div> : null}
    {history.length && !basisUnavailable ? <div style={small} data-testid="v7-intent-history">
      {history.length} earlier decision{history.length === 1 ? '' : 's'} held{history.some(h => h.active) ? ' · one is active' : ''}.
    </div> : null}
    {preview ? <div style={{ display: 'grid', gap: 6 }} data-testid="v7-intent-preview-panel">
      <div style={small}>
        would record: intent until {preview.body.intentional_until} · basis {preview.basisAsOf ?? preview.body.source_binding.as_of} ·
        {' '}nothing written ({preview.wouldReplay ? 'this request was already previewed' : 'new request'})
      </div>
      <div style={small}>
        {preview.storeApproved
          ? 'The decision store is approved, so this can be recorded.'
          : 'The decision store is NOT approved yet — the server will refuse the write until the operator signs off the source.'}
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" style={primary} disabled={busy} data-testid="v7-intent-confirm" onClick={onConfirm}>
          {busy ? 'Recording…' : 'Confirm intent'}
        </button>
        <button type="button" style={button} disabled={busy} onClick={() => setPreview(null)}>Back</button>
      </div>
    </div> : null}
  </div>
}
