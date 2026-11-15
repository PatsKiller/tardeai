// Fundamentals page tests — plain node, no framework. The page's presentation rules are pure text decisions
// (`evidence.ts`) plus one JSX table, so the whole page is asserted without a browser and without a fixture
// server. Every payload here is SYNTHETIC (fixtures.ts: QZ… symbols, SYN_… accounts).
//
//   node node_modules/typescript/bin/tsc --target ES2020 --module commonjs --moduleResolution node --strict \
//     --skipLibCheck --allowImportingTsExtensions --rewriteRelativeImportExtensions --jsx react-jsx \
//     --typeRoots node_modules/@types --types node --outDir node_modules/.cache/fundamentals-tests \
//     src/pages/fundamentals/fundamentalsTests.ts
//   echo '{"type":"commonjs"}' > node_modules/.cache/fundamentals-tests/package.json
//   node node_modules/.cache/fundamentals-tests/pages/fundamentals/fundamentalsTests.js
//
// What is pinned, and why each pin can fail:
//   T-1  the two not-wired cells print the route's LITERAL, character for character;
//   T-2  they take no row, so a served valuation cannot leak a status word into the cell (no derived status);
//   T-3  a served provider multiple prints as the same multiple the Holdings preset prints, with wire named;
//   T-4  market cap prints the served field in its own unit (MILLIONS) with source AND clock of the row's
//        profile record — the cell cannot print a cap with no provenance;
//   T-5  the eight preset columns and their headers are the approved preset's, in its order;
//   T-6  every table sits in a .table-wrap, and every row's cells are the preset's own decisions on cash;
//   T-7  the two route-fixed cells are the literal on EVERY row, read cell by cell — and the P/E columns keep
//        the preset's own text, which for a fund IS a served status word (the page's foot says so).

import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import type { HoldingsRow } from '../portfolio/contract'
import { FIXTURE_BOOK, staleTrailingPe } from '../portfolio/fixtures'
import { preset } from '../portfolio/presets'
import {
  NOT_WIRED,
  assessmentText,
  marketCapClock,
  marketCapProvenance,
  marketCapSource,
  marketCapText,
  peerMedianText,
  peText,
  priceText,
  yieldText,
} from './evidence'
import { FundamentalsTable } from './FundamentalsTable'

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

// ---- T-1 / T-2: the route's literal, and no assessment status can reach it -----------------------------

eq('T-1 the not-wired literal is the route string', NOT_WIRED, 'not wired — valuation-assessment@1')
eq('T-1 peer median prints the literal', peerMedianText(), NOT_WIRED)
eq('T-1 the valuation-evidence cell prints the literal', assessmentText(), NOT_WIRED)
eq('T-2 peerMedianText takes no row', peerMedianText.length, 0)
eq('T-2 assessmentText takes no row, so a served assessment cannot leak', assessmentText.length, 0)
check(
  'T-2 the literal names the contract version',
  /valuation-assessment@1/.test(assessmentText()),
  assessmentText(),
)

// ---- T-3: served provider multiples, and the assessment fallback when no multiple is served ------------

eq('T-3 a served trailing P/E prints as the preset prints it', peText(bySymbol('QZTA'), 'peTrailing'), '21.4x')
eq('T-3 a served forward P/E prints as the preset prints it', peText(bySymbol('QZTA'), 'peForward'), '18.9x')
const lastKnown = bySymbol('QZDX')
const unassessedWithValue: HoldingsRow = { ...lastKnown, valuation: staleTrailingPe('SYN_TAX:QZDX'), fundamentals: null }
eq(
  'T-3 a null multiple with an UNASSESSED assessment keeps the last-known value and its status',
  peText(unassessedWithValue, 'peTrailing'),
  '18.8x · Unassessed (last known)',
)
eq('T-3 an assessment with no trailing measure prints N/A, not a word', peText(lastKnown, 'peTrailing'), 'N/A')
eq('T-3 a fund with no company multiple keeps the fund metric', peText(bySymbol('QZFD'), 'peTrailing'), '17.4x · fund metric')
const noPe = { ...bySymbol('QZTA'), fundamentals: { ...(bySymbol('QZTA').fundamentals as NonNullable<HoldingsRow['fundamentals']>), peTrailing: null }, valuation: null }
check(
  'T-3 a row with neither a multiple nor an assessment states both reasons',
  peText(noPe, 'peTrailing').startsWith('N/A — ') && /no served pe multiple/.test(peText(noPe, 'peTrailing')),
  peText(noPe, 'peTrailing'),
)

// ---- T-4: market cap in its own unit, with the profile record's source AND clock -----------------------

eq('T-4 millions are divided once: 41200 -> $41.2B', marketCapText(bySymbol('QZTA')), '$41.2B')
eq('T-4 230500 -> $230.5B', marketCapText(bySymbol('QZEP')), '$230.5B')
eq('T-4 a sub-billion cap stays in millions', marketCapText(bySymbol('QZDL')), '$640M')
eq('T-4 an unpublished cap is a reason, not zero', marketCapText(bySymbol('QZNV')), 'N/A — not published for this instrument')
eq('T-4 cash has no market cap', marketCapText(bySymbol('CASH')), 'N/A — cash has no market cap')
eq('T-4 source is the row profile record', marketCapSource(bySymbol('QZTA')), 'fixture')
eq('T-4 clock is the row profile clock', marketCapClock(bySymbol('QZTA')), '2026-11-14T13:00:00Z')
eq(
  'T-4 provenance prints source and clock together',
  marketCapProvenance(bySymbol('QZTA')),
  'source fixture · record 2026-11-14T13:00:00Z',
)
const unprofiled: HoldingsRow = { ...bySymbol('QZTA'), profileSource: null, profileUpdatedAt: null }
eq(
  'T-4 an unserved provenance says so instead of inventing one',
  marketCapProvenance(unprofiled),
  'source not served · record clock not served',
)

// ---- unit traps the page inherits from the wire -------------------------------------------------------

eq('T-3 a percent yield is printed once, not multiplied', yieldText(bySymbol('QZTA')), '1.80%')
eq('T-3 an unpublished yield is a reason, not zero', yieldText(bySymbol('QZDL')), 'N/A — not published for this instrument')
eq('T-3 a served price keeps its cents', priceText(bySymbol('QZTA')), '$75.00')
eq('T-3 a worthless identifier has no price to print', priceText(bySymbol('QZDX')), 'N/A — no price served for a worthless identifier')

// ---- T-5 / T-6 / T-7: the rendered table --------------------------------------------------------------

const html = renderToStaticMarkup(createElement(FundamentalsTable, { rows: ROWS, preset: PRESET }))
// What the reader sees, as text: SSR inserts comment separators between adjacent text nodes (`{head}{' '}` and
// the token), so the literal is asserted on the rendered TEXT, not on the markup string.
const text = html
  .replace(/<!--[\s\S]*?-->/g, '')
  .replace(/<[^>]*>/g, ' ')
  .replace(/\s+/g, ' ')
  .trim()

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
const literalCount = text.split(NOT_WIRED).length - 1
eq('T-1 every security row carries the literal twice (peer median + evidence)', literalCount, securityRows * 2)
check(
  'T-6 a cash row takes the preset cash rule, not the security columns',
  html.includes('aria-label="N/A — this column does not apply to a cash row"'),
)
// ---- T-7: the two route-fixed columns, cell by cell -----------------------------------------------------
//
// The fixture rows DO carry valuation-assessment@1 statuses (UNASSESSED on QZTA, FUND_METRIC on QZFD) and the
// table DOES render one of those statuses — as the preset's own P/E text ("17.4x · fund metric"). A whole-table
// regex for the raw enum names therefore proves nothing: it passes while a status word is on screen. The route
// fixes exactly two columns, so the assertion is per cell: those two cells are the literal on every row, while
// the P/E columns keep the preset's text and are allowed to say what they are.

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
  (tr.match(/<t[dh][^>]*>[\s\S]*?<\/t[dh]>/g) ?? []).map(c =>
    c.replace(/<!--[\s\S]*?-->/g, '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim(),
  )
const allRows = (html.match(/<tr[^>]*>[\s\S]*?<\/tr>/g) ?? []).map(cellsOf)
const bodyRows = allRows.filter(c => c.length === PRESET.columns.length && c !== allRows[0])
eq('T-7 every fixture row is parsed out of the rendered table, eight cells each', bodyRows.length, ROWS.length)
for (const [i, cells] of bodyRows.entries()) {
  // A cash row takes the preset's own cash rule in every column except identity and price (§3 of the READY,
  // pinned by the aria-label assertion in T-6); every security row carries the literal.
  const want = ROWS[i].kind === 'CASH' ? 'N/A' : NOT_WIRED
  eq(`T-7 ${ROWS[i].symbol}: peer median cell is ${want === NOT_WIRED ? 'the literal' : 'the cash rule'}`, cells[COL.peerMedian], want)
  eq(`T-7 ${ROWS[i].symbol}: evidence cell is ${want === NOT_WIRED ? 'the literal' : 'the cash rule'}`, cells[COL.evidence], want)
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

if (failures > 0) {
  console.error(`FAIL — ${failures} assertion(s):`)
  for (const f of fails) console.error(`  ✗ ${f}`)
  process.exit(1)
}
console.log(`PASS — ${ROWS.length} synthetic rows, ${securityRows * 2} not-wired cells, fundamentals assertions green`)
