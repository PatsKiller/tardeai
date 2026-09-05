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
// Coverage-% moved OFF the tile face by operator decision (exception-driven
// header): it answers "how much of the book is stale", which is a drill
// question, while "how stale" (oldestMark) stays reachable on the face when it
// matters. The string is NOT deleted — it must still reach the tooltip. A bare
// includes() would keep passing while the fact left the surface entirely, so
// both halves are asserted: still composed, and no longer on the face composer.
check('the value coverage the headline date speaks for still reaches the tooltip',
  code.includes('covers ${cov.at_newest_pct}% of value')
  && /const coverageMark/.test(code)
  // origin/main renamed the off-face carrier to portfolioHoverAccounts; the
  // property asserted is unchanged — coverage must still reach the hover.
  && code.includes('${portfolioHoverAccounts'))
check('coverage-% no longer competes for tile-face width',
  !/const portfolioFaceNote[\s\S]{0,400}coverageMark/.test(code))
check('the oldest contributor carries a stamp and an age, not just a name',
  code.includes('const oldestLine') && code.includes('ageMark(posOldestAgeH)'))
// Operator 2026-09-04: account + date on HOVER only. Face keeps the position date
// and compact divergence; oldest/empties/coverage live in tip + drill.
check('the oldest contributor is on HOVER (tip), not concatenated into face asOfNote',
  code.includes('portfolioHoverAccounts') &&
  code.includes('ACCOUNTS (hover)') &&
  !code.includes('const oldestMark') &&
  /asOfNote: portfolioFaceNote/.test(code))
check('face portfolio note is divergence-only (no account census)',
  /portfolioFaceNote = clockDivergences\.length/.test(code) &&
  !/asOfNote: portfolioAsOfNote/.test(code))
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
  code.includes('id ${setupRun.runId}'))
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
check('the selected quote observation is its own mark',
  code.includes('quoteObservedMark'))
check('an UNDATED tile renders a line rather than nothing',
  code.includes('data-surface-undated'))
check('the overview mark names data_as_of and states UNDATED',
  code.includes('· data_as_of ') && code.includes('data_as_of UNDATED'))


// ── the exception-driven redesign (2026-09-05) ───────────────────────────────
// These exist because the layout defect they guard was invisible to every
// source-shape check that came before: the strings were all correct and the
// header was still unreadable.

check('every tile renders a fixed three-element subtree, so no ordinal CSS rule can retarget the value',
  code.includes('className="ms-label"') && code.includes('className="ms-value"') && code.includes('className="ms-meta"'))
check('the value line states its own size rather than inheriting an ordinal override',
  /fontSize: \(t as any\)\.valueSize \?\? VALUE_BIG/.test(code))
check('no line in a tile may wrap', (() => {
  const m = code.match(/const NOWRAP = \{[^}]*\}/)
  return !!m && /whiteSpace: 'nowrap'/.test(m[0]) && /textOverflow: 'ellipsis'/.test(m[0])
})())
check('the price stamp is clipped, not spilled',
  /data-price-stamp/.test(code) && code.includes('priceStampShort') && code.includes('...NOWRAP'))
check('the full price stamp survives in the title rather than being dropped',
  markIsLive('priceStampFull', 'quoteSel|`\\$\\{priceStamp'))
check('run health is read from freshness_status, never inferred from reconciliation',
  code.includes('setupRun.healthDegraded') && code.includes('setupRun.runHealthStatus'))
check('run health and reconciliation stay separately named on the tile', (() => {
  // Both must be READ, and the tile's tone must be driven by the health one —
  // a tile that only ever consults reconciliation is the defect this replaces.
  if (!code.includes('setupRun.degraded') || !code.includes('setupRun.healthDegraded')) return false
  const tone = code.match(/const setupsTone[\s\S]{0,300}?\n  \)/)
  return !!tone && /healthDegraded/.test(tone[0]) && /setupRun\.degraded/.test(tone[0])
})())
check('the underfill floor is stated beside the scanned count',
  code.includes('scannedVsFloor') && /expected_min_symbols/.test(code))
check('the two run clocks are named scheduled vs finished',
  code.includes('runSlot') && code.includes('slot`') && code.includes('finished '))
check('an unzoned run stamp is marked unzoned, never given an assumed zone',
  code.includes('runFinishedZoned') && code.includes('unzoned'))
check('the source no longer claims the run zone is stated', !/the zone is stated/.test(raw))
// I had put a literal "clocks ok" zero-state on the face. origin/main's later
// operator decision makes the face divergence-only, and that is defensible: the
// meta line is never blank (it carries the position date), so the tile is not
// silent. But the AGENTS.md 9.1 concern is real — "no divergence" must stay
// distinguishable from "the field was never published" — so the check moves to
// where the answer now lives rather than being dropped.
check('a divergence-only face still leaves the clock facts stated on hover', (() => {
  const face = code.match(/const portfolioFaceNote\s*=\s*([\s\S]{0,200}?)\n\n/)
  if (!face || !/clockDivergences\.length/.test(face[1])) return false
  // and the tooltip must enumerate the clocks whether or not one diverged
  return /const clockLines/.test(code) && code.includes('${clockLines.join')
})())
check('quote coverage stays on the face in the healthy state',
  code.includes('quoteCoverMark') && code.includes('${quoteCoverMark'))
check('a tile signals state through a rail, at zero width cost',
  code.includes('rowRail(') && /tone === 'bad' \? 'breach'/.test(code))

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
// origin/main moved the TODAY account census to hover and retargeted this rail
// at `todayHoverAccounts`. That target is right. The 240-character proximity
// match is not: proximity is not the property that matters, and it silently
// passes or fails on unrelated refactors. Their target, checked by mechanism —
// the hover note derives from a scope label that falls back to ALL ACCOUNTS,
// never to an account name.
check('the TODAY hover note falls back to a scope, never a single account name', (() => {
  const block = code.match(/const todayHoverAccounts[\s\S]{0,600}?\n  \}\)\(\)/)
  if (!block) return false
  const scope = block[0].match(/const scope\s*=\s*([^\n]*)/)
  return !!scope && /ALL ACCOUNTS/.test(scope[1]) && !/overviewAcct/.test(block[0])
})())

// "53.3% . 169 . $55,429" was three unlabelled numbers, and the dollar figure sat beside
// a REALIZED tile showing a different one.
check('the TRADING tile labels its win rate', /\$\{winRate\}% win/.test(code))
check('the TRADING tile labels its trade count', /\$\{winTrades\} trades/.test(code))
check('the TRADING tile labels its P&L', /fmt\$\(journalPnl, 0\)\} P&L/.test(code))

console.log(`\nmetric_strip_header_truth: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
