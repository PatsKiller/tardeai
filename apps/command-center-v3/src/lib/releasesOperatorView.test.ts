// Releases & Schedules operator view: plain words, honest clocks, no machine identifiers.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/releasesOperatorView.test.ts
import {
  checkSentence, goingLive, jobsLine, liveNow, needsYou, needsYouAction, needsYouFacts, plainReason, plainText, stuck,
} from './releasesOperatorView.ts'
import type { SectionView } from './releasesSchedules.ts'
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
check('a green reviewed change is the operator’s to approve', needsYou([pr()]).length === 1)
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
  work: { ...pr().work, review: { state: 'UNKNOWN', reason: 'no_review_record' }, ci: { state: 'UNKNOWN', reason: 'no_ci_observation' } },
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

console.log(`releasesOperatorView: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
