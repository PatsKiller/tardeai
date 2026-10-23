// node --experimental-strip-types src/lib/optionsDeskModel.test.ts
// The desk layout model on a captured fixture, plus the audit's reading rules.
import {
  BLOCKER_KEYS, buildIdeas, buildPlans, classifyBlock, freshnessChips, groupKey, laneCounts, laneFor, MODEL_GLOSSARY_KEYS,
  planIdeas, sessionLabel, truthSentence,
} from './optionsDeskModel.ts'
import { hasGlossary } from './optionsGlossary.ts'
import { FIXTURE } from './optionsDesk.fixture.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: unknown) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

const NOW = new Date('2026-10-22T15:00:00Z')
const P = FIXTURE.proposals
const raw: any[] = P.data.proposals
const ideas = buildIdeas(raw, NOW)

// One row per idea: the two SPCX accounts merge.
eq('5 proposals → 4 ideas (SPCX accounts merged)', ideas.length, 4)
const spcx = ideas.find(i => i.symbol === 'SPCX')!
eq('SPCX merged contracts', spcx.contract, 'Nov 20 $148P × 8')
eq('SPCX merged cost is the summed premium_total', spcx.cost, '$3,720')
eq('SPCX does', spcx.does, 'Insures 800 shares below $148 for 29 days')
eq('SPCX lane is your decision (BLOCKED, owner CIO/operator)', spcx.lane, 'you')
ok('SPCX stuck names the CIO review failures', /CIO review failed 3×/.test(spcx.stuck))
eq('SPCX next step opens the existing review', [spcx.next.kind, spcx.next.label], ['review', 'Decide'])
eq('SPCX floor tile sums both accounts', spcx.econ.find(e => e.label === 'Floor')?.value, '$114,680')
eq('SPCX scenarios come from combined exposure (both accounts)', spcx.scenarios[0], { move: '-10%', stockOnly: '−$12,330', withThis: '−$8,616', saved: '+$3,714' })
ok('SPCX checklist fails on the stale chain', spcx.checks.some(c => c.mark === '✗' && /stale/i.test(c.text)))
ok('SPCX checklist ends with your decision and 2FA as not-yet', spcx.checks.slice(-2).every(c => c.mark === '○'))
eq('group key ignores account', groupKey(raw[0]) === groupKey(raw[1]), true)

const xlb = ideas.find(i => i.symbol === 'XLB')!
eq('XLB lane needs data', xlb.lane, 'data')
eq('XLB insures 500 of 506 shares', xlb.does, 'Insures 500 of 506 shares below $48 for 57 days')
ok('XLB stuck on the wide quote', /Quote too wide/.test(xlb.stuck))
eq('XLB next step re-quotes through the existing validate flow', xlb.next.kind, 'validate')
eq('edge hidden when the liquidity gate fails', xlb.econ.find(e => e.label === 'Edge')?.value, '—')
ok('edge hidden note says why', /liquidity gate failed/.test(xlb.econ.find(e => e.label === 'Edge')?.note || ''))
eq('edge shown when liquidity passes', spcx.econ.find(e => e.label === 'Edge')?.value, '68.4')

const schg = ideas.find(i => i.symbol === 'SCHG')!
eq('SCHG illiquid → pick another strike (read-only chain)', [schg.lane, schg.next.kind], ['data', 'chain'])
const xar = ideas.find(i => i.symbol === 'XAR')!
eq('XAR needs research', xar.lane, 'research')
ok('XAR stuck on the missing exit criteria first', /exit criteria/.test(xar.stuck))

// Lanes and counts.
const plans = buildPlans(FIXTURE.intents, ideas, NOW)
const counts = laneCounts(P, ideas, FIXTURE.intents, FIXTURE.openPositions)
eq('lane counts', counts.map(c => [c.key, c.n]), [['scan', 5646], ['research', 1], ['data', 2], ['plan', 13], ['you', 1], ['place', 0], ['open', 0]])
eq('archived (served lifecycle_stage) leaves the lanes', laneFor({ lifecycle_stage: 'ARCHIVED_ABANDONED', review_workflow: { state: 'NEEDS_DATA' } }), null)
eq('review failure cap needs the operator', laneFor({ lifecycle_stage: 'REVIEW_FAILURE_CAP', review_workflow: { state: 'BLOCKED' } }), 'you')
eq('rejected ideas leave the lanes', laneFor({ review_workflow: { state: 'REJECTED_OR_EXPIRED' } }), null)

// Served accuracy fields (FIELD_CONTRACT.md) win over derivations.
const clone = (o: any) => JSON.parse(JSON.stringify(o))
const sx = raw.filter(p => p.symbol === 'SPCX').map(clone)
sx.forEach(p => { p.lifecycle_stage = 'REVIEW_FAILURE_CAP'; p.review_failures = 3; p.review_failure_reason = 'POLICY_NOT_ALLOWED' })
const capped = buildIdeas(sx, NOW)[0]
ok('capped review says operator reopen', capped.checks.some(c => /stopped after 3 failures.*operator reopen/.test(c.text)))
const xw = clone(raw.find(p => p.symbol === 'SPCX'))
xw.edge_status = 'WITHHELD_LIQUIDITY'; xw.edge_score = null; xw.edge_withheld_reason = 'liquidity gate failed: spread 18.0% > 12%'
eq('served edge withheld → —', buildIdeas([xw], NOW)[0].econ.find(e => e.label === 'Edge')?.value, '—')
ok('served withheld reason shown', /spread 18\.0%/.test(buildIdeas([xw], NOW)[0].econ.find(e => e.label === 'Edge')?.note || ''))
const xo = clone(raw.find(p => p.symbol === 'XLB'))
xo.review_workflow.next_action = 'Re-quote after the open (market AFTER_HOURS)'
eq('outside REGULAR the re-quote is not offered', buildIdeas([xo], NOW)[0].next.kind, 'none')
const cspCard = { id: 'c1', symbol: 'ZZ', strategy: 'cash_secured_put', option_type: 'put', strike: 100, expiration: '2026-11-20', dte: 29, contracts: 1, premium: 2,
  premium_total: 200, premium_basis: 'bid', premium_over_collateral_pct: 2.0, simple_annualized_yield_pct: 25.2, review_workflow: { state: 'READY_FOR_REVIEW' },
  economics: { cash_committed: 10000, net_cost_if_assigned_total: 9800, net_cost_if_assigned_per_share: 98 }, risk_reward: null, not_applicable_metrics: ['risk_reward', 'max_loss_to_zero'] }
const cspIdea = buildIdeas([cspCard], NOW)[0]
eq('CSP tiles use served yields, no reward/risk', cspIdea.econ.map(e => [e.label, e.value]).filter(([l]) => /collateral|annualized|reward|assigned/i.test(l)),
  [['Cost if assigned', '$9,800'], ['Premium / collateral', '2.00%'], ['Simple annualized', '25.2%']])
eq('CSP row cost is a credit', cspIdea.cost, '+$200 credit')
const feed2 = clone(FIXTURE.intents)
feed2.data.intents[0].earnings_dates = { provider_date: '2027-02-09', operator_estimate: '2027-02-08', conflict: false, effective_date: '2027-02-08' }
feed2.data.intents[0].conflicts = [{ kind: 'HEDGE_VS_ACCUMULATE', text: 'served conflict text' }]
feed2.data.intents[1].watch_only = true
const plans2 = buildPlans(feed2, ideas, NOW)
ok('served conflict:false suppresses the earnings warning', !plans2[0].warnings.some(w => /Earnings dates disagree/.test(w)))
ok('served conflict text is used', plans2[0].warnings.includes('Conflict: served conflict text'))
ok('served watch_only badge', plans2[1].badges.includes('Not held · watch only'))

// Plans: conflict, both earnings dates, CSP shown as premium/collateral + simple annualized (never reward/risk).
const sp = plans.find(p => p.symbol === 'SPCX')!
ok('SPCX plan warns accumulate vs hedge', sp.warnings.some(w => /wants more SPCX/.test(w) && /hedging/.test(w)))
ok('SPCX plan shows both earnings dates on conflict', /2027-02-09/.test(sp.facts) && /2026-11-03/.test(sp.facts))
const bestCsp = sp.best.find(b => b.glossaryKey === 'strategy.cash_secured_put')!
ok('CSP note: premium/collateral and simple annualized, not repeatable', /3\.75% premium\/collateral/.test(bestCsp.note) && /47\.2% simple annualized \(not repeatable\)/.test(bestCsp.note))
ok('CSP note never says reward/risk', !/reward|R:R/i.test(bestCsp.note))
eq('covered call with no match says why', sp.best.find(b => b.glossaryKey === 'strategy.covered_call')?.contract, 'none')
eq('stage CTA carries the plan match identity only', bestCsp.cta.kind === 'stage' ? Object.keys(bestCsp.cta.source).sort() : null, ['contract_guid', 'directive_id', 'play'])
const nflx = plans.find(p => p.symbol === 'NFLX')!
ok('NFLX plan is flagged not held when it holds no shares', nflx.badges.includes('Not held · watch only') === (Object.values(FIXTURE.intents.data.intents[1].matches.shares_by_account || {}).reduce((a: number, v: any) => a + Number(v || 0), 0) === 0))
const pRows = planIdeas(plans)
ok('plan rows sit in Not staged and stage via the existing modal', pRows.length > 0 && pRows.every(r => r.lane === 'plan' && r.next.kind === 'stage'))

// Freshness chips: never "closed" during REGULAR; missing → "—".
const chips = freshnessChips(P, raw, NOW)
eq('chip keys', chips.map(c => c.key), ['market', 'stock', 'chain', 'holdings', 'scan', 'open'])
ok('REGULAR session reads open, never closed', /Open/.test(chips[0].value) && !/closed/i.test(chips[0].value))
eq('scan coverage chip', chips[4].value, '4 of 5,646 evaluated')
eq('chain chip shows the oldest chain against the cap', [chips[2].value, chips[2].tone], ['87 min old', 'warning'])
const bare = freshnessChips({ data: {} }, [], NOW, null)
ok('absent fields show — and say not provided', bare.every(c => c.value === '—' && /not provided by this server version/.test(c.detail)))
eq('no session → no label (never guessed closed)', sessionLabel(undefined), null)
eq('pre-market label', sessionLabel('PRE_MARKET'), 'Pre-market')

// Truth sentence.
eq('served execution_state_text wins', truthSentence({ data: { execution_state_text: 'Served sentence.' } }, FIXTURE.execStatus, 0), 'Served sentence.')
ok('armed with nothing eligible says so', /no idea on this desk is eligible/.test(truthSentence(P, FIXTURE.execStatus, 0)))
ok('unreadable status is advisory', /advisory/.test(truthSentence(P, null, 0)))

// Block classification.
eq('liquidity strings classify', ['spread 114.0% > 12.0%', 'OI 9 < 50', 'volume 1 < 5'].map(s => classifyBlock(s).key), ['blocker.wide_spread', 'blocker.low_open_interest', 'blocker.low_volume'])
eq('unknown code keeps its raw reason', classifyBlock({ code: 'brand_new', reason: 'new reason' }).text, 'new reason')

// Every key the model can emit, and every key it emitted on the fixture, has a glossary entry.
for (const k of [...MODEL_GLOSSARY_KEYS, ...BLOCKER_KEYS]) ok(`glossary has model key ${k}`, hasGlossary(k))
const emitted = new Set<string>()
for (const i of [...ideas, ...pRows]) {
  emitted.add(i.stuckKey)
  i.econ.forEach(e => emitted.add(e.glossaryKey)); i.checks.forEach(c => emitted.add(c.glossaryKey))
}
chips.forEach(c => emitted.add(c.glossaryKey)); plans.forEach(p => p.best.forEach(b => emitted.add(b.glossaryKey)))
for (const k of emitted) ok(`glossary has emitted key ${k}`, hasGlossary(k))

if (failed) { console.error(`optionsDeskModel: ${failed} failure(s)`); throw new Error('optionsDeskModel tests failed') }
console.log('optionsDeskModel: ok')
