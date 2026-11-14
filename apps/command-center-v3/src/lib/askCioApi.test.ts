// Ask the CIO — the POST contract (campaign Home item 6: persist before ack).
//
// The operator's question is acknowledged only after the server has accepted (and stored) it: `askCio` resolves with
// the server's ask_id/thread_id, and the update that refreshes every list is published only then. A failed or refused
// POST publishes nothing, so no view can draw a question the store does not hold. The refusal keeps the server's typed
// code and HTTP status. Fetch and the window event bus are stubbed; no network.
import { askCio, AskApiError, requestDeep } from './askCioApi.ts'
import { ASK_UPDATED_EVENT } from './askCioPresentation.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const g = globalThis as any
if (typeof g.CustomEvent === 'undefined') {
  g.CustomEvent = class { type: string; detail: unknown; constructor(type: string, init?: { detail?: unknown }) { this.type = type; this.detail = init?.detail } }
}
const events: any[] = []
g.window = { dispatchEvent: (e: any) => { events.push(e); return true } }

const calls: Array<{ url: string; init: any }> = []
function stubFetch(handler: (url: string) => any) {
  g.fetch = (url: string, init: any) => { calls.push({ url, init }); return handler(url) }
}
const reply = (body: unknown, status = 200, ok = status < 400) => Promise.resolve({
  ok, status, json: async () => body,
})
const ASK_OK = { ok: true, data: { ask_id: 'ask_0123456789abcdef', thread_id: 'thr_0123456789abcdef', answer_text: 'synthetic answer', thread: null } }

async function main() {
  check('CustomEvent and window are available to the stub', typeof g.CustomEvent === 'function' && typeof g.window.dispatchEvent === 'function')

  // ── persist before ack ────────────────────────────────────────────────────
  {
    let release!: (v: any) => void
    const gate = new Promise<any>(resolve => { release = resolve })
    stubFetch(() => gate)
    events.length = 0
    // Read through a getter: the assignment happens inside a promise callback, which TS's control-flow narrowing
    // cannot see, so a direct `settled === true` after `let settled = false` is a type error (not a real one).
    let settledFlag = false
    const settled = (): boolean => settledFlag
    const pending = askCio('Is the synthetic position inside its stated band?').then(r => { settledFlag = true; return r })
    await Promise.resolve()
    await Promise.resolve()
    check('not acknowledged before the server answers', settled() === false)
    check('nothing published before the server answers', events.length === 0)
    check('the request is a same-origin JSON POST', calls.length === 1 && calls[0].init.method === 'POST'
      && String(calls[0].init.headers['Content-Type']).includes('application/json') && calls[0].init.credentials === 'same-origin')
    const sent = JSON.parse(calls[0].init.body)
    check('the server receives the question as typed', sent.question === 'Is the synthetic position inside its stated band?')
    check('the request carries a client_request_id (one identity for one ask)', typeof sent.client_request_id === 'string' && sent.client_request_id.length > 0)
    check('quick is the default depth', sent.depth === 'quick')
    release({ ok: true, status: 200, json: async () => ASK_OK })
    const r = await pending
    check('the ack is the server ask_id after persistence', settled() === true && r.ask_id === 'ask_0123456789abcdef')
    check('exactly one refresh is published, for the server thread', events.length === 1 && events[0].type === ASK_UPDATED_EVENT
      && events[0].detail.threadId === 'thr_0123456789abcdef')
  }

  // ── a refusal carries the server's typed code and publishes nothing ───────
  {
    stubFetch(() => reply({ ok: false, error: 'AGENT_CALLER_REFUSED', detail: 'Ask the CIO answers only the operator’s tailnet identity' }, 403, false))
    events.length = 0
    let err: any = null
    try { await askCio('A question that will be refused') } catch (e) { err = e }
    check('a refused ask rejects', err instanceof AskApiError)
    check('the typed code survives', err?.code === 'AGENT_CALLER_REFUSED')
    check('the HTTP status survives', err?.status === 403)
    check('the server detail is kept', String(err?.message).includes('tailnet identity'))
    check('a refused ask publishes nothing (no phantom question)', events.length === 0)
  }

  // ── a transport failure is not a refusal code ─────────────────────────────
  {
    stubFetch(() => Promise.resolve({ ok: false, status: 500, json: async () => { throw new Error('not json') } }))
    events.length = 0
    let err: any = null
    try { await askCio('Another question') } catch (e) { err = e }
    check('an unreadable 500 is HTTP_500, not a refusal code', err instanceof AskApiError && err.code === 'HTTP_500')
    check('a failed ask publishes nothing', events.length === 0)
  }

  // ── one deep refresh per thread, and it too publishes only on success ─────
  {
    const gate: any = {}
    gate.p = new Promise(resolve => { gate.release = resolve })
    stubFetch(() => gate.p)
    events.length = 0
    const a = requestDeep('thr_0123456789abcdef')
    const b = requestDeep('thr_0123456789abcdef')
    check('two clicks join one in-flight deep request', a === b)
    check('no refresh published while the deep request is open', events.length === 0)
    gate.release({ ok: true, status: 200, json: async () => ({ ok: true, data: { status: 'pending' } }) })
    await a
    check('the deep request publishes one refresh on success', events.length === 1 && events[0].detail.threadId === 'thr_0123456789abcdef')
    const c = requestDeep('thr_0123456789abcdef')
    check('after it settles, a later refresh is a new request', c !== a)
    await c
  }

  console.log(`\naskCioApi: ${pass} passed, ${fail} failed`)
  if (fail > 0) process.exit(1)
}

void main().catch(e => { console.error(e); process.exit(1) })
