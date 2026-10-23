// Coordination → Who's working: claim lifecycle grouping, filters, CI/PR/lock labels, timeline.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/agentClaimLifecycle.test.ts
import {
  STAGES, ageLabel, ciView, filterCards, groupByStage, isFinished, lockView, prLabel, stageCounts, stageOf, timeline,
  vendorsOf, warningOf, type ClaimCard,
} from './agentClaimLifecycle.ts'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as opsControls.test.ts).
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
const ok = (c: unknown, m: string) => { if (!c) fail(m) }
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const base = (o: Partial<ClaimCard>): ClaimCard => ({ claim_id: o.claim_id || 'x', state: 'live', status: 'active', ...o })
const CARDS: ClaimCard[] = [
  base({ claim_id: 'a', vendor: 'claude', stage: 'claimed', started_at: '2026-10-23T13:00:00Z', locks_held: true }),
  base({ claim_id: 'b', vendor: 'codex', stage: 'building', stages: { claimed: '2026-10-23T12:00:00Z', building: '2026-10-23T12:10:00Z' }, locks_held: true }),
  base({ claim_id: 'c', vendor: 'claude', stage: 'pr_open', pr_number: 1990, pr_state: 'open', ci: { state: 'failing', failing: ['ci-gate'], basis: 'required', required: ['ci-gate'], head_sha: 'abcdef1234567' }, locks_held: true, stale_warning: 'CI failing: ci-gate' }),
  base({ claim_id: 'd', vendor: 'cursor', stage: 'ci_green', pr_number: 1991, pr_state: 'open', ci: { state: 'green', basis: 'required', required: ['ci-gate'] }, locks_held: true }),
  base({ claim_id: 'e', vendor: 'claude', stage: 'merged', pr_number: 1977, pr_state: 'merged', locks_held: false, stages: { claimed: '2026-10-22T20:00:00Z', merged: '2026-10-23T12:54:22Z' } }),
  base({ claim_id: 'f', vendor: 'codex', state: 'done', status: 'done', stage: 'released', pr_number: 1900, pr_state: 'merged', locks_held: false }),
  base({ claim_id: 'g', vendor: 'claude', state: 'abandoned', status: 'abandoned', stage: 'abandoned', locks_held: false }),
  base({ claim_id: 'h', vendor: 'claude', state: 'done', status: 'done', stage: 'building', locks_held: false }),
]

t('every stage is a kanban column, cards land in their stage', () => {
  const g = groupByStage(CARDS)
  eq(Object.keys(g), STAGES)
  eq(g.pr_open.map(c => c.claim_id), ['c'])
  eq(g.building.map(c => c.claim_id).sort(), ['b', 'h'])
  eq(stageCounts(CARDS).released, 1)
})

t('older server without lifecycle fields: stage derived from status + PR', () => {
  eq(stageOf(base({ pr: '12' })), 'pr_open')
  eq(stageOf(base({})), 'claimed')
  eq(stageOf(base({ state: 'abandoned', status: 'abandoned' })), 'abandoned')
})

t('finished = released, abandoned, or done with no PR in flight', () => {
  eq(CARDS.filter(isFinished).map(c => c.claim_id), ['f', 'g', 'h'])
  eq(filterCards(CARDS, {}).map(c => c.claim_id), ['a', 'b', 'c', 'd', 'e'])
  eq(filterCards(CARDS, { showFinished: true }).length, CARDS.length)
})

t('filters by vendor and by stage (a stage filter shows finished cards of that stage)', () => {
  eq(filterCards(CARDS, { vendor: 'codex' }).map(c => c.claim_id), ['b'])
  eq(filterCards(CARDS, { stage: 'released' }).map(c => c.claim_id), ['f'])
  eq(filterCards(CARDS, { vendor: 'claude', stage: 'merged' }).map(c => c.claim_id), ['e'])
  eq(vendorsOf(CARDS), ['claude', 'codex', 'cursor'])
})

t('CI label, tone and tooltip', () => {
  const c = ciView(CARDS[2])
  eq([c.label, c.tone], ['CI failing', 'danger'])
  ok(c.title.includes('ci-gate') && c.title.includes('abcdef123'), 'failing tooltip names the check and head')
  eq(ciView(CARDS[3]).label, 'CI green')
  eq(ciView(CARDS[4]).label, 'merged')
  eq(ciView(CARDS[0]).label, 'no PR')
  eq(ciView(base({ pr: '5' })).label, 'CI —')
})

t('PR label', () => {
  eq(prLabel(CARDS[2]), '#1990')
  eq(prLabel(CARDS[4]), '#1977 merged')
  eq(prLabel(base({ pr: 'PR 77' })), '#77')
  eq(prLabel(CARDS[0]), '—')
})

t('lock state: held, free after merge, stale not protected', () => {
  eq(lockView(CARDS[0]).label, 'files held')
  eq(lockView(CARDS[4]).label, 'files free')
  ok(lockView(CARDS[4]).title.includes('merged'), 'merge tooltip')
  eq(lockView(base({ state: 'stale', locks_held: true })).label, 'not protected')
})

t('timeline lists reached stages in order with times', () => {
  eq(timeline(CARDS[1]).map(x => x.stage), ['claimed', 'building'])
  eq(timeline(CARDS[0]), [{ stage: 'claimed', at: '2026-10-23T13:00:00Z' }])
  eq(timeline(CARDS[4]).map(x => x.stage), ['claimed', 'merged'])
})

t('age and warning', () => {
  eq(ageLabel(30), '30m'); eq(ageLabel(150), '2.5h'); eq(ageLabel(4000), '3d'); eq(ageLabel(null), '—'); eq(ageLabel(-5), '—')
  eq(warningOf(CARDS[2]), 'CI failing: ci-gate')
  eq(warningOf(CARDS[0]), null)
  eq(warningOf(base({ warnings: ['stale: no heartbeat'] })), 'stale: no heartbeat')
})

console.log(`agentClaimLifecycle: ${n} passed`)
