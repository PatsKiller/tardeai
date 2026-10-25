import { assetUrl, canSubmit, decidedAt, designMessage, mergeRecent, outcomeTone, thumbsFor } from './designApprovals.ts'
const fail = (m: string) => { throw new Error(m) }
const assert = {
  equal: (a: unknown, b: unknown) => { if (a !== b) fail(`${JSON.stringify(a)} !== ${JSON.stringify(b)}`) },
  deepEqual: (a: unknown, b: unknown) => { if (JSON.stringify(a) !== JSON.stringify(b)) fail(`${JSON.stringify(a)} != ${JSON.stringify(b)}`) },
  match: (a: string, re: RegExp) => { if (!re.test(a)) fail(`${a} !~ ${re}`) },
}

// Three widths in order; a missing width stays missing.
const t = thumbsFor([{ path: 'v002/mockups/m-390.png', width: 390, sha256: 'a' }, { path: 'v002/mockups/m-1440.png', width: 1440, sha256: 'b' }])
assert.deepEqual(t.map(x => [x.width, x.image?.path ?? null]), [[1440, 'v002/mockups/m-1440.png'], [412, null], [390, 'v002/mockups/m-390.png']])

// ET, readable, never raw ISO.
assert.equal(decidedAt('2026-10-24'), 'Oct 24')
assert.equal(decidedAt('2026-10-25T14:25:00+00:00'), 'Oct 25 10:25 ET')
assert.equal(decidedAt(null), 'Time not recorded')
assert.equal(decidedAt('garbage'), 'Time not recorded')

// Reject needs a reason; busy blocks double taps.
assert.equal(canSubmit('APPROVE', '', false), true)
assert.equal(canSubmit('REJECT', '  ', false), false)
assert.equal(canSubmit('REJECT', 'why', false), true)
assert.equal(canSubmit('APPROVE', '', true), false)

assert.equal(outcomeTone('Approved'), 'success')
assert.equal(outcomeTone('Rejected'), 'danger')
assert.match(designMessage('STORE_APPROVAL_PENDING'), /sign-off/)
assert.match(designMessage('UNKNOWN'), /unavailable/)
assert.equal(assetUrl('watch', 'v002', 'v002/mockups/a b.png'), '/api/v2/design/asset?page=watch&version=v002&path=v002%2Fmockups%2Fa%20b.png')

// Board 19: design titles kept, other decisions labelled by kind, de-duplicated, newest first.
const merged = mergeRecent(
  [{ id: 'design-version:x/v002', title: 'X v002', decision: 'APPROVE', outcome: 'Approved', at: '2026-10-26T01:00:00+00:00', actor: 'op', recorded: 'ledger' },
   { id: 'backfill:a', title: 'Desk boards', decision: 'APPROVE', outcome: 'Approved', at: '2026-10-24', actor: 'operator', recorded: 'recorded in handoff' }],
  [{ item_id: 'design-version:x/v002', decision: 'APPROVE', at: '2026-10-26T01:00:00+00:00', kind: 'DESIGN' },
   { item_id: 'policy:9', decision: 'REQUEST_CHANGES', at: '2026-10-25T12:00:00+00:00', kind: 'POLICY' }],
  { POLICY: 'Policy' })
assert.deepEqual(merged.map(m => m.title), ['X v002', 'Policy decision', 'Desk boards'])
assert.equal(merged[1].outcome, 'Changes requested')
console.log('designApprovals.test: ok')
