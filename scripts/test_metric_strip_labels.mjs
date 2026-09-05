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
  code.includes("asOfLabel: 'obs'") && code.includes('positions observed'))
check("the today tile names the P&L's own session",
  code.includes("asOfLabel: 'session'") && /P&L session/.test(code))
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
// Operator 2026-09-04: account + date on HOVER only. Face keeps the position date
// and compact divergence; oldest/empties/coverage live in tip + drill.
check('the oldest contributor is on HOVER (tip), not concatenated into face asOfNote',
  code.includes('portfolioHoverAccounts') &&
  code.includes('ACCOUNTS (hover)') &&
  !code.includes('const oldestMark') &&
  /asOfNote: null/.test(code) &&
  /warnBadge: clockDivergences\.length/.test(code))
check('face portfolio note is divergence-only (no account census)',
  /portfolioFaceNote = clockDivergences\.length/.test(code) &&
  !/asOfNote: portfolioAsOfNote/.test(code) &&
  /warnBadge: clockDivergences\.length/.test(code))
check('the four aggregate clocks are rendered as separate lines',
  code.includes('const clockLines') &&
  code.includes('positions observed') && code.includes('valued ') &&
  code.includes('quotes observed '))
check('an empty account cannot make TODAY incomplete', (() => {
  // The tile flagged STALE off `complete === false`, which an empty account set.
  // Only a FUNDED account that failed to report may raise the warning.
  const m = code.match(/stale: today[^\n]*/)
  return !!m && /todayMissing\.length/.test(m[0]) && !/complete === false/.test(m[0])
})())
check('TODAY distinguishes empty accounts from ones that did not report',
  code.includes('todayEmpty') && code.includes('MISSING ${todayMissing'))
check("today's coverage is stated over FUNDED accounts, not linked ones",
  code.includes('funded accts') && code.includes('todayFunded'))
check("today's coverage names the missing accounts rather than only a count",
  /MISSING \$\{todayMissing\.join/.test(code))
check('the setups tile carries its run id',
  /id \$\{String\(setupRun\.runId\)/.test(code) || code.includes('id ${setupRun.runId}'))
check('unaccounted setup rows are shown on the tile face',
  code.includes('UNACCOUNTED'))
// Hover still publishes these facts; they must remain data-driven in tip/hover
// strings even when the face is date-only.
const markIsLive = (name, drivenBy) => {
  if (!code.includes('${' + name + '}') && !code.includes(name + '.replace')) return false
  const m = code.match(new RegExp('const ' + name + '\\s*=\\s*([^\\n]*)'))
  return !!m && new RegExp('^' + drivenBy).test(m[1].trim())
}
check('a divergence between the two position-clock copies is shown, not resolved',
  code.includes('observation_divergences') &&
  (markIsLive('divergenceMark', 'clockDivergences\\.length') || code.includes('portfolioFaceNote')))
check('accounts holding nothing are named, not counted as unobserved',
  code.includes('accounts_non_contributing') &&
  (markIsLive('emptyMark', 'cov\\?\\.accounts_non_contributing') || code.includes('portfolioHoverAccounts')))
check('undated is counted over contributors, not over every account row',
  code.includes('accounts_contributing') && code.includes('contributing undated'))
check('degraded quotes state their symbol coverage',
  code.includes('quoteCoverMark') && code.includes('quotes DEGRADED'))
check('degraded quote coverage is tip-only (face stays short)',
  code.includes('quoteStatusFace') &&
  code.includes('quoteStatusTip') &&
  code.includes('pricesFace') &&
  /quoteStatusTip[\s\S]*quoteCoverMark/.test(code) &&
  !/pricesFace[\s\S]*quoteObservedMark/.test(code.split('const pricesFace')[1]?.slice(0, 200) || 'quoteObservedMark'))
check('prices face cannot paint over tiles (ellipsis + overflow)',
  code.includes('data-testid="metric-strip-prices"') &&
  code.includes("textOverflow: 'ellipsis'") &&
  /metric-strip-brand[\s\S]{0,400}overflow: 'hidden'/.test(code))
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
check('the TODAY tile keeps account census on hover, not face asOfNote',
  /todayHoverAccounts/.test(code) &&
  /asOfNote: null/.test(code) &&
  /ACCOUNTS \(hover\)/.test(code))
check('the TODAY provenance note is derived from the contributing accounts',
  /todayAccountCount\s*=\s*Object\.keys\(overview\?\.today_by_account/.test(code))
check('the TODAY hover note falls back to a scope, never a single account name',
  /todayHoverAccounts[\s\S]{0,240}ALL ACCOUNTS/.test(code))

// "53.3% . 169 . $55,429" was three unlabelled numbers, and the dollar figure sat beside
// a REALIZED tile showing a different one.
check('the TRADING tile labels its win rate', /\$\{winRate\}%/.test(code))
check('the TRADING tile labels its trade count', /\$\{winTrades\} trades/.test(code))
check('the TRADING tile labels its P&L', /fmt\$\(journalPnl, 0\)\} P&L/.test(code))
check('SETUPS face is counts-only; population is a sub line',
  /setupsSub = setupsPopulationShort/.test(code) &&
  /valueSub: setupsSub/.test(code) &&
  !/return pop \? `\$\{setupRun\.counts\} · \$\{pop\}/.test(code))
check('metric strip uses semantic classes (not :last-child sizing)',
  code.includes('metric-strip-value') &&
  code.includes('metric-strip-asof') &&
  code.includes('metric-strip-label'))
check('prices brand cell is isolated (bg + overflow)',
  /metric-strip-brand[\s\S]{0,500}background: 'var\(--bg0\)'/.test(code) &&
  /metric-strip-brand[\s\S]{0,500}overflow: 'hidden'/.test(code))

console.log(`\nmetric_strip_header_truth: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
