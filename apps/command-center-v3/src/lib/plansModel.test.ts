// Plans page model: the read-only registry view, in the operator's words.
// Runs in the CC-v3 build: node --experimental-strip-types src/lib/plansModel.test.ts
import {claimHref, detailGap, openStepCount, pickedUp, planFrom, plansFrom, plansGap, prUrl, statusWord, stepSummary, waitingDecision, type PlanRow} from './plansModel.ts'
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
eq(plansFrom({schema: 'Other@v1', plans: [row]}), [], 'wrong schema lists no rows')
eq(plansFrom(null), [], 'no view lists no rows')
// A payload the page cannot parse is a gap, not an authoritative empty registry.
ok(plansGap({schema: 'Other@v1', plans: [row]}) !== null, 'wrong schema is a gap, not an empty registry')
ok(plansGap({}) !== null, 'missing schema is a gap')
eq(plansGap({ok: false, error: 'store down'}), 'store down', 'ok:false listing is a gap')
ok(plansGap({schema: 'PlanRegistryView@v1', plans: []}) === null, 'a valid empty listing is a known empty registry')
ok(plansGap({schema: 'PlanRegistryView@v1', plans: [row]}) === null, 'a valid listing has no gap')
ok(plansGap({schema: 'PlanRegistryView@v1'}) !== null, 'a missing plan list is a gap')
ok(plansGap(null) !== null, 'a missing response is a gap')
eq(plansFrom({schema: 'PlanRegistryView@v1', plans: [
  {...row, id: 'old', approved_at: '2026-11-01T00:00:00Z'},
  {...row, id: 'new', approved_at: '2026-11-02T00:00:00Z'},
]}).map(p => p.id), ['new', 'old'], 'newest first')

eq(stepSummary(row), '2 of 3 steps done · 1 left', 'step words (valid pair)')
eq(openStepCount({} as unknown as PlanRow), null, 'openStepCount never invents a zero')
eq(openStepCount({steps_left: '2'} as unknown as PlanRow), null, 'openStepCount rejects a string count')
eq(openStepCount({steps_left: 2} as unknown as PlanRow), 2, 'openStepCount keeps a valid count')
eq(stepSummary({id: 'x'}), 'no steps listed', 'no steps')
eq(stepSummary({id: 'x', status: 'unreadable'} as unknown as PlanRow), 'steps unknown', 'an unreadable plan never claims it listed no steps')

// The page must never invent progress. A count is usable only when it is a non-negative integer and
// the other count is present; anything else renders "steps unknown", never a derived total.
const steps = (done: unknown, left: unknown): string =>
  stepSummary({id: 'x', steps_done: done, steps_left: left} as unknown as PlanRow)
eq(steps(5, undefined), 'steps unknown', 'done only is unknown, never a fabricated 100%')
eq(steps(undefined, 2), 'steps unknown', 'left only is unknown, never a made-up done count')
eq(steps(-1, 3), 'steps unknown', 'negative done is unknown')
eq(steps(3, -1), 'steps unknown', 'negative left is unknown')
eq(steps('5', 2), 'steps unknown', 'string done is unknown')
eq(steps(2, '1'), 'steps unknown', 'string left is unknown')
eq(steps(1.5, 2), 'steps unknown', 'float done is unknown')
eq(steps(2, 1.5), 'steps unknown', 'float left is unknown')
eq(steps(Number.NaN, 2), 'steps unknown', 'NaN done is unknown')
eq(steps(0, 0), 'no steps listed', 'two zero counts are no steps listed')
eq(steps(0, 2), '0 of 2 steps done · 2 left', 'zero done with a left count is valid')
eq(steps(1, 0), '1 of 1 step done · 0 left', 'singular total is grammatically valid')
ok(statusWord('stalled').includes('no activity'), 'stalled is described')
eq(statusWord('weird'), 'Unknown', 'unknown status')

eq(prUrl(row), 'https://github.com/PatsKiller/tardeai/pull/42', 'pr url')
eq(prUrl({id: 'x'}), null, 'no pr')
eq(claimHref(row), '/coordination', 'claim link')
eq(claimHref({id: 'x'}), null, 'no claim')

eq(planFrom({schema: 'PlanRegistryView@v1', plan: row})?.id, row.id, 'detail plan')
eq(planFrom({schema: 'Other@v1', plan: row}), null, 'detail wrong schema')
// A detail `{ok:false}` is a gap (useApi leaves it in data), not a silent empty sheet.
ok(detailGap({schema: 'PlanRegistryView@v1', plan: row}, row.id) === null, 'a valid detail has no gap')
eq(detailGap({ok: false, error: 'plan not found'}, 'deleted-id'), 'plan not found', 'detail ok:false is a gap')
ok(detailGap({schema: 'PlanRegistryView@v1'}, 'gone') !== null, 'a detail without a plan is a gap')
ok(detailGap({schema: 'Other@v1', plan: row}, row.id) !== null, 'a detail with the wrong schema is a gap')
ok(detailGap(null, row.id) !== null, 'a detail with no response is a gap')

// The Decisions line must never assert an empty, healthy queue before the listing is known.
eq(waitingDecision(0, {loading: true, known: false}),
   'Waiting plans unknown — the plan registry is still loading.', 'loading says waiting is unknown')
ok(!waitingDecision(0, {loading: true, known: false}).includes('Nothing approved'),
   'loading never claims nothing is waiting')
ok(!waitingDecision(0, {loading: false, known: false}).includes('Nothing approved'),
   'an unreadable registry never claims nothing is waiting')
eq(waitingDecision(0, {loading: false, known: true}),
   'Nothing approved and unclaimed right now.', 'a known empty registry says nothing is waiting')
eq(waitingDecision(1, {loading: false, known: true}),
   '1 approved plan nobody has picked up yet.', 'a known waiting count is singular')
eq(waitingDecision(2, {loading: false, known: true}),
   '2 approved plans nobody has picked up yet.', 'a known waiting count is plural')

// A linked plan keeps status "approved" (the registry's link() does not move it), so ownership must come
// from the links, not the status word.
ok(pickedUp({...row, status: 'approved'}), 'a linked plan is picked up')
ok(!pickedUp({...row, claim: undefined, branch: undefined, pr: undefined}), 'an unlinked plan is not picked up')
eq(statusWord('approved', {...row, status: 'approved'}), 'Approved · picked up', 'linked approved reads picked up')
eq(statusWord('approved', {...row, status: 'approved', claim: undefined, branch: undefined, pr: undefined}),
   'Approved — nobody has picked it up', 'unlinked approved keeps the warning')
eq(statusWord('approved'), 'Approved — nobody has picked it up', 'status-only call is unchanged')

console.log(`plansModel: ${n} checks passed`)
