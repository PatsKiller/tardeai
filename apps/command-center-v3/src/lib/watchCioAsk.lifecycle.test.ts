// node --experimental-strip-types src/lib/watchCioAsk.lifecycle.test.ts
// A4 (item-6 review -5): the Watch card must not say the CIO is answering before the server accepted the question.
// Pure seam: runCioAsk takes the network and the render callback, so the ORDER of published entries is testable here.
declare const process: { exit(code?: number): never }
import {
  askFailureView, runCioAsk, sendingView, type CioAskEntry, type WatchAskView,
} from './watchCioAsk.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: boolean) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

/** A promise whose settlement the test controls, so "still in flight" is a fact, not a race. */
function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const tick = () => new Promise<void>(r => setTimeout(r, 0))
const phases = (log: CioAskEntry[]) => log.map(e => e.view?.phase ?? '(none)')
/** The fake server error the real ask helper throws: AskApiError carries code, status and (now) detail apart. */
const apiError = (code: string, status: number, detail?: string) => Object.assign(new Error(detail ? `${code}: ${detail}` : code), { code, status, detail: detail ?? '' })
const QUEUED = { ok: true, message: 'CIO review queued.', state: null, requestId: 'RQ-1', nextRun: '2031-03-07T15:30:00Z' }

async function main() {
  // ── 1. Nothing is published before the response that claims the CIO is engaged ─────────────────────────────
  {
    const log: CioAskEntry[] = []
    const ask = deferred<{ thread_id: string; stance?: string }>()
    const run = runCioAsk({ put: e => log.push(e), ask: () => ask.promise, queue: async () => QUEUED })
    await tick(); await tick()
    eq('before the response: one entry, phase sending', phases(log), ['sending'])
    eq('before the response: the label says what the browser is doing', log[0].view?.message, sendingView().message)
    ok('before the response: busy', log[0].busy === true)
    ok('before the response: no entry claims an answer', !phases(log).some(p => p === 'asked' || p === 'answered' || p === 'failed'))
    ask.resolve({ thread_id: 'TH-1', stance: 'HOLD' })
    await run
  }

  // ── 2. "asked" only after the server returned a thread, and before the queue settles ──────────────────────
  {
    const log: CioAskEntry[] = []
    const queue = deferred<typeof QUEUED>()
    const run = runCioAsk({ put: e => log.push(e), ask: async () => ({ thread_id: 'TH-2', stance: 'HOLD' }), queue: () => queue.promise })
    await tick(); await tick()
    eq('accepted: sending then asked while the queue is open', phases(log), ['sending', 'asked'])
    ok('accepted: asked does not publish a thread link before the answer', log[1].view?.threadId === null)
    ok('accepted: no "answered" before the queue settles', !phases(log).includes('answered'))
    queue.resolve(QUEUED); const out = await run
    eq('accepted: settled as answered', out.view.phase, 'answered')
    eq('accepted: settled carries the thread', out.view.threadId, 'TH-2')
    ok('accepted: outcome ok', out.ok === true)
  }

  // ── 3. A refused ask is the typed denial, and never passes through "asked" ───────────────────────────────
  {
    const log: CioAskEntry[] = []
    const out = await runCioAsk({
      put: e => log.push(e),
      ask: async () => { throw apiError('AGENT_CALLER_REFUSED', 403, 'agents are not the operator') },
      queue: async () => QUEUED,
    })
    eq('refused: the only phases are sending then failed', phases(log), ['sending', 'failed'])
    ok('refused: no phase ever claimed an answer', !phases(log).some(p => p === 'asked' || p === 'answered'))
    eq('refused: settled as failed', out.view.phase, 'failed')
    ok('refused: marked as a denial', out.view.denied === true)
    eq('refused: the server code is carried', out.view.code, 'AGENT_CALLER_REFUSED')
    eq('refused: the HTTP status is carried', out.view.httpStatus, 403)
    ok('refused: the message names the code', out.view.message.includes('AGENT_CALLER_REFUSED'))
    ok('refused: the message carries the server detail, not a generic sentence', out.view.message.includes('agents are not the operator'))
    eq('refused: the queue note is kept beside the refusal', out.view.queueNote, QUEUED.message)
    eq('refused: the entry keeps the denial reason for the retry label', log[log.length - 1].errorReason, out.view.message)
    eq('refused: the settled entry is not busy', log[log.length - 1].busy, false)
  }

  // ── 4. 401 reads as sign-in required; a transport error is a failure but not a denial ────────────────────
  {
    const out = await runCioAsk({ put: () => {}, ask: async () => { throw apiError('UNAUTHORIZED', 401) }, queue: async () => null })
    ok('401: a denial', out.view.denied === true)
    eq('401: status carried', out.view.httpStatus, 401)
    ok('401: the sentence is the sign-in one', out.view.message.startsWith('Sign-in required'))
    eq('401: the code the server sent is carried', out.view.code, 'UNAUTHORIZED')
    // The ask helper's fallback when the body carried no code is `HTTP_401` — the transport's word, not the server's.
    const bare = await runCioAsk({ put: () => {}, ask: async () => { throw apiError('HTTP_401', 401) }, queue: async () => null })
    eq('401 without a server code: no code shown', bare.view.code, null)
    ok('401 without a server code: the identity is the status', bare.view.message.endsWith('(HTTP 401)'))
    ok('401 without a server code: the invented code is not echoed as a detail', !bare.view.message.includes('HTTP_401'))
    const net = await runCioAsk({ put: () => {}, ask: async () => { throw new Error('Failed to fetch') }, queue: async () => null })
    eq('transport: failed', net.view.phase, 'failed')
    ok('transport: not a denial', !net.view.denied)
    eq('transport: the server/transport text is kept', net.view.message, 'Failed to fetch')
    eq('transport: no queue note when the queue said nothing', net.view.queueNote, null)
  }

  // ── 5. A successful ask with no structured stance says so; a refusal of the queue alone does not erase an answer
  {
    const out = await runCioAsk({
      put: () => {},
      ask: async () => ({ thread_id: 'TH-3' }),
      queue: async () => ({ ok: false, message: 'Could not queue: HTTP 503', state: null }),
    })
    eq('answered: phase', out.view.phase, 'answered')
    ok('answered: a missing stance is named, never inferred', (out.view.stanceGap || '').includes('stance'))
    eq('answered: the queue failure is a note, not the verdict', out.view.queueNote, 'Could not queue: HTTP 503')
    ok('answered: outcome ok because the ask was accepted', out.ok === true)
  }

  // ── 6. A 200 without a thread is a failure, not an answer ────────────────────────────────────────────────
  {
    const out = await runCioAsk({ put: () => {}, ask: async () => ({ thread_id: '' }), queue: async () => QUEUED })
    eq('no thread: failed', out.view.phase, 'failed')
    ok('no thread: no thread link', out.view.threadId === null)
    eq('no thread: the sentence says the thread is missing', out.view.message, 'The CIO did not return a thread.')
  }

  // ── 7. The pure failure projection: unknown code is named by its code, never dropped ─────────────────────
  {
    const v: WatchAskView = askFailureView({ code: 'SOMETHING_NEW', status: 500, text: 'boom' })
    eq('unknown 500: not a denial', v.denied, false)
    eq('unknown 500: keeps the text', v.message, 'boom')
    const d = askFailureView({ status: 403, code: 'CSRF_REFUSED' })
    ok('403 without detail: the known code sentence is used', d.message.includes('same-origin'))
  }

  if (failed) { console.error(`watchCioAsk.lifecycle: ${failed} failure(s)`); process.exit(1) }
  console.log('watchCioAsk.lifecycle: all checks passed')
}

await main()
