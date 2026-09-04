// MetricStrip label check — the PORTFOLIO/TODAY chips must not call the DATA
// clock "as_of".
//
// Cause (2026-09-01, #825 follow-up): `overviewSurfaceFreshness` was rebound to
// `data_as_of`, but MetricStrip still rendered a hardcoded `as_of {value}`. The
// number became right while the label named the one field it is specifically
// not reporting. #825 shipped with tsc + a TypeScript unit test, neither of
// which looks at the rendered label.
//
// LIMITATION, stated rather than glossed: this app has no jsdom/render harness,
// so this is a SOURCE-SHAPE assertion, not proof of what renders. It catches a
// regression of this exact defect and nothing more.
//
// Comments are stripped before matching: a substring search cannot otherwise
// tell code from a comment quoting it (AGENTS.md 7, detector shape).
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const target = path.join(here, '..', 'apps', 'command-center-v3', 'src', 'components', 'MetricStrip.tsx')

const raw = fs.readFileSync(target, 'utf8')
const code = raw
  .replace(/\/\*[\s\S]*?\*\//g, '')   // block comments
  .replace(/^\s*\/\/.*$/gm, '')       // whole-line // comments

let pass = 0, fail = 0
const check = (name, cond) => {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

check('renderer no longer hardcodes the as_of label',
  !/\n\s*as_of \{String\(\(t as any\)\.asOf\)/.test(code))
check('renderer takes the label from the tile',
  code.includes("(t as any).asOfLabel || 'as_of'"))
// This previously asserted BOTH tiles carried `asOfLabel: 'data_as_of'`, and it
// passed while the header was at its most misleading: PORTFOLIO and TODAY showed
// the same stamp under the same name for two different clocks. `data_as_of` names
// no clock at all -- it is the position observation, and the operator's capture
// had it standing over a P&L struck the following session. The assertion is
// inverted: the tiles must declare DIFFERENT, self-describing labels.
check('no tile labels a clock "data_as_of" any more',
  !/asOfLabel: 'data_as_of'/.test(code))
check('the portfolio tile names the position-observation clock',
  code.includes("asOfLabel: 'positions observed'"))
check("the today tile names the P&L's own session",
  code.includes("asOfLabel: 'P&L session'"))
check('no two tiles share a static clock label', (() => {
  // The trailing `|| size > 1` this once carried made it pass for any header
  // with two distinct labels anywhere -- including the defect. A duplicate is
  // now the only thing it looks at.
  const labels = [...code.matchAll(/asOfLabel: '([^']+)'/g)].map(m => m[1])
  if (labels.length < 2) return false          // vacuous pass is a failure
  return new Set(labels).size === labels.length
})())
check('the portfolio tile states how much value its date covers',
  code.includes('covers ${cov.at_newest_pct}% of value'))
check('the oldest contributor carries a stamp and an age, not just a name',
  code.includes('const oldestLine') && code.includes('ageMark(posOldestAgeH)'))
// A tooltip is not rendered text. The live audit found the oldest account had
// vanished from the visible tile entirely -- I had replaced "oldest <name>" with
// the coverage figure, which answers a different question. Both belong on the face.
check('the oldest contributor is on the tile FACE, not only in the tooltip',
  code.includes('const oldestMark') && code.includes('${oldestMark}'))
check('the visible oldest mark carries the stamp and the age',
  /oldestMark = posOldest[\s\S]{0,220}\$\{posOldest\}\$\{ageMark\(posOldestAgeH\)\}/.test(code))
check('the four aggregate clocks are rendered as separate lines',
  code.includes('const clockLines') &&
  code.includes('positions observed') && code.includes('valued ') &&
  code.includes('quotes observed '))
check("today's coverage names the missing accounts rather than only a count",
  code.includes('missing ${todayMissing.join'))
check('the setups tile carries its run id',
  code.includes('id ${setupRun.runId}'))
check('unaccounted setup rows are shown on the tile face',
  code.includes('UNACCOUNTED'))
check('degraded quotes state their symbol coverage',
  code.includes('quoteCoverMark') && code.includes('quotes DEGRADED'))
check('the selected quote observation is its own mark',
  code.includes('quoteObservedMark'))
check('an UNDATED tile renders a line rather than nothing',
  code.includes('data-surface-undated'))
check('the overview mark names data_as_of and states UNDATED',
  code.includes('· data_as_of ') && code.includes('data_as_of UNDATED'))

console.log(`\nmetric_strip_labels: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

// ── header truth: TODAY is an all-accounts aggregate and must say so ──────────
//
// The live audit of release ee200ec3 recorded "Alpaca-only Today metadata beside an
// ALL ACCOUNTS aggregate". Re-measured against 2ef5fd115 it was still present:
//
//   PORTFOLIO | $1,281,637 | data_as_of 2026-09-03 . ALL ACCOUNTS . oldest fidelity_rollover_ira
//   TODAY     | -$2,908 -0.23% | data_as_of 2026-09-03 . alpaca_taxable_live
//
// The Today VALUE was correct -- it sums today_by_account across every account and
// reconciles to -2907.70 exactly. Only the attribution was wrong, which is the worse
// half: a right number credited to one account it did not come from reads as
// authoritative rather than as obviously missing.
//
// Matched against `code`, the comment-stripped source, for the reason stated at the top
// of this file: these very comments quote the strings under test.

check('the TODAY tile no longer attributes an all-accounts figure to one account',
  !/label: 'TODAY'[\s\S]{0,400}asOfNote: overviewAcct\b/.test(code))
check('the TODAY tile uses an all-accounts provenance note',
  /asOfNote: todayAsOfNote/.test(code))
check('the TODAY provenance note is derived from the contributing accounts',
  /todayAccountCount\s*=\s*Object\.keys\(overview\?\.today_by_account/.test(code))
check('the TODAY note falls back to a scope, never a single account name',
  /todayAsOfNote[\s\S]{0,240}ALL ACCOUNTS/.test(code))

// "53.3% . 169 . $55,429" was three unlabelled numbers, and the dollar figure sat beside
// a REALIZED tile showing a different one.
check('the TRADING tile labels its win rate', /\$\{winRate\}% win/.test(code))
check('the TRADING tile labels its trade count', /\$\{winTrades\} trades/.test(code))
check('the TRADING tile labels its P&L', /fmt\$\(journalPnl, 0\)\} P&L/.test(code))

console.log(`\nmetric_strip_header_truth: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
