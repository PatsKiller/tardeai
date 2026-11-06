// Pure-logic tests for reportFormat.ts (Reports redesign v001 — read-side formatting layer).
//   node --experimental-strip-types src/components/reports/reportFormat.test.ts
// PUBLIC repo: made-up symbols only (ZQXA, ZQXB, ZQXC …), no real holdings.
import {
  tokenize, leafTokens, plain, parseReport, extractAsOf, chipLabel, sectionSummary, isTicker,
  isMarketReport, ageLabel, splitQuery,
} from './reportFormat.ts'
import type { Tok } from './reportFormat.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}
const find = (toks: Tok[], k: string): any[] => {
  const out: any[] = []
  for (const t of toks) {
    if (t.k === k) out.push(t)
    if (Array.isArray(t.v)) out.push(...find(t.v, k))
  }
  return out
}

console.log('reportFormat — inline tokens')
const row = '- **ZQXA** Zeta Quux Corp — $133.55, -46.9% from 10-28 close; fwd P/E 34.3 → 18.2; next-FY EPS est +8.8% in 30d; ' +
  'est. revisions 30d ↑27/↓1; target $314 (+135% upside, was $341) ⚠ fell -22% vs tech median -5% — check before treating it as a sector dip'
const t1 = tokenize(row)
check('text round-trips unchanged except ** markers (no character lost)', plain(t1) === row.replace(/\*\*/g, ''))
check('**ZQXA** → ticker (bold)', find(t1, 'ticker').some(t => t.v === 'ZQXA'))
const pcts = find(t1, 'pct')
check('-46.9% is a negative pct (red)', pcts.some(p => p.v === '-46.9%' && p.tone === 'neg'))
check('+8.8% is a positive pct (green)', pcts.some(p => p.v === '+8.8%' && p.tone === 'pos'))
check('+135% positive', pcts.some(p => p.v === '+135%' && p.tone === 'pos'))
check('↑27 green, ↓1 red', find(t1, 'arrow').some(a => a.v === '↑27' && a.tone === 'pos') && find(t1, 'arrow').some(a => a.v === '↓1' && a.tone === 'neg'))
const looks = find(t1, 'look')
check('⚠ flag onward is a "look" (italic) span', looks.length === 1 && plain(looks[0].v).startsWith('⚠ fell -22%'))
check('pct inside the ⚠ span is still coloured', find(looks[0].v, 'pct').some(p => p.v === '-22%' && p.tone === 'neg'))

const range = tokenize('Monday close was up 56-72% of the time; 2.3-2.6x normal.')
check('"56-72%" is a range, not a red -72%', !find(range, 'pct').some(p => p.tone === 'neg'))
check('unsigned 72% stays neutral (not coloured)', find(range, 'pct').every(p => p.tone === 'flat'))
const unicode = tokenize('a −3% 10th percentile')
check('unicode minus −3% is negative', find(unicode, 'pct').some(p => p.v === '−3%' && p.tone === 'neg'))

const lead = tokenize('- **This is a valuation selloff, not an earnings selloff.** Prices fell; forecasts did not.')
check('bold lead sentence (≥4 words) → key highlight', find(lead, 'key').length === 1)
check('short bold label stays plain bold', find(tokenize('**Data as-of:** prices = close'), 'bold').length === 1)

const words = leafTokens('Market risk is RED 68 and CPI is Tue; the ETF and EPS and AI moved; ZQXB too.')
const tick = find(words, 'ticker').map(t => t.v)
check('RED / CPI / ETF / EPS / AI are not tickers', !tick.some(v => ['RED', 'CPI', 'ETF', 'EPS', 'AI'].includes(v)))
check('bare ZQXB is a ticker', tick.includes('ZQXB'))
check('single letters are not tickers unless known', !isTicker('F') && isTicker('F', new Set(['F'])))
check('class share ZQ.B is a ticker', isTicker('ZQ.B'))

const verdict = tokenize('- **Verdict:** a modest bounce exists. Watch the first hour before adding. Samples are small.')
check('a "watch … before adding" sentence is italic (look)', find(verdict, 'look').some(l => /Watch the first hour/.test(plain(l.v))))
check('neighbouring sentences are not italic', !find(verdict, 'look').some(l => /Samples are small/.test(plain(l.v))))
check('decimal point is not a sentence boundary', plain(tokenize('EPS +8.8% then watch it.')) === 'EPS +8.8% then watch it.')
check('code + route tokens', find(tokenize('see `cfg` at /v3/risk'), 'code').length === 1 && find(tokenize('see /v3/risk'), 'route').length === 1)

console.log('reportFormat — sections')
const md = [
  '# Zeta Selloff Deep Dive — Fri 2026-01-09',
  '',
  'Built from the read-only DB. Advisory only.',
  '**Data as-of:** prices = Thu close; analysts = daily since 05-10.',
  '',
  '## Bottom line',
  '- **This is a valuation selloff, not an earnings one.** Detail.',
  '- Second point.',
  '## 1. Biggest drops since the 10-28 peak (quality filter: price ≥ $5)',
  '33 names down 10%+.',
  '- **ZQXA** -40%', '- **ZQXB** -30%',
  '## Known gaps in this report',
  '- Friday price action is not included.',
  '- Feed stalled on 01-05.',
].join('\n')
const p = parseReport(md, 'fallback')
check('title from "# "', p.title === 'Zeta Selloff Deep Dive — Fri 2026-01-09')
check('three sections', p.sections.length === 3)
check('chip label trims numbering + parenthetical', p.sections[1].chip === 'Biggest drops since the…' || p.sections[1].chip.startsWith('Biggest drops'))
check('chip for gaps section is "Gaps"', p.sections[2].chip === 'Gaps')
check('bottom-line summary = bold lead', p.sections[0].summary === 'This is a valuation selloff, not an earnings one')
check('bullet count', p.sections[1].bullets === 2)
const asof = extractAsOf(p)
check('as-of read from the intro', asof.text === 'prices = Thu close; analysts = daily since 05-10.')
check('gaps listed from the gaps section', asof.gaps.length === 2 && asof.gapsSection === p.sections[2].id)
check('meta.as_of wins when present', extractAsOf(p, { as_of: { prices: 'X' }, gaps: [{ text: 'g1' }] }).text === 'prices = X')
check('no as-of → null (UI shows "as-of not recorded")', extractAsOf(parseReport('## A\nbody')).text === null)
check('headerless body → no sections, intro kept', parseReport('plain text only').sections.length === 0 && parseReport('plain text only').intro === 'plain text only')
check('chipLabel long title truncates', chipLabel('What usually happens next — matched past days').length <= 26)
check('sectionSummary empty body', sectionSummary('') === '')

console.log('reportFormat — kind, age, query')
check('market by category', isMarketReport({ category: 'market_reports' }))
check('market by title (selloff stored as weekly)', isMarketReport({ category: 'weekly_reviews', type: 'weekly', title: 'Selloff Deep Dive + Monday Plan — Fri 01-09' }))
check('a weekly review is not market', !isMarketReport({ category: 'weekly_reviews', type: 'strategy_weekly', title: 'Strategy Weekly Review' }))
const now = new Date('2026-01-10T12:00:00Z').getTime()
check('daily, 71 days → stopped', ageLabel('2025-10-31T12:00:00Z', 1, now).tone === 'bad' && ageLabel('2025-10-31T12:00:00Z', 1, now).text === 'stopped 71d')
check('daily, 3 days → warn', ageLabel('2026-01-07T12:00:00Z', 1, now).tone === 'warn')
check('weekly, 3 days → ok', ageLabel('2026-01-07T12:00:00Z', 7, now).tone === 'ok')
check('never', ageLabel(null, 1, now).tone === 'none')
const sq = splitQuery('ZQXA sector:Technology trend:bullish')
check('splitQuery pulls sector/trend', sq.text === 'ZQXA' && sq.sector === 'Technology' && sq.trend === 'bullish')

console.log(`\n${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
