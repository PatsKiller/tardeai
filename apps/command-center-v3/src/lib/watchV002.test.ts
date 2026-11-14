// LQ-20261107-2993a: the Watch v002 Overview model. Unknown/stale/timed-out never reads as OK.
//   node --experimental-strip-types src/lib/watchV002.test.ts
import { buildWatchStatus, gradeInput, watchDiagnostics, type WatchStatusWire } from './watchV002.ts'
import type { Read } from './homeV010.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const NOW = Date.parse('2026-11-13T17:00:00Z')
const iso = (secAgo: number) => new Date(NOW - secAgo * 1000).toISOString()
const inp = (id: string, over: Record<string, unknown> = {}) => ({
  id, label: id, required: true, state: 'OK', source_id: `src_${id}`, owner: `own_${id}`, as_of: iso(60), age_s: 60,
  threshold_s: 1800, reason: null, needs_backend: false, timed_out: false, ...over,
})
const body = (over: Partial<WatchStatusWire> = {}, inputs = ['my_list', 'prospects', 'alerts', 'regime'].map(i => inp(i))): WatchStatusWire =>
  ({ schema: 'WatchStatus@v1', verdict: 'OK', cause: 'ok', computed_at: iso(10), session: 'RTH',
     required_inputs: ['my_list', 'prospects', 'alerts', 'regime'], inputs, ...over })
const ok = (data: WatchStatusWire): Read<WatchStatusWire> => ({ state: 'OK', data, error: null, at: iso(10), source: '/api/v2/watch/status' })

console.log('watchV002 chip')
check('4 fresh inputs and a fresh read = OK with age', (() => { const m = buildWatchStatus(ok(body()), NOW); return m.chip.state === 'OK' && m.chip.tone === 'ok' && /oldest input 1 m/.test(m.chip.text) && m.gates.length === 4 })())
check('no read = LOADING, never OK', buildWatchStatus(undefined, NOW).chip.state === 'LOADING')
check('timeout = TIMED OUT, never OK', buildWatchStatus({ state: 'TIMED OUT', data: null, error: 'timed out after 30s', at: null, source: 'x' }, NOW).chip.state === 'TIMED OUT')
check('failed read = UNKNOWN', buildWatchStatus({ state: 'ERROR' as never, data: null, error: 'HTTP 503', at: null, source: 'x' }, NOW).chip.state === 'UNKNOWN')
check('wrong schema = UNKNOWN', buildWatchStatus(ok(body({ schema: 'Other@v9' })), NOW).chip.state === 'UNKNOWN')
check('empty inputs = UNKNOWN', buildWatchStatus(ok(body({}, [])), NOW).chip.state === 'UNKNOWN')
check('server says OK but one input is past its threshold = STALE (re-graded here)', (() => {
  const m = buildWatchStatus(ok(body({}, [inp('my_list', { as_of: iso(4000), age_s: 60 }), inp('prospects'), inp('alerts'), inp('regime')])), NOW)
  return m.chip.state === 'STALE' && m.blockers.length === 1 && m.blockers[0].id === 'my_list' && /my_list: STALE/.test(m.cause)
})())
check('an input with state OK and no as_of is UNKNOWN, not OK', gradeInput(inp('alerts', { as_of: null }), NOW).state === 'UNKNOWN')
check('an input with no threshold cannot be OK', gradeInput(inp('alerts', { threshold_s: null }), NOW).state === 'UNKNOWN')
check('a future as_of is UNKNOWN', gradeInput(inp('alerts', { as_of: iso(-3600) }), NOW).state === 'UNKNOWN')
check('timed_out input is TIMED OUT', gradeInput(inp('regime', { timed_out: true, state: 'UNKNOWN' }), NOW).state === 'TIMED OUT')
check('a required input missing from the body is UNKNOWN', (() => {
  const m = buildWatchStatus(ok(body({}, [inp('my_list'), inp('prospects'), inp('regime')])), NOW)
  return m.chip.state === 'UNKNOWN' && m.gates.some(g => g.id === 'alerts' && g.state === 'UNKNOWN')
})())
check('server verdict UNKNOWN beats four fresh inputs', buildWatchStatus(ok(body({ verdict: 'UNKNOWN' })), NOW).chip.state === 'UNKNOWN')
check('server verdict STALE beats four fresh inputs', buildWatchStatus(ok(body({ verdict: 'STALE' })), NOW).chip.state === 'STALE')
check('an unrecognised server verdict is not OK', buildWatchStatus(ok(body({ verdict: 'GREAT' })), NOW).chip.state === 'UNKNOWN')
check('computed_at older than 120s demotes a tab left open to STALE', buildWatchStatus(ok(body({ computed_at: iso(600) })), NOW).chip.state === 'STALE')
check('no computed_at = UNKNOWN', buildWatchStatus(ok(body({ computed_at: null })), NOW).chip.state === 'UNKNOWN')
check('future computed_at = UNKNOWN', buildWatchStatus(ok(body({ computed_at: iso(-3600) })), NOW).chip.state === 'UNKNOWN')
check('OK is never worse-to-better: OK only when every gate is OK', (() => {
  const m = buildWatchStatus(ok(body()), NOW); return m.gates.every(g => g.state === 'OK') && m.blockers.length === 0
})())

check('chip age is the oldest input, not the read', buildWatchStatus(ok(body({}, [inp('my_list', { as_of: iso(7200) }), ...['prospects', 'alerts', 'regime'].map(i => inp(i))])), NOW).chip.text.includes('oldest input 2 h'))

console.log('watchV002 diagnostics')
check('diagnostics carry source, owner, observed time, threshold and failure per input', (() => {
  const m = buildWatchStatus(ok(body({}, [inp('my_list', { as_of: iso(4000), reason: null }), inp('prospects'), inp('alerts'), inp('regime')])), NOW)
  const d = watchDiagnostics(m); const r = d.find(x => /my_list/.test(x.widget))!
  return d.length === 4 && /own_my_list/.test(r.widget) && r.source === 'src_my_list' && /observed/.test(r.age) && r.threshold !== '—' && r.status === 'STALE' && r.failureMode !== 'none'
})())
check('a failed read yields no diagnostics rows to paint green', watchDiagnostics(buildWatchStatus(undefined, NOW)).length === 0)

console.log(`\n${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
