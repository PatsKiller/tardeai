// node --experimental-strip-types src/lib/intelImplication.test.mjs
//
// FQ-040: the Decision implications panel showed the whole thesis at 9–11 px with estimated-error metadata beside it.
// The row now leads with a conclusion, then how sure the source is, then the next step — and the thesis is one tap away.
import { MAX_CONCLUSION_WORDS, firstSentence, implicationModel, rowTitle, uncertaintyText } from './intelImplication.ts'

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
check('a short thesis is not marked clamped', thesisOnly.conclusionClamped === false)
check('the long case really is shorter than the thesis', thesisOnly.conclusion.length < THESIS.length / 2)
check('the conclusion carries the sentence\'s verb, not just a prefix', thesisOnly.conclusion.includes('is tracking'))

// ---- R1: an abbreviation is not a sentence end (cc-deepseek-8) ------------------------------------------------
check('vs. does not cut the conclusion',
  firstSentence('NVDA revenue is tracking 8% above consensus vs. 5% last quarter. Risk is China.')
    === 'NVDA revenue is tracking 8% above consensus vs. 5% last quarter.')
check('Dr. does not reduce the conclusion to a title',
  firstSentence('Dr. Chen notes demand is strong. Nothing else.') === 'Dr. Chen notes demand is strong.')
check('U.S. does not cut the conclusion at the country',
  firstSentence('The U.S. export rule is the risk. Nothing has priced it.') === 'The U.S. export rule is the risk.')
check('e.g. does not cut the conclusion',
  firstSentence('NVDA beats consensus e.g. by 8%. Risk remains.') === 'NVDA beats consensus e.g. by 8%.')
check('a decimal still does not split (the guard is not traded away)',
  firstSentence('Revenue grew 3.5% year over year') === 'Revenue grew 3.5% year over year')
check('a real sentence boundary still splits',
  firstSentence('Q3 beat: revenue up 12% and margins held. Margin cut the next quarter.')
    === 'Q3 beat: revenue up 12% and margins held.')
check('a boundary that leaves a fragment is refused, not shown alone',
  firstSentence('Q3 beat. Revenue rose 12%.') !== 'Q3 beat.'
    && firstSentence('Q3 beat. Revenue rose 12%.').startsWith('Q3 beat.'))

// ---- R2: a terminator-free thesis is bounded, and the expansion keeps the whole text ---------------------------
const WALL = 'NVDA ' + 'beat consensus by eight percent on three independent supply checks '.repeat(10)
  + 'and nothing has priced the China export rule'
const wallConclusion = firstSentence(WALL)
check('a terminator-free thesis is clamped to a bounded number of words',
  wallConclusion.split(' ').length <= MAX_CONCLUSION_WORDS)
check('the clamp is still the source\'s own prefix', WALL.startsWith(wallConclusion))
const wallModel = implicationModel({ ...LONG, action: null, title: WALL }, 'x')
check('the model says the conclusion was clamped', wallModel.conclusionClamped === true)
check('the full thesis is kept for the expansion', wallModel.headline === WALL)

// ---- nothing is invented when a field is missing ---------------------------------------------------------------
const bare = implicationModel({ id: 'i2', source: '', type: '', title: '', action: null, confidence: null, freshnessH: null }, 'Do something.')
check('a missing confidence says so', bare.uncertainty === 'confidence not recorded · age not recorded', bare.uncertainty)
check('a missing thesis is admitted, not faked', bare.conclusion === 'The source gave no conclusion.' && bare.headline === 'The source gave no title.')
check('no identifiers are claimed when the source gave none', bare.identifiers.length === 0)

// ---- a confidence outside 0..1 is NOT silently rescaled ---------------------------------------------------------
check('62 is not read as 62%', uncertaintyText(62, 1) === 'confidence not recorded · 1 h old', uncertaintyText(62, 1))
check('0 is a real confidence', uncertaintyText(0, null) === '0% confidence · age not recorded')
check('1 is a real confidence', uncertaintyText(1, 30) === '100% confidence · 30 h old')
// F2: a timestamp ahead of the caller's clock is a clock mismatch, never a fresh observation.
check('a future timestamp is not called fresh', uncertaintyText(0.62, -1) === '62% confidence · source timestamp is in the future', uncertaintyText(0.62, -1))

// ---- the visible title -----------------------------------------------------------------------------------------
check('the symbol labels the row', rowTitle(m, 'NVDA') === 'NVDA: review')
check('no symbol, no dangling colon', rowTitle(m, null) === 'review')

console.log(`intelImplication: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
