// FQ-088 (HQ-04): the list as-of and the row's quote age/session are consumed, and a stale or missing quote is never
// presented as current. Behavioural: the helper is imported and called, not read as text.
import { listAsOfWords, quoteAge, QUOTE_STALE_MINUTES } from './opportunityQuoteAge.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

// 2026-11-04 12:00 ET = 17:00Z (EST is UTC-5 in November)
const NOW = new Date('2026-11-04T17:00:00Z')

// ---- 1. a fresh quote is current and says its session ---------------------------------------------
const fresh = quoteAge('2026-11-04T11:55:03-05:00', NOW)     // 12:00 ET, 5 min old, regular session
check('a 5-minute-old regular-session quote is current', fresh.state === 'current', JSON.stringify(fresh))
check('it names the session', fresh.session === 'regular', String(fresh.session))
check('its caption carries the age', /5m old/.test(fresh.short), fresh.short)
check('its sentence names the observation clock', /11:55 ET/.test(fresh.words), fresh.words)

// ---- 2. an old quote is stale and says so ---------------------------------------------------------
const old = quoteAge('2026-11-04T09:30:00-05:00', NOW)       // 150 min old
check(`older than ${QUOTE_STALE_MINUTES} minutes is stale`, old.state === 'stale', JSON.stringify(old))
check('and its caption says it is not current', /not current/.test(old.short), old.short)
check('and its sentence says it is not a current reading', /not a current reading/.test(old.words), old.words)

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
check('the page calls listAsOfWords on the payload as-of', /listAsOfWords\(unwrap\(oppTop\)\?\.as_of\)/.test(page), 'the payload as-of is still discarded')

console.log(`opportunityQuoteAge: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
