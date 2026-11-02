// Releases & schedules → Deploy in flight: the typed model. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/deployInFlight.test.ts
//
// Covers the failure classes the operator reported: a GitHub enum read as a boolean (every row UNKNOWN →
// "auto-rebase"), a review/CI receipt for an older head shown as current, local-only work shown as published,
// and an old backend (no `work` / no `coordination`) pretending to have facts.
import {
  IN_FLIGHT_SCHEMA, IN_FLIGHT_SCHEMA_V2, KNOWN_SCHEMAS, agentStateTone, ciLabel2, draftLabel, nextActionFor,
  normalizeCoordination, normalizeFactor, normalizeMergeable, normalizeReview, normalizeRow, normalizeWork, publicationLabel,
  reviewLabel, rowFacts, shortSha, type CiState, type ReviewState,
} from './deployInFlight.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (name: string, got: unknown, want: unknown) => check(name, got === want, got)

const HEAD = 'aaaaaaaabbbbbbbbccccccccddddddddeeeeeeee'
const OLD = '1111111122222222333333334444444455555555'

// ── mergeable: the GitHub enum, plus the legacy boolean ─────────────────────────────────────────────────────
eq('enum MERGEABLE', normalizeMergeable('MERGEABLE'), 'MERGEABLE')
eq('enum CONFLICTING', normalizeMergeable('CONFLICTING'), 'CONFLICTING')
eq('lowercase enum is the same enum', normalizeMergeable('conflicting'), 'CONFLICTING')
eq('legacy true', normalizeMergeable(true), 'MERGEABLE')
eq('legacy false', normalizeMergeable(false), 'CONFLICTING')
eq('null stays UNKNOWN', normalizeMergeable(null), 'UNKNOWN')
eq('missing stays UNKNOWN', normalizeMergeable(undefined), 'UNKNOWN')
eq('an unknown string never becomes CONFLICTING', normalizeMergeable('DIRTY'), 'UNKNOWN')

// ── head binding ────────────────────────────────────────────────────────────────────────────────────────────
const rv = (raw: unknown) => normalizeFactor<ReviewState>(raw, ['MERGE', 'CHANGES', 'NONE'], HEAD, 'review')
eq('review on the exact head counts', rv({ state: 'MERGE', head_sha: HEAD, as_of: '2026-11-02T17:00:00Z', source: 'ledger' }).state, 'MERGE')
const moved = rv({ state: 'MERGE', head_sha: OLD, as_of: '2026-11-02T17:00:00Z', source: 'ledger' })
eq('review for another head is UNKNOWN', moved.state, 'UNKNOWN')
check('head_changed is stated with both heads', !!moved.reason && moved.reason.includes('head_changed') && moved.reason.includes(shortSha(OLD)) && moved.reason.includes(shortSha(HEAD)), moved.reason)
eq('a review receipt naming no head is UNKNOWN', rv({ state: 'MERGE' }).state, 'UNKNOWN')
eq('a free-text review is not a state', rv({ state: 'looks good to me', head_sha: HEAD }).state, 'UNKNOWN')
eq('no receipt is UNKNOWN', rv(null).state, 'UNKNOWN')
eq('no row head cannot bind', normalizeFactor<ReviewState>({ state: 'MERGE', head_sha: HEAD }, ['MERGE'], '', 'review').state, 'UNKNOWN')
eq('source_gap survives as the reason', normalizeFactor<ReviewState>({ state: 'MERGE', head_sha: HEAD, source_gap: 'no_typed_receipt' }, ['MERGE'], HEAD, 'review').reason, 'no_typed_receipt')

// ── CI: red, green, pending, skipped (draft) ────────────────────────────────────────────────────────────────
const ci = (state: string, head = HEAD) => normalizeFactor<CiState>({ state, head_sha: head, source: 'receipt' }, ['GREEN', 'RED', 'PENDING', 'SKIPPED'], HEAD, 'ci')
eq('CI red', ci('RED').state, 'RED')
eq('CI red is danger', ciLabel2(ci('RED')).tone, 'danger')
eq('CI green', ciLabel2(ci('GREEN')).tone, 'success')
eq('CI pending is not red', ciLabel2(ci('PENDING')).tone, 'info')
eq('CI skipped (draft) is not red', ciLabel2(ci('SKIPPED')).tone, 'neutral')
eq('CI for an older head is UNKNOWN', ci('RED', OLD).state, 'UNKNOWN')

// ── the work block ──────────────────────────────────────────────────────────────────────────────────────────
const work = (over: Record<string, unknown> = {}) => normalizeWork({
  owner: 'cc2', current_task: 'backend contract', publication_state: 'published',
  local_head: HEAD, published_head: HEAD,
  review: { state: 'MERGE', head_sha: HEAD, as_of: '2026-11-02T17:00:00Z', source: 'ledger' },
  ci: { state: 'GREEN', head_sha: HEAD, as_of: '2026-11-02T17:01:00Z', source: 'receipt' },
  blockers: [], next_action: 'merge', as_of: '2026-11-02T17:02:00Z', source: 'claims', ...over,
}, HEAD)

const w = work()
eq('owner', w.owner, 'cc2')
eq('review bound', w.review.state, 'MERGE')
eq('ci bound', w.ci.state, 'GREEN')
eq('as_of is the source time, not captured time', w.as_of, '2026-11-02T17:02:00Z')
eq('publication published', publicationLabel(w).text, 'PUBLISHED · on remote')
eq('local ahead of published is visible', publicationLabel(work({ local_head: OLD })).text.startsWith('PUBLISHED · local'), true)
eq('local-only work is never "published"', publicationLabel(work({ publication_state: 'local_only' })).tone, 'warning')
eq('unpublished text', publicationLabel(work({ publication_state: 'local_only' })).text, 'LOCAL · unpublished work')
eq('merged is success', publicationLabel(work({ publication_state: 'merged' })).tone, 'success')
eq('live is success', publicationLabel(work({ publication_state: 'live' })).tone, 'success')
eq('a made-up publication state is UNKNOWN', publicationLabel(work({ publication_state: 'shipped-ish' })).tone, 'warning')

// blockers: strings and objects both render; empty is empty
eq('blocker strings', work({ blockers: ['waiting on CI'] }).blockers[0].text, 'waiting on CI')
eq('blocker objects', work({ blockers: [{ kind: 'claim', text: 'claim conflict', owner: 'cc2' }] }).blockers[0].owner, 'cc2')
eq('no blockers', work({ blockers: null }).blockers.length, 0)

// old backend: no work block at all
const old = normalizeWork(undefined, HEAD)
eq('old backend: work not present', old.present, false)
eq('old backend: review UNKNOWN', old.review.state, 'UNKNOWN')
eq('old backend: reason says the backend predates it', (old.reason ?? '').includes('predates'), true)
check('old backend: nothing is invented green', old.ci.state === 'UNKNOWN' && old.owner === null)

// ── row → view ──────────────────────────────────────────────────────────────────────────────────────────────
const row = (over: Record<string, unknown> = {}) => normalizeRow({
  number: 2485, title: 'Releases view', url: 'https://example/2485', head_sha: HEAD, branch: 'wt/x',
  is_draft: false, mergeable: 'MERGEABLE', merge_state: 'CLEAN', why_held: null, next: 'auto-merge',
  work: { owner: 'cc2', current_task: 't', publication_state: 'published', local_head: HEAD, published_head: HEAD,
    review: { state: 'MERGE', head_sha: HEAD }, ci: { state: 'GREEN', head_sha: HEAD }, blockers: [],
    next_action: 'merge', as_of: '2026-11-02T17:02:00Z', source: 'claims' }, ...over,
})

eq('row mergeable from the enum', row().mergeable, 'MERGEABLE')
eq('row is not draft', draftLabel(row()).text, 'READY')
eq('draft label', draftLabel(row({ is_draft: true })).text, 'DRAFT')
eq('stated next action wins', nextActionFor(row()), 'merge')
check('row facts carry owner and task', rowFacts(row()).owner === 'cc2' && rowFacts(row()).task === 't')
check('row facts carry as_of and source', rowFacts(row()).asOf === '2026-11-02T17:02:00Z' && rowFacts(row()).source === 'claims')

// UNKNOWN mergeability must never say auto-rebase
const unknownRow = row({ mergeable: 'UNKNOWN', merge_state: 'UNKNOWN', next: 'auto-rebase', work: undefined })
eq('UNKNOWN mergeable does not become auto-rebase', nextActionFor(unknownRow), 'unknown: mergeability not stated (not auto-rebase)')
eq('CONFLICTING mergeable is a conflict', nextActionFor(row({ mergeable: 'CONFLICTING', next: 'coordinator', work: undefined })), 'coordinator: resolve conflict')
eq('draft next step', nextActionFor(row({ is_draft: true, work: undefined })), 'author: mark ready for review')

// a renamed backend field must not crash the board
const legacy = normalizeRow({ number: 7, headRefOid: OLD, headRefName: 'wt/legacy', isDraft: true, mergeable: 'CONFLICTING' })
eq('legacy wire headRefOid', legacy.head_sha_short, shortSha(OLD))
eq('legacy wire isDraft', legacy.is_draft, true)
eq('legacy wire mergeable enum', legacy.mergeable, 'CONFLICTING')

// review labels
eq('review merge', reviewLabel(work().review).text, 'REVIEW · passed')
eq('review changes', reviewLabel(work({ review: { state: 'CHANGES', head_sha: HEAD } }).review).tone, 'danger')
eq('review none', reviewLabel(work({ review: { state: 'NONE', head_sha: HEAD } }).review).text, 'REVIEW · none')
check('review unknown carries its reason', reviewLabel(work({ review: null }).review).text.includes('UNKNOWN'))

// ── coordination envelope ──────────────────────────────────────────────────────────────────────────────────
const missing = normalizeCoordination(undefined)
eq('no coordination: not present', missing.present, false)
eq('no coordination: UNAVAILABLE', missing.status, 'UNAVAILABLE')
check('no coordination: reason names the old backend', (missing.reason ?? '').includes('predates'))

const co = normalizeCoordination({
  status: 'PARTIAL', as_of: '2026-11-02T17:00:00Z', source: 'claims',
  agents: [
    { session: 'cc2', agent: 'claude', task: 'backend contract', state: 'working', branch: 'wt/x', pr: 2485, as_of: '2026-11-02T16:59:00Z', source: 'claims' },
    { session: 'cc4', task: 'frontend', state: 'blocked', blocker: 'needs the wire', next_action: 'wait for cc2', source: 'claims' },
    { task: 'no session — dropped' },
    { session: 'ghost', state: 'flying' },
  ],
})
eq('status PARTIAL is kept', co.status, 'PARTIAL')
eq('partial is still present', co.present, true)
eq('three agents survive (the one with no session is dropped)', co.agents.length, 3)
eq('agent pr', co.agents[0].pr, 2485)
eq('agent state', co.agents[1].state, 'blocked')
eq('agent next action', co.agents[1].next_action, 'wait for cc2')
eq('unrecognised agent state is unknown', co.agents[1].state === 'blocked' ? normalizeCoordination({ status: 'OK', agents: [{ session: 'x', state: 'flying' }] }).agents[0].state : 'n/a', 'unknown')
eq('agent tones', [agentStateTone('assigned'), agentStateTone('working'), agentStateTone('blocked'), agentStateTone('waiting'), agentStateTone('idle'), agentStateTone('unknown')].join(','), 'info,success,danger,info,neutral,warning')

// The exact shape the backend sends (releases_coordination.build at 57c7939e): a BOARD row is "assigned",
// never "working", and execution is a separate field the claim proves.
const beAgent = normalizeCoordination({
  status: 'OK', as_of: '2026-11-02T18:00:00Z', source: 'claims+coordinator_ledger',
  agents: [{ session: 'cc2', claim_id: 'c1', task: 'backend ledger', state: 'assigned', branch: 'wt/be', pr: 2501,
    head_sha: HEAD, blocker: null, next_action: null, as_of: '2026-11-02T18:00:00Z', source: 'board+claims',
    execution_state: 'UNKNOWN', claim_as_of: null, branch_or_pr: 'wt/be' }],
}).agents[0]
eq('BOARD "assigned" is assigned, not working', beAgent.state, 'assigned')
eq('the source word is kept', beAgent.reported_state, 'assigned')
eq('a claim-backed agent shows execution separately', beAgent.execution_state, null)
eq('branch_or_pr fills branch', beAgent.branch, 'wt/be')
eq('a claim stage building is working', normalizeCoordination({ status: 'OK', agents: [{ session: 'c3', state: 'building' }] }).agents[0].state, 'working')
eq('a claim at pr_open is waiting', normalizeCoordination({ status: 'OK', agents: [{ session: 'c4', state: 'pr_open' }] }).agents[0].state, 'waiting')
eq('the literal UNKNOWN next_action is not text', beAgent.next_action, null)
eq('assigned is amber-free but distinct', agentStateTone(beAgent.state), 'info')

eq('review passed is not "merge requested"', reviewLabel({ state: 'MERGE', reported: 'MERGE', head_sha: HEAD, as_of: null, as_of_basis: null, source: null, reason: null }).text, 'REVIEW · passed')
eq('a made-up status is UNAVAILABLE', normalizeCoordination({ status: 'GREAT', agents: [] }).status, 'UNAVAILABLE')

// ── schema compatibility ───────────────────────────────────────────────────────────────────────────────────
eq('v1 remains known', (KNOWN_SCHEMAS as readonly string[]).includes(IN_FLIGHT_SCHEMA), true)
eq('v2 additive is known', (KNOWN_SCHEMAS as readonly string[]).includes(IN_FLIGHT_SCHEMA_V2), true)

// ── review aggregation: BLOCK dominates, count is not a verdict ────────────────────────────────────────────
const rev = (verdicts: unknown[], head = HEAD) => normalizeReview({ head_sha: head, source: 'ledger', verdicts }, head)
eq('one BLOCK is blocked', rev([{ verdict: 'BLOCK', reviewer: 'cc3' }]).state, 'CHANGES')
eq('a BLOCK alone is never green', reviewLabel(rev([{ verdict: 'BLOCK', reviewer: 'cc3' }])).tone, 'danger')
eq('all MERGE is merge', rev([{ verdict: 'MERGE', reviewer: 'a' }, { verdict: 'MERGE', reviewer: 'b' }]).state, 'MERGE')
const mixed = rev([{ verdict: 'MERGE', reviewer: 'a' }, { verdict: 'BLOCK', reviewer: 'b' }])
eq('MERGE beside BLOCK is not green', mixed.state, 'CHANGES')
check('the conflict is stated', (mixed.reason ?? '').includes('conflicting_verdicts'), mixed.reason)
eq('latest verdict per reviewer wins (block then merge)', rev([
  { verdict: 'BLOCK', reviewer: 'a', as_of: '2026-11-02T10:00:00Z' },
  { verdict: 'MERGE', reviewer: 'a', as_of: '2026-11-02T11:00:00Z' },
]).state, 'MERGE')
eq('latest verdict per reviewer wins (merge then block)', rev([
  { verdict: 'MERGE', reviewer: 'a', as_of: '2026-11-02T10:00:00Z' },
  { verdict: 'BLOCK', reviewer: 'a', as_of: '2026-11-02T11:00:00Z' },
]).state, 'CHANGES')
eq('a verdict on another head is not this head\'s review', rev([{ verdict: 'BLOCK', reviewer: 'a', head_sha: OLD }]).state, 'UNKNOWN')
eq('records count alone is not a review', normalizeReview({ count: 12, head_sha: HEAD }, HEAD).state, 'UNKNOWN')
check('count-only says why', (normalizeReview({ count: 12, head_sha: HEAD }, HEAD).reason ?? '').includes('count'))
eq('records array works like verdicts', normalizeReview({ head_sha: HEAD, records: [{ verdict: 'BLOCK', by: 'cc3' }] }, HEAD).state, 'CHANGES')
eq('case and request_changes are normalised', rev([{ verdict: 'request_changes', reviewer: 'a' }]).state, 'CHANGES')
eq('an unrecognised word is not a verdict', rev([{ verdict: 'probably fine', reviewer: 'a' }]).state, 'UNKNOWN')

// CI times: as_of preferred, observed_at is the explicit honest fallback, never a capture time.
const ciObserved = normalizeFactor<CiState>({ state: 'GREEN', head_sha: HEAD, observed_at: '2026-11-02T17:00:00Z' }, ['GREEN'], HEAD, 'ci')
eq('observed_at fills a missing as_of', ciObserved.as_of, '2026-11-02T17:00:00Z')
eq('the fallback is labelled', ciObserved.as_of_basis, 'observed_at')
eq('as_of wins when both are present', normalizeFactor<CiState>({ state: 'GREEN', head_sha: HEAD, as_of: '2026-11-02T17:00:00Z', observed_at: '2026-11-02T16:00:00Z' }, ['GREEN'], HEAD, 'ci').as_of, '2026-11-02T17:00:00Z')
eq('no time is stated as none', normalizeFactor<CiState>({ state: 'GREEN', head_sha: HEAD }, ['GREEN'], HEAD, 'ci').as_of, null)

console.log(`deployInFlight: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
