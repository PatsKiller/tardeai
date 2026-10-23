// Work pipeline Tier 2 model: words, phrase rule, flags.  node --experimental-strip-types src/lib/workPipelineTier2.test.ts
import { canCreate, disabledReason, needsWords, phraseMatches, requestParams, type Tier2Action } from './workPipelineTier2.ts'
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`) }
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const approve: Tier2Action = { kind: 'pipeline.approve_design', label: 'Approve', params: { design_id: 'DSN-20261022-data-domains' }, enabled: true }
const merge: Tier2Action = { kind: 'pipeline.merge_pr', label: 'Merge PR 1997', params: { pr: 1997, head_sha: 'a'.repeat(40) }, enabled: false, policy_note: 'OFF until an AGENTS.md clause allows a merge' }

t('approvals carry the operator words; merge does not', () => {
  eq(needsWords(approve.kind), true); eq(needsWords(merge.kind), false)
  eq(requestParams(approve, '  approve B-D  '), { design_id: 'DSN-20261022-data-domains', words: 'approve B-D' })
  eq(requestParams({ ...merge, enabled: true }, 'x'), { pr: 1997, head_sha: 'a'.repeat(40) })
})
t('a disabled kind cannot create a request and says why', () => {
  eq(canCreate(merge, ''), false); eq(disabledReason(merge), 'OFF until an AGENTS.md clause allows a merge')
  eq(canCreate(approve, 'ok'), false); eq(canCreate(approve, 'approved'), true)
})
t('typed phrase: whitespace collapsed, otherwise exact', () => {
  eq(phraseMatches(' APPROVE DESIGN  DSN-x 2026-10-23 ', 'APPROVE DESIGN DSN-x 2026-10-23'), true)
  eq(phraseMatches('approve design DSN-x 2026-10-23', 'APPROVE DESIGN DSN-x 2026-10-23'), false)
  eq(phraseMatches('x', null), false)
})
console.log(`workPipelineTier2: ${n} passed`)
