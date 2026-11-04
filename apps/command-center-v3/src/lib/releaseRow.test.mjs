// node --experimental-strip-types src/lib/releaseRow.test.mjs
import { releaseRowModel, releaseVerdict } from './releaseRow.ts'
import { verifyLabel } from './releasesSchedules.ts'
let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }
const SHA = '105df180ec68a1a20e700c185a14f638a77122a3'
const base = { receipt: 'receipt-20261104-091803', mode: 'promote', at: '2026-11-04T09:18:03Z', sha: SHA, short_sha: '105df180ec68',
  sha_basis: 'deploy receipt readback', release_name: 'release-20261104', prs: [2602, 2623], prs_reason: null, verify: { ok: true }, verify_reason: null }

const good = releaseRowModel(base, 'Nov 4 09:18 ET')
const vis = [good.purpose, good.changes, good.blocker ?? '', good.nextAction, good.when].join(' ')
check('a verified release says nothing is left to do', good.verdict.kind === 'verified' && good.nextAction === 'Nothing to do.')
check('the visible half carries no SHA', !vis.includes(SHA) && !vis.includes('105df180ec68'), vis)
check('the visible half carries no git wording', !/git |sha_basis|readback/i.test(vis), vis)
check('the changes are named as PRs', good.changes === 'PR 2602, PR 2623', good.changes)
check('the SHA and its basis survive in diagnostics', JSON.stringify(good.diagnostics).includes(SHA) && JSON.stringify(good.diagnostics).includes('readback'))

const bad = releaseRowModel({ ...base, verify: { ok: false, readback_errors: ['serving pin mismatch'] }, verify_reason: 'serving pin mismatch' }, 'Nov 4 09:18 ET')
check('a failed verification is NOT VERIFIED and says so', bad.verdict.kind === 'not_verified' && /NOT VERIFIED/.test(bad.verdict.label), bad.verdict.label)
// the kind and the existing label must never disagree, for every shape the record can take
for (const shape of [base, { ...base, verify: { ok: false } }, { ...base, verify: null }, { ...base, mode: 'rollback' }, { ...base, verify: { ok: true, rolled_back: true } }, { ...base, verify: { ok: true, readback_errors: ['x'] } }]) {
  const k = releaseVerdict(shape), l = verifyLabel(shape)
  const agree = (k === 'verified' && l.tone === 'success') || (k === 'not_verified' && l.text === 'NOT VERIFIED')
    || (k === 'rollback' && l.text === 'ROLLBACK') || (k === 'not_recorded' && /not retained/.test(l.text))
  check(`kind ${k} agrees with the label "${l.text}"`, agree)
}
check('it states the blocker it was given', /did not verify/.test(bad.blocker ?? ''), String(bad.blocker))
check('and points at the receipt', /deploy receipt/.test(bad.nextAction), bad.nextAction)

const none = releaseRowModel({ ...base, verify: null }, 'x')
check('a release with no verification is not called verified', none.verdict.kind === 'not_recorded' && /cannot be called verified/.test(none.blocker ?? ''), String(none.blocker))
const roll = releaseRowModel({ ...base, mode: 'rollback' }, 'x')
check('a rollback is named as one', roll.verdict.kind === 'rollback' && /rollback/i.test(roll.purpose), roll.purpose)
const unnamed = releaseRowModel({ ...base, release_name: null }, 'x')
check('an unnamed release admits it, rather than showing a receipt id as a name', /without a name/.test(unnamed.purpose), unnamed.purpose)
const noPrs = releaseRowModel({ ...base, prs: null, prs_reason: 'receipt has no PR member' }, 'x')
check('unrecorded PRs say why', /not recorded \(receipt has no PR member\)/.test(noPrs.changes), noPrs.changes)
console.log(`releaseRow: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
