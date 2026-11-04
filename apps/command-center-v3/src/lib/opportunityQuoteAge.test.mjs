// FQ-088 (HQ-04): the list as-of and the row's quote age/session are consumed, and a stale or missing quote is never
// presented as current. Behavioural: the helper is imported and called, not read as text.
import { listAsOfWords, opportunitiesCardState, quoteAge, QUOTE_STALE_MINUTES } from './opportunityQuoteAge.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

// 2026-11-04 12:00 ET = 17:00Z (EST is UTC-5 in November)
const NOW = new Date('2026-11-04T17:00:00Z')

// ---- 1. a fresh quote is current and says its session ---------------------------------------------
const fresh = quoteAge('2026-11-04T11:55:03-05:00', NOW)     // 12:00 ET, 5 min old, regular session
check('a 5-minute-old regular-session quote is current', fresh.state === 'current', JSON.stringify(fresh))
check('it names the session', fresh.session === 'regular', String(fresh.session))
check('its caption carries the age', /minutes? old/.test(fresh.short), fresh.short)
check('its sentence names the observation clock', /11:55 ET/.test(fresh.words), fresh.words)

// ---- 2. an old quote is stale and says so ---------------------------------------------------------
const old = quoteAge('2026-11-04T09:30:00-05:00', NOW)       // 150 min old
check(`older than ${QUOTE_STALE_MINUTES} minutes is stale`, old.state === 'stale', JSON.stringify(old))
check('and its caption says it is not current', /not current/.test(old.short), old.short)
check('and its sentence says it is not a current reading', /not a current reading/.test(old.words), old.words)


// ---- 2b. R3 boundary controls, the exact cases codex measured --------------------------------
const at30 = quoteAge('2026-11-04T12:00:00-05:00', new Date('2026-11-04T12:30:00-05:00'))
check('exactly 30 minutes old is still inside the window', at30.state === 'current', JSON.stringify(at30))
const at30m20 = quoteAge('2026-11-04T11:59:40-05:00', new Date('2026-11-04T12:30:00-05:00'))
check('30m20s old is stale, not rounded down to 30m', at30m20.state === 'stale', JSON.stringify(at30m20))
const plus30 = quoteAge('2026-11-04T12:30:30-05:00', new Date('2026-11-04T12:30:00-05:00'))
check('30 seconds in the future is not current', plus30.state === 'unknown', JSON.stringify(plus30))
const plus1 = quoteAge('2026-11-04T12:30:01-05:00', new Date('2026-11-04T12:30:00-05:00'))
check('1 second in the future is already not current', plus1.state === 'unknown', JSON.stringify(plus1))

// ---- 3. the real 11:30 ET quote is stale by the afternoon, and pre-market by session ----------------
const premarket = quoteAge('2026-11-04T09:00:00-05:00', new Date('2026-11-04T09:05:00-05:00'))
check('a pre-market quote is named pre-market', premarket.session === 'pre-market', String(premarket.session))
const morning = quoteAge('2026-11-04T11:30:03-05:00', new Date('2026-11-04T11:35:00-05:00'))
check('an 11:30 ET quote five minutes later is current', morning.state === 'current', JSON.stringify(morning))

// ---- 4. missing, unreadable and future clocks are UNKNOWN, never current ---------------------------
for (const bad of [undefined, null, '', 'not-a-date', {}]) {
  const q = quoteAge(bad, NOW)
  check(`no readable quote (${JSON.stringify(bad)}) is unknown`, q.state === 'unknown', JSON.stringify(q))
  check(`and it is not presented as current (${JSON.stringify(bad)})`, !/current$/.test(q.short) || /not current/.test(q.short), q.short)
}
const future = quoteAge('2026-11-04T19:00:00-05:00', NOW)
check('a future observation is not trusted', future.state === 'unknown', JSON.stringify(future))

// ---- 5. the list as-of is rendered in words, or absent when the payload did not carry one ----------
check('the list as-of is said in words', /Opportunity list as of 12:00 ET/.test(listAsOfWords('2026-11-04T17:00:00Z') ?? ''), String(listAsOfWords('2026-11-04T17:00:00Z')))
for (const bad of [undefined, null, '', 'nope']) check(`no list as-of for ${JSON.stringify(bad)}`, listAsOfWords(bad) === null, String(listAsOfWords(bad)))

// ---- 6. the page actually consumes both ---------------------------------------------------------
import { readFileSync } from 'node:fs'
const page = readFileSync(new URL('../pages/HomeDoNow.tsx', import.meta.url), 'utf8')
check('the page renders the list as-of', /data-testid="home-opportunities-as-of"/.test(page), 'no list as-of on the page')
check('the page renders a per-row quote age', /data-testid=\{`home-opp-quote-\$\{o\.symbol\}`\}/.test(page), 'no per-row quote caption')
check('the page calls quoteAge on the row quote', /quoteAge\(o\?\.inputs_as_of\?\.quote\)/.test(page), 'the row quote is not aged')
// R1: a failed poll must not look current, and a failed FIRST load must not claim a list it does not have
check('the page feeds the poll transport state into the tested composition',
  /opportunitiesCardState\(\{[\s\S]{0,200}?error: !!oppError, stale: !!oppStale/.test(page), 'the poll transport state is not consumed')
check('and renders the composition\'s own retained sentence',
  /oppState\.retainedText/.test(page), 'the page invents its own retained wording instead of rendering the tested one')
check('and renders the composition\'s own empty-state sentence',
  /oppState\.emptyText/.test(page), 'the page invents its own empty-state wording instead of rendering the tested one')
// R2: the age is labelled as the input clock, never as proof the ratio is current
check('the caption calls it the input clock', /input clock/.test(page), 'the caption does not name the clock it uses')
check('a row with no price is called plan-based', /plan-based · not a current price/.test(page), 'a plan-only ratio is not qualified')
check('and the title disclaims the binding', /not proven to come from that observation/.test(page), 'the tooltip does not disclaim the price binding')
check('the page calls listAsOfWords on the payload as-of', /listAsOfWords\(unwrap\(oppTop\)\?\.as_of\)/.test(page), 'the payload as-of is still discarded')
// FQ-114 wiring: the page must take its rows from the receipt helper, never from the raw items list.
check('the page selects top candidates through the receipt helper', /topEligibleRows\(oppBody\)/.test(page),
  'the page still takes every row, receipt or not')
check('the page renders the producer qualification sentence', /home-opportunities-qualification/.test(page),
  'the producer risk/qualification sentence is not rendered')

// ---- 7. what the card may SAY on each transport state (cc-deepseek-8 R1 at f44f21fbe) --------------
// Behavioural, not string-presence: these are the compositions that produced the false statement.
const failedFirstLoad = opportunitiesCardState({ loading: false, error: true, stale: false, itemCount: 0, listLoaded: false })
check('a failed FIRST load claims no retained list', failedFirstLoad.retained === false && failedFirstLoad.retainedText === '',
  JSON.stringify(failedFirstLoad))
check('a failed first load says the request failed, not "Loading…"',
  failedFirstLoad.emptyText.includes('could not be loaded') && !/Loading/.test(failedFirstLoad.emptyText),
  failedFirstLoad.emptyText)
check('and it never claims the bar is empty', !/Nothing clears/.test(failedFirstLoad.emptyText), failedFirstLoad.emptyText)

const staleFirstLoad = opportunitiesCardState({ loading: false, error: false, stale: true, itemCount: 0, listLoaded: false })
check('a retained-but-empty answer is a failure, not an empty list', staleFirstLoad.emptyText === failedFirstLoad.emptyText,
  staleFirstLoad.emptyText)

const failedWithRows = opportunitiesCardState({ loading: false, error: true, stale: false, itemCount: 3, listLoaded: true })
check('a failed REFRESH with rows says retained', failedWithRows.retained === true && /showing the last list/.test(failedWithRows.retainedText),
  JSON.stringify(failedWithRows))
check('and shows no empty-state sentence', failedWithRows.emptyText === '', failedWithRows.emptyText)

const loading = opportunitiesCardState({ loading: true, error: false, stale: false, itemCount: 0, listLoaded: false })
check('a first load in flight says Loading', loading.emptyText === 'Loading…' && loading.retained === false, JSON.stringify(loading))

const loadedEmpty = opportunitiesCardState({ loading: false, error: false, stale: false, itemCount: 0, listLoaded: true, qualificationPresent: true })
check('a loaded empty list with the producer receipt says no candidate clears the bar',
  loadedEmpty.emptyText === 'No reviewed name clears the bar right now.', loadedEmpty.emptyText)

const loadedNoReceipt = opportunitiesCardState({ loading: false, error: false, stale: false, itemCount: 0, listLoaded: true })
check('an empty list WITHOUT the producer receipt says the qualification is unavailable, not that none qualifies',
  loadedNoReceipt.emptyText === 'Top list qualification unavailable; open the research list.', loadedNoReceipt.emptyText)

// ---- 9. cx-openai-4 R1: a timestamp with no zone is not a timestamp we may read (AGENTS.md §5) ----------
for (const unzoned of ['2026-11-04T17:00:00', '2026-11-04T17:00:00.000', '2026-11-04', '2026-11-04 17:00:00']) {
  const q = quoteAge(unzoned, NOW)
  check(`an unzoned timestamp (${unzoned}) is unknown, never read as the host's local clock`, q.state === 'unknown', JSON.stringify(q))
  check(`and its list as-of is not invented (${unzoned})`, listAsOfWords(unzoned) === null, String(listAsOfWords(unzoned)))
}
check('the same instant WITH a zone is still read',
  quoteAge('2026-11-04T17:00:00Z', NOW).state === 'current' && listAsOfWords('2026-11-04T17:00:00Z') !== null,
  JSON.stringify(quoteAge('2026-11-04T17:00:00Z', NOW)))
check('a numeric offset counts as a named zone',
  quoteAge('2026-11-04T12:00:00-05:00', NOW).state === 'current', JSON.stringify(quoteAge('2026-11-04T12:00:00-05:00', NOW)))
check('a Date object carries its own instant and is accepted', quoteAge(new Date('2026-11-04T17:00:00Z'), NOW).state === 'current')

// ---- 10. codex P2651-R4: a truthy body is not a successful read -------------------------------------
const srcErr = opportunitiesCardState({ loading: false, error: false, stale: false, itemCount: 0, listLoaded: false, sourceError: true, qualificationPresent: true })
check('ok:false is a source error, never "nothing clears the bar"',
  srcErr.emptyText.includes('source error') && !/Nothing clears|No reviewed name/.test(srcErr.emptyText), srcErr.emptyText)
const malformed = opportunitiesCardState({ loading: false, error: false, stale: false, itemCount: 0, listLoaded: false, sourceError: true })
check('a body with no items array is a source error, not a perpetual Loading',
  malformed.emptyText.includes('source error') && !/Loading/.test(malformed.emptyText), malformed.emptyText)
const answeredEmpty = opportunitiesCardState({ loading: false, error: false, stale: false, itemCount: 0, listLoaded: true, qualificationPresent: false })
check('a real answer with no receipt says the qualification is unavailable', /qualification unavailable/.test(answeredEmpty.emptyText), answeredEmpty.emptyText)

// ---- 8. FQ-114: the producer, not the page, decides who is a top candidate -------------------------
import { topEligibleRows, topListNotice } from './bestOpportunities.ts'
const legacy = { items: [{ symbol: 'AAA', conviction: 90 }, { symbol: 'BBB', conviction: 80 }] }
check('a legacy response (no receipt) yields NO top candidate', topEligibleRows(legacy).length === 0,
  JSON.stringify(topEligibleRows(legacy)))
const mixed = { items: [
  { symbol: 'AAA', top_eligibility: { eligible: true } },
  { symbol: 'BBB', top_eligibility: { eligible: false } },
  { symbol: 'CCC' },
  { symbol: 'DDD', top_eligibility: { eligible: true } },
] }
check('only rows the producer marked eligible are shown', JSON.stringify(topEligibleRows(mixed).map(r => r.symbol)) === '["AAA","DDD"]',
  JSON.stringify(topEligibleRows(mixed).map(r => r.symbol)))
for (const junk of [null, undefined, {}, { items: 5 }, { items: [null, 'x'] }]) {
  check(`a malformed body (${JSON.stringify(junk)}) yields no candidate`, topEligibleRows(junk).length === 0, JSON.stringify(junk))
}
check('the producer risk sentence is carried verbatim',
  topListNotice({ top_list: { notice: 'Risk hold: RED regime — no new long.' } }) === 'Risk hold: RED regime — no new long.',
  String(topListNotice({ top_list: { notice: 'Risk hold: RED regime — no new long.' } })))
check('no notice stays silent rather than inventing an unavailable line',
  topListNotice({ items: [] }) === null && topListNotice({ top_list: { notice: '   ' } }) === null)


const healthy = opportunitiesCardState({ loading: false, error: false, stale: false, itemCount: 2, listLoaded: true })
check('a healthy list says nothing at all', healthy.retained === false && healthy.retainedText === '' && healthy.emptyText === '',
  JSON.stringify(healthy))


console.log(`opportunityQuoteAge: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
