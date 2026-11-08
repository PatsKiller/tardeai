// LQ-20261107-481 — a burst of components asking the same question costs one request.
//
// Measured 2026-11-07 19:20 ET on /v3/intelligence/classic: 21 identical GET /api/v2/llm/oauth-lanes
// and 26 GET /api/v2/inference/ensemble in 27 s, all from one page, every response under 1.5 s. The
// lane read is the same answer for every card, so the duplicates bought nothing and kept the page
// from ever reaching network idle.
//
// Red-first: this file does not resolve `./sharedGet.ts` on the parent commit.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { sharedGetJSON, resetSharedGet, DEFAULT_TTL_MS } from './sharedGet.ts'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

type Call = { url: string; at: number }
const calls: Call[] = []
let respond: (url: string) => Promise<unknown> = async (url) => ({ ok: true, url })
const realFetch = globalThis.fetch
globalThis.fetch = (async (input: any) => {
  const url = String(input)
  calls.push({ url, at: Date.now() })
  return { json: async () => respond(url) } as Response
}) as typeof fetch
const reset = () => { resetSharedGet(); calls.length = 0 }

const tick = (ms = 5) => new Promise(r => setTimeout(r, ms))

// 1. The measured shape: 21 mounts read the same URL in one paint. One request, one answer object.
reset()
const burst = await Promise.all(Array.from({ length: 21 }, () => sharedGetJSON<any>('/api/v2/llm/oauth-lanes', 5_000)))
assert.equal(calls.length, 1, `21 concurrent identical reads must cost 1 fetch, got ${calls.length}`)
assert.equal(burst.length, 21)
assert.ok(burst.every(v => v === burst[0]), 'every concurrent caller receives the same parsed answer')

// 2. A remount inside the window costs nothing.
await sharedGetJSON('/api/v2/llm/oauth-lanes', 5_000)
assert.equal(calls.length, 1, 'a read inside the TTL must not reach the server')

// 3. It is a window, not a cache: after the TTL the next read is real.
await tick(20)
await sharedGetJSON('/api/v2/llm/oauth-lanes', 5)
assert.equal(calls.length, 2, 'a read after the TTL must reach the server')

// 4. Distinct targets are never conflated (the ensemble read is per target_id).
reset()
await Promise.all([
  sharedGetJSON('/api/v2/inference/ensemble?target_type=signal&target_id=a', 5_000),
  sharedGetJSON('/api/v2/inference/ensemble?target_type=signal&target_id=b', 5_000),
])
assert.equal(calls.length, 2, 'two targets are two reads')

// 5. A failure is an answer for nobody: it is not cached, and the next caller reaches the server.
reset()
respond = async () => { throw new Error('backend down') }
await assert.rejects(() => sharedGetJSON('/api/v2/inference/ensemble?target_id=x', 5_000))
respond = async (url) => ({ ok: true, url })
const recovered = await sharedGetJSON<any>('/api/v2/inference/ensemble?target_id=x', 5_000)
assert.equal(calls.length, 2, 'a rejected read must not be cached')
assert.equal(recovered.ok, true)

// 6. The window is shorter than every caller's own poll, so no caller's cadence is stretched.
assert.ok(DEFAULT_TTL_MS < 4_000, 'default TTL must sit inside the 4 s ensemble poll')

// 7. The two consumers read through it — the source guard makes the fix load-bearing at the call sites.
// nosemgrep: tq-ts-test-reads-source-text -- a source guard layered on the behavioural assertions above; the coalescing itself is proven by calling sharedGetJSON with a stubbed fetch, so this only proves the call sites use it.
const lanes = readFileSync(join(app, 'src/hooks/useOAuthLanes.ts'), 'utf8')
assert.ok(lanes.includes("from '../lib/sharedGet'"), 'useOAuthLanes must import the shared read')
assert.ok(lanes.includes("sharedGetJSON<any>('/api/v2/llm/oauth-lanes'"), 'useOAuthLanes must read through it')
assert.ok(!lanes.includes("fetch('/api/v2/llm/oauth-lanes'"), 'useOAuthLanes must not call fetch directly')

// nosemgrep: tq-ts-test-reads-source-text -- the card's coalescing is asserted behaviourally above; this guard only proves EnsembleValidationCard reads through the shared call and encodes target_id.
const card = readFileSync(join(app, 'src/components/EnsembleValidationCard.tsx'), 'utf8')
assert.ok(card.includes('sharedGetJSON<any>(url)'), 'the ensemble card must read through the shared read')
assert.ok(!card.includes('await fetch(`/api/v2/inference/ensemble'), 'the ensemble card must not call fetch directly')
assert.ok(card.includes('encodeURIComponent(String(targetId))'), 'target_id must be encoded in the query')

globalThis.fetch = realFetch
console.log('sharedGet: 21 concurrent mounts -> 1 read; TTL is a window; failures are not cached; both consumers read through it')
