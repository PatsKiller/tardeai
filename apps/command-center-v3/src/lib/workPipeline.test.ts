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


// Source-bound current-flow projection; all new records below are synthetic.
import { FLOW_STAGES, flowProjection, waitingProjection } from './workPipelineFlow.ts'
const FLOW_NOW = new Date('2026-11-03T02:00:00Z'), FLOW_HEAD = 'a'.repeat(40), OTHER_HEAD = 'b'.repeat(40)
const CREATED = '2026-11-02T23:00:00Z', ENTERED = '2026-11-03T01:00:00Z'
function flowItem(extra: Record<string, unknown> = {}) {
  return { id: 'PR-9001', title: 'Synthetic work', stage: 'checks', owner: { session: 'fixture-session', vendor: 'fixture', coordinator: 'fixture-lead' },
    created_at: CREATED, last_touched: '2026-11-03T01:55:00Z', stage_since: ENTERED, head_sha: FLOW_HEAD,
    next: { actor: 'coordinator', text: 'Review current evidence', command: null }, checks: { head_sha: FLOW_HEAD, passed: 2, total: 3, failed_names: ['fixture-check'] },
    reviews: [{ reviewer: 'fixture-reviewer', verdict: 'MERGE', head_sha: FLOW_HEAD, at: ENTERED, source: 'fixture-ledger' }],
    stuck: { basis: 'stage' }, pr_number: 9001, pr_url: 'https://example.test/pull/9001', ...extra }
}
function flowEnvelope(items: unknown[], extra: Record<string, unknown> = {}) {
  return { schema: 'WorkPipeline@v1', as_of: FLOW_NOW.toISOString(), coordination: { complete: true, source_at: FLOW_NOW.toISOString(), items,
    stuck_after_minutes: 45, approvals: { complete: true, as_of: FLOW_NOW.toISOString(), items: [] }, agents: [], ...extra } }
}
const flowN = n

t('nine current stages and an explicit coordinator actor share one in-flight grouping', () => {
  eq(FLOW_STAGES, ['requested', 'building', 'uploaded', 'pr_open', 'checks', 'review', 'approval', 'merged', 'live'])
  const p = flowProjection(flowEnvelope([flowItem()]), FLOW_NOW)
  eq(p.items[0].next.actor, 'coordinator'); eq(p.items[0].owner.coordinator, 'fixture-lead')
  eq([p.items[0].ageMinutes, p.items[0].stageAgeMinutes, p.items[0].stuck], [180, 60, true])
  eq(p.inFlight.map(x => x.id), p.groups.flatMap(g => g.items.map(x => x.id)))
})
t('only valid full aware instants can date a current item', () => {
  eq(flowProjection(flowEnvelope([flowItem({ created_at: '2026-11-02T18:00:00-05:00' })]), FLOW_NOW).items[0].createdAt, '2026-11-02T23:00:00.000Z')
  for (const bad of ['2026-11-02', '2026-11-02 23:00:00', '2026-11-04T00:00:00Z', '2026-02-30T23:00:00Z', '2026-11-02T24:00:00Z']) {
    const it = flowProjection(flowEnvelope([flowItem({ created_at: bad })]), FLOW_NOW).items[0]
    eq(it.createdAt, null); eq(it.ageMinutes, null); eq(it.gaps.some(g => g.startsWith('Created:')), true)
  }
})
t('explicit null clocks do not borrow timing or API capture fields', () => {
  const p = flowProjection(flowEnvelope([flowItem({ created_at: null, last_touched: null, stage_since: null, when: { created_at: CREATED, last_activity: CREATED, stage_since: CREATED } })], { source_at: null, observed_at: CREATED }), FLOW_NOW)
  eq([p.items[0].createdAt, p.items[0].touchedAt, p.items[0].stageSince, p.sourceAt], [null, null, null, null])
  eq(flowProjection({ items: [], as_of: CREATED }, FLOW_NOW).sourceAt, null)
})
t('mismatched or unbound reviews and checks never become current-head proof', () => {
  const it = flowProjection(flowEnvelope([flowItem({ checks: { head_sha: OTHER_HEAD, passed: 3, total: 3 }, reviews: [{ reviewer: 'old', verdict: 'MERGE', head_sha: OTHER_HEAD }] })]), FLOW_NOW).items[0]
  eq([it.checks.passed, it.checks.total, it.reviews[0].currentHead], [null, null, false])
  const unbound = flowProjection(flowEnvelope([flowItem({ reviews: [{ reviewer: 'unbound', verdict: 'MERGE', current_head: true }] })]), FLOW_NOW).items[0]
  eq(unbound.reviews[0].currentHead, null)
})
t('required check and review counts are source-owned, never assumed', () => {
  const it = flowProjection(flowEnvelope([flowItem({ checks: { head_sha: FLOW_HEAD, state: 'GREEN' }, reviews: { required_count: 2, items: [] } })]), FLOW_NOW).items[0]
  eq([it.checks.passed, it.checks.total, it.reviewRequired], [null, null, 2])
})
t('old batch and task-complete stages remain readable without claiming Review or Live', () => {
  const a = item({ id: 'old-batch', stage: 'in_batch', rag: 'green' }), b = item({ id: 'done-task', kind: 'task', stage: 'verified', rag: 'green', finished: true })
  const p = flowProjection({ items: [a, b], as_of: CREATED }, FLOW_NOW)
  eq(p.items.map(x => x.stage), [null, null]); eq(p.inFlight.length, 2); eq(p.metrics.inFlight, null); eq(p.metrics.liveToday, null)
  eq(p.items[0].events.some(e => e.label.startsWith('Legacy ')), true)
})
t('old holds and next-owner operator labels never populate the canonical waiting queue', () => {
  const old = item({ id: 'old-held', stage: 'approved', rag: 'amber', next: { owner: 'operator', text: 'Unhold', command: 'legacy-command' } })
  const p = flowProjection({ items: [old], summary: { needs_me: 99 } }, FLOW_NOW)
  eq(p.items[0].stage, 'requested'); eq(p.items[0].next.actor, 'unknown'); eq(p.waiting, null); eq(p.metrics.waiting, null)
})
t('unproven Live stays unresolved; proven Live is retired by the shared membership projection', () => {
  const unknown = flowProjection(flowEnvelope([flowItem({ stage: 'live' })]), FLOW_NOW)
  eq(unknown.items[0].stage, null); eq(unknown.inFlight.length, 1); eq(unknown.metrics.liveToday, null)
  const live = flowItem({ stage: 'live', merged_at: '2026-11-03T00:30:00Z', live: { served: true, verified: true, source: 'fixture-receipt', at: '2026-11-03T01:30:00Z' }, checks: { head_sha: FLOW_HEAD, passed: 3, total: 3, green_at: ENTERED } })
  const p = flowProjection(flowEnvelope([live, flowItem({ id: 'inactive', in_flight: false })]), FLOW_NOW)
  eq(p.inFlight.length, 0); eq([p.metrics.inFlight, p.metrics.liveToday, p.metrics.mergedToday, p.metrics.greenToLiveMinutes], [0, 1, 1, 30])
})
t('missing green time never fabricates zero green-to-live latency', () => {
  const p = flowProjection(flowEnvelope([flowItem({ stage: 'live', merged_at: ENTERED, live: { served: true, verified: true, source: 'fixture-receipt', at: '2026-11-03T01:30:00Z' } })]), FLOW_NOW)
  eq(p.metrics.greenToLiveMinutes, null)
})
t('missing, partial and failed collection sources never produce healthy zero metrics', () => {
  for (const raw of [null, flowEnvelope([], { complete: false }), { ...flowEnvelope([]), sources: { census: { warning: 'synthetic census unavailable' } } }]) {
    const p = flowProjection(raw, FLOW_NOW)
    eq([p.metrics.inFlight, p.metrics.mergedToday, p.metrics.liveToday, p.metrics.idleAgentMinutes], [null, null, null, null]); eq(p.gaps.length > 0, true)
  }
})
t('a complete empty source can report measured zeros', () => {
  const p = flowProjection(flowEnvelope([]), FLOW_NOW)
  eq([p.metrics.inFlight, p.metrics.stuck, p.metrics.mergedToday, p.metrics.liveToday, p.metrics.waiting, p.metrics.idleAgentMinutes], [0, 0, 0, 0, 0, 0])
})
t('malformed returned members yield a named gap rather than empty healthy totals', () => {
  const p = flowProjection(flowEnvelope([null, 'bad-member']), FLOW_NOW)
  eq(p.metrics.inFlight, null); eq(p.metrics.mergedToday, null); eq(p.gaps.some(g => g.includes('malformed member')), true)
})
t('canonical waiting members drive counts with partial and conflicting-source refusals', () => {
  const member = { id: 'canonical-action', title: 'Synthetic decision', source: 'fixture-approval-queue', as_of: CREATED, head_sha: FLOW_HEAD }
  const p = flowProjection(flowEnvelope([], { approvals: { complete: true, as_of: ENTERED, actionable_items: [member, member] } }), FLOW_NOW)
  eq(p.metrics.waiting, 1); eq(p.waiting?.map(x => x.id), ['canonical-action'])
  const partial = flowProjection(flowEnvelope([], { approvals: { complete: false, as_of: ENTERED, actionable_items: [member] } }), FLOW_NOW)
  eq(partial.waiting?.length, 1); eq(partial.metrics.waiting, null)
  const conflict = flowProjection(flowEnvelope([], { approvals: { complete: true, as_of: ENTERED, actionable_items: [member, { ...member, head_sha: OTHER_HEAD }] } }), FLOW_NOW)
  eq(conflict.metrics.waiting, null); eq(conflict.waiting?.length, 0)
})
t('agent idle uses its own activity clock and unknown nudge counts stay unknown', () => {
  const agent = { session: 'fixture-session', last_activity: '2026-11-03T01:45:00Z', nudges_today: 3 }
  const p = flowProjection(flowEnvelope([], { agents: [agent] }), FLOW_NOW)
  eq([p.agents[0].idleMinutes, p.agents[0].nudgesToday, p.metrics.idleAgentMinutes], [15, 3, 15])
  const future = flowProjection(flowEnvelope([], { agents: [{ ...agent, last_activity: '2026-11-04T00:00:00Z', nudges_today: null }] }), FLOW_NOW)
  eq([future.agents[0].idleMinutes, future.agents[0].nudgesToday, future.metrics.idleAgentMinutes], [null, null, null])
})
t('claim stale labels do not invent a configured stuck verdict', () => {
  const p = flowProjection(flowEnvelope([flowItem({ stale: true, stuck: undefined })], { stuck_after_minutes: undefined }), FLOW_NOW)
  eq(p.items[0].stuck, null); eq(p.metrics.stuck, null)
})
function aSourcePayload(extra: Record<string, unknown> = {}, bundleExtra: Record<string, unknown> = {}) {
  const fact = (value: unknown, source = 'claim_board') => ({ value, source, as_of: ENTERED, gap: null })
  const bundle = { owner: fact({ session: 'a-session', vendor: 'fixture', coordinator: 'a-lead' }), coordinator: fact('a-lead'), last_activity: fact('2026-11-03T01:45:00Z'), next_action: fact('Read current proof', 'claim_worklog'),
    ci: { state: 'GREEN', head_sha: FLOW_HEAD, as_of: ENTERED, source: 'fixture-ci', workflows: [], gap: null },
    review: { head_sha: FLOW_HEAD, state: 'MERGE', evidence_class: 'reported_review_not_approval', source: 'coordinator_ledger', gap: null, records: [{ reviewer_session: 'a-reviewer', verdict: 'MERGE', observed_at: ENTERED }] },
    live: fact(false, 'served_release+deploy_receipt'), timeline: [{ kind: 'pr_open', as_of: CREATED, source: 'github_census', source_ref: 'github_pr:9001', head_sha: FLOW_HEAD }], ...bundleExtra }
  const sources = Object.fromEntries(['claims', 'coordinator_ledger', 'digest_approvals', 'plans', 'releases'].map(k => [k, { source: k, as_of: ENTERED, gap: null }]))
  return { schema: 'WorkPipeline@v1', as_of: FLOW_NOW.toISOString(), items: [{ ...item({ id: 'PR-9001', stage: 'pr_open', rag: 'amber', pr_number: 9001 }), in_flight: true, coordination: bundle }], sources: { census: { refreshed_at: ENTERED, warning: null } },
    coordination: { schema: 'WorkPipelineSources@v1', as_of: ENTERED, captured_at: FLOW_NOW.toISOString(), sources, gaps: [], claims: [], active_claim_ids: [], ...extra } }
}
t('actual A fact envelopes work without a guessed coordination.items collection', () => {
  const p = flowProjection(aSourcePayload(), FLOW_NOW), it = p.items[0]
  eq(it.owner, { session: 'a-session', vendor: 'fixture', coordinator: 'a-lead' }); eq(it.touchedAt, '2026-11-03T01:45:00.000Z')
  eq([it.stage, it.createdAt, it.stageSince], ['pr_open', '2026-11-02T23:00:00.000Z', null]); eq(it.next.actor, 'unknown'); eq(it.next.text, 'Read current proof')
  eq(it.reviews[0].currentHead, true); eq(it.checks.total, null); eq(p.sourceAt, '2026-11-03T01:00:00.000Z'); eq(p.metrics.inFlight, 1)
})
t('A explicit inactive membership is honored without inventing Live status', () => {
  const raw = aSourcePayload(); raw.items[0].in_flight = false; const p = flowProjection(raw, FLOW_NOW)
  eq(p.inFlight.length, 0); eq(p.metrics.inFlight, 0)
})
t('A verified live fact keeps its own source clock rather than capture time', () => {
  const p = flowProjection(aSourcePayload({}, { live: { value: true, source: 'served_release+deploy_receipt', as_of: '2026-11-03T01:30:00Z', gap: null } }), FLOW_NOW)
  eq([p.items[0].stage, p.items[0].liveAt, p.inFlight.length], ['live', '2026-11-03T01:30:00.000Z', 0])
})
t('A missing source remains named and makes collection counters unknown', () => {
  const raw = aSourcePayload({ sources: { plans: { source: 'plan_registry', gap: 'synthetic missing registry', as_of: null } }, gaps: [{ source: 'plans', reason: 'synthetic missing registry' }] })
  const p = flowProjection(raw, FLOW_NOW); eq(p.items.length, 1); eq(p.metrics.inFlight, null); eq(p.gaps.some(g => g.includes('plans') && g.includes('missing registry')), true)
})
t('unsafe partial legacy shapes are never attached to the old action-card renderer', () => {
  for (const patch of [{ where: { files: null } }, { cells: [null] }, { what: null }, { next: { text: {} } }]) {
    const bad = { ...item({ id: 'malformed-old', stage: 'building', rag: 'amber' }), ...patch }
    eq(flowProjection(flowEnvelope([bad]), FLOW_NOW).items[0].legacy, undefined)
  }
})
t('flow projection preserves raw canonical facts and legacy action data without mutation', () => {
  const raw = aSourcePayload(), before = JSON.stringify(raw); flowProjection(raw, FLOW_NOW); eq(JSON.stringify(raw), before)
})


t('submillisecond future observations cannot become observed creation or Live evidence', () => {
  const future = '2026-11-03T02:00:00.000001Z'
  const p = flowProjection(flowEnvelope([flowItem({ stage: 'live', created_at: future,
    live: { verified: true, served: true, source: 'fixture-receipt', at: future } })]), FLOW_NOW)
  eq([p.items[0].createdAt, p.items[0].stage, p.items[0].liveAt, p.inFlight.length], [null, null, null, 1])
  const past = flowProjection(flowEnvelope([flowItem({ created_at: '2026-11-03T01:59:59.999999Z' })]), FLOW_NOW)
  eq(past.items[0].createdAt, '2026-11-03T01:59:59.999Z')
})
t('A positive Live fact with an invalid observation remains named unknown rather than measured zero', () => {
  const p = flowProjection(aSourcePayload({}, { live: { value: true, source: 'served_release+deploy_receipt',
    as_of: '2026-11-03T02:00:00.000001Z', gap: null } }), FLOW_NOW)
  eq(p.items[0].stage === 'live', false); eq(p.items[0].liveAt, null)
  eq(p.items[0].gaps.some(g => g.startsWith('Live:')), true); eq(p.metrics.liveToday, null)
})

console.log(`workPipelineFlow: ${n - flowN} passed`)


// Canonical A waiting_on_you / E actionable projection integration.
const waitingN = n
const POLICY_COMMAND = `APPROVE_AGENTS_POLICY_99_0_0 9001 ${FLOW_HEAD}`
function approvalMember(extra: Record<string, unknown> = {}) {
  return { id: 'policy:fixture-9001', title: 'Review synthetic policy', kind: 'POLICY', version: '99.0.0', source: 'fixture-policy-source',
    source_sha: FLOW_HEAD, source_as_of: ENTERED, policy_approval_command: POLICY_COMMAND,
    pr: 9001, pr_url: 'https://github.com/example/repository/pull/9001', governed_href: '/approvals/policy-fixture',
    next_actor: 'operator', next_action: 'Read the exact current version', actionable: true, stale: false, source_gap: null, ...extra }
}
function canonicalQueue(extra: Record<string, unknown> = {}) {
  return { scope: 'all_operator_approvals', source: 'operator_approvals_api.queue_summary', actionable_items: [approvalMember()], actionable_count: 1,
    known_pending_count: 1, pending_count: 1, complete: true, gaps: [], as_of: '2026-11-03T01:50:00Z', stale: false, ...extra }
}
t('actual root waiting_on_you maps E proof, exact command and operator display metadata', () => {
  const q = canonicalQueue(), p = waitingProjection({ waiting_on_you: q }, FLOW_NOW), member = p.members![0]
  eq([p.count, p.complete, p.sourceAt], [1, true, '2026-11-03T01:50:00.000Z'])
  eq([member.head, member.sourceAt, member.command], [FLOW_HEAD, '2026-11-03T01:00:00.000Z', POLICY_COMMAND])
  eq([member.prNumber, member.nextActor, member.nextAction, member.url], [9001, 'operator', 'Read the exact current version', '/approvals/policy-fixture'])
  eq(waitingProjection(q, FLOW_NOW).members, p.members)
})
t('canonical member order is shared by header helper and full flow without reclassification', () => {
  const other = approvalMember({ id: 'activation:fixture', kind: 'ACTIVATE', source_sha: OTHER_HEAD, policy_approval_command: null, pr: 9002, governed_href: '/releases', actionable: false })
  const q = canonicalQueue({ actionable_items: [other, approvalMember()], actionable_count: 2, known_pending_count: 2, pending_count: 2 })
  const raw = { ...flowEnvelope([]), waiting_on_you: q }, direct = waitingProjection(raw, FLOW_NOW), flow = flowProjection(raw, FLOW_NOW)
  eq(direct.members!.map(x => x.id), ['activation:fixture', 'policy:fixture-9001'])
  eq(flow.waiting, direct.members); eq(flow.metrics.waiting, direct.count)
})
t('explicit null or invalid root queue never borrows a prototype list', () => {
  const proto = flowEnvelope([], { approvals: { complete: true, items: [{ id: 'proto-only', title: 'Old prototype' }] } })
  eq(waitingProjection(proto, FLOW_NOW).members!.map(x => x.id), ['proto-only'])
  for (const bad of [null, {}, [], { actionable_items: null }]) {
    const p = waitingProjection({ ...proto, waiting_on_you: bad }, FLOW_NOW)
    eq(p.members, null); eq(p.count, null); eq(p.complete, false)
  }
})
t('all three E counter mismatches preserve known members but hide commands and total', () => {
  for (const bad of [{ actionable_count: 2 }, { known_pending_count: 2 }, { pending_count: 2 }, { known_pending_count: undefined }]) {
    const p = waitingProjection({ waiting_on_you: canonicalQueue(bad) }, FLOW_NOW)
    eq(p.members!.map(x => x.id), ['policy:fixture-9001']); eq(p.count, null); eq(p.complete, false)
    eq(p.members![0].command, null); eq(p.gaps.some(g => g.startsWith('actionable_queue:')), true)
  }
})
t('partial global queue allows independently proven commands while keeping total unknown', () => {
  const p = waitingProjection({ waiting_on_you: canonicalQueue({ complete: false, pending_count: 99, gaps: [{ source: 'plans', reason: 'Synthetic source missing' }] }) }, FLOW_NOW)
  eq([p.count, p.complete, p.members![0].command], [null, false, POLICY_COMMAND])
  eq(p.gaps.some(g => g.includes('plans') && g.includes('Synthetic source missing')), true)
})
t('a complete empty canonical source reports measured zero and no stale fallback', () => {
  const p = waitingProjection({ waiting_on_you: canonicalQueue({ actionable_items: [], actionable_count: 0, known_pending_count: 0, pending_count: 0 }) }, FLOW_NOW)
  eq([p.members, p.count, p.complete], [[], 0, true])
})
t('stale canonical queue keeps members but exposes no executable policy line', () => {
  const p = waitingProjection({ waiting_on_you: canonicalQueue({ stale: true }) }, FLOW_NOW)
  eq(p.members!.length, 1); eq([p.count, p.complete, p.members![0].command], [null, false, null])
})
t('member proof clocks refuse unknown and microfuture instants without any queue/creation fallback', () => {
  for (const at of [null, undefined, '2026-11-02', '2026-11-03 01:00:00', 'bad-clock', '2026-11-04T00:00:00Z', '2026-11-03T02:00:00.000001Z']) {
    const q = canonicalQueue({ actionable_items: [approvalMember({ source_as_of: at, as_of: ENTERED, created_at: CREATED })] })
    const p = waitingProjection({ waiting_on_you: q }, FLOW_NOW)
    eq([p.members![0].sourceAt, p.members![0].command], [null, null]); eq(p.count, 1)
    eq(p.gaps.some(g => g.includes('source_as_of')), true)
  }
})
t('individual actionable, stale and source-gap refusals cannot erase canonical membership', () => {
  for (const patch of [{ actionable: false }, { actionable: undefined }, { stale: true }, { source_gap: 'Unverified source' }]) {
    const p = waitingProjection({ waiting_on_you: canonicalQueue({ actionable_items: [approvalMember(patch)] }) }, FLOW_NOW)
    eq(p.members!.length, 1); eq(p.count, 1); eq(p.members![0].command, null)
  }
})
t('policy lines require the provided exact head and PR, and are never reconstructed', () => {
  for (const patch of [{ source_sha: OTHER_HEAD }, { source_sha: 'a'.repeat(7) }, { pr: 9002 }]) {
    const p = waitingProjection({ waiting_on_you: canonicalQueue({ actionable_items: [approvalMember(patch)] }) }, FLOW_NOW)
    eq(p.members![0].command, null); eq(p.gaps.some(g => g.includes('exact source head or PR')), true)
  }
  const exact = `  ${POLICY_COMMAND}\n`
  eq(waitingProjection({ waiting_on_you: canonicalQueue({ actionable_items: [approvalMember({ policy_approval_command: exact })] }) }, FLOW_NOW).members![0].command, exact)
})
t('financial-only totals and wrong scope never become global waiting membership', () => {
  for (const q of [{ total: 7, by_type: { financial: 7 }, complete: true }, canonicalQueue({ scope: 'financial_only' })]) {
    const p = waitingProjection({ waiting_on_you: q, summary: { needs_me: 7 } }, FLOW_NOW)
    eq(p.members, null); eq(p.count, null); eq(p.complete, false)
  }
})
t('queue snapshot null does not borrow API capture and unsafe navigation URLs stay absent', () => {
  const p = waitingProjection({ as_of: ENTERED, waiting_on_you: canonicalQueue({ as_of: null, actionable_items: [approvalMember({ governed_href: 'javascript:fixture', pr_url: '//external.test/fixture' })] }) }, FLOW_NOW)
  eq(p.sourceAt, null); eq(p.members![0].sourceAt, '2026-11-03T01:00:00.000Z'); eq(p.members![0].url, null)
})
t('waiting projection never mutates provider members or their verbatim evidence', () => {
  const raw = { waiting_on_you: canonicalQueue() }, before = JSON.stringify(raw)
  waitingProjection(raw, FLOW_NOW); flowProjection(raw, FLOW_NOW); eq(JSON.stringify(raw), before)
})
console.log(`workPipelineWaiting: ${n - waitingN} passed`)


// One shared queue-snapshot and transport gate for Header and Work.
const queueGateN = n

t('unknown queue snapshot clocks retain members but block both shared total and commands', () => {
  for (const at of [undefined, null, '2026-11-02', '2026-11-03 01:50:00', 'bad-clock', '2026-11-04T00:00:00Z', '2026-11-03T02:00:00.000001Z']) {
    const raw = { ...flowEnvelope([]), waiting_on_you: canonicalQueue({ as_of: at }) }
    const waiting = waitingProjection(raw, FLOW_NOW), flow = flowProjection(raw, FLOW_NOW)
    eq(waiting.members!.map(m => m.id), ['policy:fixture-9001']); eq(waiting.members![0].sourceAt, '2026-11-03T01:00:00.000Z')
    eq([waiting.count, waiting.complete, waiting.members![0].command], [null, false, null])
    eq(flow.metrics.waiting, waiting.count); eq(flow.waiting, waiting.members)
    eq(waiting.gaps.some(g => g.startsWith('Canonical approval queue snapshot:')), true)
  }
})
t('a prototype without its own measured queue clock stays unknown, even with an API capture', () => {
  const member = { id: 'prototype', title: 'Historical proposal', as_of: ENTERED }
  for (const at of [undefined, null, '2026-11-02', '2026-11-03 01:50:00', '2026-11-04T00:00:00Z', '2026-11-03T02:00:00.000001Z']) {
    const raw = flowEnvelope([], { approvals: { complete: true, as_of: at, items: [member] } })
    const waiting = waitingProjection(raw, FLOW_NOW)
    eq(waiting.members!.map(m => m.id), ['prototype']); eq([waiting.count, waiting.complete, waiting.sourceAt], [null, false, null])
    eq(flowProjection(raw, FLOW_NOW).metrics.waiting, null)
  }
  const measured = waitingProjection(flowEnvelope([], { approvals: { complete: true, as_of: ENTERED, items: [member] } }), FLOW_NOW)
  eq([measured.count, measured.complete, measured.sourceAt], [1, true, '2026-11-03T01:00:00.000Z'])
})
t('retained-error and stale transports use one nonmutating total and command gate', () => {
  const raw = { ...flowEnvelope([]), waiting_on_you: canonicalQueue() }, before = JSON.stringify(raw)
  const healthy = waitingProjection(raw, FLOW_NOW)
  eq([healthy.count, healthy.complete, healthy.members![0].command], [1, true, POLICY_COMMAND])
  for (const context of [{ readFailed: true }, { stale: true }]) {
    const waiting = waitingProjection(raw, FLOW_NOW, context), flow = flowProjection(raw, FLOW_NOW, context)
    eq(waiting.members!.map(m => m.id), healthy.members!.map(m => m.id))
    eq([waiting.count, waiting.complete, waiting.members![0].command], [null, false, null])
    eq(waiting.sourceAt, healthy.sourceAt); eq(flow.metrics.waiting, waiting.count); eq(flow.waiting, waiting.members)
    eq(waiting.gaps.some(g => g.includes(context.readFailed ? 'read unavailable' : 'transport is stale')), true)
  }
  eq(JSON.stringify(raw), before)
})
t('valid partial queue clock preserves an independently proven command after a healthy read', () => {
  const raw = { ...flowEnvelope([]), waiting_on_you: canonicalQueue({ complete: false, pending_count: null }) }
  const waiting = waitingProjection(raw, FLOW_NOW, { readFailed: false, stale: false })
  eq([waiting.count, waiting.complete, waiting.members![0].command], [null, false, POLICY_COMMAND])
  eq(flowProjection(raw, FLOW_NOW, {}).waiting, waiting.members)
})
t('invalid evaluation clock cannot certify queue total or command recency', () => {
  const p = waitingProjection({ waiting_on_you: canonicalQueue() }, Number.NaN)
  eq([p.count, p.complete, p.members![0].command], [null, false, null])
  eq(p.gaps.some(g => g.includes('evaluation clock')), true)
})
t('A typed stuck and exact blocker facts populate their current display aliases', () => {
  const raw = aSourcePayload({}, { stuck: { value: true, source: 'fixture-stage-clock', as_of: ENTERED, gap: null },
    blocker: { value: 'Synthetic current check is failing', source: 'fixture-check-evidence', as_of: ENTERED, gap: null } })
  const p = flowProjection(raw, FLOW_NOW)
  eq([p.items[0].stuck, p.items[0].blocker, p.metrics.stuck], [true, 'Synthetic current check is failing', 1])
})
t('explicit empty blocker and false stuck facts override historical values without guessing', () => {
  const raw = aSourcePayload({}, { stuck: { value: false, source: 'fixture-stage-clock', as_of: ENTERED, gap: null },
    blocker: { value: null, source: 'fixture-check-evidence', as_of: ENTERED, gap: null } })
  Object.assign(raw.items[0], { blocker: 'Old blocker', stuck: true })
  const p = flowProjection(raw, FLOW_NOW)
  eq([p.items[0].stuck, p.items[0].blocker, p.metrics.stuck], [false, null, 0])
})
console.log(`workPipelineQueueGate: ${n - queueGateN} passed`)


// Independent refusal probe found these malformed policy-line bindings.
const policyBindingN = n
t('policy copy lines require the declared kind, operator actor, version, positive PR and exact token shape', () => {
  for (const patch of [{ pr: null }, { pr: undefined }, { pr: '9001' }, { pr: 0 },
    { next_actor: 'coordinator' }, { next_actor: 'agent' }, { next_actor: null }, { kind: 'FINDING' },
    { version: null }, { version: '30.0.0' },
    { policy_approval_command: `SYNTHETIC_INVALID 9001 ${FLOW_HEAD}` },
    { policy_approval_command: `${POLICY_COMMAND} extra` },
    { policy_approval_command: `APPROVE_AGENTS_POLICY_99_0_0 09001 ${FLOW_HEAD}` }]) {
    const q = canonicalQueue({ actionable_items: [approvalMember(patch)] })
    const p = waitingProjection({ waiting_on_you: q }, FLOW_NOW)
    eq([p.count, p.members!.map(m => m.id)], [1, ['policy:fixture-9001']])
    eq(p.members![0].command, null)
  }
})
t('a semantically exact policy line is preserved verbatim after its bindings are checked', () => {
  const line = `  APPROVE_AGENTS_POLICY_99_0_0  9001 ${FLOW_HEAD}\n`
  const p = waitingProjection(canonicalQueue({ actionable_items: [approvalMember({ policy_approval_command: line })] }), FLOW_NOW)
  eq(p.members![0].command, line)
})
console.log(`workPipelinePolicyBinding: ${n - policyBindingN} passed`)
