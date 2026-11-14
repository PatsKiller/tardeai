// Home deploy card model (src/lib/homeDeploy.ts) — CAMPAIGN-8H Home item 5. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/homeDeploy.test.ts
// The claim under test: the card's served identity comes only from the server's `served` block; the poller's last
// receipt is a separate labelled fact and can never become the served version; every relative age is computed at
// render from an instant, never carried in the model.
import { homeDeployView, DEPLOY_SOURCE } from './homeDeploy.ts'
import type { DeploysStatusWire } from './deploys.ts'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as deploys.test.ts).
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
function eq(a: unknown, b: unknown, m: string) { if (JSON.stringify(a) !== JSON.stringify(b)) fail(`${m}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`) }
function ok(c: unknown, m: string) { if (!c) fail(m) }

const NOW = Date.parse('2031-03-10T15:00:00Z')
const READ_AT = '2031-03-10T14:59:30Z'
const SERVED = 'd12fe7ec303385c4398c8eeba7dab6def89c0ccc'
const POLLER = '9c21372aa' + 'b'.repeat(31)

const body = (over: Partial<DeploysStatusWire> = {}): DeploysStatusWire => ({
  schema: 'DeploysStatus@v1',
  generated_at: '2031-03-10T14:59:00Z',
  served: { sha: SERVED, release: 'd12fe7ec3-live-integration-20310310-145500', stamped_at: '2031-03-10T14:55:00Z', activated_at: '2031-03-10T14:56:00Z', is_current: true, error: null },
  latest: { schema: 'DeployOnMainReceipt@v1', as_of: '2031-03-10T14:58:00Z', path: 'poller', outcome: 'deploy_failed', main_sha: POLLER },
  latest_error: null,
  stop: { schema: 'DeployStopStatus@v1', as_of: '2031-03-10T14:59:00Z', latch: { status: 'ABSENT' }, window_run_lock: 'FREE' },
  ...over,
})
const read = (over: Partial<DeploysStatusWire> = {}, state: 'OK' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING' = 'OK', error: string | null = null) =>
  ({ state, data: state === 'OK' ? body(over) : null, error, at: READ_AT, source: DEPLOY_SOURCE })

eq(DEPLOY_SOURCE, '/api/v2/ops/deploys', 'the card reads the ops/deploys route')

// 1. Served identity is the server's, and the poller's failure is not the card's verdict.
const ok1 = homeDeployView(read(), NOW)
eq(ok1.served.sha, SERVED.slice(0, 9), 'served sha is the served release, short')
eq(ok1.served.fullSha, SERVED, 'full sha kept for identity')
eq([ok1.served.current, ok1.served.activatedAt], [true, '2031-03-10T14:56:00Z'], 'activation instant kept, not an age')
eq([ok1.state, ok1.stop.text], ['OK', 'STOP clear'], 'transport OK, STOP clear')
eq(ok1.poller.vsServed, 'differs', 'poller main differs from served')
ok(ok1.poller.text.includes('deploy_failed'), 'poller decision named as such')
eq(ok1.tone, 'warning', 'a failed poller is a warning, never the card state')
ok(!JSON.stringify(ok1).includes('ago') && !JSON.stringify(ok1).includes(' old'), 'no relative age is stored in the model')

// 2. The poller's sha can never fill an unreported served release.
const noServed = homeDeployView(read({ served: null }), NOW)
eq(noServed.served.sha, null, 'no served block -> no served sha')
eq(noServed.served.fullSha, null, 'and no full sha')
ok(noServed.poller.text.includes('deploy_failed'), 'the poller fact is still shown, labelled separately')
ok(!JSON.stringify(noServed.served).includes(POLLER.slice(0, 7)), 'the poller sha never enters `served`')

// 3. An unparseable activation is "not published", never "now"; is_current absent is unknown, never true.
const bad = homeDeployView(read({ served: { sha: SERVED, activated_at: 'yesterday-ish', is_current: null } }), NOW)
eq(bad.served.activatedAt, null, 'unparseable activated_at -> null')
eq(bad.served.current, null, 'absent is_current -> unknown')
ok(bad.served.sha, 'the sha itself is still served fact')

// 3b. C1 (review item 5): the server's own reason for an unresolved identity survives the model — the view draws it
//     beside the callout, so dropping it here would silently lose the only sentence that says WHY.
const why = homeDeployView(read({ served: { sha: SERVED, activated_at: '2031-03-10T14:56:00Z', is_current: null, error: 'CURRENT symlink not readable next to this release' } }), NOW)
eq(why.served.error, 'CURRENT symlink not readable next to this release', 'served.error survives as the why')
eq(why.served.current, null, 'the currency stays unresolved, never true')

// 4. A served release that is not CURRENT is called out.
const stale = homeDeployView(read({ served: { sha: SERVED, activated_at: '2031-03-10T14:56:00Z', is_current: false } }), NOW)
eq(stale.served.current, false, 'is_current false survives the model')

// 5. A kept body older than the transport bar demotes to STALE (computed against the render clock).
const old = homeDeployView(read({ generated_at: '2031-03-10T14:20:00Z' }), NOW)
eq(old.state, 'STALE', 'a body 40 min old is STALE')
const stillFresh = homeDeployView(read({ generated_at: '2031-03-10T14:58:00Z' }), NOW)
eq(stillFresh.state, 'OK', 'the same body a minute old is OK')

// 6. An unreadable route is UNAVAILABLE with its reason, STOP fails closed, and nothing is invented.
const gone = homeDeployView({ state: 'UNKNOWN', data: null, error: 'HTTP 503', at: READ_AT, source: DEPLOY_SOURCE }, NOW)
eq([gone.state, gone.served.sha, gone.stop.effective, gone.stop.text], ['UNAVAILABLE', null, true, 'STOP UNAVAILABLE'], 'unreadable fails closed')
eq(gone.reason, 'HTTP 503', 'the reason travels')
const loading = homeDeployView({ state: 'LOADING', data: null, error: null, at: null, source: DEPLOY_SOURCE }, NOW)
eq([loading.state, loading.stop.effective], ['LOADING', false], 'loading is not a STOP yet')

// 7. An unreadable STOP latch fails closed even with a served release reported.
const latch = homeDeployView(read({ stop: { latch: { status: 'UNREADABLE' } } as DeploysStatusWire['stop'] }), NOW)
eq([latch.stop.effective, latch.stop.text], [true, 'STOP UNREADABLE'], 'unreadable latch is an effective STOP')
ok(latch.tone === 'danger', 'an effective STOP is the card tone')

// 8. A poller receipt older than the activation is marked as such.
const before = homeDeployView(read({ latest: { as_of: '2031-03-10T14:50:00Z', outcome: 'verified', main_sha: SERVED } }), NOW)
eq([before.poller.beforeServed, before.poller.vsServed], [true, 'same'], 'same commit, but before it was activated')

console.log('homeDeploy: ok (8 groups)')
