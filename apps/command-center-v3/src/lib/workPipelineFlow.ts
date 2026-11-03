// Current read-only projection shared by Coordination and Releases. Legacy stages/actions remain in workPipeline.ts.
import type { PipelineItem } from './workPipeline.ts'

export const FLOW_STAGES = ['requested', 'building', 'uploaded', 'pr_open', 'checks', 'review', 'approval', 'merged', 'live'] as const
export type FlowStage = typeof FLOW_STAGES[number]
export const FLOW_STAGE_LABEL: Record<FlowStage, string> = { requested: 'Requested', building: 'Building', uploaded: 'Uploaded', pr_open: 'PR open', checks: 'Checks', review: 'Review', approval: 'Approval', merged: 'Merged', live: 'Live' }
export type FlowActor = 'agent' | 'coordinator' | 'operator' | 'unknown'
export type FlowEvent = { id: string; label: string; at: string | null; source: string | null; detail: string | null }
export type FlowApproval = { id: string; title: string; command: string | null; url: string | null; head: string | null; sourceAt: string | null; source: string | null }
export type FlowAgent = { session: string; vendor: string | null; coordinator: string | null; itemId: string | null; stage: FlowStage | null; lastActivity: string | null; idleMinutes: number | null; nudgesToday: number | null; gaps: string[] }
export type FlowReview = { reviewer: string | null; verdict: string | null; currentHead: boolean | null; at: string | null; source: string | null }
export type FlowItem = {
  id: string; title: string; stage: FlowStage | null
  owner: { session: string | null; vendor: string | null; coordinator: string | null }
  createdAt: string | null; touchedAt: string | null; stageSince: string | null; ageMinutes: number | null; stageAgeMinutes: number | null
  next: { actor: FlowActor; text: string; command: string | null }
  blocker: string | null; checks: { passed: number | null; total: number | null; failedNames: string[]; gap: string | null }
  reviews: FlowReview[]; reviewRequired: number | null; stuck: boolean | null; prNumber: number | null; prUrl: string | null
  events: FlowEvent[]; legacy?: PipelineItem; gaps: string[]; inFlight: boolean; membershipKnown: boolean
  mergedAt: string | null; liveAt: string | null; greenAt: string | null
}
export type FlowProjection = {
  items: FlowItem[]; inFlight: FlowItem[]; groups: { stage: FlowStage | null; items: FlowItem[] }[]
  metrics: { inFlight: number | null; stuck: number | null; waiting: number | null; mergedToday: number | null; liveToday: number | null; greenToLiveMinutes: number | null; idleAgentMinutes: number | null }
  waiting: FlowApproval[] | null; agents: FlowAgent[]; gaps: string[]; sourceAt: string | null
}
type Row = Record<string, unknown>
const rec = (v: unknown): Row => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Row : {}
const own = (r: Row, ...keys: string[]): unknown => { for (const k of keys) if (Object.prototype.hasOwnProperty.call(r, k)) return r[k]; return undefined }
const prefer = (r: Row, keys: string[], fallback: unknown): unknown => keys.some(k => Object.prototype.hasOwnProperty.call(r, k)) ? own(r, ...keys) : fallback
const txt = (v: unknown): string | null => typeof v === 'string' && v.trim() ? v.trim() : null
const num = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null
const count = (v: unknown): number | null => { const n = num(v); return n !== null && Number.isSafeInteger(n) ? n : null }
const words = (v: unknown): string[] => Array.isArray(v) ? v.map(txt).filter((s): s is string => s !== null) : []
const messages = (v: unknown): string[] => Array.isArray(v) ? v.flatMap(x => { const r = rec(x); const reason = txt(r.reason); const s = txt(x) ?? (reason ? `${txt(r.source) ?? 'Source'}: ${reason}` : null); return s ? [s] : [] }) : []
const stage = (v: unknown): FlowStage | null => (FLOW_STAGES as readonly unknown[]).includes(v) ? v as FlowStage : null
const head = (v: unknown): string | null => typeof v === 'string' && /^[a-fA-F0-9]{40}$/.test(v) ? v.toLowerCase() : null
const age = (v: string | null, now: number): number | null => v && Number.isFinite(now) ? (now - Date.parse(v)) / 60_000 : null

/** An instant requires a valid calendar day, time and explicit offset. Future/naive/date-only values remain gaps. */
function instant(v: unknown, now: number): string | null {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(v)) return null
  const [y, m, d] = v.slice(0, 10).split('-').map(Number)
  if (new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10) !== v.slice(0, 10)) return null
  const time = v.slice(11).match(/^(\d{2}):(\d{2})(?::(\d{2}))?/)!
  if (Number(time[1]) > 23 || Number(time[2]) > 59 || Number(time[3] ?? 0) > 59) return null
  const n = Date.parse(v.replace(' ', 'T'))
  // Date.parse truncates below milliseconds; a positive remainder at `now`
  // is still future evidence, rather than an observation at the boundary.
  const fraction = v.match(/\.(\d+)(?=Z|[+-]\d{2}:\d{2}$)/)?.[1] ?? ''
  const futureRemainder = n === now && /[1-9]/.test(fraction.slice(3))
  return Number.isFinite(n) && !futureRemainder && (!Number.isFinite(now) || n <= now) ? new Date(n).toISOString() : null
}
function clock(raw: unknown, name: string, gaps: string[], now: number): string | null {
  const value = instant(raw, now)
  if (!value) gaps.push(`${name}: source observation time unavailable${raw == null ? '' : ' (date-only, naive, invalid or future)'}`)
  return value
}
const legacyStages: Record<string, FlowStage> = { proposed: 'requested', approved: 'requested', queued: 'requested', claimed: 'building', building: 'building', pr_open: 'pr_open', ci: 'checks', merged: 'merged' }
function eventRows(raw: unknown, now: number): FlowEvent[] {
  return Array.isArray(raw) ? raw.map((v, i) => { const r = rec(v); return { id: txt(r.id) ?? `event-${i}`, label: txt(own(r, 'label', 'event', 'kind', 'stage')) ?? 'Source event', at: instant(own(r, 'at', 'timestamp', 'as_of'), now), source: txt(r.source), detail: txt(own(r, 'detail', 'reason', 'text')) } }) : []
}
function legacyItem(raw: Row): PipelineItem | undefined {
  if (!['who', 'what', 'when', 'where', 'how', 'next'].every(k => raw[k] !== null && typeof raw[k] === 'object' && !Array.isArray(raw[k]))) return undefined
  const where = rec(raw.where), who = rec(raw.who), what = rec(raw.what), next = rec(raw.next)
  if (!Array.isArray(where.files) || !where.files.every(f => typeof f === 'string') || !Array.isArray(raw.cells)) return undefined
  if (typeof raw.id !== 'string' || typeof who.label !== 'string' || typeof what.title !== 'string' || typeof next.text !== 'string') return undefined
  if (next.owner !== 'agent' && next.owner !== 'operator') return undefined
  if (!raw.cells.every(v => { const c = rec(v); return !!txt(c.stage) && ['green', 'amber', 'red', 'grey'].includes(String(c.rag)) && typeof c.label === 'string' })) return undefined
  const actions = rec(raw.actions)
  if (actions.available !== undefined && !Array.isArray(actions.available)) return undefined
  return raw as unknown as PipelineItem
}
function projectItem(value: unknown, canonical: boolean, now: number, threshold: unknown): FlowItem {
  const raw = rec(value), flow = Object.keys(rec(raw.flow)).length ? rec(raw.flow) : raw
  const when = rec(flow.when), what = rec(raw.what), gaps = messages(flow.gaps)
  const modern = canonical || Object.prototype.hasOwnProperty.call(flow, 'current_stage') || Object.keys(rec(raw.flow)).length > 0
  const oldStage = txt(raw.stage), current = own(flow, 'current_stage', 'stage')
  let currentStage = modern ? stage(current) : legacyStages[oldStage ?? ''] ?? null
  if (!currentStage) gaps.push(`Current stage: ${modern ? 'coordination stage evidence unavailable' : `legacy ${oldStage ?? 'stage unavailable'} has no proven current-stage equivalent`}`)
  const id = txt(raw.id) ?? txt(what.task_id) ?? 'unidentified-item'
  const owner = rec(own(flow, 'owner', 'who'))
  const session = txt(owner.session), vendor = txt(owner.vendor), coordinator = txt(owner.coordinator)
  if (!session) gaps.push('Owner session: claim board/worklog source unavailable')
  if (!vendor) gaps.push('Owner vendor: claim board/worklog source unavailable')
  if (!coordinator) gaps.push('Owner coordinator: coordination assignment source unavailable')
  const createdAt = clock(prefer(flow, ['created_at', 'createdAt'], own(when, 'created_at')), 'Created', gaps, now)
  const touchedAt = clock(prefer(flow, ['last_touched', 'touched_at', 'touchedAt'], own(when, 'last_activity')), 'Last touched', gaps, now)
  // Legacy stage_since sometimes substitutes PR.updated_at; it cannot date a newly mapped stage.
  const stageSince = clock(modern ? prefer(flow, ['stage_since', 'stageSince'], own(when, 'stage_since')) : undefined, 'Time in current stage', gaps, now)
  const rawNext = rec(flow.next), actorRaw = own(rawNext, 'actor')
  const actor: FlowActor = actorRaw === 'agent' || actorRaw === 'coordinator' || actorRaw === 'operator' ? actorRaw : 'unknown'
  if (actor === 'unknown') gaps.push('Next actor: canonical coordination actor unavailable; legacy owner is not an approval requirement')
  const next = { actor, text: txt(rawNext.text) ?? 'Next action unavailable from coordination source', command: txt(rawNext.command) }
  const checks = rec(own(flow, 'checks', 'ci')), itemHead = head(own(flow, 'head_sha', 'head')), checkHead = head(own(checks, 'head_sha', 'head'))
  let passed = count(own(checks, 'passed', 'green')), total = count(own(checks, 'total', 'required_count'))
  let checkGap = txt(checks.gap)
  if (!itemHead || checkHead !== itemHead) { passed = null; total = null; checkGap = 'Checks: source is missing or not bound to the current exact head' }
  if (passed === null || total === null || passed > total || total === 0) { passed = null; total = null; checkGap ??= 'Checks: measured required/green counts unavailable' }
  if (checkGap) gaps.push(checkGap)
  const reviewBlock = rec(flow.reviews), reviewRows = Array.isArray(flow.reviews) ? flow.reviews : reviewBlock.items
  const reviews: FlowReview[] = Array.isArray(reviewRows) ? reviewRows.map(v => { const r = rec(v), h = head(own(r, 'head_sha', 'head', 'envelope_head')); return { reviewer: txt(own(r, 'reviewer', 'who', 'agent')), verdict: txt(r.verdict), currentHead: itemHead && h ? h === itemHead && r.current_head !== false : null, at: instant(own(r, 'at', 'as_of'), now), source: txt(r.source) } }) : []
  if (!Array.isArray(reviewRows)) gaps.push('Reviews: exact-head review ledger source unavailable')
  const live = rec(own(flow, 'live', 'verification'))
  const liveAt = instant(prefer(flow, ['live_verified_at', 'liveAt'], own(live, 'verified_at', 'at')), now)
  const liveProof = (live.verified === true || flow.live_verified === true) && liveAt !== null && !!txt(own(live, 'source') ?? flow.source)
    && (live.served === true || live.contains_merge === true || head(live.served_sha) !== null)
  if (currentStage === 'live' && !liveProof) { currentStage = null; gaps.push('Live: served and verified evidence with its own source time unavailable') }
  const activity = own(flow, 'in_flight', 'active')
  const membershipKnown = typeof activity === 'boolean' || liveProof || (modern && currentStage !== null && currentStage !== 'live') || (!modern && currentStage !== null)
  const inFlight = activity !== false && !liveProof
  if (!membershipKnown) gaps.push('In-flight membership: canonical active/completion source unavailable; retained as unresolved')
  const stuckBlock = rec(flow.stuck), rawStuck = typeof flow.stuck === 'boolean' ? flow.stuck : own(stuckBlock, 'flag', 'value')
  const stuckThreshold = num(own(stuckBlock, 'threshold_minutes') ?? own(flow, 'stuck_after_minutes') ?? threshold)
  const basis = txt(stuckBlock.basis), stageAgeMinutes = age(stageSince, now)
  const stuck = typeof rawStuck === 'boolean' ? rawStuck : stuckThreshold !== null && stuckThreshold > 0 && basis === 'stage' && stageAgeMinutes !== null ? stageAgeMinutes > stuckThreshold : null
  if (stuck === null) gaps.push('Stuck: configured threshold or matching source-clock evidence unavailable')
  if (!modern && (oldStage === 'verified' || oldStage === 'released')) gaps.push('Live: legacy completion/release is not served and verified evidence')
  const events = eventRows(own(flow, 'events', 'timeline'), now)
  if (!Array.isArray(own(flow, 'events', 'timeline'))) gaps.push('Timeline: coordination ledger source unavailable; legacy cells retained as history')
  if (Array.isArray(raw.cells)) for (const v of raw.cells) { const c = rec(v); if (c.at || c.evidence) events.push({ id: `legacy-${txt(c.stage) ?? events.length}`, label: `Legacy ${txt(c.stage) ?? 'stage'}`, at: instant(c.at, now), source: 'WorkPipeline@v1 stage history', detail: txt(c.evidence) }) }
  return { id, title: txt(flow.title) ?? txt(what.title) ?? id, stage: currentStage, owner: { session, vendor, coordinator }, createdAt, touchedAt, stageSince, ageMinutes: age(createdAt, now), stageAgeMinutes, next,
    blocker: txt(flow.blocker), checks: { passed, total, failedNames: words(own(checks, 'failed_names', 'failing', 'failedNames')), gap: checkGap }, reviews, reviewRequired: count(own(reviewBlock, 'required_count', 'required')),
    stuck, prNumber: count(own(flow, 'pr_number', 'prNumber') ?? what.pr_number), prUrl: txt(own(flow, 'pr_url', 'prUrl') ?? what.pr_url ?? rec(raw.links).pr), events,
    ...(legacyItem(raw) ? { legacy: legacyItem(raw) } : {}), gaps, inFlight, membershipKnown,
    mergedAt: instant(own(flow, 'merged_at', 'mergedAt'), now), liveAt: liveProof ? liveAt : null, greenAt: itemHead && checkHead === itemHead ? instant(own(checks, 'green_at', 'completed_at'), now) : null }
}
function approvalRows(raw: unknown, now: number, gaps: string[]): { members: FlowApproval[] | null; complete: boolean } {
  const block = rec(raw)
  const rows = own(block, 'actionable_items', 'items')
  if (!Array.isArray(rows)) { gaps.push('Waiting on you: canonical actionable approval member source unavailable'); return { members: null, complete: false } }
  const members: FlowApproval[] = [], ids = new Map<string, string>(); let complete = block.complete === true
  if (!complete) gaps.push('Waiting on you: canonical approval member source is partial; total unavailable')
  for (const value of rows) {
    const r = rec(value), id = txt(r.id)
    if (!id) { complete = false; gaps.push('Waiting on you: canonical member has no stable id'); continue }
    const wire = JSON.stringify(r)
    if (ids.has(id)) { if (ids.get(id) !== wire) { complete = false; const index = members.findIndex(m => m.id === id); if (index >= 0) members.splice(index, 1); gaps.push(`Waiting on you: conflicting canonical approval id ${id}`) }; continue }
    ids.set(id, wire)
    members.push({ id, title: txt(r.title) ?? id, command: txt(r.command), url: txt(own(r, 'url', 'governed_href')), head: head(own(r, 'head_sha', 'head')), sourceAt: instant(own(r, 'source_at', 'as_of', 'created_at'), now), source: txt(r.source) })
  }
  return { members, complete }
}
/** Adapter for A's frozen WorkPipelineSources@v1 facts; no second census or action policy. */
function sourceItem(value: unknown, sources: Row, now: number): Row {
  const raw = rec(value), number = own(raw, 'pr_number') ?? rec(raw.what).pr_number
  const bundle = Object.prototype.hasOwnProperty.call(raw, 'coordination') ? rec(raw.coordination) : rec(rec(sources.by_pr)[String(number)])
  const timeline = Array.isArray(bundle.timeline) ? bundle.timeline.map(rec) : []
  const fact = (key: string): Row => rec(bundle[key])
  const owner = fact('owner'), ownerValue = rec(owner.value), nextFact = fact('next_action'), liveFact = fact('live')
  const liveAt = instant(liveFact.as_of, now), provenLive = liveFact.value === true && liveAt !== null && txt(liveFact.source) !== null && !liveFact.gap
  const merged = timeline.find(e => e.kind === 'merged' && e.source === 'github_census' && instant(e.as_of, now))
  const opened = timeline.find(e => e.kind === 'pr_open' && e.source === 'github_census' && instant(e.as_of, now))
  const currentHead = head(bundle.head_sha) ?? head(opened?.head_sha)
  const ci = rec(bundle.ci), review = rec(bundle.review)
  const typedReview = review.evidence_class === 'reported_review_not_approval' && !review.gap && head(review.head_sha) !== null
  const reviews = Array.isArray(review.records) ? review.records.map(v => { const r = rec(v); return { ...r, reviewer: r.reviewer_session, at: r.observed_at, source: review.source, envelope_head: typedReview ? review.head_sha : null } }) : undefined
  const localGaps = messages(bundle.gaps)
  if (liveFact.value === true && !provenLive) localGaps.push('Live: positive source fact lacks a proven nonfuture observation or source binding')
  for (const key of ['owner', 'coordinator', 'last_activity', 'next_action', 'live']) { const f = fact(key); if (txt(f.gap)) localGaps.push(`${txt(f.source) ?? key}: ${txt(f.gap)}`) }
  if (!bundle.current_stage && !provenLive && !merged && !legacyStages[txt(raw.stage) ?? '']) localGaps.push('Current stage: legacy batch/release history does not establish Review, Approval or Live')
  const declaredStage = rec(bundle.current_stage).value ?? bundle.current_stage
  const currentStage = stage(declaredStage) ?? (provenLive ? 'live' : merged ? 'merged' : legacyStages[txt(raw.stage) ?? ''] ?? null)
  const stageFact = fact('stage_since'), createdFact = fact('created_at')
  const rawOwner = Object.keys(owner).length ? ownerValue : rec(raw.who)
  const flow: Row = { ...raw, current_stage: currentStage,
    owner: { ...rawOwner, coordinator: Object.keys(fact('coordinator')).length ? fact('coordinator').value : rawOwner.coordinator },
    created_at: Object.keys(createdFact).length ? createdFact.value : prefer(raw, ['created_at'], opened?.as_of),
    last_touched: Object.keys(fact('last_activity')).length ? fact('last_activity').value : rec(raw.when).last_activity,
    stage_since: stageFact.value,
    next: { actor: fact('next_actor').value ?? bundle.next_actor, text: Object.keys(nextFact).length ? nextFact.value : rec(raw.next).text, command: null },
    head_sha: currentHead, checks: ci, reviews: { items: reviews, required_count: review.required_count },
    merged_at: merged?.as_of, live_verified_at: liveAt,
    live: { verified: provenLive, served: provenLive, source: liveFact.source, at: liveAt },
    events: timeline.map(e => ({ id: txt(e.source_ref) ?? `${e.kind}-${e.as_of}`, label: txt(e.kind)?.replace(/_/g, ' '), at: e.as_of, source: e.source, detail: [txt(e.source_ref), txt(e.verdict), txt(e.head_sha)].filter(Boolean).join(' · ') || null })),
    gaps: localGaps,
  }
  return { ...raw, flow }
}
function sourceAgents(sources: Row, items: FlowItem[], now: number): Row[] | undefined {
  if (!Array.isArray(sources.claims)) return undefined
  const bySession = new Map<string, Row>(), activeIds = Array.isArray(sources.active_claim_ids) ? new Set(sources.active_claim_ids) : null
  for (const value of sources.claims) {
    const r = rec(value), session = txt(r.session)
    if (!session) continue
    const activity = [instant(r.heartbeat_at, now), instant(rec(r.worklog).last_entry_at, now)].filter((v): v is string => v !== null).sort().slice(-1)[0] ?? null
    const member = items.find(i => i.inFlight && (i.owner.session === session || i.prNumber === r.pr_number || i.prNumber === r.pr))
    const local: string[] = []
    const active = activeIds ? activeIds.has(r.claim_id) : null
    if (active === null) local.push('Claim activity: canonical active-claim source unavailable')
    else if (!active) local.push('Claim is inactive or stale in canonical active-claim membership')
    const row: Row = { session, vendor: r.vendor, coordinator: r.coordinator, item_id: member?.id, stage: member?.stage,
      last_activity: activity, nudges_today: r.nudges_today, active, gaps: local }
    const prior = bySession.get(session)
    if (!prior || (active === true && prior.active !== true) || (active === prior.active && String(activity ?? '') > String(prior.last_activity ?? ''))) bySession.set(session, row)
  }
  return [...bySession.values()]
}
function etDay(value: string | null): string | null { return value ? new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value)) : null }

export function flowProjection(payload: unknown, now: number | Date = Date.now()): FlowProjection {
  const outer = rec(payload), root = outer.ok === true && outer.data && typeof outer.data === 'object' ? rec(outer.data) : outer
  const c = rec(root.coordination), gaps = messages(c.gaps), ms = now instanceof Date ? now.getTime() : now
  if (!Number.isFinite(ms)) gaps.push('Projection evaluation clock unavailable')
  const sourceContract = c.schema === 'WorkPipelineSources@v1'
  const canonical = Array.isArray(c.items) || sourceContract, rawItems = Array.isArray(c.items) ? c.items : root.items
  const collectionPresent = Array.isArray(rawItems)
  const sourceIssues = Object.entries({ ...rec(root.sources), ...rec(c.sources) }).flatMap(([name, value]) => { const s = rec(value); const status = txt(s.status)?.toUpperCase(); const warning = txt(s.warning) ?? txt(s.gap); return warning || (status && ['PARTIAL', 'UNAVAILABLE', 'UNKNOWN', 'ERROR', 'FAILED'].includes(status)) ? [`${name}: ${warning ?? txt(s.reason) ?? `source ${status}`}`] : [] })
  gaps.push(...sourceIssues)
  const sourceComplete = sourceContract && ['claims', 'coordinator_ledger', 'digest_approvals', 'plans', 'releases'].every(k => Object.keys(rec(rec(c.sources)[k])).length > 0) && instant(rec(rec(root.sources).census).refreshed_at, ms) !== null
  const complete = c.complete !== false && (c.complete === true || sourceComplete) && root.complete !== false && !['PARTIAL', 'UNAVAILABLE', 'UNKNOWN', 'ERROR'].includes(txt(c.status)?.toUpperCase() ?? '') && sourceIssues.length === 0
  if (!complete) gaps.push('Work-item membership completeness unavailable from canonical coordination sources; observed rows retained')
  if (!canonical) gaps.push('Current coordination envelope unavailable; retained legacy item history')
  if (!collectionPresent) gaps.push('Work-item membership source unavailable')
  const items = Array.isArray(rawItems) ? rawItems.filter(v => Object.keys(rec(v)).length > 0).map(v => projectItem(sourceContract ? sourceItem(v, c, ms) : v, canonical, ms, c.stuck_after_minutes)) : []
  const dropped = Array.isArray(rawItems) ? rawItems.length - items.length : 0
  if (dropped) gaps.push(`Work-item source has ${dropped} malformed member(s); total unavailable`)
  const collectionKnown = collectionPresent && complete && dropped === 0
  const inFlight = items.filter(i => i.inFlight), membershipKnown = collectionKnown && items.every(i => i.membershipKnown)
  const approval = approvalRows(c.approvals, ms, gaps)
  const agentRows = Array.isArray(c.agents) ? c.agents : sourceContract ? sourceAgents(c, items, ms) : undefined
  const agentsKnown = Array.isArray(agentRows) && (c.agents_complete === true || complete)
  if (!agentsKnown) gaps.push('Agents: claim/worklog activity and nudge source unavailable')
  const agents: FlowAgent[] = Array.isArray(agentRows) ? agentRows.filter(v => rec(v).active !== false).flatMap(v => {
    const r = rec(v), session = txt(r.session), local = messages(r.gaps)
    if (!session) { gaps.push('Agents: source row has no session'); return [] }
    const lastActivity = clock(own(r, 'last_activity', 'lastActivity'), `Agent ${session} activity`, local, ms)
    const nudgesToday = count(own(r, 'nudges_today', 'nudgesToday')); if (nudgesToday === null) local.push('Nudges today: nudger ledger source unavailable')
    return [{ session, vendor: txt(r.vendor), coordinator: txt(r.coordinator), itemId: txt(own(r, 'item_id', 'itemId')), stage: stage(r.stage), lastActivity, idleMinutes: age(lastActivity, ms), nudgesToday, gaps: local }]
  }) : []
  const day = Number.isFinite(ms) ? etDay(new Date(ms).toISOString()) : null
  const mergedUnknown = items.some(i => (i.stage === 'merged' || i.liveAt !== null) && i.mergedAt === null)
  const liveUnknown = items.some(i => i.gaps.some(g => g.startsWith('Live:')))
  const liveItems = items.filter(i => i.liveAt !== null), durations = liveItems.map(i => i.greenAt && i.liveAt && Date.parse(i.liveAt) >= Date.parse(i.greenAt) ? (Date.parse(i.liveAt) - Date.parse(i.greenAt)) / 60_000 : null)
  if (durations.some(v => v === null)) gaps.push('Green to live: exact-head green/verified clock pair incomplete')
  const groups = FLOW_STAGES.map(s => ({ stage: s as FlowStage | null, items: inFlight.filter(i => i.stage === s) }))
  if (inFlight.some(i => i.stage === null)) groups.push({ stage: null, items: inFlight.filter(i => i.stage === null) })
  const sourceAt = clock(prefer(c, ['source_at', 'observed_at'], sourceContract ? c.as_of : undefined), 'Coordination source observation', gaps, ms)
  return { items, inFlight, groups, waiting: approval.members, agents, gaps, sourceAt, metrics: {
    inFlight: membershipKnown ? inFlight.length : null,
    stuck: membershipKnown && inFlight.every(i => i.stuck !== null) ? inFlight.filter(i => i.stuck).length : null,
    waiting: approval.complete && approval.members !== null ? approval.members.length : null,
    mergedToday: collectionKnown && !mergedUnknown && day ? items.filter(i => i.mergedAt && etDay(i.mergedAt) === day).length : null,
    liveToday: collectionKnown && !liveUnknown && day ? liveItems.filter(i => etDay(i.liveAt) === day).length : null,
    greenToLiveMinutes: collectionKnown && durations.length > 0 && durations.every((v): v is number => v !== null) ? durations.reduce((a, b) => a + b, 0) / durations.length : null,
    idleAgentMinutes: agentsKnown && agents.every(a => a.idleMinutes !== null) ? agents.reduce((sum, a) => sum + (a.idleMinutes ?? 0), 0) : null,
  } }
}
