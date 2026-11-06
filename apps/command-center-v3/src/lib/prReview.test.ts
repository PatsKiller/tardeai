// node --experimental-strip-types src/lib/prReview.test.ts — synthetic values only.
const assert = {
  equal(a: unknown, b: unknown) { if (a !== b) throw new Error(`expected ${String(b)}, got ${String(a)}`) },
  match(a: string, re: RegExp) { if (!re.test(a)) throw new Error(`unexpected text: ${a}`) },
}
import { approveBlock, approveEffect, cancelledApprovals, checksText, classText, etTime, plusMinus, waited } from './prReview.ts'

const merge = { head_sha: 'a'.repeat(40), held: false, reviewed: true, stale: false, state: 'ready' as const, refusal: null }
const opts = { reviewId: 'review_x', unread: 0, applierLive: true }

assert.equal(approveBlock({ merge, decisions_store_approved: false }, opts), 'Decision store not yet approved')
assert.equal(approveBlock({ merge: { ...merge, refusal: 'REVIEW_STALE' }, decisions_store_approved: true }, opts), 'A new push is being re-reviewed')
assert.equal(approveBlock({ merge: { ...merge, refusal: 'REVIEW_REQUIRED', state: 'credit' }, decisions_store_approved: true }, opts), 'The review is waiting for credit')
assert.equal(approveBlock({ merge, decisions_store_approved: true }, { ...opts, unread: 2 }), 'Read 2 more findings')
assert.match(String(approveBlock({ merge, decisions_store_approved: true }, { ...opts, applierLive: false })), /separate held PR/)
assert.equal(approveBlock({ merge: { ...merge, held: true }, decisions_store_approved: true }, { ...opts, applierLive: false }), null)
assert.equal(approveBlock({ merge, decisions_store_approved: true }, opts), null)

assert.match(approveEffect(true, 9110, 'e02d5f1aa'), /adds no label/)
assert.match(approveEffect(false, 9107, '7c41e2a90'), /operator-merge for this head only/)

assert.equal(checksText({ a: 'SUCCESS', b: 'SUCCESS', c: 'SUCCESS', d: 'SUCCESS' }, true), 'checks 4/4 green')
assert.equal(checksText({ a: 'SUCCESS', b: 'PENDING' }, false), 'checks running')
assert.equal(classText({ held: ['merge_deploy_control'], shared_infra: false }), 'held · merge & deploy tooling')
assert.equal(classText({ held: [], shared_infra: true }), 'shared-infra')
assert.equal(plusMinus([{ additions: 3, deletions: 1 }, { additions: 2, deletions: 0 }]), '+5 −1')

const now = Date.parse('2031-03-04T17:00:00Z')
assert.equal(waited('2031-03-04T16:20:00Z', now), 'waiting 40 min')
assert.equal(waited('2031-03-04T15:00:00Z', now), 'waiting 2 h')
assert.match(etTime('2031-03-04T17:14:00Z', new Date(now)), /^Today 12:14 PM ET$/)
assert.equal(etTime(null), '—')

const ds = [{ at: '', decision: 'APPROVE', effect: 'OPERATOR_MERGE_LABEL', head_sha: 'old', source_sha: 'old', actor: 'op', comment: '' },
  { at: '', decision: 'APPROVE', effect: 'OPERATOR_MERGE_LABEL', head_sha: 'new', source_sha: 'new', actor: 'op', comment: '' }]
assert.equal(cancelledApprovals(ds, 'new').length, 1)
