// Plans page model: the read-only registry view, in the operator's words.
// Runs in the CC-v3 build: node --experimental-strip-types src/lib/plansModel.test.ts
import {claimHref, pickedUp, planFrom, plansFrom, prUrl, statusWord, stepSummary} from './plansModel.ts'
declare const process: {exit(code?: number): never}
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
let n = 0
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`); n += 1
}
const ok = (cond: boolean, m: string) => { if (!cond) fail(m); n += 1 }

const row = {
  id: '20261102-demo-ab12cd34', title: 'Demo', status: 'in_progress', vendor: 'claude',
  approved_at: '2026-11-02T10:00:00Z', steps_done: 2, steps_left: 1, claim: 'C1', pr: 42,
}

eq(plansFrom({schema: 'PlanRegistryView@v1', plans: [row]}).length, 1, 'valid view lists')
eq(plansFrom({schema: 'Other@v1', plans: [row]}), [], 'wrong schema lists nothing')
eq(plansFrom(null), [], 'no view lists nothing')
eq(plansFrom({schema: 'PlanRegistryView@v1', plans: [
  {...row, id: 'old', approved_at: '2026-11-01T00:00:00Z'},
  {...row, id: 'new', approved_at: '2026-11-02T00:00:00Z'},
]}).map(p => p.id), ['new', 'old'], 'newest first')

eq(stepSummary(row), '2 of 3 steps done · 1 left', 'step words')
eq(stepSummary({id: 'x'}), 'no steps listed', 'no steps')
ok(statusWord('stalled').includes('no activity'), 'stalled is described')
eq(statusWord('weird'), 'Unknown', 'unknown status')

eq(prUrl(row), 'https://github.com/PatsKiller/tardeai/pull/42', 'pr url')
eq(prUrl({id: 'x'}), null, 'no pr')
eq(claimHref(row), '/coordination', 'claim link')
eq(claimHref({id: 'x'}), null, 'no claim')

eq(planFrom({schema: 'PlanRegistryView@v1', plan: row})?.id, row.id, 'detail plan')
eq(planFrom({schema: 'Other@v1', plan: row}), null, 'detail wrong schema')

// A linked plan keeps status "approved" (the registry's link() does not move it), so ownership must come
// from the links, not the status word.
ok(pickedUp({...row, status: 'approved'}), 'a linked plan is picked up')
ok(!pickedUp({...row, claim: undefined, branch: undefined, pr: undefined}), 'an unlinked plan is not picked up')
eq(statusWord('approved', {...row, status: 'approved'}), 'Approved · picked up', 'linked approved reads picked up')
eq(statusWord('approved', {...row, status: 'approved', claim: undefined, branch: undefined, pr: undefined}),
   'Approved — nobody has picked it up', 'unlinked approved keeps the warning')
eq(statusWord('approved'), 'Approved — nobody has picked it up', 'status-only call is unchanged')

console.log(`plansModel: ${n} checks passed`)
