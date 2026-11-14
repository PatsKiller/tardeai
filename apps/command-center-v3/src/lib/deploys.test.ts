// Deploys pure helpers (src/lib/deploys.ts). Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/deploys.test.ts
import {
  DEPLOYS_PATHS, deploysSummary, freshness, newIdempotencyKey, NO_STOP_REQUEST, outcomeTone, stopModelFrom,
  stopReasonError, type DeploysStatusWire,
} from './deploys.ts'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as opsControls.test.ts).
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
function eq(a: unknown, b: unknown, m: string) { if (JSON.stringify(a) !== JSON.stringify(b)) fail(`${m}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`) }
function ok(c: unknown, m: string) { if (!c) fail(m) }

const NOW = Date.parse('2031-03-10T15:00:00Z')
const wire = (latch: string, outcome: string | null): DeploysStatusWire => ({
  schema: 'DeploysStatus@v1', generated_at: '2031-03-10T14:59:00Z',
  latest: outcome ? { schema: 'DeployOnMainReceipt@v1', as_of: '2031-03-10T14:58:00Z', path: 'poller', outcome, main_sha: 'a'.repeat(40) } : null,
  latest_error: outcome ? null : 'no receipt yet',
  stop: { schema: 'DeployStopStatus@v1', as_of: '2031-03-10T14:59:00Z', latch: { status: latch }, window_run_lock: 'FREE' },
})

eq(DEPLOYS_PATHS.status, '/api/v2/ops/deploys', 'status path')
eq(DEPLOYS_PATHS.stop, '/api/v2/ops/deploys/stop', 'stop path')
for (const p of Object.values(DEPLOYS_PATHS)) ok(!p.includes('train'), 'no train path')

const f = freshness('2031-03-10T14:59:00Z', true, { nowMs: NOW })
eq(f.state, 'OK', 'fresh')
const clear = deploysSummary(wire('ABSENT', 'verified'), f)
eq([clear.stopEffective, clear.stopText, clear.lastTone], [false, 'STOP clear', 'success'], 'clear + verified')
ok(clear.line.includes('verified · main aaaaaaaaa'), 'line names outcome + sha')
const set = deploysSummary(wire('SET', 'deploy_failed'), f)
eq([set.stopEffective, set.stopTone, set.lastTone], [true, 'danger', 'danger'], 'set + failed')
eq(deploysSummary(wire('UNREADABLE', null), f).stopEffective, true, 'unreadable latch fails closed')
ok(deploysSummary(wire('ABSENT', null), f).lastText.startsWith('no receipt'), 'no receipt is said, not green')
const gone = deploysSummary(null, freshness(null, false, { nowMs: NOW, error: 'HTTP 503' }))
eq([gone.state, gone.stopEffective, gone.stopText], ['UNAVAILABLE', true, 'STOP UNAVAILABLE'], 'unavailable fails closed')
eq(deploysSummary(null, freshness(null, false, { nowMs: NOW, loading: true })).stopEffective, false, 'loading is not a STOP yet')
eq(outcomeTone('noop'), 'neutral', 'noop')
eq(outcomeTone('something_new'), 'warning', 'unknown word is a warning')

// A09 (LQ-20261113-3077): the deploy state is the SERVED release; the poller's last result is separate and labelled.
{
  const live = { ...wire('ABSENT', 'deploy_failed'), served: { sha: '7b0cc18d05cb892e8da50f8acadcfa3e340ebdd9', release: '7b0cc18d0-x', activated_at: '2031-03-10T14:50:00Z', is_current: true, error: null } }
  live.latest = { ...live.latest!, as_of: '2031-03-09T22:30:00Z', main_sha: '9c21372aa5ef' }
  const d = deploysSummary(live, f)
  eq([d.servedSha, d.servedAt, d.pollerVsServed, d.pollerBeforeServed], ['7b0cc18d0', '2031-03-10T14:50:00Z', 'differs', true], 'served sha/time; poller differs and predates it')
  eq(d.line, 'STOP clear · serving 7b0cc18d0 · poller last deploy_failed · main 9c21372aa', 'line: served first, poller labelled')
  ok(d.line.indexOf('7b0cc18d0') < d.line.indexOf('poller last'), 'served named before the poller result')
  const same = deploysSummary({ ...live, latest: { ...live.latest!, main_sha: '7b0cc18d0' } }, f)
  eq(same.pollerVsServed, 'same', 'prefix match is the same release')
  eq(deploysSummary({ ...live, latest: { ...live.latest!, main_sha: '7b0' } }, f).pollerVsServed, 'differs', 'a 3-character prefix proves nothing')
  const none = deploysSummary(wire('ABSENT', 'verified'), f)
  eq([none.servedSha, none.pollerVsServed, none.servedText.startsWith('UNKNOWN')], [null, 'unknown', true], 'no served block is UNKNOWN, never the poller sha')
  ok(!none.line.includes('serving aaaaaaaaa'), 'the poller sha is never printed as the served one')
  const err = deploysSummary({ ...live, served: { sha: null, error: 'no BUILD_SHA in x' } }, f)
  ok(err.servedText.includes('UNKNOWN') && err.servedText.includes('no BUILD_SHA in x'), 'unreadable served release names its cause')
  ok(deploysSummary({ ...live, served: { ...live.served, is_current: false } }, f).servedText.includes('not the CURRENT release'), 'a non-CURRENT served release is said')
  eq(deploysSummary(null, freshness(null, false, { nowMs: NOW, error: 'HTTP 503' })).servedText, 'UNAVAILABLE', 'unavailable read')
}

const m = stopModelFrom(wire('SET', 'noop').stop, NO_STOP_REQUEST, freshness('2031-03-10T14:59:00Z', true, { nowMs: NOW, staleAfterS: 120 }))
eq(m.headline, 'DEPLOYS STOPPED', 'stop headline')
ok(stopReasonError('short') !== null && stopReasonError('a long enough reason') === null, 'reason bounds')
ok(/^cc-stop-[A-Za-z0-9._:-]+$/.test(newIdempotencyKey(() => 'x y!z')), 'idempotency key sanitized')
console.log('deploys.test.ts: ok')
