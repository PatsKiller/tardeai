// Fundamentals page tests — plain node, no framework. The page's presentation rules are pure text decisions
// (`evidence.ts`), one pure filter (`filter.ts`) and JSX, so the table AND the whole page are asserted without a
// browser and without a fixture server. Every payload here is SYNTHETIC (fixtures.ts: QZ… symbols, SYN_… accounts).
//
// Run (from apps/wealth; the outdir must be outside the shared, symlinked node_modules):
//
//   OUT=/tmp/fundamentals-tests
//   node node_modules/typescript/bin/tsc --target ES2020 --module commonjs --moduleResolution node --strict \
//     --skipLibCheck --allowImportingTsExtensions --rewriteRelativeImportExtensions --jsx react-jsx \
//     --typeRoots node_modules/@types --types node --outDir "$OUT" \
//     src/pages/fundamentals/fundamentalsTests.ts
//   echo '{"type":"commonjs"}' > "$OUT/package.json"
//   ln -s "$PWD/node_modules" "$OUT/node_modules"
//   mkdir -p "$OUT/pages/portfolio/analytics"
//   cp src/pages/portfolio/analytics/*.mjs "$OUT/pages/portfolio/analytics/"   # the shared selector, plain JS
//   : > "$OUT/pages/portfolio/analytics/analytics.css"                        # the page's stylesheet stub
//   node "$OUT/pages/fundamentals/fundamentalsTests.js"
//
// This file is written to RUN UNCHANGED on both trees: on 399aa8298 (before G1/G2) it compiles and fails on
// assertions, and on the G1/G2 head it passes. The two names that do not exist before the change (`filter.ts`,
// `evidenceCopy`, `NOT_AVAILABLE`) are reached through the module object so that a missing export is a pushed-back
// check, not a compile error — a base run must fail on what the page SAYS, not on an unresolved import.
//
// What is pinned, and why each pin can fail:
//   T-1  the two route-fixed cells print the short truthful phrase, and no table cell carries the contract id;
//   T-2  those cells take no row, so a served valuation cannot leak a status word into them (no derived status);
//   T-3  a served provider multiple prints as the same multiple the Holdings preset prints, with wire named;
//   T-4  market cap prints the served field in its own unit (MILLIONS) with source AND clock of the row's
//        profile record — the cell cannot print a cap with no provenance;
//   T-5  the eight preset columns and their headers are the approved preset's, in its order;
//   T-6  every table sits in a .table-wrap, and every row's cells are the preset's own decisions on cash;
//   T-7  the two route-fixed cells are the short phrase on EVERY security row, cell by cell — and the P/E columns
//        keep the preset's own text, which for a fund IS a served status word (the page's foot says so);
//   G1   the page's account/sector/search controls are the shell's ONE selection and the approved selector, the
//        header states the filter, and no row is a re-derived copy (`===` the served row);
//   G2   one compact evidence line with the full notice behind the disclosure, the contract id reachable exactly
//        once per gap, no initials badge, and no two-letter badge / repeated per-row warning anywhere.

import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import type { HoldingsBook, HoldingsRow } from '../portfolio/contract'
import { FIXTURE_BOOK, staleTrailingPe } from '../portfolio/fixtures'
import { preset } from '../portfolio/presets'
import { normalizeBook } from '../portfolio/analyticsAdapter'
import * as bookView from '../portfolio/bookView'

// The route string is a literal here, not an import: `FUNDAMENTALS_ROUTE` does not exist on 399aa8298, and this
// file must compile there so the base run fails on what the shell SAYS, not on an unresolved export.
const FUNDAMENTALS_ROUTE = '/portfolio/fundamentals'
const { ALLOCATION_ROUTE, HOLDINGS_ROUTE, barStatus, isBookRoute } = bookView
import { DrawerProvider } from '../../components/Drawer'
import * as evidenceModule from './evidence'
import { FundamentalsTable } from './FundamentalsTable'

// The page imports its stylesheet (`analytics.css`, the shared `.wm-pa` classes). Under node there is no CSS
// loader, so register a no-op for `.css` and require the page AFTER it — the page is otherwise pure SSR.
;(require as unknown as { extensions: Record<string, (m: unknown, f: string) => unknown> }).extensions['.css'] = () => ({})
const { FundamentalsPage } = require('./FundamentalsPage') as typeof import('./FundamentalsPage')

// Names that exist only after G1/G2. `any` here on purpose: see the header — a base run must fail on assertions.
const ev: any = evidenceModule
const NOT_AVAILABLE: string | null = typeof ev.NOT_AVAILABLE === 'string' ? (ev.NOT_AVAILABLE as string) : null
const evidenceCopy: ((notice: string | null | undefined, snapshot: any, line: string | null | undefined) => {
  line: string | null
  detail: string | null
}) | null = typeof ev.evidenceCopy === 'function' ? ev.evidenceCopy : null

let failures = 0
const fails: string[] = []

function check(name: string, cond: boolean, detail = ''): void {
  if (!cond) {
    failures += 1
    fails.push(`${name}${detail ? ` — ${detail}` : ''}`)
  }
}

function eq<T>(name: string, got: T, want: T): void {
  check(name, Object.is(got, want), `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`)
}

const PRESET = preset('fundamentals')
const ROWS = FIXTURE_BOOK.rows
const bySymbol = (s: string): HoldingsRow => {
  const r = ROWS.find(x => x.symbol === s)
  if (!r) throw new Error(`fixture row missing: ${s}`)
  return r
}

const stripTags = (h: string): string =>
  h.replace(/<!--[\s\S]*?-->/g, '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

// ---- T-1 / T-2: the short phrase in the cells, the contract id in the disclosure ------------------------
//
// G2 moved the long literal OUT of the cells. It stays the page disclosure's text (and each cell's title), so the
// contract is still named in one reachable place; the cells print the short, truthful phrase.

eq('T-1 the contract id is the route string, character for character', evidenceModule.NOT_WIRED, 'not wired — valuation-assessment@1')
check(
  'T-1 the cells print the short truthful phrase instead of the contract id',
  NOT_AVAILABLE === 'Not available',
  `got ${JSON.stringify(NOT_AVAILABLE)}, want "Not available"`,
)
eq('T-1 peer median text (the disclosure’s) is the contract id', evidenceModule.peerMedianText(), evidenceModule.NOT_WIRED)
eq('T-1 the valuation-evidence text (the disclosure’s) is the contract id', evidenceModule.assessmentText(), evidenceModule.NOT_WIRED)
eq('T-2 peerMedianText takes no row', evidenceModule.peerMedianText.length, 0)
eq('T-2 assessmentText takes no row, so a served assessment cannot leak', evidenceModule.assessmentText.length, 0)
check(
  'T-2 the literal names the contract version',
  /valuation-assessment@1/.test(evidenceModule.assessmentText()),
  evidenceModule.assessmentText(),
)

// ---- T-3: served provider multiples, and the assessment fallback when no multiple is served ------------

eq('T-3 a served trailing P/E prints as the preset prints it', evidenceModule.peText(bySymbol('QZTA'), 'peTrailing'), '21.4x')
eq('T-3 a served forward P/E prints as the preset prints it', evidenceModule.peText(bySymbol('QZTA'), 'peForward'), '18.9x')
const lastKnown = bySymbol('QZDX')
const unassessedWithValue: HoldingsRow = { ...lastKnown, valuation: staleTrailingPe('SYN_TAX:QZDX'), fundamentals: null }
eq(
  'T-3 a null multiple with an UNASSESSED assessment keeps the last-known value and its status',
  evidenceModule.peText(unassessedWithValue, 'peTrailing'),
  '18.8x · Unassessed (last known)',
)
eq('T-3 an assessment with no trailing measure prints N/A, not a word', evidenceModule.peText(lastKnown, 'peTrailing'), 'N/A')
eq('T-3 a fund with no company multiple keeps the fund metric', evidenceModule.peText(bySymbol('QZFD'), 'peTrailing'), '17.4x · fund metric')
const noPe = { ...bySymbol('QZTA'), fundamentals: { ...(bySymbol('QZTA').fundamentals as NonNullable<HoldingsRow['fundamentals']>), peTrailing: null }, valuation: null }
check(
  'T-3 a row with neither a multiple nor an assessment states both reasons',
  evidenceModule.peText(noPe, 'peTrailing').startsWith('N/A — ') && /no served pe multiple/.test(evidenceModule.peText(noPe, 'peTrailing')),
  evidenceModule.peText(noPe, 'peTrailing'),
)

// ---- T-4: market cap in its own unit, with the profile record's source AND clock -----------------------

eq('T-4 millions are divided once: 41200 -> $41.2B', evidenceModule.marketCapText(bySymbol('QZTA')), '$41.2B')
eq('T-4 230500 -> $230.5B', evidenceModule.marketCapText(bySymbol('QZEP')), '$230.5B')
eq('T-4 a sub-billion cap stays in millions', evidenceModule.marketCapText(bySymbol('QZDL')), '$640M')
eq('T-4 an unpublished cap is a reason, not zero', evidenceModule.marketCapText(bySymbol('QZNV')), 'N/A — not published for this instrument')
eq('T-4 cash has no market cap', evidenceModule.marketCapText(bySymbol('CASH')), 'N/A — cash has no market cap')
eq('T-4 source is the row profile record', evidenceModule.marketCapSource(bySymbol('QZTA')), 'fixture')
eq('T-4 clock is the row profile clock', evidenceModule.marketCapClock(bySymbol('QZTA')), '2026-11-14T13:00:00Z')
eq(
  'T-4 provenance prints source and clock together',
  evidenceModule.marketCapProvenance(bySymbol('QZTA')),
  'source fixture · record 2026-11-14T13:00:00Z',
)
const unprofiled: HoldingsRow = { ...bySymbol('QZTA'), profileSource: null, profileUpdatedAt: null }
eq(
  'T-4 an unserved provenance says so instead of inventing one',
  evidenceModule.marketCapProvenance(unprofiled),
  'source not served · record clock not served',
)

// ---- unit traps the page inherits from the wire -------------------------------------------------------

eq('T-3 a percent yield is printed once, not multiplied', evidenceModule.yieldText(bySymbol('QZTA')), '1.80%')
eq('T-3 an unpublished yield is a reason, not zero', evidenceModule.yieldText(bySymbol('QZDL')), 'N/A — not published for this instrument')
eq('T-3 a served price keeps its cents', evidenceModule.priceText(bySymbol('QZTA')), '$75.00')
eq('T-3 a worthless identifier has no price to print', evidenceModule.priceText(bySymbol('QZDX')), 'N/A — no price served for a worthless identifier')

// ---- T-5 / T-6 / T-7: the rendered table --------------------------------------------------------------

const html = renderToStaticMarkup(createElement(FundamentalsTable, { rows: ROWS, preset: PRESET }))
// What the reader sees, as text: SSR inserts comment separators between adjacent text nodes (`{head}{' '}` and
// the token), so the literal is asserted on the rendered TEXT, not on the markup string.
const text = stripTags(html)

eq(
  'T-5 the preset columns are the approved eight, in order',
  PRESET.columns.map(c => c.key).join('|'),
  'security|price|peTrailing|peForward|peerMedian|marketCap|yield|evidence',
)
for (const c of PRESET.columns) {
  check(`T-5 header "${c.header}" renders`, html.includes(`<th scope="col">${c.header}</th>`), c.header)
}
check('T-6 the table sits inside the .table-wrap scroll container', html.startsWith('<div class="table-wrap"><table>'))
check(
  'T-6 the preset method note is under the table',
  html.includes('Trailing and forward P/E print the SERVED provider multiple'),
)
for (const l of PRESET.limits) {
  check('T-6 the preset limit is under the table', html.includes(l.slice(0, 60)), l)
}
const securityRows = ROWS.filter(r => r.kind !== 'CASH').length

// G2: the phrase is in the cells; the contract id is NOT.
const phraseCount = text.split('Not available').length - 1
eq('G2 every security row carries the short phrase twice (peer median + evidence)', phraseCount, securityRows * 2)
eq(
  'G2 no table cell carries the contract id any more',
  text.split(evidenceModule.NOT_WIRED).length - 1,
  0,
)
check(
  'G2 the contract id is on each cell’s accessible name, once per cell',
  html.split('aria-label="Not available — ').length - 1 === securityRows * 2,
  `${html.split('aria-label="Not available — ').length - 1} of ${securityRows * 2}`,
)
check('G2 no initials badge in the identity cell', !html.includes('ticker-icon'), 'ticker-icon survives')
check(
  'G2 the table foot no longer repeats the contract id',
  !/<tfoot>[\s\S]*not wired/.test(html),
)
check(
  'T-6 a cash row takes the preset cash rule, not the security columns',
  html.includes('aria-label="N/A — this column does not apply to a cash row"'),
)

// ---- T-7: the two route-fixed columns, cell by cell -----------------------------------------------------
//
// The fixture rows DO carry valuation-assessment@1 statuses (UNASSESSED on QZTA, FUND_METRIC on QZFD) and the
// table DOES render one of those statuses — as the preset's own P/E text ("17.4x · fund metric"). A whole-table
// regex for the raw enum names therefore proves nothing: it passes while a status word is on screen. The route
// fixes exactly two columns, so the assertion is per cell: those two cells are the short phrase on every security
// row, while the P/E columns keep the preset's text and are allowed to say what they are.

// Indices come from the preset, not from a literal: if the approved order ever changes, T-5 fails and these
// assertions read the columns the preset actually declares.
const colIndex = (key: string): number => PRESET.columns.findIndex(c => c.key === key)
const COL = {
  peTrailing: colIndex('peTrailing'),
  peForward: colIndex('peForward'),
  peerMedian: colIndex('peerMedian'),
  evidence: colIndex('evidence'),
} as const
check(
  'T-7 all four asserted columns exist in the preset',
  [COL.peTrailing, COL.peForward, COL.peerMedian, COL.evidence].every(i => i >= 0),
  JSON.stringify(COL),
)
const cellsOf = (tr: string): string[] =>
  (tr.match(/<t[dh][^>]*>[\s\S]*?<\/t[dh]>/g) ?? []).map(stripTags)
const allRows = (html.match(/<tr[^>]*>[\s\S]*?<\/tr>/g) ?? []).map(cellsOf)
const bodyRows = allRows.filter(c => c.length === PRESET.columns.length && c !== allRows[0])
eq('T-7 every fixture row is parsed out of the rendered table, eight cells each', bodyRows.length, ROWS.length)
for (const [i, cells] of bodyRows.entries()) {
  // A cash row takes the preset's own cash rule in every column except identity and price (§3 of the READY,
  // pinned by the aria-label assertion in T-6); every security row carries the short phrase.
  const want = ROWS[i].kind === 'CASH' ? 'N/A' : 'Not available'
  eq(`T-7 ${ROWS[i].symbol}: peer median cell is ${want === 'Not available' ? 'the short phrase' : 'the cash rule'}`, cells[COL.peerMedian], want)
  eq(`T-7 ${ROWS[i].symbol}: evidence cell is ${want === 'Not available' ? 'the short phrase' : 'the cash rule'}`, cells[COL.evidence], want)
}
check(
  'T-7 no status word reaches the two route-fixed columns on any row',
  bodyRows.every(c => !/assessed|fund metric|n\/m/i.test(c[COL.peerMedian]) && !/assessed|fund metric|n\/m/i.test(c[COL.evidence])),
  bodyRows.map(c => `${c[0]}: ${c[COL.peerMedian]} | ${c[COL.evidence]}`).join(' ; '),
)
const qzfdCells = bodyRows[ROWS.findIndex(r => r.symbol === 'QZFD')]
eq(
  'T-7 a fund row prints the preset’s fund metric in BOTH P/E columns — a served status, in the P/E column only',
  `${qzfdCells[COL.peTrailing]} | ${qzfdCells[COL.peForward]}`,
  '17.4x · fund metric | 17.4x · fund metric',
)
const capRows = ROWS.filter(r => r.marketCapB !== null).length
eq(
  'T-4 every served cap carries its source+clock line',
  html.split('>source fixture · record 2026-11-14T13:00:00Z<').length - 1,
  capRows,
)
check('T-4 the cap cell prints the formatted cap', html.includes('$41.2B'))
check('T-3 the P/E cells print served multiples', html.includes('21.4x') && html.includes('18.9x'))

// ---- G2: one compact evidence line, and the long text behind the disclosure -----------------------------
//
// The line is the adapter's sentence verbatim when it has one; when it does not (a current read whose payload has
// no health flag and no producer clock — `holdingsProps` still sets `notice`), the notice's own lead clause is the
// line. Everything the line truncated goes behind the disclosure. Each case below can fail on a plain-string
// change, and the whole block is skipped only on the pre-G2 tree, where `evidenceCopy` does not exist.

check('G2 the page has a compact-line helper (evidenceCopy)', evidenceCopy !== null)
if (evidenceCopy !== null) {
  const clock = 'Session weekend · read 2026-11-14T21:00:00Z.'
  const current = { reason: undefined as string | undefined, session: 'weekend', observedAt: '2026-11-14T21:00:00Z' }

  const quiet = evidenceCopy(null, current, '')
  eq('G2 a current read with no notice prints no line and no detail', `${quiet.line}|${quiet.detail}`, 'null|null')

  const adapterLine = 'Last available snapshot · freshness unverified'
  const withLine = evidenceCopy(null, { ...current, reason: 'freshness unverified' }, adapterLine)
  eq('G2 the adapter’s sentence is the line, verbatim', withLine.line, adapterLine)
  eq(
    'G2 a reason the line already carries is not repeated, and the clock is behind it',
    withLine.detail,
    clock,
  )

  const notice =
    'Holdings read is unverified: the producer served no health flag and no producer clock for this read ' +
    '(the payload carried no freshness block), so this page cannot claim the values are current.'
  const lead = 'Holdings read is unverified: the producer served no health flag and no producer clock for this read'
  const unproven = evidenceCopy(notice, current, '')
  eq('G2 a current read with an unproven notice still prints its lead clause, not a calm strip', unproven.line, lead)
  eq(
    'G2 the whole notice goes behind the disclosure, with the clock',
    unproven.detail,
    `Full notice: ${notice} ${clock}`,
  )

  const short = evidenceCopy('Read is unverified', current, '')
  eq('G2 a short notice is the whole line', short.line, 'Read is unverified')
  eq('G2 a short notice adds only the clock behind it', short.detail, clock)

  const doubled = evidenceCopy('unverified', { ...current, session: 'Session unknown' }, '')
  eq('G2 the clock never doubles the word Session', doubled.detail, 'Session unknown · read 2026-11-14T21:00:00Z.')

  const reasonOnly = evidenceCopy(null, { ...current, reason: 'no producer clock' }, '')
  eq('G2 a reason with no line is disclosed, not printed as a top line', `${reasonOnly.line}|${reasonOnly.detail}`, `null|no producer clock ${clock}`)
}

// ---- G1: the pure filter is the approved selector over the ONE book -------------------------------------
//
// Loaded through the module object so this block is a pushed-back check on 399aa8298 (where `./filter` does not
// exist) and full-strength on the head. Every assertion is about which SERVED rows remain — never about a value.

interface FilterViewShape {
  rows: HoldingsRow[]
  sectorOptions: string[]
  accounts: { key: string; label: string }[]
  bookRows: number
  refused: string | null
}
type FilterApi = {
  filterFundamentals: (book: HoldingsBook, f: { scope: string; sector: string; query: string }) => FilterViewShape
  EMPTY_NO_MATCH: string
}
let filterApi: FilterApi | null = null
try {
  filterApi = require('./filter') as FilterApi
} catch {
  filterApi = null
}
check('G1 the page filters through its own module (filter.ts), reusing the approved selector', filterApi !== null)
if (filterApi !== null) {
  const F = filterApi.filterFundamentals
  const all = F(FIXTURE_BOOK, { scope: 'ALL', sector: '', query: '' })
  eq('G1 no filter keeps every served row', all.rows.length, ROWS.length)
  eq('G1 the denominator is the whole book, stated beside the filtered count', all.bookRows, ROWS.length)
  check(
    'G1 the kept rows are the served row OBJECTS, not re-derived copies',
    all.rows.length === ROWS.length && all.rows.every((r, i) => r === ROWS[i]),
  )
  eq('G1 a valid view states no refusal', all.refused, null)
  eq(
    'G1 the empty-view copy is the reviewed selector’s own sentence',
    filterApi.EMPTY_NO_MATCH,
    'No holdings match this view. Clear a filter to continue.',
  )

  // Account: the shell's one selection narrows to that account and nothing else.
  const account = ROWS[0].accountKey
  const inAccount = ROWS.filter(r => r.accountKey === account)
  const byAccount = F(FIXTURE_BOOK, { scope: account, sector: '', query: '' })
  eq('G1 an account scope keeps exactly that account’s rows', byAccount.rows.length, inAccount.length)
  check('G1 an account scope keeps no other account’s row', byAccount.rows.every(r => r.accountKey === account))
  check(
    'G1 an account scope is a proper subset of the book',
    byAccount.rows.length > 0 && byAccount.rows.length < ROWS.length,
  )
  check('G1 the account options are the book’s served accounts', byAccount.accounts.length >= 2, JSON.stringify(byAccount.accounts.map(a => a.key)))

  // An unknown scope yields NO row — never the whole book (the fail-open filter bug).
  const unknownScope = F(FIXTURE_BOOK, { scope: 'SYN_NOT_A_BOOK_ACCOUNT', sector: '', query: '' })
  eq('G1 an unknown account scope yields zero rows, not the whole book', unknownScope.rows.length, 0)

  // Sector: the selector's own bucket, matching the bucket `selectorSector` assigns.
  const sector = all.sectorOptions[0]
  check('G1 the sector options are served buckets', typeof sector === 'string' && sector !== '', String(sector))
  const bucketOf = new Map(normalizeBook(FIXTURE_BOOK).map(r => [r.holding, r.sector ?? '']))
  const expectedSector = all.rows.filter(r => bucketOf.get(r) === sector)
  const bySector = F(FIXTURE_BOOK, { scope: 'ALL', sector, query: '' })
  eq(`G1 a sector scope keeps exactly the rows in the "${sector}" bucket`, bySector.rows.length, expectedSector.length)
  check(
    'G1 a sector scope keeps only the bucket’s rows',
    bySector.rows.every(r => bucketOf.get(r) === sector),
    JSON.stringify(bySector.rows.map(r => r.symbol)),
  )
  check(
    'G1 the selected sector stays in the options it was chosen from',
    bySector.sectorOptions.includes(sector),
    JSON.stringify(bySector.sectorOptions),
  )

  // Search: symbol, name or account, case-insensitive (the selector's rule).
  const target = ROWS.find(r => r.kind !== 'CASH') ?? ROWS[0]
  const bySymbolQuery = F(FIXTURE_BOOK, { scope: 'ALL', sector: '', query: target.symbol.toLowerCase() })
  check(
    'G1 a search on a lower-cased symbol finds it',
    bySymbolQuery.rows.some(r => r.symbol === target.symbol),
    JSON.stringify(bySymbolQuery.rows.map(r => r.symbol)),
  )
  const byAccountName = F(FIXTURE_BOOK, { scope: 'ALL', sector: '', query: target.accountLabel.toUpperCase() })
  eq(
    'G1 a search on an upper-cased account label keeps that account’s rows',
    byAccountName.rows.length,
    ROWS.filter(r => r.accountKey === target.accountKey).length,
  )
  const noMatch = F(FIXTURE_BOOK, { scope: 'ALL', sector: '', query: 'QXQZXQ NO SUCH HOLDING' })
  eq('G1 a search that matches nothing yields zero rows, not everything', noMatch.rows.length, 0)
  eq('G1 a zero-row view is empty, not a refusal', noMatch.refused, null)

  // Combined, as the page applies them: the account narrows first, then the sector must exist inside it.
  const combined = F(FIXTURE_BOOK, { scope: account, sector, query: '' })
  check(
    'G1 account and sector compose without widening the population',
    combined.rows.every(r => r.accountKey === account && bucketOf.get(r) === sector),
  )
}

// ---- G1 / G2 on the rendered page: the filterbar, ONE line, the disclosure, no badge --------------------

const NOTICE =
  'Holdings read is unverified: the producer served no health flag and no producer clock for this read ' +
  '(the payload carried no freshness block), so this page cannot claim the values are current.'
const NOTICE_LEAD =
  'Holdings read is unverified: the producer served no health flag and no producer clock for this read'


// ---- G1: the shell bar admits this route, so its ONE scope control is live here --------------------------
//
// The page's account control is the top bar's (bookView + snapshot): `isBookRoute` must accept the route, or
// `barStatus` keeps the bar on "not read here" and the page would show a book the bar denies. This is the one
// shared line the lead approved (LEAD-RULING-G1-BOOKVIEW-OPTION-A-20261115T1922Z).

check(`G1 the shell admits ${FUNDAMENTALS_ROUTE} as a book route`, isBookRoute(FUNDAMENTALS_ROUTE))
check('G1 a trailing slash is tolerated, as for the other book routes', isBookRoute(`${FUNDAMENTALS_ROUTE}/`))
for (const r of [HOLDINGS_ROUTE, ALLOCATION_ROUTE]) {
  check(`G1 the existing book route ${r} still qualifies`, isBookRoute(r))
}
check('G1 a route that does not read the book still says so', !isBookRoute('/portfolio/performance'))
check(
  'G1 the bar shows THIS page’s book on this route',
  barStatus(FUNDAMENTALS_ROUTE, { book: FIXTURE_BOOK, loading: false, error: null, notice: null } as never).kind === 'book',
)
check(
  'G1 a snapshot published on another route is still refused there',
  barStatus('/portfolio/performance', { book: FIXTURE_BOOK, loading: false, error: null, notice: null } as never).kind === 'not-read',
)

const pageHtml = renderToStaticMarkup(
  createElement(DrawerProvider, null, createElement(FundamentalsPage, { book: FIXTURE_BOOK, notice: NOTICE })),
)
const pageText = stripTags(pageHtml)
const statusMatch = /<div class="wm-pa-status"[^>]*>([\s\S]*?)<\/div>/.exec(pageHtml)
const statusText = statusMatch === null ? '' : stripTags(statusMatch[1])
const tableRegion = /<div class="table-wrap"><table>[\s\S]*?<\/table><\/div>/.exec(pageHtml)
const panelSub = /<h2>Fundamentals workspace<\/h2><p>([\s\S]*?)<\/p>/.exec(pageHtml)

check('G1 the page renders the shared filterbar', pageHtml.includes('class="wm-pa-filterbar"'), 'no .wm-pa-filterbar')
// One account control, and it is the shell's: the page states the selection and renders NO second select for it.
check('G1 the page renders no second account select', !/<select[^>]*id="account"/.test(pageHtml) && !/<label>\s*Account\s*<select/.test(pageHtml), 'a page-local account select is present')
eq('G1 the filterbar holds exactly one select — the sector control', (pageHtml.match(/<select/g) ?? []).length, 1)
check('G1 the page states the account scope the top bar holds', pageHtml.includes('Account: <b>all accounts (3)</b>'), 'no account scope statement')
check('G1 the page says where the account is chosen', pageHtml.includes('— chosen in the top bar'), 'no pointer to the top bar')
check('G1 the sector control is present and starts at every sector', /<label>Sector<select/.test(pageHtml) && pageHtml.includes('>All sectors</option>'), 'no sector select')
check('G1 the search control is present', pageHtml.includes('type="search"') && pageHtml.includes('placeholder="Symbol, name or account"'))
check('G1 a reset control is present', pageHtml.includes('Reset filters'))
eq('G1 exactly one status line', pageHtml.split('class="wm-pa-status"').length - 1, 1)
check(
  'G1 the header states the filter over the whole book',
  statusText.includes(`${ROWS.length} of ${ROWS.length} rows · all accounts (`),
  statusText,
)
check(
  'G1 the workspace header states the SAME filter text as the status line',
  panelSub !== null && panelSub[1].includes('rows · all accounts (') && /synthetic fixture/.test(panelSub[1]),
  panelSub === null ? 'no panel sub' : stripTags(panelSub[1]),
)
check(
  'G1 the page says the account control is the shell’s one scope, not a second book',
  pageText.includes('The account control is the top bar’s portfolio scope'),
)
check(
  'G1 no second book is read: the page states one read of the one book',
  pageText.includes('No second read and no second book'),
)

check('G2 the page prints the notice’s lead clause as the one evidence line', statusText.includes(NOTICE_LEAD), statusText)
check(
  'G2 the status line does NOT print the whole notice',
  !statusText.includes('the payload carried no freshness block') && statusText.length < 260,
  `${statusText.length} chars: ${statusText}`,
)
check(
  'G2 the full notice is behind the disclosure, with the clock',
  pageHtml.includes(`Full notice: ${NOTICE}`) && pageHtml.includes('Session weekend · read 2026-11-14T21:00:00Z.'),
)
check('G2 the disclosure is a collapsed <details> with a summary', /<details>\s*<summary>[\s\S]*?<\/summary>/.test(pageHtml))
check('G2 the disclosure summary names the two gaps', pageText.includes('the two gaps'))
eq(
  'G2 the contract id appears exactly twice on the page — once per gap, in the disclosure',
  pageText.split(evidenceModule.NOT_WIRED).length - 1,
  2,
)
check('G2 no table wraps a cell in a per-row warning about the unwired contract', tableRegion !== null && !tableRegion[0].includes(evidenceModule.NOT_WIRED))
check('G2 no initials badge is rendered anywhere on the page', !pageHtml.includes('ticker-icon'), 'ticker-icon survives')
check(
  'G2 no two-letter badge markup: no .ticker-icon and no aria-hidden initials span',
  !/aria-hidden="true"><span>[A-Z]{2}<\/span>/.test(pageHtml),
)
check('G2 the page does not print a second, page-level warning line', pageHtml.split('wm-pa-warning').length - 1 === 1, `${pageHtml.split('wm-pa-warning').length - 1} warnings`)

// A current read with nothing withheld: no line at all — and no invented one.
const quietHtml = renderToStaticMarkup(
  createElement(DrawerProvider, null, createElement(FundamentalsPage, { book: FIXTURE_BOOK })),
)
check(
  'G2 a current read with nothing withheld prints no warning line',
  !quietHtml.includes('wm-pa-warning') && !stripTags(quietHtml).includes('freshness unverified'),
)

if (failures > 0) {
  console.error(`FAIL — ${failures} assertion(s):`)
  for (const f of fails) console.error(`  ✗ ${f}`)
  process.exit(1)
}
console.log(`PASS — ${ROWS.length} synthetic rows, ${securityRows * 2} short-phrase cells, G1 filter + G2 disclosure green`)
