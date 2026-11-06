// Releases & Schedules operator view: plain words, honest clocks, no machine identifiers.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/releasesOperatorView.test.ts
import {
  agentStateSentence, checkSentence, coordinationNote, coordinationSource, engineerPanelProps, flightFreshnessNote,
  flightSource, goingLive, goingLiveSentence, jobsLine, liveNow, mergedWaiting, needsYou, needsYouAction,
  needsYouFacts, PANEL_NONE, panelSentence, plainReason, plainText, stuck, type Panel,
} from './releasesOperatorView.ts'
import type { SectionView } from './releasesSchedules.ts'
import { normalizeRow } from './deployInFlight.ts'
declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) { if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) } }
const when = (v: string | null | undefined) => (v ? `at ${v}` : 'unknown')
const sec = (value: unknown, extra: Partial<SectionView<unknown>> = {}): SectionView<unknown> =>
  ({ value, state: 'OK', asOf: '2026-11-03T15:00:00Z', source: 'fixture', reason: null, label: 'OK', ...extra }) as SectionView<unknown>

// ---- plain text: identifiers never reach the operator
check('a SHA is stripped', !/[0-9a-f]{7,}/i.test(plainText('Fix the widget a41d7274b3fc9cf7acca58823e652cf1c0cda3a7')))
check('a PR number is stripped', !/#\d+/.test(plainText('Land the test fix (#2501)')))
check('a branch name is stripped', !/wt\//.test(plainText('wt/disk-pressure-act-20261103 ready')))
check('empty text falls back', plainText('') === 'an unnamed change')
check('a reason code becomes a sentence', plainReason('no_review_record') === 'nobody has recorded a review for this version yet')
check('an unknown reason code is not shown raw', plainReason('some_new_code') === 'the source says: some new code')

// ---- review / CI sentences
check('a passed review says nothing', checkSentence({ state: 'MERGE' }) === null)
check('changes asked for', checkSentence({ state: 'CHANGES' }) === 'a reviewer asked for changes')
check('red checks', checkSentence({ state: 'RED' }) === 'the checks failed')
check('unknown with a gap code', checkSentence({ state: 'UNKNOWN', gap: 'no_ci_observation' }) === 'the checks for this version have not been observed')

// ---- block 1: what is live, with its clock
const live = liveNow({ serving: sec({ release_name: 'Home health fix', since: '2026-11-03T11:37:00Z' }), next_release: sec({ is_serving: true }), release_errors: sec({ rows: [] }) }, null, when)
check('live line names the release in words', live.headline.includes('Home health fix') && !/[0-9a-f]{7,}/i.test(live.headline))
check('live line carries its clock', live.clock.startsWith('Checked at'))
const noSource = liveNow({ serving: sec(null, { state: 'UNAVAILABLE', reason: 'git_failed' }) }, null, when)
check('an unavailable source is never an all-clear', noSource.tone !== 'success' && /not an all-clear/i.test(noSource.detail))
const buildId = liveNow({ serving: sec({ release_name: 'release-20261103123058-a41d7274b' }), next_release: sec({ is_serving: true }), release_errors: sec({ rows: [] }) }, null, when)
check('a build id is not printed as the release name', !/a41d7274b/.test(buildId.headline))

// ---- blocks 2-4: who acts, where a change is, what is stuck
const pr = (over: Record<string, unknown> = {}) => ({
  number: 1, title: 'Fix it', url: 'u', head_sha: 'a'.repeat(40), head_sha_short: 'aaaaaaa', branch: 'wt/x',
  has_operator_merge: false, mergeable: 'MERGEABLE', merge_state: 'CLEAN', is_draft: false, why_held: null, next: 'auto-merge',
  work: { present: true, owner: 'cc4', current_task: 't', publication_state: 'published', local_head: null, published_head: null,
    review: { state: 'MERGE', reason: null }, ci: { state: 'GREEN', reason: null }, blockers: [], next_action: null,
    next_action_source: null, board_owner: null, as_of: '2026-11-03T14:00:00Z', source: 's', reason: null }, ...over,
}) as any
check('a green reviewed legacy row remains visible for inspection', needsYou([pr()]).length === 1)
check('a draft is not the operator’s', needsYou([pr({ is_draft: true })]).length === 0)
check('a conflicted change is not the operator’s', needsYou([pr({ mergeable: 'CONFLICTING' })]).length === 0)
check('an already-queued change is not the operator’s', needsYou([pr({ has_operator_merge: true })]).length === 0)
const groups = goingLive([pr(), pr({ mergeable: 'CONFLICTING' }), pr({ is_draft: true })])
check('groups are in plain order', groups.every((g, i) => i === 0 || groups[i - 1].stage !== g.stage))
check('a conflicted change is stuck and the coordinator fixes it', (() => { const r = stuck([pr({ mergeable: 'CONFLICTING' })]); return r.length === 1 && r[0].because === 'conflicts with newer code' })())
check('a clean change is not stuck', stuck([pr()]).length === 0)

// ---- block 8: a number never appears without its clock
const jobs = jobsLine(sec({ total: 1560, errors_total: 10, dead_letters: { available: true, unreleased: 1017, recent: [] } }), when)
check('jobs sentence is in words', jobs.text.includes('1,560 runs today') && jobs.text.includes('1,017 failed runs'))
check('jobs sentence carries its clock', jobs.clock.startsWith('counted'))
const jobsGone = jobsLine(sec(null, { state: 'UNAVAILABLE', reason: 'ledger unreadable' }), when)
check('an unreadable ledger is not zero runs', /not the same as zero runs/.test(jobsGone.text) && jobsGone.tone === 'warning')
const jobsNoClock = jobsLine(sec({ total: 3, errors_total: 0, dead_letters: { available: true, unreleased: 0 } }, { asOf: null }), when)
check('a missing clock is stated, never implied', /as of unknown/.test(jobsNoClock.clock))

// ---- the SERVER decides who may act; the UI never overrules it
const withActions = (acts: any) => pr({ operator_actions: acts })
check('server eligibility gates the operator list', needsYou([withActions({ required: true, eligible: ['approve'], reason: null })]).length === 1)
check('a row the server did not open for approval is not the operator’s',
  needsYou([withActions({ required: false, eligible: ['hold'], reason: 'not yours' })]).length === 0)
check('github evidence that could not be fetched is never green',
  checkSentence({ state: 'UNAVAILABLE', reason: 'github check rollup fetch failed' }) === 'CI not checked right now')

// cc3 review F3: "no record of a review" is not a stuck change — the served contract says so explicitly.
const notRecorded = pr({ work: { ...pr().work, review: { state: 'UNKNOWN', reason: 'no_review_record' }, ci: { state: 'UNAVAILABLE', reason: 'not fetched' } } })
check('an unreviewed change is not stuck', stuck([notRecorded]).length === 0)
check('a change with requested changes is stuck', stuck([pr({ work: { ...pr().work, review: { state: 'CHANGES', reason: null } } })]).length === 1)
check('a change with failed checks is stuck', stuck([pr({ work: { ...pr().work, ci: { state: 'RED', reason: null } } })]).length === 1)
check('a named blocker is stuck', stuck([pr({ work: { ...pr().work, blockers: [{ text: 'waiting', owner: 'cc2', as_of: null }] } })]).length === 1)

// cc3 review F5: the server flags approval AND push-budget decisions as the operator's; both belong in Needs you,
// and the card must offer the action the server actually listed.
const pushOnly = pr({ operator_actions: { required: true, eligible: ['push'], reason: 'upload limit', withheld: [] } })
check('a push-budget decision is in Needs you', needsYou([pushOnly]).length === 1)
check('a push-budget card offers authorising the upload', needsYouAction(pushOnly).kind === 'push' && /upload/i.test(needsYouAction(pushOnly).label))
check('an approval card offers approving', needsYouAction(pr({ operator_actions: { required: true, eligible: ['approve'], reason: null } })).kind === 'approve')
check('a row the server did not flag and did not list is not in Needs you',
  needsYou([pr({ operator_actions: { required: false, eligible: [], reason: 'the agent has the next step' } })]).length === 0)

// cc3 review F6: the card used to say the work was finished and the checks passed, unconditionally. On the push-budget
// rows the server flags, that is the opposite of what the payload says.
const pushDraft = pr({ is_draft: true, merge_state: 'BLOCKED',
  work: { ...pr().work, publication_state: 'local_only', review: { state: 'UNKNOWN', reason: 'no_review_record' }, ci: { state: 'UNKNOWN', reason: 'no_ci_observation' } },
  operator_actions: { required: true, eligible: ['push'], reason: 'upload limit', withheld: [] } })
const pushFacts = needsYouFacts(pushDraft, needsYouAction(pushDraft))
check('a push card never claims the checks passed', !/checks passed|green/i.test(pushFacts.headline) && /not been uploaded/i.test(pushFacts.headline))
check('a blocked push card names the blockage', /blocked/i.test(pushFacts.warning ?? ''))
const dirtyFacts = needsYouFacts(pr({ mergeable: 'CONFLICTING', operator_actions: { required: true, eligible: ['push'], reason: null } }),
  { kind: 'push' })
check('a conflicting push card names the conflict and does not forbid the upload',
  /conflicts with newer code/i.test(dirtyFacts.warning ?? '') && /upload is still possible/i.test(dirtyFacts.warning ?? ''))
const approveFacts = needsYouFacts(pr({ operator_actions: { required: true, eligible: ['approve'], reason: null } }), { kind: 'approve' })
check('an approve card may say the checks passed when the payload proves it', /checks passed/i.test(approveFacts.headline))
const approveUnproven = needsYouFacts(pr({ work: { ...pr().work, review: { state: 'MERGE', reason: null }, ci: { state: 'UNKNOWN', reason: 'no_ci_observation' } } }), { kind: 'approve' })
check('an approve card does not invent a green check', !/checks passed/i.test(approveUnproven.headline) && /incomplete/i.test(approveUnproven.headline))

// cc2 review B1: the page must read GitHub's observed evidence, not the ledger's silence.
const ghRow = normalizeRow({ number: 11, title: 't', url: 'u', head_sha: 'b'.repeat(40), branch: 'b',
  work: { present: true, publication_state: 'published', as_of: '2026-11-03T16:00:00Z', source: 's',
    review: { state: 'UNKNOWN', reason: 'no_review_record' }, ci: { state: 'UNKNOWN', reason: 'no_ci_observation' },
    evidence_state: 'OBSERVED', evidence_sources: ['github_check_rollup', 'github_review_decision'],
    github_evidence: { ci: { state: 'RED', source: 'github_check_rollup' }, review: { state: 'NONE_REQUIRED', source: 'github_review_decision' } } } })
check('a red GitHub rollup is carried onto the row', ghRow.work.ci.state === 'RED')
check('a red rollup reads as failed checks, not "not observed"', checkSentence(ghRow.work.ci) === 'the checks failed')
check('no review required is not "nobody reviewed it"',
  (checkSentence(ghRow.work.review) ?? '') === 'no review is required for this change')
check('the served evidence state survives normalization', ghRow.work.evidence_state === 'OBSERVED'
  && (ghRow.work.evidence_sources ?? []).join(',') === 'github_check_rollup,github_review_decision')
const greenRow = normalizeRow({ number: 12, head_sha: 'c'.repeat(40),
  work: { present: true, ci: { state: 'UNKNOWN' }, review: { state: 'UNKNOWN' }, evidence_state: 'OBSERVED',
    github_evidence: { ci: { state: 'GREEN' }, review: { state: 'APPROVED' } } } })
check('a green rollup is not reported as unobserved', checkSentence(greenRow.work.ci) === null && greenRow.work.ci.state === 'GREEN')
const unfetched = normalizeRow({ number: 13, head_sha: 'd'.repeat(40),
  work: { present: true, ci: { state: 'UNKNOWN' }, evidence_state: 'PARTIAL',
    github_evidence: { ci: { state: 'UNAVAILABLE', reason: 'fetch failed' } } } })
check('an un-fetched rollup says so and is never green', /not checked/i.test(checkSentence(unfetched.work.ci) ?? '') && unfetched.work.ci.state !== 'GREEN')


// ---- codex R6 (#2541): a file path and a database-style identifier are machine diagnostics, not plain English
check('an absolute path is not printed', !/\/home\//.test(plainText('/home/example/project source_table_name')))
check('a snake_case identifier is not printed', !/source_table_name/.test(plainText('/home/example/project source_table_name')))
check('ordinary prose survives the cleaner', plainText('per item on hold') === 'per item on hold')

// ---- codex R2 (#2541): a RETAINED value is not a verified current one
const servingSections = (over: Record<string, unknown>, state = 'OK') => ({
  serving: sec({ release_name: 'rel-a', since: '2026-11-03T14:00:00Z', pins_agree: true, ...over }, { state: state as any }),
  next_release: sec({ is_serving: true }),
  release_errors: sec({ rows: [] }),
})
const staleLive = liveNow(servingSections({}, 'STALE') as any, '2026-11-03T15:00:00Z', when)
check('a stale serving reading is never "All good"', staleLive.tone !== 'success' && /older than 5 minutes/.test(staleLive.detail))
const pinClash = liveNow(servingSections({ pins_agree: false }) as any, '2026-11-03T15:00:00Z', when)
check('a pin disagreement is never "All good"', pinClash.tone !== 'success' && /disagrees/.test(pinClash.detail))
const noNext = liveNow({ ...servingSections({}), next_release: { ...sec(null), state: 'UNAVAILABLE', value: null } } as any, '2026-11-03T15:00:00Z', when)
check('an unreadable "what is next" is unknown, not "nothing is waiting"', !/Nothing is waiting/.test(noNext.detail) && /could not be read/.test(noNext.detail))
const noErrors = liveNow({ ...servingSections({}), release_errors: { ...sec(null), state: 'UNAVAILABLE', value: null } } as any, '2026-11-03T15:00:00Z', when)
check('an unreadable release-error source is unknown', !/Nothing is waiting/.test(noErrors.detail) && noErrors.tone !== 'success')
const allGood = liveNow(servingSections({}) as any, '2026-11-03T15:00:00Z', when)
check('a clean current reading is still "All good"', allGood.tone === 'success' && /Nothing is waiting/.test(allGood.detail))

// ---- codex R5 (#2541): merged is NOT live; only activation evidence may claim Live
const mergedRow = pr({ work: { ...pr().work, publication_state: 'merged' } })
const liveRow = pr({ work: { ...pr().work, publication_state: 'live' } })
const mergedGroups = goingLive([mergedRow])
check('a merged change is not shown as Live', !mergedGroups.some(g => g.stage === 'live'))
check('a merged change says it is waiting to go live', mergedGroups.some(g => g.label === 'Merged, waiting to go live'))
const liveGroups = goingLive([liveRow])
check('a change the producer reports live still groups as Live', liveGroups.some(g => g.stage === 'live'))

// ---- codex R3 (#2541): closed means closed, in the attribute AND the computed style
const closed = engineerPanelProps(false)
const opened = engineerPanelProps(true)
check('a closed engineer panel is hidden', closed.hidden === true && closed.style.display === 'none')
check('an open engineer panel is laid out', opened.hidden === false && opened.style.display === 'grid')


// ---- codex R5 (#2541): merged-but-not-live is derived from RELEASE data, not from a list of open pull requests
const nextAhead = { is_serving: false, commits_ahead: 2, committed_at: '2026-11-04T09:00:00Z',
  prs_since_serving: [2550, 2564], prs_reason: null, subject: 'x', sha: 's', short_sha: 's' }
const servingNow = { release_name: '056c4b2ca-main-exact', since: '2026-11-04T08:26:02Z' }
const ahead = mergedWaiting(nextAhead as any, servingNow as any, when)
check('merged-ahead-of-deploy is representable with no PR feed', ahead.waiting === true && /2 merged changes/.test(ahead.headline))
check('it dates the version that IS running', /has been serving since/.test(ahead.detail) && !/[0-9a-f]{7,}/i.test(ahead.detail))
check('it says the merged code is not running yet', /has not been promoted yet/.test(ahead.detail))
const current = mergedWaiting({ ...nextAhead, is_serving: true, commits_ahead: 0 } as any, servingNow as any, when)
check('main being the running version is not "waiting"', current.waiting === false && /is the version that is running/.test(current.headline))
const unreadable = mergedWaiting(null, servingNow as any, when)
check('an unreadable comparison is unknown, never an all-clear', unreadable.waiting === false && unreadable.tone === 'warning' && /cannot be read/i.test(unreadable.headline))
// cx-openai D52 at ea9442610: `is_serving: false` with no serving identity and no measured distance is what the
// backend emits when the serving SHA is unavailable — it must not become "A merge is not live yet".
const unidentifiedServing = mergedWaiting(
  { is_serving: false, commits_ahead: null, prs_reason: 'serving SHA unavailable' } as any, null, when)
check('an unidentified serving version is unknown, never "a merge is not live yet"',
  unidentifiedServing.known === false && unidentifiedServing.waiting === false
  && unidentifiedServing.tone === 'warning' && !/not live yet/i.test(unidentifiedServing.headline))
const servedButUncounted = mergedWaiting({ ...nextAhead, commits_ahead: null } as any, servingNow as any, when)
check('a known serving version with no measured distance is also unknown',
  servedButUncounted.known === false && servedButUncounted.waiting === false)
const countedButUnnamed = mergedWaiting({ ...nextAhead, commits_ahead: 2 } as any, null, when)
check('a measured distance with no serving block is still unknown rather than invented',
  countedButUnnamed.waiting === false && /cannot be read/i.test(countedButUnnamed.headline))
const single = mergedWaiting({ ...nextAhead, commits_ahead: 1 } as any, servingNow as any, when)
check('one change is singular', /1 merged change is not live yet/.test(single.headline))

// ---- codex R4 (#2541): the source's own state, for lists that DO have rows
check('a current list needs no note', flightFreshnessNote({}, when) === null)
check('a stale non-empty list says so', /out of date/.test(flightFreshnessNote({ stale: true, asOf: '2026-11-04T09:00:00Z' }, when) ?? ''))
check('a still-loading list says so', /still being read/.test(flightFreshnessNote({ loading: true }, when) ?? ''))
check('a partly-answered agent list is not "nobody working"', /only partly answered/.test(coordinationNote('PARTIAL') ?? ''))
check('an unanswered agent list says unknown', /did not answer/.test(coordinationNote('UNAVAILABLE') ?? ''))
check('a healthy agent list needs no note', coordinationNote('OK') === null)
check('an unrecorded agent state is NOT idle', agentStateSentence('').idle === null && agentStateSentence(undefined).idle === null)
check('an unrecognised agent state is NOT idle', agentStateSentence('pondering').idle === null)
check('working is not idle, and idle is', agentStateSentence('working').idle === false && agentStateSentence('idle').idle === true)
check('a stale agent report is unknown, not idle', agentStateSentence('stale').idle === null)


// ---- THE GENERAL PROPERTY (codex third read, #2541): every panel can say "I do not know", and does whenever its
//      inputs are insufficient. The table below is the whole rule: for each panel x each insufficient source state,
//      the panel must NOT claim "none", and the claim is allowed only on a current source.
const INSUFFICIENT = [
  { name: 'loading',     src: flightSource({ loading: true }, when) },
  { name: 'no answer',   src: flightSource({}, when) },
  { name: 'errored',     src: flightSource({ answered: true, error: 'boom' }, when) },
  { name: 'stale empty', src: flightSource({ stale: true }, when) },
  { name: 'stale rows',  src: flightSource({ answered: true, stale: true }, when) },
]
const PANELS: Panel[] = ['needs_you', 'going_live', 'stuck', 'agents']
for (const panel of PANELS) {
  for (const { name, src } of INSUFFICIENT) {
    const sentence = panelSentence(panel, src)
    check(`${panel}: a ${name} source never claims "none"`, sentence !== PANEL_NONE[panel])
    check(`${panel}: a ${name} source says it cannot tell`, /^Cannot tell /.test(sentence))
  }
  check(`${panel}: a CURRENT source may claim "none"`,
    panelSentence(panel, flightSource({ answered: true }, when)) === PANEL_NONE[panel])
}

// the three counterexamples codex measured, as source-level facts
const coordStale = coordinationSource({ status: 'OK', answered: true, stale: true }, when)
check('cached coordination with status OK is not current when the response is stale', coordStale.canAssertEmpty === false)
check('a stale agent list does not say nobody is working', panelSentence('agents', coordStale) !== PANEL_NONE.agents)
const coordPartial = coordinationSource({ status: 'PARTIAL', answered: true }, when)
check('a partly answered agent list does not say nobody is working', panelSentence('agents', coordPartial) !== PANEL_NONE.agents)
const coordMissing = coordinationSource({ status: null }, when)
check('a missing coordination block does not say nobody is working', panelSentence('agents', coordMissing) !== PANEL_NONE.agents)
const stuckStale = flightSource({ answered: true, stale: true }, when)
check('a stale open-change list does not say nothing is stuck', panelSentence('stuck', stuckStale) !== PANEL_NONE.stuck)
check('an unreadable open-change source does not say nothing needs you',
  panelSentence('needs_you', flightSource({ answered: true, error: 'x' }, when)) !== PANEL_NONE.needs_you)

// R5 contradiction: known merged work + unknown open-change census must not produce an empty-census claim
const knownWaiting = { known: true, waiting: true }
const unknownComparison = { known: false, waiting: false }
const currentFlight = flightSource({ answered: true }, when)
check('an unknown comparison never renders "nothing is going live"',
  goingLiveSentence(currentFlight, unknownComparison) !== PANEL_NONE.going_live)
check('an unknown comparison says the comparison could not be read',
  /could not be read/.test(goingLiveSentence(currentFlight, unknownComparison)))
check('known-merged + current empty census is allowed to say no open change is waiting',
  /No open change is waiting to merge/.test(goingLiveSentence(currentFlight, knownWaiting)))
check('known-merged + unknown census says it cannot tell whether an open change is waiting',
  /cannot tell whether an open change is also waiting/.test(goingLiveSentence(stuckStale, knownWaiting)))
check('no merged work + unknown census still says it cannot tell',
  goingLiveSentence(stuckStale, { known: true, waiting: false }) !== PANEL_NONE.going_live)


// ---- F2 (cx-openai-2): an approval is not a promise that the change will merge
const approvedRed = { number: 7, title: 't', url: 'u', head_sha: 'a'.repeat(40), head_sha_short: 'a',
  branch: 'wt/x', has_operator_merge: true, mergeable: 'MERGEABLE', merge_state: 'CLEAN', is_draft: false,
  why_held: null, next: 'auto-merge',
  work: { present: true, owner: 'cc4', current_task: 't', publication_state: 'published', local_head: null,
    published_head: null, review: { state: 'MERGE', reason: null }, ci: { state: 'RED', reason: null },
    blockers: [], next_action: null, next_action_source: null, board_owner: null, as_of: '2026-11-04T14:00:00Z',
    source: 's', reason: null } }
const g = goingLive([approvedRed as any])
check('approved-but-red is NOT shown as merging', !g.some(x => x.stage === 'merging'))
check('approved-but-red says something honest', g.length === 1 && g[0].label !== 'Merging in the next window')

console.log(`releasesOperatorView: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
