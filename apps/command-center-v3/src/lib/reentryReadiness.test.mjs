// node --experimental-strip-types src/lib/reentryReadiness.test.mjs
//
// FQ-051: the readiness rows repeated the writer's codes (BUY_READY, ENTRY_NEAR) as the operator's text. The words are
// the page's; the codes stay as the chip's secondary detail.
import { clockUtc, emptyText, LANE_TITLE, ledgerPopulation, packetPopulations, populationLegend, readinessOf, readinessSummary, readinessWords, resistancePopulation } from './reentryReadiness.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

// ---- 1. the three states the runner writes have words ------------------------------------------------------------
// OBS-B2-4d: a packet is a record of a moment, not a current verdict. The chip once read "Ready to buy now" on a
// packet 55 h old with markets closed; the words must state what the packet recorded, never what is true now.
check('BUY_READY states what the packet recorded', readinessWords('BUY_READY') === 'Recorded ready to buy', readinessWords('BUY_READY'))
check('ENTRY_NEAR states what the packet recorded', readinessWords('ENTRY_NEAR') === 'Recorded near the entry zone', readinessWords('ENTRY_NEAR'))
check('WATCH is plain', readinessWords('WATCH') === 'Watching', readinessWords('WATCH'))
check('no state word claims the present', ['BUY_READY', 'ENTRY_NEAR', 'WATCH'].every(c => !/\bnow\b/i.test(readinessWords(c))), [readinessWords('BUY_READY'), readinessWords('ENTRY_NEAR')].join(' | '))

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
check('the summary names what it counted', s === '3 recorded ready to buy · 2 recorded near the entry zone · 2 other', s)
check('and carries no code', !/_/.test(s) && !/BUY_READY/.test(s))
check('the summary makes no present-tense readiness claim', !/\bnow\b/i.test(s), s)
check('a quiet lane still counts zero plainly', readinessSummary({}, 0) === '0 recorded ready to buy · 0 recorded near the entry zone', readinessSummary({}, 0))
check('missing counts do not become NaN', !/NaN/.test(readinessSummary(null, 4)), readinessSummary(null, 4))
check('a negative remainder is never shown', !/-/.test(readinessSummary({ BUY_READY: 9 }, 2)), readinessSummary({ BUY_READY: 9 }, 2))

// ---- 5. the empty state says what happened -------------------------------------------------------------------------
const e = emptyText(24)
check('the empty state names the window', /last 24h/.test(e), e)
check('and says what the runner does, in words', /ready to buy|entry zone/.test(e), e)
check('without a single code', !/_/.test(e) && !/BUY_READY|ENTRY_NEAR/.test(e), e)

// ---- 6. OBS-B2-4d: four counts on one page, four different populations ------------------------------------------
// Live 2026-11-14: the re-entry ledger held 93 symbols, the resistance cache 95, and the entry-alert index 36 current
// packets + 275 older ones. The page printed each as a bare number, so a reader could take 36 for "symbols tracked".
// Every count must carry its population, its unit and its clock; a count the server did not send is not a zero.
// 36 rows over 34 symbols: the index serves one row per (symbol, account), so packets > symbols is normal (FQ-096).
const rows36 = Array.from({ length: 36 }, (_, i) => ({ symbol: `ZZ${String(i % 34).padStart(2, '0')}` }))
const pk = packetPopulations({ count: 36, rows: rows36, stale: new Array(275).fill(null), max_age_h: 48, max_age_basis: 'trading_days' })
check('current entries are counted in packets', /36 current packets/.test(pk), pk)
check('and again in distinct symbols', /34 symbols/.test(pk), pk)
check('the window is stated with its basis', /48 h trading window \(weekends and exchange holidays not counted\)/.test(pk), pk)
check('older entries are named as packets kept in history', /275 packets older than the 48 h trading window/.test(pk) && /kept in history/.test(pk), pk)
const pkNoStale = packetPopulations({ count: 36, rows: rows36 })
check('an older count the server did not send is never 0', /not sent/.test(pkNoStale) && !/\b0 packets/.test(pkNoStale), pkNoStale)
const pkNoCount = packetPopulations({ rows: rows36, stale: [] })
check('a current count the server did not send is stated, never the row count', /current packet count not sent/.test(pkNoCount), pkNoCount)
check('a lane with none older says so, not a blank', /none older than the 24 h window/.test(packetPopulations({ count: 0, rows: [], stale: [], max_age_h: 24 })), packetPopulations({ count: 0, rows: [], stale: [], max_age_h: 24 }))

// ---- 7. the resistance universe is a rule, not "symbols" -----------------------------------------------------------
const rp = resistancePopulation({ symbol_count: 95, symbols: {}, generated_at: '2026-11-13T21:40:02.768644+00:00' })
check('the resistance universe names its rule', /95 symbols in the resistance universe/.test(rp) && /sold in the last 365 days/.test(rp), rp)
check('and its generation clock in UTC', /generated 2026-11-13 21:40 UTC/.test(rp), rp)
const rf = resistancePopulation({ symbol_count: 95, generated_at: null, matching: 12 })
check('a filter is stated beside the universe, never instead of it', /95 symbols/.test(rf) && /12 matching the filter/.test(rf), rf)
check('a missing clock says so', /generation time not published/.test(resistancePopulation({ symbol_count: 95 })), resistancePopulation({ symbol_count: 95 }))
check('a stamp with no offset says the offset was not published, not that one was served',
  /offset not published/.test(clockUtc('2026-11-14T18:11:33')) && !/as served/.test(clockUtc('2026-11-14T18:11:33')), clockUtc('2026-11-14T18:11:33'))
check('a non-UTC offset is not called UTC', !/UTC/.test(resistancePopulation({ symbol_count: 95, generated_at: '2026-11-13T21:40:02+05:00' })), resistancePopulation({ symbol_count: 95, generated_at: '2026-11-13T21:40:02+05:00' }))

// ---- 8. the ledger population and the legend that reconciles all four ----------------------------------------------
const lp = ledgerPopulation({ symbol_count: 93, generated_at: '2026-11-13T21:40:02.768644+00:00' })
check('the ledger population is named and its generation clocked', /93 symbols in the re-entry ledger/.test(lp) && /generated 2026-11-13 21:40 UTC/.test(lp), lp)
const lg = populationLegend({
  ledger: { symbol_count: 93, generated_at: '2026-11-13T21:40:02.768644+00:00' },
  resistance: { symbol_count: 95, generated_at: '2026-11-13T21:40:02.768644+00:00' },
  packets: { count: 36, rows: rows36, stale: new Array(275).fill(null), max_age_h: 48, max_age_basis: 'trading_days' },
})
check('the legend carries all four counts', ['93 symbols in the re-entry ledger', '95 symbols in the resistance universe', '36 current packets', '275 packets older than'].every(s => lg.includes(s)), lg)
check('and says a symbol can be in more than one', /can appear in more than one/.test(lg), lg)
check('the legend never adds the counts together', !/total|altogether|sum/i.test(lg), lg)
check('a surface holding nothing says so, never 0', /none was sent/.test(populationLegend({})), populationLegend({}))
check('a legend of the two counts a surface holds names only those', (() => {
  const two = populationLegend({ ledger: { symbol_count: 93 }, resistance: { symbol_count: 95 } })
  return two.includes('93 symbols in the re-entry ledger') && two.includes('95 symbols in the resistance universe') && !/packet/.test(two)
})(), populationLegend({ ledger: { symbol_count: 93 }, resistance: { symbol_count: 95 } }))

// ---- 9. the wired lane cannot reintroduce a present-tense claim -----------------------------------------------------
// The chip and the summary are the two places the lane speaks about a packet's state. Both must come from this
// module, and neither the module nor the lane may carry the old present-tense phrase back in.
import { readFileSync } from 'node:fs'
const lane = readFileSync(new URL('../components/reentry/EntryAlertsLane.tsx', import.meta.url), 'utf8')
const mod = readFileSync(new URL('./reentryReadiness.ts', import.meta.url), 'utf8')
check('the lane renders the state through readinessWords', /readinessWords\(r\.state\)/.test(lane))
check('the lane builds its summary through readinessSummary', /readinessSummary\(counts, rows\.length\)/.test(lane))
check('the present-tense claim is gone from the lane', !/Ready to buy now/.test(lane))
check('the present-tense claim is gone from the module', !/Ready to buy now/.test(mod) && !/ready to buy now/.test(mod))
check('the summary source states the record, not the present', /recorded ready to buy/.test(mod))
check('the lane still shows the packet age beside the state', /alert \{age\(r\.packet_age_h\)\}/.test(lane))

console.log(`reentryReadiness: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
