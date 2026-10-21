import { formatR, formatRr, planText, recommendationOrigin, shortRecId } from './recommendationOrigin.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const linked = {
  rec_id: 'rec_715bf5d5b23823d61fa5', rec_source: 'cio_opportunity', link_confidence: 'exact', origin: 'recommendation',
  plan_entry_low: 89.1, plan_entry_high: 92, plan_stop: 86, plan_target: 100, r_achieved: 1.254, r_null_reason: null,
  planned_rr: 2.1, target_hit: true, stop_hit: false, stop_source: 'recommendation',
}
const o = recommendationOrigin(linked, 'ok')
check('linked trade says From recommendation with the short id and source', o.kind === 'recommendation'
  && o.headline === 'From recommendation rec_715bf5d5… · CIO opportunity')
check('exact confidence is labelled and toned success', o.tone === 'success' && (o.confidenceLabel ?? '').startsWith('exact'))
check('plan shows zone, stop, target', o.plan === 'Entry 89.10–92.00 · Stop 86.00 · Target 100.00')
check('R achieved is signed with two decimals', o.rAchieved === '+1.25R' && o.rAchievedValue === 1.254)
check('planned R:R', o.plannedRr === '2.1 : 1')
check('target outcome', o.outcome === 'target reached at exit')

const zone = recommendationOrigin({ ...linked, link_confidence: 'zone', rec_source: 'paper_trade_proposal' }, 'ok')
check('zone confidence is info, proposal label', zone.tone === 'info' && zone.sourceLabel === 'Trade proposal')
const win = recommendationOrigin({ ...linked, link_confidence: 'window_only', rec_source: 'scalp_alert' }, 'ok')
check('window-only is warning and its chip says timing', win.tone === 'warning' && win.chip === 'Scalp alert · timing')

const own = recommendationOrigin({ origin: 'operator_initiated', link_confidence: 'none', rec_id: null,
  r_achieved: null, r_null_reason: 'operator_initiated_no_journal_stop', stop_source: 'none' }, 'ok')
check('unmatched trade reads as your own trade', own.kind === 'own' && own.headline.startsWith('Your own trade'))
check('own trade has no plan and an explained missing R', own.plan === null && own.rAchieved === '—' && own.rNote === 'no stop on the journal')

const shortStop = recommendationOrigin({ ...linked, r_achieved: null, r_null_reason: 'stop_on_wrong_side_of_entry' }, 'ok')
check('wrong-side stop explains the missing R', shortStop.rNote === 'stop was on the wrong side of the fill')
const jStop = recommendationOrigin({ ...linked, plan_stop: null, stop_source: 'journal', r_achieved: -0.5 }, 'ok')
check('journal stop is disclosed', jStop.rNote === 'R uses the journal stop' && jStop.rAchieved === '-0.50R')

check('migration not applied → unknown, never own', recommendationOrigin(null, 'unavailable').kind === 'unknown'
  && recommendationOrigin(null, 'unavailable').headline.includes('not available'))
check('not linked yet → unknown, never own', recommendationOrigin(null, 'ok').kind === 'unknown')
check('missing status → unknown even with a block', recommendationOrigin(linked, undefined).kind === 'unknown')

check('shortRecId', shortRecId('rec_1234567890abcdef') === 'rec_12345678…' && shortRecId(null) === null)
check('formatR / formatRr nulls', formatR(null) === '—' && formatRr(null) === '—' && formatR(0) === '0.00R')
check('single-price plan prints one entry', planText({ plan_entry_low: 4.5, plan_entry_high: 4.5, plan_stop: null, plan_target: null }) === 'Entry 4.50 · Stop — · Target —')
check('penny prices keep 4 dp', planText({ plan_entry_low: 0.22, plan_entry_high: 0.22 }) === 'Entry 0.2200 · Stop — · Target —')

console.log(`\nrecommendationOrigin: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
