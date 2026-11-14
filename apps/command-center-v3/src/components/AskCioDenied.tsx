/**
 * Ask the CIO / My questions — the refused-read panel (campaign Home item 6).
 *
 * Drawn in place of the list when `useApi`'s answer to the read was 401/403. It names the server's typed code (or the
 * HTTP status when the body carried none), quotes the server's own sentence, says that polling stopped, and offers the
 * one recovery that exists — an operator refetch. It never draws the held list: the caller cannot see the queue, so an
 * older list shown as current would be a second lie (the 3076 rule on the approvals card).
 *
 * Pure presentational: the clock is a prop, so the same refusal renders the same age in a test.
 */
import { RADIUS, TOKENS, TYPE } from '../lib/designTokens'
import { refusalLabel, type AskDenialView } from '../lib/askCioDenied'
import { relativeAge } from '../lib/askCioModel'
import { readableTime } from '../lib/readableTime'

export default function AskCioDenied({ view, heldAt, nowMs, onRetry }: {
  view: AskDenialView
  /** When the questions were last read successfully, if this page still holds that body. */
  heldAt?: string | null
  /** The render clock. */
  nowMs?: number
  onRetry: () => void
}) {
  if (!view.denied) return null
  const now = Number.isFinite(nowMs) ? new Date(nowMs as number) : new Date()
  const read = heldAt ? readableTime(heldAt) : null
  const age = heldAt ? relativeAge(heldAt, now) : ''
  return (
    <section role="alert" data-testid="ask-denied" data-code={view.code ?? ''} data-status={String(view.httpStatus)}
      aria-label="Ask the CIO refused"
      style={{ border: `1px solid ${TOKENS.warning}`, borderLeftWidth: 4, borderRadius: RADIUS.lg, background: TOKENS.bg[1], padding: 12, display: 'grid', gap: 6 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <b style={{ fontSize: TYPE.base, color: TOKENS.text[0] }}>{view.title}</b>
        <code data-testid="ask-denied-identity" style={{ fontSize: TYPE.sm, color: TOKENS.warning }}>{refusalLabel(view)}</code>
      </div>
      <div data-testid="ask-denied-detail" style={{ fontSize: TYPE.sm, color: TOKENS.text[1], overflowWrap: 'anywhere' }}>{view.detail}</div>
      {heldAt && read
        ? <div data-testid="ask-denied-held" style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
            The questions last read at {read}{age ? ` · ${age}` : ''} are not shown: they may have changed since.
          </div>
        : <div data-testid="ask-denied-none" style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
            This page has not read any questions in this session.
          </div>}
      <div data-testid="ask-denied-recovery" style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{view.recovery}</div>
      <div>
        <button type="button" onClick={onRetry} data-testid="ask-denied-retry"
          style={{ minHeight: 44, minWidth: 44, fontSize: TYPE.sm, padding: '4px 12px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.text[0], cursor: 'pointer' }}>
          {view.retryLabel}
        </button>
      </div>
    </section>
  )
}
