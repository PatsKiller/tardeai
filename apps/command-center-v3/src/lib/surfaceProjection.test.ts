// Pure-logic tests for surfaceProjection.ts.
//   node apps/command-center-v3/src/lib/surfaceProjection.test.ts
//
// Cases: populated, empty, partial, stale, malformed, disconnected, unauthorized,
// forbidden, error, missing-envelope, and the record-level conflict scope.
import {
  projectSurface,
  renderableCount,
  projectConflicts,
  isFieldUnverified,
} from './surfaceProjection.ts'

declare const process: { exit(code?: number): never; env: Record<string, string | undefined> }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const env = (state: string, reason = 'because') => ({
  state, state_reason: reason, schema: 'X@v1', authority: 'READ_ONLY', calculation_version: '1.0.0',
})

console.log('surfaceProjection: every state a surface can reach')

for (const s of ['POPULATED', 'LEGITIMATE_EMPTY', 'STALE', 'PARTIAL', 'DEGRADED']) {
  const p = projectSurface(env(s))
  check(`${s} is a measurement`, p.hasMeasurement && p.countsRenderable)
  check(`${s} carries its reason`, p.reason === 'because')
}

for (const s of ['DISCONNECTED', 'UNAUTHORIZED', 'FORBIDDEN', 'MALFORMED', 'ERROR', 'LOADING']) {
  const p = projectSurface(env(s))
  check(`${s} measured nothing`, !p.hasMeasurement)
  check(`${s} may not render a count`, !p.countsRenderable)
}

check('POPULATED shows no notice', projectSurface(env('POPULATED')).showNotice === false)
check('LEGITIMATE_EMPTY shows no notice', projectSurface(env('LEGITIMATE_EMPTY')).showNotice === false)
check('STALE shows a notice', projectSurface(env('STALE')).showNotice === true)
check('UNAUTHORIZED shows a notice', projectSurface(env('UNAUTHORIZED')).showNotice === true)

// A missing envelope is an error, not an empty surface.
const none = projectSurface(null)
check('a missing envelope is ERROR not empty', none.state === 'ERROR' && !none.countsRenderable)
check('a missing envelope explains itself', none.reason.length > 0)

console.log('surfaceProjection: a failed read never renders a number')
check('failed read yields null not 0', renderableCount(env('DISCONNECTED'), 0) === null)
check('failed read yields null for a real count', renderableCount(env('ERROR'), 42) === null)
check('a real empty renders 0', renderableCount(env('LEGITIMATE_EMPTY'), 0) === 0)
check('a populated count renders', renderableCount(env('POPULATED'), 7) === 7)
check('a non-numeric count is null', renderableCount(env('POPULATED'), undefined) === null)
check('NaN is not a count', renderableCount(env('POPULATED'), NaN) === null)

console.log('surfaceProjection: conflict scope is per record, never global')
const conflictEnv = {
  ...env('DEGRADED'),
  conflicts: [{
    store: 'tax_lots.json',
    record_key: 'SCHD:schwab_taxable',
    render_as: 'UNVERIFIED',
    blocks: ['cost_basis[SCHD:schwab_taxable]', 'holding_period[SCHD:schwab_taxable]'],
    both_originals_preserved: true,
  }],
}
const cp = projectConflicts(conflictEnv)
check('one unresolved record is counted', cp.unresolvedCount === 1)
check('the disputed field is named', isFieldUnverified(cp, 'tax_lots.json', 'SCHD:schwab_taxable'))
check('an unrelated record in the same store is untouched',
  !isFieldUnverified(cp, 'tax_lots.json', 'AAPL:schwab_taxable'))
check('an unrelated store is untouched', !isFieldUnverified(cp, 'stops.json', 'DIV:schwab_taxable'))
check('every blocked calculation names the record',
  cp.blockedCalculations.every((b) => b.includes('SCHD:schwab_taxable')))
check('nothing global is blocked',
  !cp.blockedCalculations.some((b) => b.toLowerCase().includes('watch') || b.toLowerCase().includes('closed_loop')))
check('both originals are preserved', cp.bothOriginalsPreserved === true)

const clean = projectConflicts({ ...env('LEGITIMATE_EMPTY'), conflicts: [] })
check('no conflicts blocks nothing', clean.unresolvedCount === 0 && clean.blockedCalculations.length === 0)
const missing = projectConflicts(null)
check('a missing conflict envelope blocks nothing but counts nothing', missing.unresolvedCount === 0)

console.log(`\nsurfaceProjection: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
