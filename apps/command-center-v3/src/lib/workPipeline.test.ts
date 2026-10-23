// Coordination → Work pipeline model: URL filters, presets, summary strip, Queued section, card actions, commands body.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/workPipeline.test.ts
import {
  EMPTY_FILTER, PIPELINE_STAGES, ageLabel, cardActions, cellTitle, commandsToCopy, filterFromParams, filterItems, filterOptions,
  filterToParams, isReadyWp, liveToday, needsEvidence, nextUp, planLabel, queuedSections, ragTone, summarize, wpNumber, wpOptions,
  type PipelineItem, type WpBlock,
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
  eq(f, { preset: 'needs-me', stage: 'ci', rag: 'red', owner: 'operator', vendor: 'claude', design: 'DSN-x', batch: '2018', wp: '', q: 'shard', finished: true })
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

// Work-package structure (operator 2026-10-23): WP id/stage filter, Next up per owner, copy helpers.
function wpItem(id: string, owner: WpBlock['owner_kind'], extra: Partial<WpBlock> = {}, p: Partial<PipelineItem> = {}): PipelineItem {
  const tid = `DSN-20261023-handoff-v3-P2-T${id.slice(3)}`
  return item({
    id: tid, kind: 'task', stage: 'queued', rag: 'amber', what: { title: `${id} title`, task_id: tid, wp_id: id, stage: 'Stage 2' },
    wp: { wp_id: id, stage: 'Stage 2', owner_kind: owner, sections: ['problem', 'proof'], depends_on: [], blocked_by: [], status: 'free', wp_status: 'not_started', ...extra },
    ...p,
  })
}
const WPS = [
  wpItem('WP-05', 'OPERATOR'),
  wpItem('WP-04', 'OPERATOR', { blocked_by: ['DSN-x'] }),
  wpItem('WP-07', 'AGENT', { blocked_by: ['DSN-y'] }),
  wpItem('WP-06', 'AGENT', { wp_status: 'in_progress' }),
  wpItem('WP-08', 'BOTH'),
  wpItem('WP-03', 'AGENT', { wp_status: 'done', status: 'done' }, { finished: true }),
  wpItem('WP-12', 'AGENT', { stage: 'Stage 3', sections: [] }),
]

t('wp filter: URL round trip, stage and WP id, junk ignored', () => {
  eq(filterFromParams(new URLSearchParams('wp=Stage%202')).wp, 'Stage 2')
  eq(filterFromParams(new URLSearchParams('wp=WP-07')).wp, 'WP-07')
  eq(filterFromParams(new URLSearchParams('wp=DROP%20TABLE')).wp, '')
  eq(filterToParams({ ...EMPTY_FILTER, wp: 'WP-07' }, new URLSearchParams('tab=x')).toString(), 'tab=x&wp=WP-07')
  eq(filterItems(WPS, { ...EMPTY_FILTER, wp: 'Stage 3' }, NOW).map(i => i.wp?.wp_id), ['WP-12'])
  eq(filterItems(WPS, { ...EMPTY_FILTER, wp: 'WP-05' }, NOW).map(i => i.wp?.wp_id), ['WP-05'])
  eq(filterItems([...ITEMS, ...WPS], { ...EMPTY_FILTER, q: 'wp-08' }, NOW).map(i => i.wp?.wp_id), ['WP-08'])
})

t('next up: first ready WP per owner in plan order; blocked and done excluded', () => {
  eq(wpNumber('WP-07'), 7); eq(wpNumber('x') > 1000, true)
  eq(isReadyWp(WPS[1]), false); eq(isReadyWp(WPS[5]), false); eq(isReadyWp(ITEMS[4]), false)
  const up = nextUp([...ITEMS, ...WPS])
  eq(up.map(g => [g.owner, g.first.wp?.wp_id, g.rest.map(r => r.wp?.wp_id)]), [
    ['AGENT', 'WP-06', ['WP-12']], ['OPERATOR', 'WP-05', []], ['BOTH', 'WP-08', []],
  ])
  eq(filterItems([...ITEMS, ...WPS], { ...EMPTY_FILTER, preset: 'next-up' }, NOW).map(i => i.wp?.wp_id).sort(), ['WP-05', 'WP-06', 'WP-08', 'WP-12'])
})

t('wp options: imported stages first, then stages seen on tasks; WPs in plan order', () => {
  const o = wpOptions(WPS, [{ stage: 'Stage 2', title: 'Release train' }])
  eq(o.stages.map(s => s.stage), ['Stage 2', 'Stage 3'])
  eq(o.wps.map(w => w.id), ['WP-03', 'WP-04', 'WP-05', 'WP-06', 'WP-07', 'WP-08', 'WP-12'])
})

t('operator WPs land in the operator to-dos; evidence needed when a proof exists', () => {
  const q = queuedSections(WPS)
  eq(q.operator.map(i => i.wp?.wp_id), ['WP-05', 'WP-04'])
  eq(needsEvidence(WPS[0]), true); eq(needsEvidence(WPS[6]), false); eq(needsEvidence(ITEMS[0]), false)
})

t('copy commands: fenced code bodies, else the text', () => {
  eq(commandsToCopy('(only if no grant)\n```\nbin/guard grant x\n```\nthen\n```bash\ngh pr merge 1\n```'), 'bin/guard grant x\ngh pr merge 1')
  eq(commandsToCopy('  `gh pr merge 1991 --merge`, then release.  '), '`gh pr merge 1991 --merge`, then release.')
  eq(commandsToCopy(null), '')
})

console.log(`workPipeline: ${n} passed`)
