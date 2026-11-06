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

// Cloud review 2026-11-05 (P2): `read_history()` nulls verify_reason when it attaches a deploy receipt and keeps the failure
// detail in verify.readback_errors, so the row must not say "no reason was recorded" beside the exact error.
const receiptOnly = releaseRowModel({ ...base, verify: { ok: false, readback_errors: ['serving pin mismatch on /health'] }, verify_reason: null }, 'x')
check('a failure held only in the receipt still names its reason', /serving pin mismatch on \/health/.test(receiptOnly.blocker ?? ''), String(receiptOnly.blocker))
check('and never claims no reason was recorded', !/no reason was recorded/.test(receiptOnly.blocker ?? ''), String(receiptOnly.blocker))
check('the readback errors are retained in Diagnostics', JSON.stringify(receiptOnly.diagnostics).includes('serving pin mismatch on /health'))

// Cloud review 2026-11-05 (P2): a rollback is an operation, not a successful recovery — it can itself fail to verify.
const rollFailed = releaseRowModel({ ...base, mode: 'rollback', verify: { ok: false, readback_errors: ['previous version did not come back'] }, verify_reason: null }, 'x')
check('a rollback that did not verify never says the previous version is back', !/restored deliberately/.test(rollFailed.nextAction), rollFailed.nextAction)
check('a failed rollback says it did not verify, and why', /did not verify/.test(rollFailed.blocker ?? '') && /previous version did not come back/.test(rollFailed.blocker ?? ''), String(rollFailed.blocker))
check('a failed rollback points at the rollback receipt', /rollback receipt/.test(rollFailed.nextAction), rollFailed.nextAction)
const rollOk = releaseRowModel({ ...base, mode: 'rollback', verify: { ok: true, rolled_back: true } }, 'x')
check('a rollback that verified still says the previous version was restored', /restored deliberately/.test(rollOk.nextAction), rollOk.nextAction)
// Cloud review 2026-11-05 (P2): the visible line keeps six PR numbers and a count, so the rest must stay identifiable in
// Diagnostics — the old history table listed up to twelve, and truncating without this lost PRs 7..12 entirely.
const many = releaseRowModel({ ...base, prs: [1, 2, 3, 4, 5, 6, 7, 8, 9] }, 'x')
check('the reading line stays compact past six PRs', many.changes === 'PR 1, PR 2, PR 3, PR 4, PR 5, PR 6 and 3 more', many.changes)
const manyPrs = many.diagnostics.find(d => d.label === 'PRs')?.value ?? ''
check('every PR number survives in Diagnostics', [7, 8, 9].every(n => manyPrs.includes(`PR ${n}`)), manyPrs)
check('and the visible line does not pretend they were named', !/PR 7/.test(many.changes), many.changes)
const noPrsDiag = releaseRowModel({ ...base, prs: null, prs_reason: 'receipt has no PR member' }, 'x').diagnostics.some(d => d.label === 'PRs')
check('a record with no PR list invents no PR diagnostics row', !noPrsDiag)
console.log(`releaseRow: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
