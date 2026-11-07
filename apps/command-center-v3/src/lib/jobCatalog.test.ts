// Ops › Job catalog + described job cards + tappable status tiles (operator 2026-11-06). Synthetic lane ids only.
//   node --experimental-strip-types src/lib/jobCatalog.test.ts
import {
  HISTORY_STATUS_KEYS, JOB_CATALOG_PATH, categoryKeyOf, categoryLabel, describedHistoryQuery, descriptionLines, effectiveHistoryFilter,
  isHistoryStatus, jobTitle, matchesCategory, mixParts, mixText, runHistoryHref, toggleStatus,
} from './jobCatalog.ts'
import { N8N_STATUS_KEYS, historyTiles, isN8nStatus, matchesN8nStatus, n8nTiles } from './jobsN8n.ts'
import { summaryOf, type N8nRowX } from './opsControlsN8n.ts'
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const CATS = [{ key: 'market_data', label: 'Market data & prices', blurb: 'Synthetic quotes.' }, { key: 'other', label: 'Other', blurb: 'Unplaced.' }]

t('readable title wins over the generated name; blank title falls back', () => {
  eq(jobTitle({ title: 'Synthetic price pull', job: 'Synthetic a' }), 'Synthetic price pull')
  eq(jobTitle({ title: '  ', job: 'Synthetic a' }), 'Synthetic a')
  eq(jobTitle({ title: null, job: 'Synthetic a' }), 'Synthetic a')
})
t('category: described, else owner fallback, else Other; label from the list', () => {
  eq(categoryKeyOf({ category: 'market_data', category_key: 'market_data', category_fallback: 'ops' }), 'market_data')
  eq(categoryKeyOf({ category: null, category_key: null, category_fallback: 'ops' }), 'ops')
  eq(categoryKeyOf({ category: null }), 'other')
  eq(categoryLabel('market_data', CATS), 'Market data & prices')
  eq(categoryLabel('agents_llm', CATS), 'Agents llm')
})
t('description lines never invent text', () => {
  eq(descriptionLines({ does: 'Pulls.', breaks: null }), { does: 'Pulls.', breaks: null, missing: false })
  eq(descriptionLines({ does: ' ', breaks: undefined }), { does: null, breaks: null, missing: true })
})
t('status mix reads "3 failed · 40 ok · 12 not measured" and omits zeros', () => {
  eq(mixText({ failed: 3, ok: 40, not_measured: 12, late: 0 }), '3 failed · 40 ok · 12 not measured')
  eq(mixText({}), 'No jobs')
  eq(mixParts({ inactive: 2 }).map(p => p.text), ['2 paused or retired'])
})
t('category search matches label, blurb or key', () => {
  eq(matchesCategory(CATS[0], 'quotes'), true)
  eq(matchesCategory(CATS[0], 'MARKET'), true)
  eq(matchesCategory(CATS[0], 'zzz'), false)
  eq(matchesCategory(CATS[0], ''), true)
})
t('jobs-history query carries status, category and search', () => {
  eq(describedHistoryQuery({ filter: 'all', status: 'failed', category: 'ops', q: ' x ' }), '/api/v2/jobs-history?filter=all&offset=0&limit=50&status=failed&category=ops&q=x')
  eq(describedHistoryQuery({ filter: 'attention' }), '/api/v2/jobs-history?filter=attention&offset=0&limit=50')
})
t('a tapped tile reads every job on Needs you / Fixes; All jobs keeps its scheduler pill', () => {
  eq(effectiveHistoryFilter('needs', 'attention', 'ok'), 'all')
  eq(effectiveHistoryFilter('fixes', 'fixed', 'failed'), 'all')
  eq(effectiveHistoryFilter('needs', 'attention', null), 'attention')
  eq(effectiveHistoryFilter('all', 'n8n', 'failed'), 'n8n')
})
t('tapping the active tile clears it', () => {
  eq(toggleStatus(null, 'failed'), 'failed')
  eq(toggleStatus('failed', 'failed'), null)
  eq(toggleStatus('failed', 'late'), 'late')
})
t('every job tile has a status key the API accepts', () => {
  for (const tab of ['needs', 'all', 'fixes'] as const) for (const tile of historyTiles(null, tab)) {
    if (!tile.key || !isHistoryStatus(tile.key)) fail(`${tab} tile ${tile.label} has no valid key`)
  }
  eq(historyTiles(null, 'needs').map(x => x.key), ['failed', 'missed', 'late', 'ok', 'ok_unverified', 'fixed'])
  eq(isHistoryStatus('nope'), false)
  eq(HISTORY_STATUS_KEYS.includes('fixed'), true)
})
t('n8n tiles are keyed and a tile filters exactly the lanes it counts', () => {
  const rows: N8nRowX[] = [
    { lane_id: 'syn-a', stage: 'canary', outcome: { effective_mode: 'live', health: 'OK' } },
    { lane_id: 'syn-b', stage: 'canary', outcome: { effective_mode: 'live', health: 'FAILING' } },
    { lane_id: 'syn-c', stage: 'shadow', outcome: { effective_mode: 'dry_run', health: 'NEVER_RAN' } },
    { lane_id: 'syn-d', stage: 'cutover', outcome: { effective_mode: 'live', health: 'STALE' }, readiness: { verdict: 'CUT_OVER' } },
    { lane_id: 'syn-e', stage: 'shadow', outcome: { effective_mode: 'dry_run', health: 'OK' }, readiness: { verdict: 'READY_FOR_CANARY' } },
  ] as N8nRowX[]
  const tiles = n8nTiles(summaryOf(rows, null), rows)
  eq(tiles.map(x => x.key), [...N8N_STATUS_KEYS])
  for (const tile of tiles) {
    if (!isN8nStatus(tile.key)) fail(`bad key ${tile.key}`)
    eq(rows.filter(r => matchesN8nStatus(r, tile.key as never)).length, tile.value, tile.label)
  }
})
t('paths', () => {
  eq(JOB_CATALOG_PATH, '/ops/jobs-catalog')
  eq(runHistoryHref('syn a'), '/ops/jobs-n8n?tab=all&history=syn%20a')
})
console.log(`jobCatalog: ${n} passed`)
