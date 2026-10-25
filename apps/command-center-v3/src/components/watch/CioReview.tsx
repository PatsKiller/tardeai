import { useCallback, useState } from 'react'
import { RADIUS, TOKENS, TYPE, chipStyle } from '../../lib/designTokens'
import { cioReviewNote, reviewStateText, reviewStateTone, type ProspectRow, type ReviewState } from '../../lib/watchProspectsModel'
import { requestCioReview } from '../../lib/watchListsModel'

/** Watch "Ask the CIO" (batch 31, operator 2026-10-25): every next step that asks the CIO for a review is actionable,
 *  and the request's recorded state (queued, blocked by acquisition with its reason, answered, expired) is visible on
 *  the row and in the record. Uses the existing POST /api/v3/opportunities/{symbol}/review-request; advisory only. */

type Entry = { busy: boolean; message: string; state: ReviewState | null }
export type CioReviewController = {
  entries: Record<string, Entry>
  ask: (row: ProspectRow, conflictKey?: string | null) => Promise<void>
}

export function useCioReview(onDone?: () => void): CioReviewController {
  const [entries, setEntries] = useState<Record<string, Entry>>({})
  const ask = useCallback(async (row: ProspectRow, conflictKey?: string | null) => {
    const sym = row.symbol
    setEntries(e => ({ ...e, [sym]: { busy: true, message: 'Asking the CIO…', state: e[sym]?.state ?? null } }))
    const res = await requestCioReview(sym, cioReviewNote(row), conflictKey)
    setEntries(e => ({ ...e, [sym]: { busy: false, message: res.message, state: res.state ?? e[sym]?.state ?? null } }))
    if (res.ok) onDone?.()
  }, [onDone])
  return { entries, ask }
}

/** The state the page should show: the fresher of the POST readback and the row's served state. */
export function currentReviewState(row: ProspectRow, cio?: CioReviewController): ReviewState | null {
  return cio?.entries[row.symbol]?.state || row.review_state || null
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

/** State + one actionable button. Shown in the record whenever the next step asks the CIO, flags or not. */
export function CioReviewPanel({ row, cio, conflictKey }: { row: ProspectRow; cio: CioReviewController; conflictKey?: string | null }) {
  const entry = cio.entries[row.symbol]
  const state = currentReviewState(row, cio)
  const last = state?.last_attempt
  return <div data-testid="watch-cio-review" style={{ display: 'grid', gap: 8 }}>
    <ReviewStateChip state={state} />
    {state?.status === 'blocked' && last?.block_reason && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>
      Recorded by the acquisition run: {last.block_reason}{state.attempts_since_request ? ` · ${state.attempts_since_request} run${state.attempts_since_request === 1 ? '' : 's'} since you asked` : ''}
    </span>}
    <button type="button" data-testid="watch-ask-cio" className="mobile-detail-primary" disabled={!!entry?.busy}
      onClick={() => { void cio.ask(row, conflictKey) }}
      style={{ ...chipStyle('warning', 'outline', 'md'), cursor: entry?.busy ? 'default' : 'pointer', minHeight: 44, width: '100%', borderRadius: RADIUS.md, justifyContent: 'center' }}>
      {entry?.busy ? 'Asking the CIO…' : 'Ask the CIO to review'}
    </button>
    {entry?.message && !entry.busy && <span role="status" data-testid="watch-cio-message" style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{entry.message}</span>}
  </div>
}
