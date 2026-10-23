import { initialProbeState, onProbeResult, type ProbeAction } from './reconnectProbe.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}
function run(seq: boolean[]): ProbeAction[] {
  let s = initialProbeState(); const out: ProbeAction[] = []
  for (const ok of seq) { const r = onProbeResult(s, ok); s = r.state; out.push(r.action) }
  return out
}
// Server up, one endpoint failing: health OK twice → endpoint-only, never a global refetch.
const a = run([true, true])
check('health never failed → endpoint-only, no recover', a[1] === 'endpoint-only' && !a.includes('recover'))
check('one OK probe is not enough', run([true])[0] === 'continue')
// Real outage: health fails, then comes back twice → recover (global refetch).
const b = run([false, false, true, true])
check('outage then two OK → recover', b[3] === 'recover' && b.slice(0, 3).every(x => x === 'continue'))
check('flapping resets the OK streak', run([false, true, false, true])[3] === 'continue')
check('outage remembered across the streak', run([false, true, true])[2] === 'recover')
console.log(`reconnectProbe: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
