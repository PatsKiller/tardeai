import {coverageWord, decisionBody, fingerprint, liveCountRows, pct, pendingProposals, proposalResolution, proposalTestCount, statusWords, unmatchedStatus} from './conflictRulesModel.ts'

const same = (a: unknown, b: unknown) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`Expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`) }
const assert = {equal: same, deepEqual: same, match: (a: string, re: RegExp) => { if (!re.test(a)) throw new Error(`Unexpected text: ${a}`) }}

const pending = {id: 'p1', state: 'PENDING', unmatched_cases: [{key: 'k1'}], test_cases: [1, 2, 3], proposed_resolution: {summary: 'CIO decides'}}
const done = {id: 'p2', state: 'APPROVED', unmatched_cases: [{key: 'k2'}], test_case_count: 4}

assert.deepEqual(pendingProposals({proposals: [pending, done]}).map(p => p.id), ['p1'])
assert.deepEqual(pendingProposals(null), [])
assert.equal(proposalTestCount(pending), 3)
assert.equal(proposalTestCount(done), 4)
assert.equal(proposalTestCount({id: 'x'}), null)
assert.equal(proposalResolution(pending), 'CIO decides')
assert.equal(proposalResolution({id: 'x'}), 'Proposed resolution not supplied')

assert.equal(unmatchedStatus('k1', {proposals: [pending, done]}, true), 'AI proposal pending — awaiting your approval')
assert.equal(unmatchedStatus('k2', {proposals: [pending, done]}, true), 'AI proposal approved')
assert.equal(unmatchedStatus('k3', {proposals: [pending]}, true), 'AI proposal pending — not drafted yet')
assert.equal(unmatchedStatus('k1', null, false), 'AI proposal status unavailable')

assert.equal(decisionBody('reject', '  ', '', 'x').ok, false)
assert.deepEqual(decisionBody('reject', 'too broad', '', 'x'), {ok: true, body: {decision: 'reject', reason: 'too broad'}})
assert.deepEqual(decisionBody('approve', 'fine', '', 'x', 2), {ok: true, body: {decision: 'approve', reason: 'fine', expected_revision: 2}})
assert.equal(decisionBody('edit-and-approve', 'tighter', 'rule', 'rule').ok, false)
assert.equal(decisionBody('edit-and-approve', 'tighter', '', 'rule').ok, false)
assert.deepEqual(decisionBody('edit-and-approve', 'tighter', ' new rule ', 'rule'),
  {ok: true, body: {decision: 'edit-and-approve', reason: 'tighter', edited_rule_text: 'new rule'}})

assert.deepEqual(liveCountRows({DATA_ERROR: 2, NEEDS_OPERATOR: 1, ZZZ: 1}).map(r => r.kind), ['NEEDS_OPERATOR', 'DATA_ERROR', 'ZZZ'])
assert.equal(liveCountRows({GATE: 3})[0].label, 'Blocked by a check')

const proposed = statusWords({status: 'PROPOSED', live_enabled: false} as never)
assert.equal(proposed.tone, 'warning')
assert.match(proposed.headline, /not yet approved/)
assert.match(proposed.live, /Not live/)
assert.equal(statusWords({status: 'APPROVED', live_enabled: true} as never).tone, 'success')

assert.equal(fingerprint('e40e97179386206cf04ac'), 'e40e97179386…')
assert.equal(fingerprint(null), 'not pinned')
assert.equal(pct(12), '12%')
assert.equal(pct(10.8), '10.8%')
assert.equal(pct(null), 'not set')
assert.deepEqual(coverageWord('IMPLEMENTED'), {label: 'Implemented', tone: 'success'})
assert.deepEqual(coverageWord('MISSING'), {label: 'Missing', tone: 'danger'})
console.log('conflictRulesModel: ok')
