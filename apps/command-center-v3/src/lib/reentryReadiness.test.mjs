// node --experimental-strip-types src/lib/reentryReadiness.test.mjs
//
// FQ-051: the readiness rows repeated the writer's codes (BUY_READY, ENTRY_NEAR) as the operator's text. The words are
// the page's; the codes stay as the chip's secondary detail.
import { emptyText, LANE_TITLE, readinessOf, readinessSummary, readinessWords } from './reentryReadiness.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

// ---- 1. the three states the runner writes have words ------------------------------------------------------------
check('BUY_READY is a readiness fact, not a code', readinessWords('BUY_READY') === 'Ready to buy now', readinessWords('BUY_READY'))
check('ENTRY_NEAR says how near', readinessWords('ENTRY_NEAR') === 'Nearly at the entry zone', readinessWords('ENTRY_NEAR'))
check('WATCH is plain', readinessWords('WATCH') === 'Watching', readinessWords('WATCH'))

// ---- 2. an unknown state is never described as ready and never guessed -----------------------------------------
const odd = readinessOf('QUARANTINED_PACKET')
check('an unlisted state says the page does not recognise it', odd.words === 'Unrecognised state', odd.words)
check('and it is not called ready', !/ready/i.test(odd.words), odd.words)
check('nor given a neighbour\'s meaning', !/watching|nearly/i.test(odd.words), odd.words)
check('a missing state is stated, not implied', readinessWords(null) === 'No state recorded', readinessWords(null))
check('and the code is not echoed back as the words', readinessWords('BUY_READY') !== 'BUY_READY')

// ---- 3. nothing visible carries the writer's vocabulary ----------------------------------------------------------
for (const code of ['BUY_READY', 'ENTRY_NEAR', 'WATCH', null]) {
  const w = readinessWords(code)
  check(`no underscore or ALL_CAPS code for ${code}: ${w}`, !/_/.test(w) && !/[A-Z]{3,}/.test(w), w)
}
check('the lane title has no codes', !/_/.test(LANE_TITLE) && !/BUY_READY|ENTRY_NEAR/.test(LANE_TITLE), LANE_TITLE)

// ---- 4. the summary counts in the reader's words -------------------------------------------------------------------
const s = readinessSummary({ BUY_READY: 3, ENTRY_NEAR: 2 }, 7)
check('the summary names what it counted', s === '3 ready to buy now · 2 nearly at the entry zone · 2 other', s)
check('and carries no code', !/_/.test(s) && !/BUY_READY/.test(s))
check('a quiet lane still counts zero plainly', readinessSummary({}, 0) === '0 ready to buy now · 0 nearly at the entry zone', readinessSummary({}, 0))
check('missing counts do not become NaN', !/NaN/.test(readinessSummary(null, 4)), readinessSummary(null, 4))
check('a negative remainder is never shown', !/-/.test(readinessSummary({ BUY_READY: 9 }, 2)), readinessSummary({ BUY_READY: 9 }, 2))

// ---- 5. the empty state says what happened -------------------------------------------------------------------------
const e = emptyText(24)
check('the empty state names the window', /last 24h/.test(e), e)
check('and says what the runner does, in words', /ready to buy|entry zone/.test(e), e)
check('without a single code', !/_/.test(e) && !/BUY_READY|ENTRY_NEAR/.test(e), e)

console.log(`reentryReadiness: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
