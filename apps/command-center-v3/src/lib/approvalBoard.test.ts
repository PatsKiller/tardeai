import { projectApprovalBoard, toneForApprovalState, ttlLabel } from './approvalBoard.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const absent = projectApprovalBoard(null)
check('no payload is UNAVAILABLE with a danger tone', absent.status === 'UNAVAILABLE' && absent.statusTone === 'danger' && absent.rows.length === 0)

const partial = projectApprovalBoard({
  status: 'PARTIAL', as_of: '2026-10-08T01:40:00+00:00', total: 1,
  sources: { packages: { status: 'OK', count: 1 }, grants: { status: 'UNAVAILABLE', reason: 'FileNotFoundError: cli' } },
  counts: { package: { OPEN: 1 } }, expiring: [], expiring_count: 0,
  items: [{ kind: 'package', id: 'pkg-1', scope: 'c:w', state: 'OPEN', expires_at: '2026-10-09T01:00:00+00:00', ttl_min_left: 1400, items_total: 3, items_pending: 2, reason: 'wave 1' }],
})
check('a partial board names the dead source', partial.status === 'PARTIAL' && partial.statusTone === 'warning' && partial.sourceNotes[0].startsWith('grants: UNAVAILABLE'))
check('package rows carry the pending count and a long ttl label', partial.rows[0].pendingLabel === '2/3 pending' && partial.rows[0].ttlLabel === '23 h 20 min left' && partial.rows[0].tone === 'info')

const ok = projectApprovalBoard({
  status: 'OK', as_of: '2026-10-08T01:40:00+00:00', total: 3,
  counts: { package: { OPEN: 1, EXPIRED: 1 }, grant: { ACTIVE: 1 } },
  expiring: [{ kind: 'grant', id: 'g-9' }], expiring_count: 1,
  items: [
    { kind: 'grant', id: 'g-9', scope: 'release-write', state: 'ACTIVE', ttl_min_left: 7, uses_left: 9, reason: 'promote 51200f611' },
    { kind: 'package', id: 'pkg-2', scope: 'c:w', state: 'OPEN', ttl_min_left: 25, items_total: 1, items_pending: 1, reason: 'x' },
    { kind: 'package', id: 'pkg-0', scope: 'c:w', state: 'EXPIRED', ttl_min_left: -90, items_total: 1, items_pending: 1, reason: 'old' },
  ],
})
check('OK label carries the row total and the as-of clock', ok.status === 'OK' && ok.statusLabel === 'OK · 3 rows' && ok.asOfLabel === '2026-10-08 01:40')
check('expiring rows are flagged from the server list', ok.expiringCount === 1 && ok.rows[0].expiring === true && ok.rows[1].expiring === false)
check('tones: ≤10 min danger, ≤30 min warning, expired danger', ok.rows[0].tone === 'danger' && ok.rows[1].tone === 'warning' && ok.rows[2].tone === 'danger')
check('ttl labels', ok.rows[0].ttlLabel === '7 min left' && ok.rows[2].ttlLabel === 'expired 90 min ago' && ttlLabel(null, 'OPEN') === 'no expiry')
check('grant rows keep uses left', ok.rows[0].usesLeft === 9 && ok.rows[1].usesLeft === null)
check('counts flatten per kind and state', ok.counts.map(c => `${c.kind}:${c.state}=${c.n}`).join(',') === 'grant:ACTIVE=1,package:OPEN=1,package:EXPIRED=1')
check('state tones without a clock', toneForApprovalState('CONSUMED', null) === 'success' && toneForApprovalState('DENIED', null) === 'danger' && toneForApprovalState('DRAFT', null) === 'neutral')

console.log(`approvalBoard: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
