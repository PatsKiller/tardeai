import { useCallback, useRef, useState } from 'react'
import { RADIUS, TOKENS, TYPE, chipStyle } from '../../lib/designTokens'
import { cioMemoryState, cioReviewNote, reviewStateText, reviewStateTone, type ProspectRow, type ReviewState } from '../../lib/watchProspectsModel'
import { requestCioReview } from '../../lib/watchListsModel'
import { newerReviewState } from '../../lib/watchReviewState'

/** Watch "Ask the CIO" (batch 31, operator 2026-10-25): every next step that asks the CIO for a review is actionable,
 *  and the request's recorded state (queued, blocked by acquisition with its reason, answered, expired) is visible on
 *  the row and in the record. Uses the existing POST /api/v3/opportunities/{symbol}/review-request; advisory only. */

type Entry = { busy: boolean; message: string; state: ReviewState | null; requestId?: string | null; nextRun?: string | null; errorReason?: string | null }
export type CioReviewController = {
  entries: Record<string, Entry>
  ask: (row: ProspectRow, conflictKey?: string | null) => Promise<void>
  sync: (states: Record<string, ReviewState>) => void
}

export function useCioReview(onDone?: () => void): CioReviewController {
  const [entries, setEntries] = useState<Record<string, Entry>>({})
  const inFlight = useRef(new Set<string>())
  const ask = useCallback(async (row: ProspectRow, conflictKey?: string | null) => {
    const sym = row.symbol
    if (inFlight.current.has(sym)) return
    inFlight.current.add(sym)
    setEntries(e => ({ ...e, [sym]: { busy: true, message: 'Asking the CIO…', state: e[sym]?.state ?? null } }))
    const res = await requestCioReview(sym, cioReviewNote(row), conflictKey)
    setEntries(e => ({ ...e, [sym]: { busy: false, message: res.message,
      state: newerReviewState(res.state, e[sym]?.state), requestId: res.requestId, nextRun: res.nextRun,
      errorReason: res.ok ? null : res.message } }))
    if (res.ok) onDone?.()
    inFlight.current.delete(sym)
  }, [onDone])
  const sync = useCallback((states: Record<string, ReviewState>) => {
    setEntries(prior => {
      const next = { ...prior }
      for (const [sym, state] of Object.entries(states)) {
        const old = prior[sym]
        const selected = newerReviewState(state, old?.state)
        next[sym] = { ...old, busy: old?.busy || false,
          message: selected?.status === 'answered' ? (selected.publication_verified ? 'CIO answer available.' : 'Research publication recorded; current CIO linkage pending.') : old?.message || '',
          state: selected }
      }
      return next
    })
  }, [])
  return { entries, ask, sync }
}

/** The state the page should show: the fresher of the POST readback and the row's served state. */
export function currentReviewState(row: ProspectRow, cio?: CioReviewController): ReviewState | null {
  return newerReviewState(row.review_state, cio?.entries[row.symbol]?.state)
}

export function ReviewStateChip({ state, testId = 'watch-review-state', compact = false }: { state: ReviewState | null; testId?: string; compact?: boolean }) {
  const text = compact ? (state && state.status !== 'none' ? state.label || state.status : null) : reviewStateText(state)
  if (!text) return null
  return <span data-testid={testId} data-status={state?.status} title={state?.last_attempt?.block_reason || undefined}
    style={{ ...chipStyle(reviewStateTone(state), 'soft', 'sm'), whiteSpace: 'normal', lineHeight: 1.4, fontSize: TYPE.sm,
      alignSelf: 'flex-start', borderRadius: RADIUS.sm, padding: '4px 8px', maxWidth: '100%', boxSizing: 'border-box' }}>
    CIO review: {text}
  </span>
}

/** Whether the review is linked into the canonical CIO memory (prospect record / shared spine).
 *  A review that is not linked is visible as a memory gap, never a silent nothing. */
export function CioMemoryChip({ state, testId = 'watch-cio-memory' }: { state: ReviewState | null; testId?: string }) {
  const mem = cioMemoryState(state)
  if (!mem) return null
  return <span data-testid={testId} data-memory={mem.tone === 'success' ? 'tracked' : mem.tone === 'info' ? 'pending' : 'not-linked'}
    title="Whether this review is linked into the CIO prospect record (the single per-security truth). A 'not linked' review is research that has not been accepted into CIO memory."
    style={{ ...chipStyle(mem.tone, 'outline', 'sm'), whiteSpace: 'normal', lineHeight: 1.4, fontSize: TYPE.sm,
      alignSelf: 'flex-start', borderRadius: RADIUS.sm, padding: '3px 7px', maxWidth: '100%', boxSizing: 'border-box' }}>
    {mem.label}
  </span>
}

/** State + one actionable button. Shown in the record whenever the next step asks the CIO, flags or not. */
export function CioReviewPanel({ row, cio, conflictKey }: { row: ProspectRow; cio: CioReviewController; conflictKey?: string | null }) {
  const entry = cio.entries[row.symbol]
  const state = currentReviewState(row, cio)
  const last = state?.last_attempt
  return <div data-testid="watch-cio-review" style={{ display: 'grid', gap: 8 }}>
    <ReviewStateChip state={state} />
    <CioMemoryChip state={state} />
    {(state?.publication_verified || state?.research_link_verified) && state?.answer_summary && <p data-testid="watch-cio-answer" style={{ margin: 0, color: TOKENS.text[1] }}>
      {state.publication_verified ? 'CIO answer' : 'Research answer · CIO decision pending'}: {state.answer_summary}
    </p>}
    {state?.status === 'blocked' && last?.block_reason && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>
      Recorded by the acquisition run: {last.block_reason}{state.attempts_since_request ? ` · ${state.attempts_since_request} run${state.attempts_since_request === 1 ? '' : 's'} since you asked` : ''}
    </span>}
    <button type="button" data-testid="watch-ask-cio" className="mobile-detail-primary" disabled={!!entry?.busy}
      onClick={() => { void cio.ask(row, conflictKey) }}
      style={{ ...chipStyle('warning', 'outline', 'md'), cursor: entry?.busy ? 'default' : 'pointer', minHeight: 44, width: '100%', borderRadius: RADIUS.md, justifyContent: 'center' }}>
      {entry?.busy ? 'Asking the CIO…' : entry?.errorReason ? `Retry — ${entry.errorReason}` : state?.status === 'waiting_budget' ? state.label : 'Ask the CIO to review'}
    </button>
    {entry?.message && !entry.busy && <span role="status" data-testid="watch-cio-message" style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{entry.message}</span>}
    {(entry?.requestId || state?.request_id) && <small data-testid="watch-cio-request" style={{ color: TOKENS.text[2] }}>
      Request #{entry?.requestId || state?.request_id}{state?.open !== false
        ? ` · next processing: ${entry?.nextRun || state?.next_run || 'ETA unavailable'}`
        : state?.publication_verified ? ' · answered' : ' · publication history; refresh available'}
    </small>}
  </div>
}
