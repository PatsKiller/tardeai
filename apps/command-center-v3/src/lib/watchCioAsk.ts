/** Watch "Ask the CIO" question and the card status after the existing ask endpoint answers.
 *  Display only. The ask endpoint owns identity and budget. Answer prose is never parsed for a stance.
 *
 *  A4 (item-6 review -5): the card used to write "Asked" and then "Answering" before `askCio` had even been called, so
 *  a refused ask was labelled "the CIO is answering" until the catch replaced it. The lifecycle that decides those
 *  labels lives here — one pure async function, `runCioAsk`, with the network and the render callback injected — so
 *  the ORDER is testable without a DOM: nothing may say the CIO is engaged before the server accepts the question. */
import type { ProspectRow, ReviewState } from './watchProspectsModel.ts'
import { askDenialView, refusalLabel } from './askCioDenied.ts'
import { newerReviewState } from './watchReviewState.ts'

/** Same ceiling as askCioModel.MAX_QUESTION_CHARS. Kept local so this file stays a plain node test. */
export const WATCH_ASK_QUESTION_CHARS = 2000

/** What the card may say, in lifecycle order. `sending` is the ONLY phase allowed before the POST returns; `asked`
 *  means the server accepted the question (it returned an id), never that the browser has merely sent it. */
export type WatchAskPhase = 'sending' | 'asked' | 'answered' | 'failed'

export type WatchAskView = {
  phase: WatchAskPhase
  message: string
  threadId: string | null
  stance: string | null
  stanceGap: string | null
  queueNote: string | null
  /** Set only when the ask was refused by the server (401/403): the typed denial the surface draws. */
  denied?: boolean
  /** The server's own code, when it sent one. */
  code?: string | null
  /** The HTTP status of the refusal, or the status of any other failed ask. */
  httpStatus?: number | null
}

export const STANCE_GAP = 'CIO stance was not in this answer.'

type AskRow = Pick<ProspectRow, 'symbol' | 'stance' | 'conviction' | 'why' | 'summary' | 'price' | 'price_as_of' | 'conflicts' | 'next_action'>

export function watchAskQuestion(row: AskRow): string {
  const lines = [`Review ${row.symbol} for my watchlist: stance, conviction, what would change it`]
  if (row.stance) lines.push(`Card stance: ${row.stance}`)
  if (row.conviction != null && Number.isFinite(row.conviction)) lines.push(`Card conviction: ${row.conviction}`)
  if (row.why) lines.push(`Why: ${row.why}`)
  if (row.summary) lines.push(`Summary: ${row.summary}`)
  if (row.next_action?.reason) lines.push(`Next: ${row.next_action.reason}`)
  const conflicts = (row.conflicts || []).map(item => item.summary).filter(Boolean).slice(0, 3)
  if (conflicts.length) lines.push(`Conflicts: ${conflicts.join('; ')}`)
  if (row.price != null && Number.isFinite(row.price)) {
    lines.push(`Price: ${row.price}${row.price_as_of ? ` as of ${row.price_as_of}` : ''}`)
  }
  return clipQuestion(lines.join('\n'))
}

export function clipQuestion(text: string): string {
  if (text.length <= WATCH_ASK_QUESTION_CHARS) return text
  return `${text.slice(0, WATCH_ASK_QUESTION_CHARS - 1).trimEnd()}…`
}

/** A stance is shown only when the ask payload carries a structured string. */
export function stanceFromAskPayload(payload: unknown): { stance: string | null; stanceGap: string | null } {
  if (!payload || typeof payload !== 'object') return { stance: null, stanceGap: STANCE_GAP }
  const stance = (payload as { stance?: unknown }).stance
  if (typeof stance === 'string' && stance.trim()) return { stance: stance.trim(), stanceGap: null }
  return { stance: null, stanceGap: STANCE_GAP }
}

/** Before the POST returns: it says what THIS browser is doing, and nothing about the CIO. */
export function sendingView(): WatchAskView {
  return { phase: 'sending', message: 'Sending the question…', threadId: null, stance: null, stanceGap: null, queueNote: null }
}

/** The server accepted the question (it returned a thread). That is a fact about the server, not an answer: no
 *  thread link and no stance are published until the answer itself arrives. */
export function acceptedView(): WatchAskView {
  return { phase: 'asked', message: 'Asked — the server accepted the question; the CIO has not answered yet.', threadId: null, stance: null, stanceGap: null, queueNote: null }
}

/** The ask helper's fallback code when the body carried no `error` is `HTTP_<status>`; that is the transport's
 *  invention, not the server's typed code, so it is dropped and the refusal is identified by its status instead. */
const STATUS_CODE = /^HTTP_\d{3}$/

/** Normalise whatever was thrown into the facts a refusal needs, without trusting its shape. */
export function failureInput(err: unknown): { code: string | null; status: number | null; detail: string | null; text: string | null } {
  if (err && typeof err === 'object') {
    const e = err as { code?: unknown; status?: unknown; detail?: unknown; message?: unknown }
    const raw = typeof e.code === 'string' && e.code.trim() ? e.code.trim() : null
    const invented = raw !== null && STATUS_CODE.test(raw)
    const message = typeof e.message === 'string' && e.message.trim() ? e.message : null
    return {
      code: raw && !invented ? raw : null,
      status: typeof e.status === 'number' && Number.isFinite(e.status) ? e.status : null,
      detail: typeof e.detail === 'string' && e.detail.trim() ? e.detail.trim() : null,
      // The helper's message for a body with no code is the invented code itself; do not render it back as a detail.
      text: message && !(invented && message === raw) ? message : null,
    }
  }
  return { code: null, status: null, detail: null, text: typeof err === 'string' && err.trim() ? err : null }
}

/** A refused ask is a typed denial (the same projection My questions draws), never a generic sentence; a transport
 *  failure keeps the server's code/text when it has one. Either way the card must not claim an answer. */
export function askFailureView(input: { code?: string | null; status?: number | null; detail?: string | null; text?: string | null }): WatchAskView {
  const status = input.status ?? null
  if (status === 401 || status === 403) {
    const denial = askDenialView({
      authState: status === 403 ? 'FORBIDDEN' : 'UNAUTHORIZED',
      errorCode: input.code ?? null,
      errorDetail: input.detail ?? null,
      error: input.text ?? null,
    })
    return {
      phase: 'failed',
      message: `${denial.title}: ${denial.detail} (${refusalLabel(denial)})`,
      threadId: null, stance: null, stanceGap: null, queueNote: null,
      denied: true, code: denial.code, httpStatus: denial.httpStatus ?? status,
    }
  }
  return {
    phase: 'failed',
    message: input.text?.trim() || input.code?.trim() || 'The CIO did not return a thread.',
    threadId: null, stance: null, stanceGap: null, queueNote: null,
    denied: false, code: input.code ?? null, httpStatus: status,
  }
}

export function finishAsk(args: {
  askOk: boolean
  askMessage: string
  threadId?: string | null
  stance?: string | null
  queueMessage?: string | null
}): WatchAskView {
  const queueNote = args.queueMessage || null
  if (!args.askOk || !args.threadId) {
    return {
      phase: 'failed',
      message: args.askMessage || 'The CIO did not return a thread.',
      threadId: null,
      stance: null,
      stanceGap: null,
      queueNote,
    }
  }
  const stance = args.stance?.trim() || null
  return {
    phase: 'answered',
    message: 'Answered',
    threadId: args.threadId,
    stance,
    stanceGap: stance ? null : STANCE_GAP,
    queueNote,
  }
}

/** One card entry as the hook stores it (the component renders `view`; the rest drives the button and the request line). */
export interface CioAskEntry {
  busy: boolean
  message: string
  state: ReviewState | null
  view?: WatchAskView
  requestId?: string | null
  nextRun?: string | null
  errorReason?: string | null
}

/** Injected so the lifecycle is a plain function: the network, the thesis-queue request and the render callback. */
export interface CioAskDeps {
  put: (entry: CioAskEntry) => void
  ask: () => Promise<{ thread_id?: string | null; stance?: unknown } | null | undefined>
  queue: () => Promise<{ ok?: boolean; message?: string | null; state?: ReviewState | null; requestId?: string | null; nextRun?: string | null } | null | undefined>
}

export interface CioAskOutcome { ok: boolean; view: WatchAskView }

/**
 * The whole ask: send → (accepted | refused) → queue note → settled. The order is the contract:
 *   1. `sending` before `ask()` is called — the only thing published while the POST is in flight;
 *   2. `asked` only after the server returned a thread id (never on a refusal);
 *   3. a refusal/failure settles as the typed denial with the queue note beside it, not as "Answered".
 */
export async function runCioAsk({ put, ask, queue }: CioAskDeps): Promise<CioAskOutcome> {
  const sending = sendingView()
  put({ busy: true, message: sending.message, state: null, view: sending })
  let askOk = false
  let threadId: string | null = null
  let stance: string | null = null
  let failure: WatchAskView | null = null
  try {
    const result = await ask()
    const id = result && typeof result.thread_id === 'string' ? result.thread_id.trim() : ''
    stance = stanceFromAskPayload(result).stance
    if (id) {
      askOk = true
      threadId = id
      const accepted = acceptedView()
      put({ busy: true, message: accepted.message, state: null, view: accepted })
    } else {
      failure = askFailureView({ text: 'The CIO did not return a thread.' })
    }
  } catch (err) {
    failure = askFailureView(failureInput(err))
  }
  const queued = (await queue()) || null
  const queueMessage = queued?.message || null
  const view: WatchAskView = askOk
    ? finishAsk({ askOk, askMessage: '', threadId, stance, queueMessage })
    : { ...(failure ?? askFailureView({ text: 'The CIO did not return a thread.' })), queueNote: queueMessage }
  put({
    busy: false,
    message: view.message,
    state: newerReviewState(queued?.state ?? null, null),
    view,
    requestId: queued?.requestId ?? null,
    nextRun: queued?.nextRun ?? null,
    errorReason: askOk ? null : view.message,
  })
  return { ok: askOk || !!queued?.ok, view }
}
