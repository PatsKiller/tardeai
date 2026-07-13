// Pure-logic tests for scannerSelection.ts. Runnable with Node 22 type-stripping:
//   node apps/command-center-v3/src/lib/scannerSelection.test.ts
// No test framework required (the repo has none); the Vite/tsc build covers the React UI, these
// cover the pagination / selection / TOS-format / scout-pill logic.
import {
  pageSlice, paginateTopN, toggleSelectedSymbol, selectSymbols, deselectSymbols,
  dedupeSymbols, formatThinkorswimSymbols, selectionStorageKey, getSocialScoutPill, getTopGainerPill,
  getSqueezePill, getRunnerPill, isSqueezeRow, isRunnerRow, scannerSortKey, buildPillTooltip, missingPillarHints,
  isSocialAwarenessRow, getSocialAwarenessPill,
} from './scannerSelection.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// ---- pagination: top 30, 10 per page ----
const rows = Array.from({ length: 47 }, (_, i) => ({ symbol: `S${i}`, score: 100 - i }))
const pg = paginateTopN(rows, 30, 10)
check('top-30 yields 3 pages', pg.pageCount === 3)
check('top-30 total is 30 not 47', pg.total === 30)
check('page sizes 10/10/10', pg.pages.map(p => p.length).join(',') === '10,10,10')

const v1 = pageSlice(rows, 1, 30, 10)
check('page 1 shows 10', v1.items.length === 10)
check('page 1 from/to = 1..10', v1.from === 1 && v1.to === 10)
check('page 1 first symbol S0', v1.items[0].symbol === 'S0')
const v3 = pageSlice(rows, 3, 30, 10)
check('page 3 from/to = 21..30', v3.from === 21 && v3.to === 30)
check('page 3 last symbol S29 (top-30 cutoff)', v3.items[v3.items.length - 1].symbol === 'S29')
const vClamp = pageSlice(rows, 9, 30, 10)
check('page clamps to pageCount', vClamp.page === 3)
const vSmall = pageSlice(rows.slice(0, 7), 1, 30, 10)
check('7 rows → 1 page, to=7', vSmall.pageCount === 1 && vSmall.to === 7)
const vEmpty = pageSlice([], 1, 30, 10)
check('empty → 1 page, from/to 0', vEmpty.pageCount === 1 && vEmpty.from === 0 && vEmpty.to === 0)

// ---- selection: toggle, dedupe, cross-page union ----
let sel = toggleSelectedSymbol([], 'aapl')
check('toggle adds uppercased', sel.length === 1 && sel[0] === 'AAPL')
sel = toggleSelectedSymbol(sel, 'AAPL')
check('toggle removes existing', sel.length === 0)
sel = selectSymbols(['AAPL'], ['MSFT', 'aapl', 'NVDA'])
check('selectSymbols unions + dedupes case-insensitive', sel.join(',') === 'AAPL,MSFT,NVDA')
sel = deselectSymbols(sel, ['msft'])
check('deselectSymbols removes case-insensitive', sel.join(',') === 'AAPL,NVDA')
check('dedupe collapses dup symbols', dedupeSymbols(['A', 'a', 'B', 'b', '']).join(',') === 'A,B')

// cross-page: select on "page 1" then "page 2", selection persists in the array
let cross = selectSymbols([], pageSlice(rows, 1, 30, 10).items.map(r => r.symbol))
cross = selectSymbols(cross, pageSlice(rows, 2, 30, 10).items.map(r => r.symbol))
check('cross-page selection accumulates to 20', cross.length === 20)
check('cross-page keeps page-1 + page-2 symbols', cross.includes('S0') && cross.includes('S10'))

// ---- Thinkorswim formats ----
check('TOS comma format', formatThinkorswimSymbols(['QCY', 'IVF', 'CNVS', 'TIT']) === 'QCY,IVF,CNVS,TIT')
check('TOS newline format', formatThinkorswimSymbols(['A', 'B'], 'newline') === 'A\nB')
check('TOS space format', formatThinkorswimSymbols(['A', 'B'], 'space') === 'A B')
check('TOS dedupes before formatting', formatThinkorswimSymbols(['A', 'a', 'B']) === 'A,B')

// ---- storage key scoped by day ----
check('storage key includes date', selectionStorageKey('2026-06-29') === 'tradeai.scanner.selectedSymbols.2026-06-29')
check('storage key includes run id', selectionStorageKey('2026-06-29', 'run42').endsWith('.run42'))

// ---- Social Scout pill derivation (no recompute) ----
const scout2 = getSocialScoutPill({ symbol: 'X', scout_status: 'SOCIAL_SCOUT', scout_pillar_count: 2,
  operator_pill: 'SOCIAL SCOUT · 2/5', operator_color_token: 'socialScout',
  operator_subtitle: 'Not quite there yet', operator_tooltip_hints: ['Needs catalyst verification'] })
check('2/5 scout pill text', scout2.isScout && scout2.text === 'SOCIAL SCOUT · 2/5')
check('2/5 scout color token socialScout', scout2.colorToken === 'socialScout')
check('2/5 scout subtitle', scout2.subtitle === 'Not quite there yet')
check('2/5 scout hint passthrough', scout2.hints!.includes('Needs catalyst verification'))

const scoutLarge = getSocialScoutPill({ symbol: 'L', scout_status: 'SOCIAL_SCOUT', scout_pillar_count: 3,
  float_class: 'large_float', manual_review_required: true })
check('large-float scout pill (derived)', scoutLarge.text === 'SOCIAL SCOUT · LARGE FLOAT · 3/5')

const go = getSocialScoutPill({ symbol: 'G', decision: 'GO', scout_status: 'NONE' })
check('GO row is not a scout (no pill)', go.isScout === false)
const none = getSocialScoutPill({ symbol: 'N' })
check('row without scout_status is not a scout', none.isScout === false)
check('missing-pillar hints map', missingPillarHints(['catalyst_evidence', 'market_confirmation']).length === 2)

// ---- Top Gainer pill (awareness only, never GO) ----
const gmm = getTopGainerPill({
  symbol: 'GMM', awareness_status: 'TOP_GAINER', change_pct: '119.2',
  operator_pill: 'TOP GAINER · +119.2%', operator_subtitle: 'Leading gainer — manual review',
  disqualified: true, disqualification_reason: 'REVERSE_SPLIT: 0.02:1 on 2026-06-11 — delisting avoidance',
})
check('GMM top gainer pill', gmm.isTopGainer && gmm.text === 'TOP GAINER · +119.2%')
check('GMM DQ hint passthrough', gmm.hints!.some(h => h.includes('REVERSE_SPLIT')))
const nogo = getTopGainerPill({ symbol: 'X', decision: 'NO-GO', score: 0 })
check('non-top-gainer row has no pill', nogo.isTopGainer === false)
check('top gainer sorts above zero-score NO-GO', scannerSortKey({ symbol: 'GMM', awareness_status: 'TOP_GAINER', change_pct: 119 }) > scannerSortKey({ symbol: 'X', score: 0 }))
check('score row uses score as sort key', scannerSortKey({ symbol: 'Y', score: 42 }) === 42)

const sq = getSqueezePill({
  symbol: 'GMM', awareness_status: 'SQUEEZE', decision: 'MANUAL_REVIEW', manual_review_required: true,
  rvol: 225, operator_pill: 'SQUEEZE · R/S · 225.0x',
  soft_flag_reason: 'REVERSE_SPLIT: 0.02:1 on 2026-06-11',
})
check('GMM squeeze pill', !!(sq.isSqueeze && sq.text?.includes('SQUEEZE')))
check('isSqueezeRow', isSqueezeRow({ symbol: 'GMM', awareness_status: 'SQUEEZE' }))
check('squeeze sorts above top gainer', scannerSortKey({ symbol: 'GMM', awareness_status: 'SQUEEZE', rvol: 100, gap_pct: 50 })
  > scannerSortKey({ symbol: 'X', awareness_status: 'TOP_GAINER', change_pct: 99 }))

const gmmTip = buildPillTooltip({
  symbol: 'GMM', price: 4.06, change_pct: '119.5', gap_pct: '207.5', rvol: 225.2, float_m: 1.68,
  score: 35, grade: 'SQUEEZE', decision: 'MANUAL_REVIEW', sector: 'Technology',
  soft_flag_reason: 'REVERSE_SPLIT: 0.02:1 on 2026-06-11',
  catalyst: 'Top Premarket Gainers', catalyst_verified: false, squeeze_sort_score: 2250,
}, 'squeeze', { subtitle: 'R/S squeeze', hints: ['Manual review only'], footer: 'test footer' })
check('GMM tooltip has symbol', gmmTip.includes('GMM'))
check('GMM tooltip has price', gmmTip.includes('Price $4.06'))
check('GMM tooltip has rvol', gmmTip.includes('RVOL 225.2x'))
check('GMM tooltip has flag', gmmTip.includes('REVERSE_SPLIT'))
const sqTip = getSqueezePill({
  symbol: 'GMM', awareness_status: 'SQUEEZE', decision: 'MANUAL_REVIEW', manual_review_required: true,
  rvol: 225, gap_pct: 61, change_pct: 99, price: 4.06, score: 35, grade: 'SQUEEZE',
  soft_flag_reason: 'REVERSE_SPLIT: 0.02:1',
})
check('squeeze pill tooltip populated', !!(sqTip.tooltip && sqTip.tooltip.includes('GMM') && sqTip.tooltip.includes('RVOL')))

const runner = getRunnerPill({
  symbol: 'IOTR', awareness_status: 'HIGH_RVOL', decision: 'MANUAL_REVIEW', manual_review_required: true,
  rvol: 12.5, operator_pill: 'RUNNER · 12.5x',
})
check('IOTR runner pill', !!(runner.isRunner && runner.text?.includes('RUNNER')))
check('isRunnerRow', isRunnerRow({ symbol: 'IOTR', awareness_status: 'HIGH_RVOL' }))
check('runner sorts above top gainer', scannerSortKey({ symbol: 'IOTR', awareness_status: 'HIGH_RVOL', rvol: 12, gap_pct: 40 })
  > scannerSortKey({ symbol: 'X', awareness_status: 'TOP_GAINER', change_pct: 99 }))
check('squeeze still above runner', scannerSortKey({ symbol: 'GMM', awareness_status: 'SQUEEZE', rvol: 100, gap_pct: 50 })
  > scannerSortKey({ symbol: 'IOTR', awareness_status: 'HIGH_RVOL', rvol: 12, gap_pct: 40 }))

const aware = getSocialAwarenessPill({
  symbol: 'QTEX', source: 'social', source_detail: 'stocktwits_premarket',
  social_stocktwits: 2, catalyst: 'QTEX trending on StockTwits pre-market',
})
check('social awareness pill', !!(aware.isAwareness && aware.text?.includes('SOCIAL AWARENESS')))
check('social awareness catalyst in hints', aware.hints?.some(h => h.includes('QTEX')) ?? false)
check('isSocialAwarenessRow', isSocialAwarenessRow({ symbol: 'HITI', source: 'social', price: 0, rvol: 0 }))
check('awareness not when finviz data', !isSocialAwarenessRow({ symbol: 'EHGO', source: 'social', price: 2.16, rvol: 10 }))

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
