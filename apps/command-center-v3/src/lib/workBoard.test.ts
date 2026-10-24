// Coordination → Work board model: stage grouping, filters, take command, design progress.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/workBoard.test.ts
import {
  WORK_STAGES, designProgress, filterWork, groupWork, holderLabel, phaseProgress, sourcesOf, statusTone, takeCommand,
  type Design, type WorkItem,
} from './workBoard.ts'
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const ITEMS: WorkItem[] = [
  { id: 'DSN-20261021-release-train-P5-T1', title: 'phase 5 dry run', source: 'design', stage: 'open', areas: ['scripts/release_train.py'] },
  { id: 'T-20261023-aaaaaa', title: 'fix chip', source: 'operator', stage: 'claimed', holder: 'codex:s1' },
  { id: '20261023T1-claude-x', title: 'claim only', source: 'claim', stage: 'in_progress', holder: 'claude:2e7e1d01' },
  { id: 'PR-1994', title: 'claim board', source: 'open PR', stage: 'in_review', holder: 'github:PatsKiller' },
  { id: 'T-2', source: 'agent', stage: 'live' },
  { id: 'T-3', source: 'agent', stage: 'weird' },
]

t('six stage columns; unknown stage lands in open', () => {
  const g = groupWork(ITEMS)
  eq(Object.keys(g), WORK_STAGES)
  eq(g.open.map(i => i.id), ['DSN-20261021-release-train-P5-T1', 'T-3'])
  eq(g.in_review[0].id, 'PR-1994')
})

t('filters: source, stage, holder prefix, text', () => {
  eq(filterWork(ITEMS, { source: 'operator' }).map(i => i.id), ['T-20261023-aaaaaa'])
  eq(filterWork(ITEMS, { stage: 'in_review' }).length, 1)
  eq(filterWork(ITEMS, { holder: 'claude' }).map(i => i.id), ['20261023T1-claude-x'])
  eq(filterWork(ITEMS, { text: 'release_train' }).length, 1)
  eq(sourcesOf(ITEMS), ['agent', 'claim', 'design', 'open PR', 'operator'])
})

t('take command only for open board tasks', () => {
  eq(takeCommand(ITEMS[0]), 'python3 scripts/agent_claim.py take DSN-20261021-release-train-P5-T1')
  eq(takeCommand(ITEMS[1]), null)
  eq(takeCommand({ id: 'PR-1', source: 'open PR', stage: 'open' }), null)
  eq(holderLabel(ITEMS[0]), 'nobody — take it')
})

t('design and phase progress, status tone', () => {
  const d: Design = { id: 'DSN-1', title: 'x', status: 'IN_PROGRESS', phases: [
    { id: 'DSN-1-P0', status: 'DONE', tasks: [{ id: 'a', status: 'DONE' }], tasks_done: 1, tasks_total: 1 },
    { id: 'DSN-1-P1', status: 'IN_PROGRESS', tasks: [{ id: 'b', status: 'IN_PROGRESS' }, { id: 'c', status: 'PROPOSED' }], tasks_done: 0, tasks_total: 2 },
    { id: 'DSN-1-P2', status: 'PROPOSED', tasks: [] },
  ] }
  eq(designProgress(d), { phases: '1/3 phases', tasks: '1/3 tasks' })
  eq(phaseProgress(d.phases[1]), '0/2 tasks')
  eq(phaseProgress(d.phases[2]), 'no tasks yet')
  eq([statusTone('PROPOSED'), statusTone('live'), statusTone('nope')], ['warning', 'success', 'neutral'])
})

console.log(`workBoard: ${n} passed`)
