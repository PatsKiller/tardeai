// node --experimental-strip-types src/lib/optionsGlossary.test.ts
// The glossary's formulas must reproduce what the server computed, on a captured fixture.
import {
  breakevenPerShare, coveredCallYieldAnnPct, cspCollateral, deskTier, GLOSSARY, hedgedMaxLossFromMark, midPrice,
  premiumOverCollateralPct, premiumTotal, protectivePutFloor, simpleAnnualizedPct, spreadPct,
} from './optionsGlossary.ts'
import { FIXTURE } from './optionsDesk.fixture.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function near(name: string, got: number | null, want: number, tol = 0.011) {
  if (got == null || Math.abs(got - want) > tol) { failed++; console.error(`FAIL ${name}: got ${got} want ${want}`) }
}
function ok(name: string, cond: unknown) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

const props: any[] = FIXTURE.proposals.data.proposals
const spcx = props.find(p => p.symbol === 'SPCX' && p.shares_held === 600)
const xlb = props.find(p => p.symbol === 'XLB')
ok('fixture has the SPCX and XLB protective puts', spcx && xlb)

// Protective put: breakeven (put alone), floor, hedged max loss, total cost — economics() outputs.
eq('put breakeven = strike − premium (economics.put_breakeven)', breakevenPerShare('protective_put', spcx.strike, spcx.premium), spcx.put_breakeven)
eq('floor = (strike − premium) × insured (economics.floor_value_after_premium)',
  protectivePutFloor(spcx.strike, spcx.premium, spcx.economics.insured_shares), spcx.economics.floor_value_after_premium)
eq('floor matches the served floor_value', protectivePutFloor(spcx.strike, spcx.premium, spcx.economics.insured_shares), spcx.floor_value)
eq('hedged max loss from mark (economics.hedged_max_loss_from_mark)',
  hedgedMaxLossFromMark(spcx.underlying_price, spcx.strike, spcx.premium, spcx.economics.insured_shares), spcx.economics.hedged_max_loss_from_mark)
eq('total cost = premium × 100 × contracts (premium_total)', premiumTotal(spcx.premium, spcx.contracts), spcx.premium_total)
eq('XLB floor on the 500 insured of 506 shares', protectivePutFloor(xlb.strike, xlb.premium, xlb.economics.insured_shares), xlb.economics.floor_value_after_premium)

// Cash-secured put plan match: premium/collateral, simple annualized, collateral, breakeven — rank_csp outputs.
const spcxPlan = FIXTURE.intents.data.intents.find((i: any) => i.symbol === 'SPCX')
const csp = spcxPlan.matches.plays.cash_secured_put[0]
eq('collateral per contract = strike × 100 (rank_csp)', cspCollateral(csp.strike), csp.collateral_per_contract)
eq('credit per contract = mid × 100 (rank_csp)', premiumTotal(csp.mid, 1), csp.credit_per_contract)
near('mid = (bid + ask) / 2 (ranking.mid)', midPrice(csp.bid, csp.ask), csp.mid, 1e-9)
near('premium/collateral % = mid / strike × 100 (rank_csp.return_pct)', premiumOverCollateralPct(csp.mid, csp.strike), csp.return_pct, 0.0006)
eq('simple annualized = return × 365 / dte × 100 (rank_csp.annualized_pct)', simpleAnnualizedPct(csp.mid / csp.strike, csp.dte), csp.annualized_pct)
near('CSP breakeven = strike − mid (rank_csp.breakeven)', breakevenPerShare('cash_secured_put', csp.strike, csp.mid), csp.breakeven, 0.0001)
for (const r of spcxPlan.matches.plays.cash_secured_put) {
  eq(`annualized for every CSP match ${r.contract}`, simpleAnnualizedPct(r.mid / r.strike, r.dte), r.annualized_pct)
}

// Spread %: the served bid_ask_spread_pct.
near('spread % = 100 × (ask − bid) / chain mid (liquidity_gate)', spreadPct(spcx.bid, spcx.ask, spcx.enterprise.liquidity.mid), spcx.bid_ask_spread_pct, 0.01)
near('XLB spread % (114%: above the 12% cap)', spreadPct(xlb.bid, xlb.ask, xlb.enterprise.liquidity.mid), xlb.enterprise.liquidity.bid_ask_spread_pct, 0.01)
for (const p of props) near(`spread % for ${p.symbol} matches liquidity_gate`, spreadPct(p.bid, p.ask, p.enterprise.liquidity.mid), p.enterprise.liquidity.bid_ask_spread_pct, 0.01)
eq('crossed quote has no spread %', spreadPct(1.3, 1.2), null)

// Tier from edge (desk_tier).
for (const p of props) eq(`tier from edge ${p.symbol} ${p.edge_score}`, deskTier(p.edge_score), p.desk_tier)

// Covered-call annualized yield helper (_cc_yield_ann_pct): $4.10 / 27 days on $148.57 ≈ 37%, the docstring example.
near('covered-call annualized yield docstring example', coveredCallYieldAnnPct(4.10, 148.57, 27), 37.3, 0.1)

// Every entry is complete.
for (const [k, g] of Object.entries(GLOSSARY)) {
  ok(`entry ${k} has term`, g.term && g.term.length > 1)
  ok(`entry ${k} has plain definition`, g.plain && g.plain.length > 10)
  ok(`entry ${k} says what it means for you`, g.forYou && g.forYou.length > 5)
  if (g.formula) ok(`entry ${k} with a formula cites its computing function`, !!g.computedBy || k.startsWith('concept.'))
}
// Terms the operator listed explicitly.
for (const k of ['term.delta', 'term.oi', 'term.iv', 'term.dte', 'term.bid', 'term.ask', 'term.mid', 'term.spread_pct', 'term.premium',
  'term.collateral', 'term.breakeven', 'term.strike', 'term.expiry', 'term.assignment', 'strategy.covered_call', 'strategy.cash_secured_put',
  'strategy.protective_put', 'strategy.leap_call', 'strategy.pmcc', 'strategy.credit_spread', 'strategy.long_call', 'strategy.long_put',
  'term.pop', 'term.edge', 'term.tier', 'term.sleeve', 'concept.thesis', 'concept.cio_decision', 'concept.aegis_review', 'concept.standing_plan',
  'exec.state', 'term.simple_annualized', 'term.premium_over_collateral', 'term.floor']) ok(`required entry ${k}`, GLOSSARY[k])

if (failed) { console.error(`optionsGlossary: ${failed} failure(s)`); throw new Error('optionsGlossary tests failed') }
console.log('optionsGlossary: ok')
