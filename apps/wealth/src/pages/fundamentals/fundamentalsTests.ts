// Fundamentals workspace tests — WB-1. Plain node, no framework, no browser: the view model is pure
// (`workspace.ts`), the presentation rules are pure text (`evidence.ts`), and the whole page is SSR-able.
// Every payload here is SYNTHETIC (fixtures.ts: QZ… symbols, SYN_… accounts) — the repository is public.
//
// Run (from apps/wealth; the outdir must be outside the shared, symlinked node_modules):
//
//   OUT=/tmp/fundamentals-wb1
//   node node_modules/typescript/bin/tsc --target ES2020 --module commonjs --moduleResolution node --strict \
//     --skipLibCheck --allowImportingTsExtensions --rewriteRelativeImportExtensions --jsx react-jsx \
//     --typeRoots node_modules/@types --types node --outDir "$OUT" \
//     src/pages/fundamentals/fundamentalsTests.ts \
//     src/pages/fundamentals/workspace.ts src/pages/fundamentals/FundamentalsPage.tsx
//     # ^ the page and its model are rooted explicitly: this file reaches them through `require`, so tsc would
//     #   otherwise emit nothing for them. (A static import would fail to compile on the base tree.)
//   echo '{"type":"commonjs"}' > "$OUT/package.json"
//   ln -s "$PWD/node_modules" "$OUT/node_modules"
//   mkdir -p "$OUT/pages/portfolio/analytics"
//   cp src/pages/portfolio/analytics/*.mjs "$OUT/pages/portfolio/analytics/"   # the shared selector, plain JS
//   : > "$OUT/pages/portfolio/analytics/analytics.css"                        # the page's stylesheet stubs
//   : > "$OUT/pages/fundamentals/workspace.css"
//   node "$OUT/pages/fundamentals/fundamentalsTests.js"
//
// This file compiles UNCHANGED on the base tree too (399aa8298, and d8ddb2f18’s predecessor): `workspace.ts` and
// the WB-1 page exports are reached through `require` so a missing module is a pushed-back assertion, never a
// compile error. A base run must fail on what the page SAYS, not on an unresolved import.
//
// What is pinned, and why each pin can fail:
//   WB-1a the reference's five cards, in its order, and the yield card stays in place printing Unknown with its
//         missing source — an absent card, a moved card or a calm zero fails;
//   WB-1b the three Tier 2 cards print Unknown in WB-1 (their formulas belong to WB-2, with tests);
//   WB-1c the reference's Equity columns, in its order and wording, and the fund table carries fund columns with
//         no empty P/E cell;
//   WB-1d a security held in two accounts is ONE display row with account sublines, each carrying its own served
//         weight — and NO summed percentage is printed anywhere;
//   WB-1e grouping/ordering is the model's: largest served weight first, one group per row in Account mode;
//   WB-1f the ▲ mark is D7 only: record clock older than quote clock, both served; no clock, no mark;
//   WB-1g the derived tags sit on the two value-share marks, with a pinned denominator, and no Tier 2 formula
//         value (e.g. the implied-EPS line) appears anywhere in WB-1;
//   WB-1h every table sits inside a .table-wrap (the design gate's rule 5), and the cash line is a collapsed
//         <details> with its count and share on the face of it;
//   WB-1i the served cells: P/E both ways, PEG, YTD, trend with RSI, beta, yield, gain with cost, protection with
//         its served stop and read clock (a recorded stop with no served price states pending activation, never
//         active protection) — and a missing field is the muted N/A with its reason, never 0;
//   WB-1j the disclosure states the grouping rule, the derived marks and the Tier 2 deferral — the page cannot
//         claim a formula it does not have;
//   WB-1k the elements the reference does not draw stay undrawn (no bar on a fund, no share count on a fund
//         subline, no count in the Funds header), and the cash share and the Coverage card each name the
//         population they divided by (a filtered numerator never sits over a book denominator).
//
// Fix sprint (LEAD-ASSIGN-WB1-FIX-SPRINT-20261115T2016Z, John's live audit) — each pin fails on the deployed fold:
//   WB-1l a security held in several accounts prints EVERY account's own gain/loss and protection, with that
//         account's label and its own detail action — a first-leg-only render fails both pins;
//   WB-1m the yield card states how many rows serve a yield; it never claims none is served;
//   WB-1n the Coverage card says "older than the quote", never "stale" (D7 is not a freshness verdict);
//   WB-1o the page contributes no <h1> — the shell's crumb is the document's single top-level heading;
//   WB-1p a pending or stale stop never reads "Protected": it reads "Stop recorded (GTC) …".
//
// G1's shell-scope wiring (bookView) is re-pinned at the end: WB-1 keeps the top bar's selection live.

import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import type { HoldingsBook, HoldingsRow } from '../portfolio/contract'
import { FIXTURE_BOOK } from '../portfolio/fixtures'
import * as bookView from '../portfolio/bookView'

// The route string is a literal here, not an import: `FUNDAMENTALS_ROUTE` does not exist on 399aa8298, and this
// file must compile there so the base run fails on what the shell SAYS, not on an unresolved export.
const FUNDAMENTALS_ROUTE = '/portfolio/fundamentals'
const { HOLDINGS_ROUTE, barStatus, isBookRoute } = bookView
import { DrawerProvider } from '../../components/Drawer'
import * as evidenceModule from './evidence'

// The page and its view model import stylesheets; under node there is no CSS loader, so register a no-op for
// `.css` and require them AFTER it (ES imports hoist, so the modules are reached through require on purpose).
;(require as unknown as { extensions: Record<string, (m: unknown, f: string) => unknown> }).extensions['.css'] = () => ({})

function safeRequire(id: string): any {
  try {
    return require(id)
  } catch {
    return null
  }
}

// Present means "carries the model", not "some file answered the require": on a tree without `workspace.ts` the
// extensionless require can be satisfied by this harness's own zero-byte `workspace.css` stub (the `.css` handler
// is registered above), which returns `{}` — so a null-only guard would crash on a stub instead of failing.
const workspaceRaw: any = safeRequire('./workspace')
const workspaceModule: any = workspaceRaw !== null && typeof workspaceRaw.buildWorkspace === 'function' ? workspaceRaw : null
const pageModule: any = safeRequire('./FundamentalsPage')
const FundamentalsPage: any =
  pageModule !== null && typeof pageModule.FundamentalsPage === 'function' ? pageModule.FundamentalsPage : null

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

const stripTags = (h: string): string =>
  h
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&#x27;|&#39;/g, '’')
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

const count = (hay: string, needle: string): number => hay.split(needle).length - 1

/** One rendered display row's markup, sliced by its `data-group` key — a cell claim is checked on ITS row only. */
const groupRow = (html: string, key: string): string => {
  const i = html.indexOf(`data-group="${key}"`)
  if (i < 0) return ''
  const end = html.indexOf('</tr>', i)
  return end < 0 ? html.slice(i) : html.slice(i, end)
}
const groupRowText = (html: string, key: string): string => stripTags(groupRow(html, key))

/** D7, computed here independently of the model: both clocks served and the record older than the quote. */
const olderRecordsIn = (rows: HoldingsRow[]): number =>
  rows.filter(r => {
    const rec = r.profileUpdatedAt === null ? NaN : Date.parse(r.profileUpdatedAt)
    const q = r.priceAsOf === null ? NaN : Date.parse(r.priceAsOf)
    return Number.isFinite(rec) && Number.isFinite(q) && rec < q
  }).length

const ROWS: HoldingsRow[] = FIXTURE_BOOK.rows
const bySymbol = (s: string): HoldingsRow => {
  const r = ROWS.find(x => x.symbol === s)
  if (!r) throw new Error(`fixture row missing: ${s}`)
  return r
}

/** The same security in a second account: the ONE case the reference does not draw and the ruling legislates. */
const TWIN: HoldingsRow = {
  ...bySymbol('QZTA'),
  accountKey: 'SYN_ROTH',
  accountLabel: 'Synthetic retirement',
  shares: 100,
  marketValue: 7500,
  gainLoss: 1500,
  gainLossPct: 20,
  portfolioPct: 5,
}
const TWO_BOOK: HoldingsBook = { ...FIXTURE_BOOK, rows: [...ROWS, TWIN] }

/**
 * The same twin with NO stop of its own: the second leg's protection differs from the first leg's. A render that
 * prints only the group's lead row shows "Protected" alone and fails WB-1l.
 */
const TWIN_GAP: HoldingsRow = {
  ...TWIN,
  protection: {
    state: 'GAP',
    stop: null,
    basis: null,
    asOf: '2026-11-14T21:00:00Z',
    stale: false,
    reason: 'no resting stop on this account',
    nextStep: 'Set a protective stop or record the decision to hold unprotected.',
  },
}
const GAP_BOOK: HoldingsBook = { ...FIXTURE_BOOK, rows: [...ROWS, TWIN_GAP] }

function renderPage(book: HoldingsBook): string | null {
  if (FundamentalsPage === null) return null
  return renderToStaticMarkup(
    createElement(DrawerProvider, null, createElement(FundamentalsPage, { book, nowMs: Date.parse('2026-11-15T00:00:00Z') })),
  )
}

// ---- G8-style evidence copy (unchanged by WB-1) -------------------------------------------------------

const ev: any = evidenceModule
eq('the contract id is still the disclosure’s text, character for character', ev.NOT_WIRED, 'not wired — valuation-assessment@1')
check(
  'the cells’ short phrase is still "Not available"-free: WB-1 prints N/A, this constant survives for its own callers',
  typeof ev.NOT_AVAILABLE === 'string',
)
if (typeof ev.evidenceCopy === 'function') {
  const copy = ev.evidenceCopy('freshness unproven', { reason: 'r', session: 'REGULAR', observedAt: 'T' }, null)
  eq('evidenceCopy falls back to the notice’s lead clause when the adapter line is empty', copy.line, 'freshness unproven')
  const verbatim = ev.evidenceCopy(null, { reason: 'r', session: 'REGULAR', observedAt: 'T' }, 'exact line')
  eq('evidenceCopy prints the adapter’s line verbatim when it is non-empty', verbatim.line, 'exact line')
} else {
  check('evidenceCopy is present', false, 'evidence.ts lost evidenceCopy')
}

// ---- WB-1 model: grouping, ordering, D7, shares, columns ----------------------------------------------

if (workspaceModule === null) {
  check('WB-1 the view model (workspace.ts) is present', false, 'no module exporting buildWorkspace — this tree predates WB-1')
} else {
  const ws = workspaceModule
  const w = ws.buildWorkspace([...ROWS, TWIN], 'security')
  const qzta = w.equities.groups.find((g: any) => g.symbol === 'QZTA')

  check('WB-1a one security in two accounts is ONE display row', qzta !== undefined && qzta.rows.length === 2, JSON.stringify(qzta?.rows.length))
  eq('WB-1a the merged group prints NO weight of its own (never a sum of percentages)', qzta?.weightPct, null)
  eq('WB-1a its order weight is the largest served row weight (a selection, not a sum)', qzta?.sortWeight, 15)
  eq(
    'WB-1a each account keeps its own served weight inside the group',
    JSON.stringify(qzta?.lines.map((l: any) => l.weightPct)),
    JSON.stringify([15, 5]),
  )
  check(
    'WB-1a no line anywhere carries the summed 20% the ruling forbids',
    JSON.stringify(qzta?.lines.map((l: any) => l.weightPct)) !== JSON.stringify([20]),
  )
  eq('WB-1a the ratio cells come from the largest-weight row (QZTA taxable)', qzta?.lead.accountKey, 'SYN_TAX')

  const sorts = w.equities.groups.map((g: any) => g.sortWeight)
  check(
    'WB-1e equity groups are ordered by served weight, largest first',
    sorts.every((v: number, i: number) => i === 0 || sorts[i - 1] >= v),
    JSON.stringify(sorts),
  )
  eq('WB-1e the largest equity position leads the table', w.equities.groups[0].symbol, 'QZTA')

  const accountMode = ws.buildWorkspace(ROWS, 'account')
  eq('WB-1e Account mode groups one row per served row', accountMode.equities.groups.length, ROWS.filter((r: HoldingsRow) => r.kind !== 'CASH' && r.assetType !== 'MUTUAL_FUND').length)
  check(
    'WB-1e Account mode never merges two accounts',
    accountMode.equities.groups.every((g: any) => g.rows.length === 1),
  )

  eq('WB-1d funds are their own section, never equities and never cash', JSON.stringify(w.funds.groups.map((g: any) => g.symbol)), JSON.stringify(['QZFD']))
  eq('WB-1d cash is its own line, one row on this fixture', w.cash.rows.length, 1)
  check(
    'WB-1d every group is filed once: equities + funds + cash rows = the rows in view',
    w.equities.rowCount + w.funds.rowCount + w.cash.rows.length === ROWS.length + 1,
  )

  eq('WB-1f record older than quote is marked', ws.recordOlderThanQuote(bySymbol('QZTA')), true)
  eq('WB-1f a row with no quote clock is not marked', ws.recordOlderThanQuote(bySymbol('CASH')), false)
  eq(
    'WB-1f a record NEWER than the quote is not marked',
    ws.recordOlderThanQuote({ ...bySymbol('QZTA'), profileUpdatedAt: '2026-11-15T00:00:00Z' }),
    false,
  )
  eq('WB-1f the mark carries the record’s own date (UTC MM-DD)', ws.shortStamp(bySymbol('QZTA').profileUpdatedAt), '11-14')
  eq('WB-1f no clock, no date', ws.shortStamp(null), null)

  eq('WB-1g the weight bar is proportional to the largest weight in the section', ws.barWidth(15, 15), 44)
  eq('WB-1g a held but small weight keeps a visible bar', ws.barWidth(0, 15), 2)

  const cov = ws.coverageOf(ROWS)
  eq('WB-1k Coverage counts the rows it is given', cov.rows, ROWS.length)
  eq(
    'WB-1k … and its “served multiple” is the served TRAILING P/E count, the same field the cell prints',
    cov.withMultiple,
    ROWS.filter((r: HoldingsRow) => r.kind !== 'CASH' && r.fundamentals?.peTrailing != null).length,
  )
  eq(
    'WB-1m … and its served-yield count is the served `yieldPct` field, the one the Yield cell prints',
    cov.withYield,
    ROWS.filter((r: HoldingsRow) => r.kind !== 'CASH' && r.yieldPct != null).length,
  )
  check(
    'WB-1m … so the live book’s served yields are counted, never claimed absent',
    cov.withYield > 0,
    `${cov.withYield} rows serve a yield`,
  )
  eq(
    'WB-1n … and its D7 count is named for what D7 proves: records OLDER than the quote',
    cov.olderRecords,
    olderRecordsIn(ROWS),
  )

  const totals = ws.valueTotal(ROWS)
  eq('WB-1g a value total counts only the rows whose value IS served', totals.valued, ROWS.filter((r: HoldingsRow) => r.marketValue !== null).length)
  eq('WB-1g … and prints its denominator with it', totals.rows, ROWS.length)
  eq('WB-1g a share of nothing is unknown, not 0', ws.shareOfValue({ usd: 0, valued: 0, rows: 1 }, { usd: 0, valued: 0, rows: 1 }), null)

  eq(
    'WB-1c the Valuation lens is the reference’s ten equity columns, in its order',
    JSON.stringify(ws.equityColumns('valuation')),
    JSON.stringify(['identity', 'weight', 'pe', 'peg', 'ytd', 'trend', 'beta', 'yield', 'gain', 'protection']),
  )
  eq(
    'WB-1c the fund table is the reference’s eight fund columns',
    JSON.stringify(ws.fundColumns('valuation')),
    JSON.stringify(['identity', 'weight', 'yield', 'expense', 'ytd', 'trend', 'gain', 'protection']),
  )
  eq('WB-1c the reference’s own header wording is pinned', ws.COLUMN_LABEL.pe, 'P/E trailing → fwd')
  eq('WB-1c … and the identity header', ws.COLUMN_LABEL.identity, 'Security · account')
  check(
    'WB-1c no lens invents a column with no served field',
    ['valuation', 'income', 'risk'].every((l: string) =>
      [...ws.equityColumns(l), ...ws.fundColumns(l)].every((k: string) => k in ws.COLUMN_LABEL),
    ),
  )
}

// ---- WB-1 page: the reference’s layout, rendered --------------------------------------------------------

const pageHtml = renderPage(FIXTURE_BOOK)
const twoHtml = renderPage(TWO_BOOK)

if (pageHtml === null || twoHtml === null) {
  check('WB-1 the page renders', false, 'no module exporting FundamentalsPage could be required')
} else {
  const pageText = stripTags(pageHtml)

  // WB-1a: the five cards, in the reference's order and with its wording.
  const cardLabels = ['Equity sleeve P/E', 'Book beta', 'Book yield · income', 'Largest sector', 'Coverage']
  const positions = cardLabels.map(l => pageHtml.indexOf(`fw-card-label\">${l}`))
  check('WB-1a all five rollup cards are rendered', positions.every(i => i >= 0), JSON.stringify(positions))
  check(
    'WB-1a the cards keep the reference’s order',
    positions.every((v, i) => i === 0 || positions[i - 1] < v),
    JSON.stringify(positions),
  )

  const cardsRegion = pageHtml.slice(pageHtml.indexOf('fw-cards'), pageHtml.indexOf('fw-toolbar'))
  const cardsText = stripTags(cardsRegion)
  // WB-1m: the card states the coverage it has. The deployed fold claimed no row serves a yield while the live
  // book served one — an absent aggregate is not the same statement as an absent field.
  const servedYield = FIXTURE_BOOK.rows.filter(r => r.kind !== 'CASH' && r.yieldPct != null).length
  check(
    'WB-1m the yield card states how many rows serve a yield, and its aggregate Unknown with the reason',
    cardsText.includes('Book yield · income') &&
      cardsText.includes(`served on ${servedYield} of ${FIXTURE_BOOK.rows.length} rows; aggregate Unknown`),
    cardsText.slice(0, 500),
  )
  check(
    'WB-1m … and it never claims the book serves no yield',
    !cardsText.includes('N/A on every row') && !cardsText.includes('no yield'),
    cardsText.slice(0, 500),
  )
  // WB-1n: D7 proves the record predates the quote. "Stale" would claim a freshness rule was violated.
  const olderCount = olderRecordsIn(FIXTURE_BOOK.rows)
  check(
    'WB-1n the Coverage card says “older than the quote”, never “stale”',
    cardsText.includes(`${olderCount} ${olderCount === 1 ? 'record' : 'records'} older than the quote`) && !cardsText.includes('stale'),
    cardsText.slice(0, 500),
  )
  check(
    'WB-1b the three Tier 2 cards print Unknown in WB-1',
    count(cardsRegion, 'fw-card-value\">Unknown') >= 3,
    `${count(cardsRegion, 'fw-card-value\">Unknown')} Unknown values`,
  )
  check(
    'WB-1b each Tier 2 card names the formula it owns',
    ['weight-harmonic, trailing → forward', 'weight-averaged, cash at 0', 'served sector × served weight'].every(s => cardsText.includes(s)),
    cardsText.slice(0, 500),
  )
  eq(
    'WB-1a Coverage counts served multiples against the ROWS SERVE, not against a derived total',
    cardsText.includes(`${FIXTURE_BOOK.rows.filter(r => r.fundamentals?.peTrailing != null).length} of ${FIXTURE_BOOK.rows.length} rows`),
    true,
  )

  // Header line: rows · scope · source · the served mark clock.
  check('WB-1a the header states the row count and the shell scope', pageText.includes(`${FIXTURE_BOOK.rows.length} rows`) && /all accounts \(\d+\)/.test(pageText))
  check(
    'WB-1a the header names its source and the served mark clock, not a borrowed one',
    pageText.includes('synthetic fixture') && pageText.includes('marks as of 2026-11-14T21:00:00Z'),
  )
  eq('WB-1a the Not-wired box is printed exactly once', count(pageText, 'Not wired: valuation-assessment@1'), 1)

  // WB-1o: one top-level heading in the document. The shell renders the crumb as its <h1> on every book page, so
  // this page must contribute none — a page <h1> beside the crumb duplicated the document's H1 (live audit).
  eq('WB-1o the page contributes no <h1> of its own', count(pageHtml, '<h1'), 0)
  check(
    'WB-1o … and the workspace title is the H2 the reference’s type is applied to',
    pageHtml.includes('<h2 class="fw-title">Fundamentals workspace</h2>'),
    'workspace title heading missing',
  )

  // WB-1c: the equity table's columns, in the reference's order.
  // The section cards are the split points: "Funds" also appears in the sector options, so a text index would
  // slice the toolbar instead of the tables.
  const sectionBlocks = pageHtml.split('class="fw-section-head"')
  const eqTable = sectionBlocks[1] ?? ''
  const fundTable = sectionBlocks[2] ?? ''
  check('WB-1c both section cards are rendered', sectionBlocks.length >= 3, `${sectionBlocks.length} blocks`)
  const eqHeads = [...eqTable.matchAll(/<th scope="col">([^<]*)<\/th>/g)].map(m => m[1])
  check(
    'WB-1c the equity header row is the reference’s, column for column',
    JSON.stringify(eqHeads) ===
      JSON.stringify([
        'Security · account',
        'Weight · value',
        'P/E trailing → fwd',
        'PEG',
        'YTD',
        'Trend',
        'Beta',
        'Yield',
        'Gain / loss',
        'Protection',
      ]),
    JSON.stringify(eqHeads),
  )
  const fundHeads = [...fundTable.matchAll(/<th scope="col">([^<]*)<\/th>/g)].map(m => m[1])
  check(
    'WB-1c the fund header row is the reference’s fund set — no empty P/E column on a fund',
    JSON.stringify(fundHeads) ===
      JSON.stringify(['Fund · account', 'Weight · value', 'Yield', 'Expense ratio', 'YTD', 'Trend', 'Gain / loss', 'Protection']),
    JSON.stringify(fundHeads),
  )

  // WB-1i: the served cells.
  check('WB-1i a served P/E prints both hundreds ways', pageText.includes('21.4x → 18.9x'), 'missing 21.4x → 18.9x')
  check('WB-1i PEG prints as served', pageHtml.includes('>1.62<'), 'PEG 1.62 missing')
  check('WB-1i YTD prints signed', pageText.includes('+18.20%'), 'YTD missing')
  check('WB-1i the trend cell carries the 200-day line and RSI', pageText.includes('+12.70% vs 200d') && pageText.includes('RSI 61.3'), 'trend cell incomplete')
  check('WB-1i gain carries the dollar change and the cost basis', pageText.includes('+25.00%') && pageText.includes('+$3,000.00') && pageText.includes('cost $60.00'))
  // WB-1i: an ACTIVE stop — served price, PROTECTED state, not stale — is the one case the word "Protected" rides.
  const qztaRowText = groupRowText(pageHtml, 'QZTA')
  check(
    'WB-1i the active stop prints Protected with the served stop and the stop-read clock',
    qztaRowText.includes('Protected') && qztaRowText.includes('stop $68.00 · stop read 11-14'),
    qztaRowText.slice(-300),
  )
  // WB-1p: the stop rule. A recorded stop with no served price, or a stale read, is NOT protection and must not
  // print the word. The deployed fold printed "Protected pending activation · read 11-14" for exactly this case.
  const PENDING_BOOK: HoldingsBook = {
    ...FIXTURE_BOOK,
    rows: FIXTURE_BOOK.rows.map(r =>
      r.symbol === 'QZTA' && r.protection !== null
        ? {
            ...r,
            protection: {
              ...r.protection,
              stop: null,
              // The live shape: the basis is a machine token, the reason carries the words "GTC".
              basis: 'broker_resting',
              reason: 'Resting GTC stop, pending activation',
            },
          }
        : r,
    ),
  }
  const pendingHtml = renderPage(PENDING_BOOK)
  const pendingRow = pendingHtml === null ? '' : groupRowText(pendingHtml, 'QZTA')
  check(
    'WB-1p a recorded stop with no served price reads “Stop recorded (GTC), pending activation · stop read …”',
    pendingRow.includes('Stop recorded (GTC)') && pendingRow.includes('pending activation · stop read 11-14'),
    pendingRow.slice(-300),
  )
  check(
    'WB-1p … and never the word Protected for a pending stop',
    !pendingRow.includes('Protected'),
    pendingRow.slice(-300),
  )
  check(
    'WB-1p … with the served basis, reason and next step on the cell for the pointer',
    pendingHtml !== null &&
      groupRow(pendingHtml, 'QZTA').includes('broker_resting') &&
      groupRow(pendingHtml, 'QZTA').includes('Resting GTC stop, pending activation') &&
      groupRow(pendingHtml, 'QZTA').includes('None — protection is in place.'),
    'the served sentence is not on the cell',
  )
  const STALE_BOOK: HoldingsBook = {
    ...FIXTURE_BOOK,
    rows: FIXTURE_BOOK.rows.map(r =>
      r.symbol === 'QZTA' && r.protection !== null
        ? { ...r, protection: { ...r.protection, stale: true } }
        : r,
    ),
  }
  const staleHtml = renderPage(STALE_BOOK)
  const staleRow = staleHtml === null ? '' : groupRowText(staleHtml, 'QZTA')
  check(
    'WB-1p a stale stop read keeps its served price but reads “Stop recorded (GTC)” and dates the read as older',
    staleRow.includes('Stop recorded (GTC)') && staleRow.includes('stop $68.00 · stop read 11-14 (older than the quote)'),
    staleRow.slice(-300),
  )
  check('WB-1p … and never the word Protected for a stale stop', !staleRow.includes('Protected'), staleRow.slice(-300))
  check(
    'WB-1i the fund row prints the fund columns: expense ratio is the muted N/A with its reason',
    fundTable.includes('expense ratio is not served by this read'),
  )
  check(
    'WB-1i a missing multiple is N/A, never 0',
    pageText.includes('N/A') && !/N\/A — no multiple served/.test(pageText),
    'long N/A text leaked into a cell',
  )
  check(
    'WB-1i an unpriced row prints N/A for price and value, with the reason on the cell',
    pageHtml.includes('aria-label="N/A — no price served"') && pageHtml.includes('aria-label="N/A — value not served"'),
  )

  // WB-1d: two accounts, one row, no summed percentage.
  const twoText = stripTags(twoHtml)
  check('WB-1d the two-account security is one row stating the account count', twoText.includes('2 accounts'), 'no account-count cell')
  check(
    'WB-1d … with each account’s own served weight on its own subline',
    twoText.includes('Synthetic taxable · 15.00%') && twoText.includes('Synthetic retirement · 5.00%'),
  )
  check(
    'WB-1d the summed 20.00% is printed in no weight cell (the twin’s own SIGNED +20.00% gain is a different field)',
    !twoText.includes('· 20.00%'),
    'a summed percentage reached a weight cell',
  )
  eq(
    'WB-1d the two-account book still renders ONE QZTA identity cell',
    count(twoHtml, 'data-group="QZTA"'),
    1,
  )

  // WB-1l: the fix sprint's item 1. The deployed fold printed the lead leg's gain and stop only, under no account
  // qualifier; each of these pins fails on that render.
  const twoQzta = groupRowText(twoHtml, 'QZTA')
  check(
    'WB-1l gain/loss prints BOTH accounts’ own served gains — a first-leg-only render shows the taxable leg alone',
    twoQzta.includes('Synthetic taxable · +25.00% · +$3,000.00 · cost $60.00') &&
      twoQzta.includes('Synthetic retirement · +20.00% · +$1,500.00 · cost $60.00'),
    twoQzta.slice(0, 600),
  )
  check(
    'WB-1l protection prints BOTH accounts’ own stop reads, in the position sublines’ order',
    twoQzta.includes('Synthetic taxable · Protected · stop $68.00 · stop read 11-14') &&
      twoQzta.includes('Synthetic retirement · Protected · stop $68.00 · stop read 11-14'),
    twoQzta.slice(0, 600),
  )
  eq(
    'WB-1l every per-account gain and protection subline is its own detail action',
    count(groupRow(twoHtml, 'QZTA'), 'fw-acct'),
    4,
  )
  const gapQzta = groupRowText(renderPage(GAP_BOOK) ?? '', 'QZTA')
  check(
    'WB-1l a second leg with no stop prints its own Gap state beside the other leg’s stop (never the first leg alone)',
    gapQzta.includes('Synthetic retirement · Gap · no resting stop') &&
      gapQzta.includes('Synthetic taxable · Protected · stop $68.00'),
    gapQzta.slice(0, 600),
  )

  // WB-1f: the D7 mark, counted against the model.
  const staleRows = FIXTURE_BOOK.rows.filter(r => {
    const rec = r.profileUpdatedAt === null ? NaN : Date.parse(r.profileUpdatedAt)
    const q = r.priceAsOf === null ? NaN : Date.parse(r.priceAsOf)
    return Number.isFinite(rec) && Number.isFinite(q) && rec < q
  }).length
  eq('WB-1f the ▲ mark appears only on rows whose record clock is older than the quote clock', count(pageHtml, '▲ record 11-14'), staleRows)
  check('WB-1f no ▲ mark rides a row with no quote clock', !pageText.includes('▲ record  ·'), 'empty record date printed')

  // WB-1g: the two derived marks carry a pinned denominator; WB-2 values do not appear.
  check('WB-1g the Equities share is tagged derived', /fw-count[\s\S]{0,200}fw-tag/.test(eqTable), 'no derived tag in the equity header')
  check(
    'WB-1g the derived tag names its denominator (valued rows, not all rows)',
    eqTable.includes('over 8 of 9 rows whose value is served'),
    'denominator text missing',
  )
  check('WB-1g no Tier 2 formula value is printed in WB-1', !pageText.includes('implies EPS'), 'an implied-EPS cell reached WB-1')

  // WB-1h: scroll containers and the collapsed cash line.
  const tables = [...pageHtml.matchAll(/<table/g)].length
  const wraps = [...pageHtml.matchAll(/table-wrap/g)].length
  check('WB-1h every table sits inside a .table-wrap (design gate rule 5)', wraps >= tables && tables >= 2, `${tables} tables / ${wraps} wraps`)
  check(
    'WB-1h the cash line is a collapsed <details> with its count, share and total on the face of it',
    /<details class="fw-cash"><summary>/.test(pageHtml) &&
      pageText.includes('1 row across accounts, collapsed') &&
      pageText.includes('43.0% of book') &&
      pageText.includes('$43,050'),
    'cash line incomplete',
  )

  // WB-1j: the disclosure cannot claim a formula the page does not have.
  check(
    'WB-1j the disclosure states the grouping rule and the Tier 2 deferral',
    pageText.includes('No percentage is summed') && pageText.includes('WB-2'),
  )
  check(
    'WB-1j the one Tier 3 sentence is printed, and the reference’s foot rule survives',
    pageText.includes('Not served by this read: valuation-assessment@1') &&
      pageText.includes('Printed as served unless tagged derived'),
  )
  check(
    'WB-1j the page prints no placeholder brackets from the design document',
    !/\[(w|y|er|state|g\/l|ytd|beta|peg|account)[^\]]*\]/.test(pageText),
    'a bracketed placeholder leaked',
  )

  // WB-1k: the elements the reference does NOT draw stay undrawn, and the two counts that could disagree with
  // their own denominator are pinned to one population (review -7 preflight D3/D4/D5/D7/D8).
  const sectionHeads = (pageHtml.match(/class="fw-section-head"[\s\S]*?<\/div>/g) ?? []).map(stripTags)
  check(
    'WB-1k the Funds header is the reference’s sentence alone — no count to pluralise',
    sectionHeads.length === 2 && !/· \d+ funds?\b/.test(sectionHeads[1] ?? ''),
    JSON.stringify(sectionHeads),
  )
  check(
    'WB-1k … and it reads exactly the reference’s words',
    (sectionHeads[1] ?? '').includes('Funds · ETFs and mutual funds get fund columns, not empty P/E cells'),
    sectionHeads[1],
  )
  check('WB-1k the Equities header pluralises its count', /Equities · \d+ positions? ·/.test(sectionHeads[0] ?? ''), sectionHeads[0])
  eq('WB-1k the funds table draws no weight bar (the reference draws it in Equities only)', count(fundTable, 'fw-bar'), 0)
  check('WB-1k … and the equities table still draws one per row', count(eqTable, 'fw-bar') >= 2, `${count(eqTable, 'fw-bar')} bars`)
  eq('WB-1k a fund’s subline carries account and price, never a share count', count(fundTable, ' sh · '), 0)
  check('WB-1k … while an equity subline carries one', count(eqTable, ' sh · ') > 0)

  // The cash share and the Coverage card must name the population they actually divided by.
  const tablesMod: any = safeRequire('./WorkspaceTables')
  if (tablesMod !== null && typeof tablesMod.CashLineRow === 'function' && workspaceModule !== null) {
    const wv = workspaceModule.buildWorkspace(ROWS, 'security')
    const viewCash = stripTags(
      renderToStaticMarkup(createElement(tablesMod.CashLineRow, { section: wv.cash, viewValue: wv.value, shareOf: 'view' })),
    )
    check(
      'WB-1k a filtered view’s cash line says “of view”, never “of book”',
      viewCash.includes('% of view') && !viewCash.includes('% of book'),
      viewCash,
    )
  } else {
    check('WB-1k CashLineRow is reachable for the share-label check', false, 'WorkspaceTables not emitted')
  }
  const twoCards = stripTags(twoHtml.slice(twoHtml.indexOf('fw-cards'), twoHtml.indexOf('fw-toolbar')))
  const twoMult = TWO_BOOK.rows.filter(r => r.kind !== 'CASH' && r.fundamentals?.peTrailing != null).length
  check(
    'WB-1k the Coverage card counts the book it names — numerator and denominator are the same population',
    twoCards.includes(`${twoMult} of ${TWO_BOOK.rows.length} rows`),
    twoCards.slice(0, 300),
  )
}

// ---- G1: the shell’s scope wiring survives WB-1 ---------------------------------------------------------

eq('G1 the fundamentals route is a book route', isBookRoute(FUNDAMENTALS_ROUTE), true)
eq('G1 the holdings route is still a book route', isBookRoute(HOLDINGS_ROUTE), true)
const bar = barStatus(FUNDAMENTALS_ROUTE, { book: FIXTURE_BOOK, loading: false, error: null, notice: null })
eq('G1 on this route the top bar may show the book this page read', bar.kind, 'book')

if (failures > 0) {
  console.error(`FAIL — ${failures} assertion(s):`)
  for (const f of fails) console.error(`  ✗ ${f}`)
  process.exit(1)
}
console.log(`PASS — ${ROWS.length} synthetic rows (+1 twin), WB-1 layout, grouping, D7 mark and derived tags green`)
