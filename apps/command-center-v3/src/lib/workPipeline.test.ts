// Coordination → Work pipeline model: URL filters, presets, summary strip, Queued section, card actions, commands body.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/workPipeline.test.ts
import {
  EMPTY_FILTER, PIPELINE_STAGES, ageLabel, cardActions, cellTitle, filterFromParams, filterItems, filterOptions, filterToParams,
  liveToday, planLabel, queuedSections, ragTone, summarize, type PipelineItem,
} from './workPipeline.ts'
import { COMMANDS_PATH, commandBody, parseSplitParts } from './workPipelineActions.ts'
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const NOW = new Date('2026-10-23T17:30:00Z')
function cells(stage: PipelineItem['stage'], rag: PipelineItem['rag'], label = '') {
  const i = PIPELINE_STAGES.indexOf(stage)
  return PIPELINE_STAGES.map((s, j) => ({ stage: s, rag: j < i ? 'green' as const : j === i ? rag : 'grey' as const, label: j === i ? label : j < i ? 'done' : '', at: j <= i ? '2026-10-23T16:06:35Z' : null }))
}
function item(p: Partial<PipelineItem> & { id: string; stage: PipelineItem['stage']; rag: PipelineItem['rag'] }): PipelineItem {
  return {
    kind: 'pr', label: '', cells: cells(p.stage, p.rag, p.label), next: { owner: 'agent', text: 'Agent: x' },
    who: { kind: 'agent', label: 'claude/x', vendor: 'claude' }, what: { title: p.id }, when: {}, where: { file_count: 0, files: [] }, how: {},
    ...p,
  } as PipelineItem
}
const ITEMS: PipelineItem[] = [
  item({ id: 'PR-2018', stage: 'ci', rag: 'red', label: '2 fail', is_batch: true, batch: 2018, next: { owner: 'agent', text: 'Agent: fix shard 5' } }),
  item({ id: 'PR-1997', stage: 'in_batch', rag: 'amber', label: 'operator merge', next: { owner: 'operator', text: 'Operator: merge #1997', command: 'gh pr merge 1997 --merge --match-head-commit d23a244' }, actions: { available: ['note', 'hold'], stale_claims: [] } }),
  item({ id: 'PR-2005', stage: 'in_batch', rag: 'amber', label: 'waiting for batch', waiting_for_batch: true, pr_number: 2005, what: { title: 'Ask CIO P9', design_id: 'DSN-20261023-ask-the-cio' }, actions: { available: ['note', 'hold', 'batch_add'], stale_claims: [] } }),
  item({ id: 'PR-2012', stage: 'in_batch', rag: 'amber', label: '#2018', batch: 2018, where: { file_count: 2, files: ['scripts/lib/request_coalesce.py', 'scripts/portfolio_server.py'] } }),
  item({ id: 'T-20261023-fc7872', kind: 'task', stage: 'queued', rag: 'amber', what: { title: 'Server memory kills', task_id: 'T-20261023-fc7872', priority: 1, kind: 'fix' }, who: { kind: 'none', label: 'nobody yet' } }),
  item({ id: 'T-20261023-73f31d', kind: 'task', stage: 'queued', rag: 'amber', what: { title: 'OPERATOR: run hotlist-budget-operator.sh', task_id: 'T-20261023-73f31d', priority: 2 }, next: { owner: 'operator', text: 'Operator: run hotlist-budget-operator.sh' }, who: { kind: 'operator', label: 'OPERATOR', vendor: 'operator' } }),
  item({ id: 'DSN-20261023-agent-ops-P1-T4', kind: 'task', stage: 'queued', rag: 'red', what: { title: 'Register policy packages', task_id: 'DSN-20261023-agent-ops-P1-T4', priority: 2 }, blocker: 'waits for DSN-20261023-agent-ops-P1-T2' }),
  item({ id: '20261023T134423Z-claude-7dfcb325', kind: 'claim', stage: 'claimed', rag: 'red', label: 'stale', stale: true, actions: { available: ['note', 'release_stale_claim'], stale_claims: ['20261023T134423Z-claude-7dfcb325'] } }),
  item({ id: 'PR-2002', stage: 'verified', rag: 'green', label: 'live', finished: true, when: { stage_since: '2026-10-23T16:06:35Z' } }),
  item({ id: 'PR-1900', stage: 'verified', rag: 'green', label: 'live', finished: true, cells: cells('verified', 'green').map(c => ({ ...c, at: '2026-10-20T16:00:00Z' })), when: { stage_since: '2026-10-20T16:00:00Z' } }),
]

t('URL params round-trip and unknown values are dropped', () => {
  const p = new URLSearchParams('tab=pipeline&preset=needs-me&stage=ci&rag=red&owner=operator&vendor=claude&design=DSN-x&batch=2018&q=shard&finished=1')
  const f = filterFromParams(p)
  eq(f, { preset: 'needs-me', stage: 'ci', rag: 'red', owner: 'operator', vendor: 'claude', design: 'DSN-x', batch: '2018', q: 'shard', finished: true })
  const back = filterToParams(f, new URLSearchParams('tab=pipeline'))
  eq(back.get('tab'), 'pipeline'); eq(back.get('rag'), 'red'); eq(back.get('finished'), '1')
  eq(filterFromParams(new URLSearchParams('preset=bogus&stage=nope&rag=purple&owner=x')), EMPTY_FILTER)
  const cleared = filterToParams(EMPTY_FILTER, back)
  eq([...cleared.keys()], ['tab'])
})

t('finished items hidden by default; toggle and Live today show them', () => {
  const ids = (f: Partial<typeof EMPTY_FILTER>) => filterItems(ITEMS, { ...EMPTY_FILTER, ...f }, NOW).map(i => i.id)
  eq(ids({}).includes('PR-2002'), false)
  eq(ids({ finished: true }).includes('PR-2002'), true)
  eq(ids({ preset: 'live-today' }), ['PR-2002'])
  eq(liveToday(ITEMS[ITEMS.length - 1], NOW), false)
})

t('presets: Needs me, Queued, Waiting for batch, Blocked/red', () => {
  const ids = (preset: typeof EMPTY_FILTER['preset']) => filterItems(ITEMS, { ...EMPTY_FILTER, preset }, NOW).map(i => i.id)
  eq(ids('needs-me'), ['PR-1997', 'T-20261023-73f31d'])
  eq(ids('queued'), ['T-20261023-fc7872', 'T-20261023-73f31d', 'DSN-20261023-agent-ops-P1-T4'])
  eq(ids('waiting-batch'), ['PR-2005'])
  eq(ids('red'), ['PR-2018', 'DSN-20261023-agent-ops-P1-T4', '20261023T134423Z-claude-7dfcb325'])
})

t('filters: stage, RAG, owner, vendor, design, batch, text (files too)', () => {
  const ids = (f: Partial<typeof EMPTY_FILTER>) => filterItems(ITEMS, { ...EMPTY_FILTER, ...f }, NOW).map(i => i.id)
  eq(ids({ stage: 'in_batch', batch: '2018' }), ['PR-2012'])
  eq(ids({ batch: 'none' }), ['PR-2005'])
  eq(ids({ design: 'DSN-20261023-ask-the-cio' }), ['PR-2005'])
  eq(ids({ vendor: 'operator' }), ['T-20261023-73f31d'])
  eq(ids({ q: 'request_coalesce' }), ['PR-2012'])
  eq(ids({ owner: 'operator', rag: 'amber' }), ['PR-1997', 'T-20261023-73f31d'])
  eq(filterOptions(ITEMS).batches, [2018])
})

t('summary strip: per-stage counts of unfinished items, red/amber, Needs me', () => {
  const s = summarize(ITEMS)
  eq(s.counts.in_batch, 3); eq(s.counts.queued, 3); eq(s.counts.verified, 0)
  eq([s.red, s.amber, s.needsMe, s.waitingForBatch, s.finished], [3, 5, 2, 1, 2])
})

t('Queued section: free tasks by priority, green PRs not batched, operator to-dos', () => {
  const q = queuedSections(ITEMS)
  eq(q.tasks.map(i => i.id), ['T-20261023-fc7872', 'DSN-20261023-agent-ops-P1-T4'])
  eq(q.green.map(i => i.id), ['PR-2005'])
  eq(q.operator.map(i => i.id), ['T-20261023-73f31d'])
})

t('card actions follow the server list; RAG tones; labels', () => {
  eq(cardActions(ITEMS[2]), ['note', 'hold', 'batch_add'])
  eq(cardActions(ITEMS[7]), ['note', 'release_stale_claim'])
  eq(cardActions(ITEMS[0]), [])
  eq([ragTone('green'), ragTone('amber'), ragTone('red'), ragTone('grey')], ['success', 'warning', 'danger', 'neutral'])
  eq([ageLabel(5), ageLabel(150), ageLabel(60 * 72), ageLabel(null)], ['5m', '2.5h', '3d', '—'])
  eq(planLabel({ ...ITEMS[0], how: { plan_done: 3, plan_total: 7 } }), '3/7')
  eq(cellTitle(ITEMS[0].cells[6]), 'CI: 2 fail · 2026-10-23T16:06:35Z')
})

t('commands: one endpoint, the actor is never in the body; split grammar', () => {
  eq(COMMANDS_PATH, '/api/v2/coordination/commands')
  const b = commandBody('hold', { item: 'PR-2005', reason: 'r' }, 'wp-key-1')
  eq(Object.keys(b).sort(), ['command', 'idempotency_key', 'params'])
  eq(JSON.stringify(b).includes('actor'), false)
  eq(parseSplitParts('half 1 | scripts/a.py, docs/a.md | tests; docs\n\nhalf 2'), [
    { title: 'half 1', areas: ['scripts/a.py', 'docs/a.md'], acceptance: ['tests', 'docs'] },
    { title: 'half 2', areas: [], acceptance: [] },
  ])
})

console.log(`workPipeline: ${n} passed`)
