import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, chipStyle } from '../../lib/designTokens'
import { askCio, askErrorText } from '../../lib/askCioApi'
import { cioReviewNote, reviewStateText, reviewStateTone, type ProspectRow, type ReviewState } from '../../lib/watchProspectsModel'
import { requestCioReview } from '../../lib/watchListsModel'
import {
  answeringView, askedView, finishAsk, stanceFromAskPayload, watchAskQuestion,
  type WatchAskView,
} from '../../lib/watchCioAsk'

/** Watch "Ask the CIO": the button uses the same ask endpoint as the header Ask bar.
 *  The thesis-queue request stays a secondary note and cannot hide an ask failure. Advisory only. */

type Entry = { busy: boolean; message: string; state: ReviewState | null; view: WatchAskView }
export type CioReviewController = {
  entries: Record<string, Entry>
  ask: (row: ProspectRow, conflictKey?: string | null) => Promise<void>
}

export function useCioReview(onDone?: () => void): CioReviewController {
  const [entries, setEntries] = useState<Record<string, Entry>>({})
  const ask = useCallback(async (row: ProspectRow, conflictKey?: string | null) => {
    const sym = row.symbol
    const put = (entry: Entry) => setEntries(prev => ({ ...prev, [sym]: entry }))
    put({ busy: true, message: 'Asked', state: null, view: askedView() })
    await new Promise(resolve => setTimeout(resolve, 0))
    put({ busy: true, message: 'Answering', state: null, view: answeringView() })
    let askOk = false
    let askMessage = 'The CIO did not return a thread.'
    let threadId: string | null = null
    let stance: string | null = null
    try {
      const result = await askCio(watchAskQuestion(row))
      threadId = result.thread_id || null
      stance = stanceFromAskPayload(result).stance
      if (threadId) askOk = true
    } catch (err) {
      askMessage = askErrorText(err)
    }
    const queued = await requestCioReview(sym, cioReviewNote(row), conflictKey)
    const view = finishAsk({
      askOk,
      askMessage,
      threadId,
      stance,
      queueMessage: queued.message,
    })
    put({ busy: false, message: view.message, state: queued.state, view })
    if (askOk || queued.ok) onDone?.()
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

export function AskPhaseStatus({ entry, testId = 'watch-ask-phase' }: { entry?: Entry | null; testId?: string }) {
  const view = entry?.view
  if (!view) return null
  const id = (suffix: string) => testId === 'watch-ask-phase' ? `watch-ask-${suffix}` : `${testId}-${suffix}`
  return <div data-testid={testId} data-phase={view.phase} role="status" style={{ display: 'grid', gap: 4, fontSize: TYPE.base, color: TOKENS.text[1] }}>
    <span>{view.message}</span>
    {view.phase === 'answered' && view.stance && <span data-testid={id('stance')}>CIO stance: {view.stance}</span>}
    {view.phase === 'answered' && view.stanceGap && <span data-testid={id('stance-gap')}>{view.stanceGap}</span>}
    {view.threadId && <Link data-testid={id('thread')} to={`/cio/questions/${encodeURIComponent(view.threadId)}`}
      style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>Open the thread</Link>}
    {view.queueNote && <span data-testid={id('queue')}>{view.queueNote}</span>}
  </div>
}

/** State + one actionable button. Shown in the record whenever the next step asks the CIO, flags or not. */
export function CioReviewPanel({ row, cio, conflictKey }: { row: ProspectRow; cio: CioReviewController; conflictKey?: string | null }) {
  const entry = cio.entries[row.symbol]
  const state = currentReviewState(row, cio)
  const last = state?.last_attempt
  return <div data-testid="watch-cio-review" style={{ display: 'grid', gap: 8 }}>
    <ReviewStateChip state={state} />
    <AskPhaseStatus entry={entry} />
    {state?.status === 'blocked' && last?.block_reason && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>
      Recorded by the acquisition run: {last.block_reason}{state.attempts_since_request ? ` · ${state.attempts_since_request} run${state.attempts_since_request === 1 ? '' : 's'} since you asked` : ''}
    </span>}
    <button type="button" data-testid="watch-ask-cio" className="mobile-detail-primary" disabled={!!entry?.busy}
      onClick={() => { void cio.ask(row, conflictKey) }}
      style={{ ...chipStyle('warning', 'outline', 'md'), cursor: entry?.busy ? 'default' : 'pointer', minHeight: 44, width: '100%', borderRadius: RADIUS.md, justifyContent: 'center' }}>
      {entry?.busy ? entry.view.message : 'Ask the CIO to review'}
    </button>
  </div>
}
