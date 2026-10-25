import {awaitingAi, coverageWord, decisionBody, decisionError, fingerprint, liveCountRows, pct, pendingProposals, proposalCases, proposalModel,
  proposalResolutions, proposalTestCount, statusWords, unmatchedStatus} from './conflictRulesModel.ts'

const same = (a: unknown, b: unknown) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`Expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`) }
const match = (a: string, re: RegExp) => { if (!re.test(a)) throw new Error(`Unexpected text: ${a}`) }

const pending = {proposal_id: 'rp-1', status: 'PENDING', revision: 7, signature: 'ups-a', plain_rule: 'Treat X as WATCH.', tier: 'T4',
  test_cases: [{}, {}, {}], proposed_resolution: [{finding_key: 'k1', resolution: 'Desk X counts as WATCH; no flag.'}],
  model: {provider: 'grok', model_id: 'grok-4'}}
const done = {proposal_id: 'rp-2', status: 'APPROVED', revision: 3, signature: 'ups-b'}
const collection = {proposals: [pending, done], unmatched: [
  {signature: 'ups-a', summary: 'desk says X', proposal_id: 'rp-1', proposal_status: 'Proposed rule awaiting your approval',
    examples: [{key: 'k1', summary: 'X vs WATCH', subject: {label: 'AAA'}}]},
  {signature: 'ups-c', summary: 'unknown role', proposal_id: null, proposal_status: 'AI proposal pending', last_failure: {reason: 'ungrounded_number'}}]}

same(pendingProposals(collection).map(p => p.proposal_id), ['rp-1'])
same(pendingProposals(null), [])
same(proposalTestCount(pending), 3)
same(proposalTestCount(done), null)
same(proposalResolutions(pending), ['Desk X counts as WATCH; no flag.'])
same(proposalResolutions(done), [])
same(proposalModel(pending), 'grok · grok-4')
same(proposalModel({proposal_id: 'x', model: {provider: 'grok', mock: true}}), 'grok (mock)')
same(proposalModel(done), 'model not recorded')
same(proposalCases(pending, collection).map(c => c.key), ['k1'])
same(awaitingAi(collection).map(r => r.signature), ['ups-c'])
same(unmatchedStatus(collection.unmatched[0]), 'Proposed rule awaiting your approval')
same(unmatchedStatus(collection.unmatched[1]), 'AI proposal pending · last attempt failed: ungrounded number')

const keep = {plain_rule: 'Treat X as WATCH.', tier: 'T4'}
same(decisionBody('reject', '  ', pending, keep, true).ok, false)
same(decisionBody('reject', 'too broad', pending, keep, true), {ok: true, body: {decision: 'reject', reason: 'too broad', expected_revision: 7}})
same(decisionBody('approve', 'fine', pending, keep, true), {ok: true, body: {decision: 'approve', reason: 'fine', expected_revision: 7, apply_current_case: true}})
same(decisionBody('approve', 'fine', {...pending, revision: undefined}, keep, true).ok, false)
same(decisionBody('edit-and-approve', 'tighter', pending, keep, false).ok, false)
same(decisionBody('edit-and-approve', 'tighter', pending, {plain_rule: ' ', tier: 'T4'}, false).ok, false)
same(decisionBody('edit-and-approve', 'stricter', pending, {plain_rule: 'Treat X as WATCH.', tier: 'T2'}, false),
  {ok: true, body: {decision: 'edit-and-approve', reason: 'stricter', expected_revision: 7, edited: {tier: 'T2'}, apply_current_case: false}})
same(decisionBody('edit-and-approve', 'narrower', pending, {plain_rule: ' New rule ', tier: 'T4'}, true),
  {ok: true, body: {decision: 'edit-and-approve', reason: 'narrower', expected_revision: 7, edited: {plain_rule: 'New rule'}, apply_current_case: true}})

same(decisionError(409, {error: 'NEVER_AUTO_REFUSED', reason: 'Safety rules always go to you.'}), 'Safety rules always go to you.')
match(decisionError(503, {error: 'PROPOSAL_DECISIONS_NOT_ACTIVATED'}), /Approval activation is pending/)
same(decisionError(500, null), 'HTTP 500')

same(liveCountRows({DATA_ERROR: 2, NEEDS_OPERATOR: 1, ZZZ: 1}).map(r => r.kind), ['NEEDS_OPERATOR', 'DATA_ERROR', 'ZZZ'])
same(liveCountRows({GATE: 3})[0].label, 'Blocked by a check')
const proposed = statusWords({status: 'PROPOSED', live_enabled: false} as never)
same(proposed.tone, 'warning')
match(proposed.headline, /not yet approved/)
match(proposed.live, /Not live/)
same(statusWords({status: 'APPROVED', live_enabled: true} as never).tone, 'success')
same(fingerprint('e40e97179386206cf04ac'), 'e40e97179386…')
same(fingerprint(null), 'not pinned')
same(pct(12), '12%')
same(pct(10.8), '10.8%')
same(pct(null), 'not set')
same(coverageWord('IMPLEMENTED'), {label: 'Implemented', tone: 'success'})
same(coverageWord('MISSING'), {label: 'Missing', tone: 'danger'})
console.log('conflictRulesModel: ok')
