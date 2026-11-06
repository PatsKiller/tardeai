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

const m = stopModelFrom(wire('SET', 'noop').stop, NO_STOP_REQUEST, freshness('2031-03-10T14:59:00Z', true, { nowMs: NOW, staleAfterS: 120 }))
eq(m.headline, 'DEPLOYS STOPPED', 'stop headline')
ok(stopReasonError('short') !== null && stopReasonError('a long enough reason') === null, 'reason bounds')
ok(/^cc-stop-[A-Za-z0-9._:-]+$/.test(newIdempotencyKey(() => 'x y!z')), 'idempotency key sanitized')
console.log('deploys.test.ts: ok')
