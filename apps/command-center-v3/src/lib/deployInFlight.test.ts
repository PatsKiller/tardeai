// Releases & schedules → Deploy in flight: the typed model. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/deployInFlight.test.ts
//
// Covers the failure classes the operator reported: a GitHub enum read as a boolean (every row UNKNOWN →
// "auto-rebase"), a review/CI receipt for an older head shown as current, local-only work shown as published,
// and an old backend (no `work` / no `coordination`) pretending to have facts.
import {
  IN_FLIGHT_SCHEMA, IN_FLIGHT_SCHEMA_V2, KNOWN_SCHEMAS, agentStateTone, ciLabel2, draftLabel, evidenceSentence, evidenceState, executionState, nextActionFor,
  normalizeCoordination, normalizeFactor, normalizeMergeable, normalizeReview, normalizeRow, normalizeRows, normalizeWork, publicationLabel,
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
eq('an array is not a work block', normalizeWork([], HEAD).present, false)
eq('nor is a string', normalizeWork('facts', HEAD).present, false)
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
eq('a claim stage building is a declaration, not proof', normalizeCoordination({ status: 'OK', agents: [{ session: 'c3', state: 'building' }] }).agents[0].state, 'assigned')
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

// The 9a0ae89e work keys: next_action_source, board_owner, and gap (not source_gap) as the honest reason.
const w9 = normalizeWork({
  owner: 'UNKNOWN', board_owner: 'cc4', current_task: 'releases frontend', publication_state: 'UNKNOWN',
  local_head: null, published_head: HEAD, review: { state: 'UNKNOWN', head_sha: null, source: 'none', gap: 'stale_review_for_other_head' },
  ci: { state: 'UNKNOWN', head_sha: null, source: 'none', gap: 'stale_ci_for_other_head' },
  blockers: [], next_action: 'land the test fix', next_action_source: 'board_open_prs', as_of: null, source: 'claims',
}, HEAD)
eq('board_owner is carried as context', w9.board_owner, 'cc4')
eq('the next step keeps its source', w9.next_action_source, 'board_open_prs')
eq('a review gap is the reason, not "names no head"', w9.review.reason, 'stale_review_for_other_head')
eq('a CI gap is the reason', w9.ci.reason, 'stale_ci_for_other_head')
eq('an absent source clock stays null', w9.as_of, null)
eq('BOARD context names the owner without inventing a claim', rowFacts(row({ work: w9 })).owner, 'cc4 · BOARD context')
eq('a derived next step says so', rowFacts(row({ work: { ...w9, next_action: null, next_action_source: null } })).nextSource, 'derived here')

// ── the five BLOCK classes, defensively on the frontend ────────────────────────────────────────────────────
const NOW_MS = Date.parse('2026-11-02T19:00:00Z')
const ago = (m: number) => new Date(NOW_MS - m * 60_000).toISOString()
eq('a 30-minute heartbeat proves working', executionState('working', ago(30), NOW_MS).state, 'working')
eq('a 5-day heartbeat does not', executionState('working', ago(5 * 24 * 60), NOW_MS).state, null)
check('and says why', (executionState('working', ago(5 * 24 * 60), NOW_MS).reason ?? '').includes('older than 2h'))
eq('no heartbeat time does not', executionState('working', null, NOW_MS).state, null)
check('and says why', (executionState('working', null, NOW_MS).reason ?? '').includes('no heartbeat'))
eq('a future heartbeat is clock skew, not working', executionState('working', ago(-60), NOW_MS).state, null)
check('and says why', (executionState('working', ago(-60), NOW_MS).reason ?? '').includes('future'))
eq('unparseable heartbeat is not working', executionState('working', 'not a time', NOW_MS).state, null)
eq('a non-working word is kept as itself', executionState('blocked', null, NOW_MS).state, 'blocked')

// empty-head evidence never becomes MERGE/GREEN
eq('blank review head is UNKNOWN', normalizeReview({ state: 'MERGE', head_sha: '' }, HEAD).state, 'UNKNOWN')
eq('blank CI head is UNKNOWN', normalizeFactor<CiState>({ state: 'GREEN', head_sha: '   ' }, ['GREEN'], HEAD, 'ci').state, 'UNKNOWN')

// multiclaim join: two rows for one session keep the NEWER branch/task and say how many were folded
const dup = normalizeCoordination({ status: 'OK', agents: [
  { session: 'cc4', task: 'old task', state: 'assigned', branch: 'wt/old', as_of: '2026-11-02T10:00:00Z' },
  { session: 'cc4', task: 'new task', state: 'assigned', branch: 'wt/new', as_of: '2026-11-02T18:00:00Z' },
] }, NOW_MS)
eq('one row per session', dup.agents.length, 1)
eq('the newest task wins', dup.agents[0].task, 'new task')
eq('the newest branch wins', dup.agents[0].branch, 'wt/new')
eq('the fold count is stated', dup.agents[0].duplicate_rows, 2)

// ── P0 BLOCK 2026-11-02: mixed verdicts stay UNKNOWN; execution uses claim_as_of; null rows survive ──────
const rv9 = (records: unknown[], envelope?: string) => normalizeReview({ head_sha: HEAD, source: 'ledger', state: envelope, records }, HEAD)
eq('MERGE + unrecognised stays UNKNOWN', rv9([{ verdict: 'MERGE', reviewer: 'a' }, { verdict: 'MAYBE', reviewer: 'b' }]).state, 'UNKNOWN')
check('and says the set is mixed', /unrecognised|mixed/.test(rv9([{ verdict: 'MERGE', reviewer: 'a' }, { verdict: 'MAYBE', reviewer: 'b' }]).reason ?? ''))
eq('MERGE + explicit UNKNOWN stays UNKNOWN', rv9([{ verdict: 'MERGE', reviewer: 'a' }, { verdict: 'UNKNOWN', reviewer: 'b' }]).state, 'UNKNOWN')
eq('BLOCK + unrecognised is still blocked', rv9([{ verdict: 'BLOCK', reviewer: 'a' }, { verdict: 'MAYBE', reviewer: 'b' }]).state, 'CHANGES')
eq('a backend UNKNOWN is never upgraded to MERGE', rv9([{ verdict: 'MERGE', reviewer: 'a' }], 'UNKNOWN').state, 'UNKNOWN')
eq('a backend BLOCK is never overridden by merge records', rv9([{ verdict: 'MERGE', reviewer: 'a' }], 'BLOCK').state, 'CHANGES')
// A state-only review (no records) must use the same vocabulary — found on the served bundle 2026-11-03.
eq('state-only BLOCK is blocked, not unrecognised', normalizeReview({ state: 'BLOCK', head_sha: HEAD }, HEAD).state, 'CHANGES')
eq('state-only APPROVE is passed', normalizeReview({ state: 'APPROVE', head_sha: HEAD }, HEAD).state, 'MERGE')
eq('state-only CHANGES_REQUESTED is blocked', normalizeReview({ state: 'CHANGES_REQUESTED', head_sha: HEAD }, HEAD).state, 'CHANGES')
eq('state-only nonsense stays UNKNOWN', normalizeReview({ state: 'PROBABLY', head_sha: HEAD }, HEAD).state, 'UNKNOWN')
check('state-only BLOCK never reads as passed', reviewLabel(normalizeReview({ state: 'BLOCK', head_sha: HEAD }, HEAD)).text.startsWith('REVIEW · blocked'))

// A contradictory envelope: the envelope names another head while its members name this one.
const contra = normalizeReview({ state: 'MERGE', head_sha: OLD, records: [{ verdict: 'MERGE', reviewer: 'a', head_sha: HEAD }] }, HEAD)
eq('envelope/member head contradiction is UNKNOWN', contra.state, 'UNKNOWN')
check('and names the contradiction', (contra.reason ?? '').includes('envelope'), contra.reason)
eq('an envelope naming this head still aggregates', normalizeReview({ state: 'MERGE', head_sha: HEAD, records: [{ verdict: 'MERGE', reviewer: 'a' }] }, HEAD).state, 'MERGE')
eq('two clean MERGEs still pass', rv9([{ verdict: 'MERGE', reviewer: 'a' }, { verdict: 'MERGE', reviewer: 'b' }]).state, 'MERGE')

const agentWith = (over: Record<string, unknown>) => normalizeCoordination({ status: 'OK', agents: [{
  session: 'cc4', state: 'assigned', execution_state: 'working', ...over }] }, NOW_MS).agents[0]
eq('a stale claim_as_of is not rescued by a fresh BOARD as_of',
  agentWith({ as_of: ago(1), claim_as_of: ago(5 * 24 * 60), source: 'board+claims' }).execution_state, null)
check('and the reason names the heartbeat',
  (agentWith({ as_of: ago(1), claim_as_of: ago(5 * 24 * 60), source: 'board+claims' }).execution_reason ?? '').includes('older than 2h'))
eq('a fresh claim_as_of proves working even when as_of is old',
  agentWith({ as_of: ago(5 * 24 * 60), claim_as_of: ago(30), source: 'board+claims' }).execution_state, 'working')
eq('claim-only rows use their own as_of', agentWith({ as_of: ago(30), source: 'claims' }).execution_state, 'working')
eq('a BOARD-only row has no heartbeat to prove execution', agentWith({ as_of: ago(1), source: 'board' }).execution_state, null)

eq('a null row is projected defensively, not crashed', normalizeRow(null).number, 0)
eq('a numeric row likewise', normalizeRow(7).title, '')
const members: unknown[] = [null, { number: 1, head_sha: HEAD }, undefined, { number: 2 }]
const kept = members.filter((p): p is Record<string, unknown> => !!p && typeof p === 'object')
eq('null members are dropped before projection', kept.length, 2)
eq('the surviving rows project', kept.map(p => normalizeRow(p).number).join(','), '1,2')
eq('normalizeRows counts what it dropped', normalizeRows([null, { number: 3 }, undefined, { number: 4 }]).dropped, 2)
eq('normalizeRows keeps the survivors', normalizeRows([null, { number: 3 }, undefined, { number: 4 }]).rows.map(r => r.number).join(','), '3,4')
eq('a whole non-array is empty, not a crash', normalizeRows(null).rows.length, 0)

// The exact payload from the independent review: an object with a non-callable toString as review.state.
// String() on it throws "Cannot convert object to primitive value"; every coercion is guarded at normalization.
const evil = { toString: 'Synthetic malformed JSON value' }
let threw: unknown = null
let ew: ReturnType<typeof normalizeWork> | null = null
try { ew = normalizeWork({ review: { state: evil, head_sha: HEAD }, ci: { state: evil, head_sha: HEAD } }, HEAD) } catch (e) { threw = e }
eq('object-valued state does not throw', threw, null)
eq('and the review is UNKNOWN', ew?.review.state, 'UNKNOWN')
eq('and the CI is UNKNOWN', ew?.ci.state, 'UNKNOWN')
eq('mergeable objects are UNKNOWN, not coerced', normalizeMergeable(evil), 'UNKNOWN')
eq('a whole object-valued row projects', normalizeRow({ number: 1, title: evil, head_sha: evil, mergeable: evil, merge_state: evil, next: evil }).merge_state, 'UNKNOWN')
eq('object-valued agent state is unknown', normalizeCoordination({ status: 'OK', agents: [{ session: 'x', state: evil, execution_state: evil }] }).agents[0].state, 'unknown')
const evilWire = normalizeRows([{ number: 4001, head_sha: HEAD, title: 't', work: { review: { state: evil, head_sha: HEAD } } }])
eq('the board payload still projects its row', evilWire.rows.length, 1)
eq('with the review UNKNOWN', evilWire.rows[0].work.review.state, 'UNKNOWN')

// ---- row 05: "UNKNOWN" on every PR was four different situations wearing one word. Each now has a sentence, and a
// state we do not recognise stays unrecognised instead of becoming a pass.
eq('evidence OBSERVED', evidenceSentence('OBSERVED'), 'checked')
eq('evidence STALE_OTHER_HEAD', evidenceSentence('STALE_OTHER_HEAD'), 'checked, but for an older version of the change')
eq('evidence NOT_RECORDED', evidenceSentence('NOT_RECORDED'), 'no check is recorded')
eq('evidence SOURCE_UNAVAILABLE', evidenceSentence('SOURCE_UNAVAILABLE'), 'the record of the check could not be read')
eq('evidence state is case-insensitive', evidenceState('observed'), 'OBSERVED')
eq('an unrecognised evidence state stays null', evidenceState('WAT'), null)
eq('no state gives no sentence', evidenceSentence(undefined), null)

// cc3's served contract adds two states to the vocabulary; both must read as words, never as a pass.
eq('evidence PARTIAL', evidenceSentence('PARTIAL'), 'partly checked — one of the sources did not answer')
eq('evidence TARGET_HEAD_MISSING', evidenceSentence('TARGET_HEAD_MISSING'), 'the check refers to a version that is no longer the one proposed')

// cc3 review F1: normalizeRow builds an explicit object, so a served field it does not name is lost. Eligibility must
// survive the projection, or the page falls back to a heuristic the live payload never satisfies.
const withActions = normalizeRow({ number: 7, title: 't', url: 'u', head_sha: HEAD, branch: 'b', mergeable: 'MERGEABLE',
  operator_actions: { required: true, eligible: ['approve', 'push'], reason: 'yours', withheld: [{ action: 'hold', why: 'no label' }] } })
eq('operator_actions survives normalization', withActions.operator_actions?.eligible.join(','), 'approve,push')
eq('withheld survives normalization', withActions.operator_actions?.withheld?.[0]?.why, 'no label')
eq('a row with no actions normalizes to null', normalizeRow({ number: 8, head_sha: HEAD }).operator_actions, null)
eq('an unknown action word is dropped', normalizeRow({ number: 9, head_sha: HEAD, operator_actions: { required: false, eligible: ['nuke'], reason: null } }).operator_actions?.eligible.length, 0)
// ---- cx-openai-4's three P1s on #2517 (2026-11-03): each was a PASS displayed where the truth is unknown or blocked.
// R3: clocks compared as text let an older MERGE beat a newer BLOCK.
const r3 = normalizeReview({ head_sha: HEAD, source: 'ledger', verdicts: [
  { verdict: 'MERGE', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' },
  { verdict: 'BLOCK', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00.900Z' },
] }, HEAD)
eq('R3 a sub-second-newer BLOCK beats an older MERGE', r3.state, 'CHANGES')

// R2: an explicit source gap cannot be discarded once records parse.
const r2 = normalizeReview({ head_sha: HEAD, source: 'ledger', source_gap: 'stale_review_for_other_head', verdicts: [
  { verdict: 'MERGE', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' },
] }, HEAD)
eq('R2 a source gap keeps the aggregate unknown', r2.state, 'UNKNOWN')
const r2b = normalizeReview({ head_sha: HEAD, source: 'ledger', gap: 'review_source_unavailable', verdicts: [
  { verdict: 'MERGE', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' },
] }, HEAD)
eq('R2 the other gap spelling is not discarded either', r2b.state, 'UNKNOWN')

// R1: an envelope word outside the vocabulary fails closed, even beside a MERGE member.
const r1 = normalizeReview({ head_sha: HEAD, source: 'ledger', state: 'WAT', verdicts: [
  { verdict: 'MERGE', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' },
] }, HEAD)
eq('R1 an unrecognised envelope is not a pass', r1.state, 'UNKNOWN')
check('R1 and it says which word it could not read', (r1.reason ?? '').toUpperCase().includes('WAT'))
const r1b = normalizeReview({ head_sha: HEAD, source: 'ledger', verdicts: [
  { verdict: 'REQUEST_CHANGES', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' },
  { verdict: 'MERGE', reviewer: 'cc3', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' },
] }, HEAD)
eq('R1 a blocking member beside a merge member is blocked', r1b.state, 'CHANGES')

// ---- cx-openai-4's surviving P1: the envelope's REQUEST_CHANGES must survive a MERGE member.
// Asserted at the REAL call path (normalizeRow -> normalizeWork -> normalizeReview), not on the helper.
const rowWith = (review: unknown) => normalizeRow({ number: 7, title: 't', url: 'u', head_sha: HEAD, branch: 'b',
  mergeable: 'MERGEABLE', merge_state: 'CLEAN', is_draft: false, work: { present: true, review } })
eq('P1 envelope REQUEST_CHANGES beside a MERGE member stays blocked',
  rowWith({ state: 'REQUEST_CHANGES', head_sha: HEAD,
    records: [{ verdict: 'MERGE', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' }] }).work.review.state,
  'CHANGES')
eq('P1 the same through the verdicts key', 
  rowWith({ state: 'REQUEST_CHANGES', head_sha: HEAD,
    verdicts: [{ verdict: 'MERGE', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' }] }).work.review.state,
  'CHANGES')
eq('P1 an unrecognised envelope beside a MERGE member stays UNKNOWN',
  rowWith({ state: 'WAT', head_sha: HEAD,
    records: [{ verdict: 'MERGE', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' }] }).work.review.state,
  'UNKNOWN')
eq('P1 a plain MERGE envelope with MERGE records is still a pass',
  rowWith({ state: 'MERGE', head_sha: HEAD,
    records: [{ verdict: 'MERGE', reviewer: 'cc2', head_sha: HEAD, as_of: '2026-11-03T12:00:00Z' }] }).work.review.state,
  'MERGE')

console.log(`deployInFlight: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
