// node --experimental-strip-types src/lib/intelImplication.test.mjs
//
// FQ-040: the Decision implications panel showed the whole thesis at 9–11 px with estimated-error metadata beside it.
// The row now leads with a conclusion, then how sure the source is, then the next step — and the thesis is one tap away.
import { firstSentence, implicationModel, rowTitle, uncertaintyText } from './intelImplication.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

const THESIS = 'NVDA second-quarter datacenter revenue is tracking roughly 8% above consensus on three independent '
  + 'supply-chain checks. That beats the guidance midpoint. Risk is a China export rule change before the call, '
  + "which no source has priced yet, and the options market's skew does not reflect it."
const LONG = { id: 'i1', source: 'research-brief', type: 'research', symbol: 'NVDA', title: THESIS,
  summary: 'Three supply-chain checks agree; China export rule is the unpriced risk.', action: 'review', confidence: 0.62, freshnessH: 3,
  model: 'hermes-3', lane: 'research' }

const m = implicationModel(LONG, 'Read the counter-view and reconcile dissent.')
check('the row leads with the ledger action', m.conclusion === 'review' && m.conclusionKind === 'action')
check('the full thesis is kept for the expansion, not truncated in the data', m.headline === THESIS)
check('the summary is carried, not dropped', m.summary === 'Three supply-chain checks agree; China export rule is the unpriced risk.')
check('uncertainty is confidence plus age', m.uncertainty === '62% confidence · 3 h old', m.uncertainty)
check('the next step comes from the page and is not re-derived', m.nextStep === 'Read the counter-view and reconcile dissent.')
check('raw identifiers are collected for the detail', m.identifiers.map(([k]) => k).join(',') === 'Model,Lane,Source,Type')
check('and keep their exact spelling', m.identifiers[0][1] === 'hermes-3' && m.identifiers[1][1] === 'research')

// ---- the point of the row: a long thesis becomes ONE visible sentence, and it is the source's own ---------------
const thesisOnly = implicationModel({ ...LONG, action: null }, 'x')
check('with no action, the conclusion is the first sentence only', thesisOnly.conclusion === firstSentence(THESIS), thesisOnly.conclusion)
check('the first sentence is the source\'s own words, not a summary', THESIS.startsWith(thesisOnly.conclusion))
check('and it is marked as a thesis, not an action', thesisOnly.conclusionKind === 'thesis')
check('the long case really is shorter than the thesis', thesisOnly.conclusion.length < THESIS.length / 2)

// ---- nothing is invented when a field is missing ---------------------------------------------------------------
const bare = implicationModel({ id: 'i2', source: '', type: '', title: '', action: null, confidence: null, freshnessH: null }, 'Do something.')
check('a missing confidence says so', bare.uncertainty === 'confidence not recorded · age not recorded', bare.uncertainty)
check('a missing thesis is admitted, not faked', bare.conclusion === 'The source gave no conclusion.' && bare.headline === 'The source gave no title.')
check('no identifiers are claimed when the source gave none', bare.identifiers.length === 0)

// ---- a confidence outside 0..1 is NOT silently rescaled ---------------------------------------------------------
check('62 is not read as 62%', uncertaintyText(62, 1) === 'confidence not recorded · 1 h old', uncertaintyText(62, 1))
check('0 is a real confidence', uncertaintyText(0, null) === '0% confidence · age not recorded')
check('1 is a real confidence', uncertaintyText(1, 30) === '100% confidence · 30 h old')

// ---- the visible title -----------------------------------------------------------------------------------------
check('the symbol labels the row', rowTitle(m, 'NVDA') === 'NVDA: review')
check('no symbol, no dangling colon', rowTitle(m, null) === 'review')

console.log(`intelImplication: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
