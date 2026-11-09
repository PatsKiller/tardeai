// LQ-20261107-1305 — two components polling one path cost one read, and nothing else changes.
//
// Measured 2026-11-08 20:52 ET at 412 px on live beb570f97: the approvals summary GET twice on load and
// twice per 60 s poll (NavRail and MetricStrip both poll it; server log shows paired requests in the same
// second). On a browser without the operator credential that is the same 403 in the console twice. The
// rule pinned here: concurrent reads for ONE path share ONE request; a finished request is never reused;
// a failed one is never handed to a later caller; distinct paths never share.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { HOME_APPROVALS } from './homeApprovals.ts'
import { coalesceInFlight, resetInFlight } from './inflightGet.ts'

const SUMMARY = `${HOME_APPROVALS}/summary`

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

const tick = () => new Promise<void>(resolveTick => setTimeout(resolveTick, 0))

// ── one read, however many callers ───────────────────────────────────────────────────────────────────

resetInFlight()
{
  let runs = 0
  const run = async () => { runs += 1; await tick(); return { status: 200, headers: new Headers(), text: '{}' } }
  const [a, b, c] = await Promise.all([
    coalesceInFlight(SUMMARY, run),
    coalesceInFlight(SUMMARY, run),
    coalesceInFlight(SUMMARY, run),
  ])
  assert.equal(runs, 1, 'three simultaneous readers of one path must issue one request')
  assert.deepEqual([a.status, a.text], [b.status, b.text], 'every caller sees the same answer')
  assert.deepEqual([a.status, a.text], [c.status, c.text])
}

// ── no cache: the next poll reaches the server ───────────────────────────────────────────────────────

resetInFlight()
{
  let runs = 0
  const run = async () => { runs += 1; return runs }
  assert.equal(await coalesceInFlight('/p', run), 1)
  // The settle handler clears the map in a microtask; one tick later a poll must run again.
  await tick()
  assert.equal(await coalesceInFlight('/p', run), 2, 'a settled read is not reused — polling still polls')
  assert.equal(runs, 2)
}

// ── a failure is shared with the callers that joined it, and never with a later one ──────────────────

resetInFlight()
{
  let runs = 0
  let fail = true
  const run = async () => {
    runs += 1
    await tick()
    if (fail) throw new Error('network down')
    return runs
  }
  const results = await Promise.allSettled([
    coalesceInFlight('/q', run),
    coalesceInFlight('/q', run),
  ])
  assert.deepEqual(results.map(r => r.status), ['rejected', 'rejected'], 'both joined callers see the failure')
  assert.equal(runs, 1)
  await tick()
  fail = false
  assert.equal(await coalesceInFlight('/q', run), 2, 'the failed read is not retained')
}

// ── different paths never share ──────────────────────────────────────────────────────────────────────

resetInFlight()
{
  let runs = 0
  const run = async (label: string) => { runs += 1; await tick(); return label }
  const [a, b] = await Promise.all([
    coalesceInFlight('/one', () => run('one')),
    coalesceInFlight('/two', () => run('two')),
  ])
  assert.equal(runs, 2)
  assert.deepEqual([a, b], ['one', 'two'])
}

// ── the hook that matters actually goes through it ───────────────────────────────────────────────────

{
  // nosemgrep: tq-ts-test-reads-source-text -- the coalescing itself is proven behaviourally above; this only proves the ONE consumer that must use it does.
  const hook = readFileSync(join(app, 'src/hooks/useApi.ts'), 'utf8')
  assert.ok(hook.includes("from '../lib/inflightGet'"), 'useApi must import the shared in-flight read')
  assert.ok(hook.includes('coalesceInFlight(path'), 'useApi must key the joined read by path')
  assert.ok(!hook.includes('await r.json()'), 'the body is read once into text; a shared Response cannot be json()-ed twice')
  // The shared value must carry `ok`. It did not on the first cut: `!r.ok` read `undefined`, so every
  // 200 took the failure branch — the desk rendered its frame and never a row (manualDeskDisclosure,
  // 2026-11-09). A plain object is not a Response; every field the caller reads has to travel.
  assert.ok(hook.includes('ok: res.ok'), 'the shared read must carry ok, status, headers and text')
}

console.log('inflightGet: 3 concurrent readers -> 1 request; no cache; failures not retained; distinct paths separate; useApi uses it')
