// node --experimental-strip-types src/lib/deploymentLog.test.mjs
// Deployment log view helpers (LQ-20261107-1794). Synthetic records only: the repository is PUBLIC, so the rows below
// carry invented ticket ids and subjects — no real ticker, holding, account or path.
import {
  commitLine, commitSubjects, fixedItems, fixedLine, kindLabel, logTitle, shownLine, summaryChips, truthChip, whenET,
} from './deploymentLog.ts'
import { etDateTime } from './releasesSchedules.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

const item = (lq, state, text = 'recorded by the builder') => ({ lq, title: `what ${lq} fixed`, owner: 'agent-example', truth: { state, text } })
const row = (over = {}) => ({ activated_at: '2026-11-10T10:54:24-05:00', activated_et: 'Tue 11-10 10:54 ET', kind: 'deploy',
  rollback: false, release: 'abcdef123-live-integration-20261110-105345', sha: 'abcdef123456', short_sha: 'abcdef123',
  previous_release: 'prev-live', previous_sha: 'prev123456', commit_count: 1,
  commits: ['LQ-9001: invented subject'], commits_shown: 1, items: [item('LQ-9001', 'VERIFIED')], is_current: false, ...over })

// ── the one rule: VERIFIED only for the record's exact VERIFIED ───────────────────────────────────────────────────
const t = (state) => truthChip({ state, text: 'why' })
check('the record VERIFIED is green', t('VERIFIED').label === 'VERIFIED' && t('VERIFIED').tone === 'success')
check('NOT_REMEASURED is amber and says so', t('NOT_REMEASURED').tone === 'warning' && t('NOT_REMEASURED').label === 'NOT RE-MEASURED', t('NOT_REMEASURED').label)
check('UNTRACKED is grey', t('UNTRACKED').tone === 'neutral')
check('NO_CHANGE is grey', t('NO_CHANGE').tone === 'neutral')
for (const state of ['verified', ' Verified', 'VERIFIED ', 'verified_by_test']) {
  const c = t(state)
  check(`"${state}" is not VERIFIED`, c.tone !== 'success' && c.label !== 'VERIFIED', `${c.label} / ${c.tone}`)
}
check('a missing truth member is NOT RECORDED, never green', truthChip(null).label === 'NOT RECORDED' && truthChip(null).tone === 'neutral')
check('an absent state is NOT RECORDED', truthChip({ state: null, text: null }).label === 'NOT RECORDED')
check('an empty state is NOT RECORDED', truthChip({ state: '', text: '' }).label === 'NOT RECORDED')
check('an unknown state is shown as unknown, with its own word', t('SOMETHING_NEW').label === 'UNKNOWN (SOMETHING_NEW)' && t('SOMETHING_NEW').tone === 'neutral')
check('the record truth text survives', t('VERIFIED').text === 'why' && truthChip({ state: 'NOT_REMEASURED', text: null }).text === null)
// exhaustive over the four states the builder writes: success iff and only iff VERIFIED
for (const s of ['VERIFIED', 'NOT_REMEASURED', 'NO_CHANGE', 'UNTRACKED']) check(`tone is success only for ${s}`, (truthChip({ state: s, text: null }).tone === 'success') === (s === 'VERIFIED'))

// ── summary chips: a count the record does not carry is unknown, never 0 ─────────────────────────────────────────
const chips = summaryChips({ summary: { deploys: 137, verified: 72, not_remeasured: 364 } })
check('the three summary counts are named', chips.map(c => c.label).join('|') === 'deploys|verified|not re-measured', chips.map(c => c.label).join('|'))
check('their values are formatted', chips[0].value === '137' && chips[2].value === '364')
check('a real zero stays a zero', summaryChips({ summary: { deploys: 0 } })[0].value === '0')
check('a missing count is unknown, not zero', summaryChips({ summary: { deploys: 1 } })[1].value === 'unknown')
check('no summary at all is three unknowns', summaryChips({}).every(c => c.value === 'unknown' && c.tone === 'warning'))
check('no log at all is three unknowns', summaryChips(null).every(c => c.value === 'unknown'))

// ── rows ─────────────────────────────────────────────────────────────────────────────────────────────────────────
check('fixed items are the LQ items it carries', fixedItems(row({ items: [item('LQ-1', 'VERIFIED'), item('LQ-2', 'NO_CHANGE')] })).length === 2)
check('an item with neither ticket nor title is dropped', fixedItems(row({ items: [{ lq: null, title: null }] })).length === 0)
check('no items array is an empty list, not a crash', fixedItems({}).length === 0 && fixedItems(null).length === 0)
check('a zero-LQ row shows its commit subjects', fixedLine(row({ items: [], commits: ['a', 'b'], commit_count: 2 })) === '2 commits', fixedLine(row({ items: [], commits: ['a', 'b'], commit_count: 2 })))
check('one commit is singular', commitLine(row({ commit_count: 1 })) === '1 commit')
check('a recorded zero commits says zero', commitLine(row({ commit_count: 0, commits: [] })) === '0 commits')
check('an unrecorded commit count is not asserted as zero', commitLine({ commits: [] }) === 'commit count not recorded')
check('subjects are only the non-empty strings', commitSubjects({ commits: ['a', '', null, 'b'] }).length === 2)
check('a row with fixes says how many', fixedLine(row({ items: [item('LQ-1', 'VERIFIED'), item('LQ-2', 'UNTRACKED')] })) === 'Fixed: 2 items')
check('one fix is singular', fixedLine(row({ items: [item('LQ-1', 'VERIFIED')] })) === 'Fixed: 1 item')

check('a rollback is flagged from the kind', kindLabel(row({ kind: 'rollback', rollback: true })).tone === 'warning')
check('a rollback/reactivate is flagged too', kindLabel(row({ kind: 'rollback/reactivate', rollback: true })).tone === 'warning')
check('an ordinary deploy is not flagged', kindLabel(row()).tone === 'neutral' && kindLabel(row()).label === 'deploy')
check('an unrecorded kind says so', kindLabel({}).label === 'kind not recorded')

check('the ET stamp the record carries is used as-is', whenET(row(), etDateTime) === 'Tue 11-10 10:54 ET')
check('a row without an ET stamp falls back to its ISO time', /11\/10, 10:54 ET/.test(whenET(row({ activated_et: null }), etDateTime)), whenET(row({ activated_et: null }), etDateTime))
check('a row with no date says so rather than showing a dash', whenET({}, etDateTime) === 'date not recorded')

check('the title names the window the log covers', logTitle({ since: '2026-11-03' }) === 'Deployment log (since 2026-11-03)')
check('an unknown window is not invented', logTitle({ since: null }) === 'Deployment log' && logTitle(null) === 'Deployment log')
check('a truncated response says what was cut', shownLine({ truncated: true, shown: 200, deployments_total: 139 }) === 'showing the newest 200 of 139 deployments')
check('an uncut response says nothing', shownLine({ truncated: false, shown: 139, deployments_total: 139 }) === null)
check('a cut response with no counts admits only the cut', shownLine({ truncated: true }) === 'older deployments are not shown')

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
