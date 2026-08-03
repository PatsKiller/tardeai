/** Centralized hover tooltips for Options Desk UI */

export const HEADER = {
  desk: 'Systematic options proposals from your portfolio + conviction signals. Refreshes every ~10 min market hours.',
  qualityGate: 'Standard proposals need edge ≥62 and POP ≥52%. Income sleeve names (V/SCHD/LMT) use relaxed floor 52.',
  updated: 'Last proposal scan timestamp (UTC/local per browser).',
  needAction: 'Open legs where monitor recommends roll, close, or defend — not advisory-only.',
  executionArmed: 'Live Schwab submit unlocked via options_pilot_arm — still requires desk approval + per-order 2FA.',
  executionAdvisory: 'Proposals are ideas only until pilot arm + desk approval + 2FA.',
  novice: 'Shows plain-English explanations, risk flags, and confirm modals before preflight.',
} as const

export const TABS = {
  proposals: 'Ranked trade ideas that passed quality gates — not yet executed.',
  positions: 'Unified open options: Schwab live legs plus Alpaca paper / monitored lifecycle positions with route badges.',
  overview: 'Desk KPIs: edge averages, income vs puts mix, open P/L, ITM/OTM counts.',
  trends: 'IV term structure, put/call skew, strike×DTE surface, and snapshot history from live Schwab chains.',
} as const

export const TRENDS = {
  symbol: 'Underlying to load live vol analytics from Schwab option chain.',
  symbolChip: 'Desk symbol from proposals, holdings, or open legs.',
  refresh: 'Reload live chain + persist IV snapshot for history chart.',
  frontIv: 'ATM implied vol at the nearest expiry (≥7 DTE).',
  backIv: 'ATM implied vol at the furthest expiry in the term structure.',
  termSlope: 'Back IV minus front IV — positive = backwardation (near-term fear).',
  skew: 'Average put IV minus call IV at ATM strikes (%).',
  spot: 'Underlying price from chain or technical snapshot.',
  ivRank: '52-week IV rank from desk proposal when symbol is on the desk.',
  termChart: 'ATM implied volatility across expirations — richness vs calendar.',
  skewChart: 'Put minus call IV at each expiry — downside fear gauge.',
  surface: 'Heatmap of IV% by strike and days-to-expiration (±12% moneyness).',
  history: 'Front IV over time from options_chain_snapshots (built on each view).',
  research: 'Per-symbol ideas staged by options_research_bridge for Hermes/TradeAI.',
} as const

export const FILTERS = {
  ticker: 'Filter by underlying symbol (e.g. RTX, V).',
  strategy: 'Exact strategy type from the options engine.',
  pop: 'Minimum probability of profit at expiration (%).',
  edge: 'Minimum composite quality score (POP + IV + R:R + conviction).',
  refresh: 'Reload cached proposals and positions from server.',
  forceScan: 'Bypass 10m cache — regenerate proposals from live chains.',
  validateAll: 'Queue ensemble review for each proposal card.',
  clear: 'Reset all proposal filters.',
  showing: 'Count after filters vs total on desk.',
  all: 'Clear type/side/pair filters.',
  income: 'Covered calls, cash-secured puts, and credit spreads — premium collection strategies.',
  hedge: 'Protective puts on large owned positions.',
  directional: 'Long calls (and long puts) — defined-risk bullish/bearish bets.',
  spreads: 'Multi-leg credit spreads (bull put verticals).',
  calls: 'Call options only — bullish or covered-call income.',
  puts: 'Put options only — CSP, protective puts, or spreads.',
  sell: 'Short premium / sell-to-open ideas (you collect credit).',
  buy: 'Debit strategies — you pay premium (long calls, protective puts).',
  singleLeg: 'One contract per idea (CC, CSP, long call, protective put).',
  spreadPairs: 'Two-leg credit spreads with short/long strike pair (e.g. $172.5/$165).',
  portfolio: 'Ideas on names you already hold (covered calls, protective puts).',
  conviction: 'Ideas on high-conviction watchlist names you do not fully own.',
  tierA: 'Desk tier A — edge ≥72, priority routing.',
  tierB: 'Desk tier B — edge ≥62.',
  tierC: 'Below tier B threshold — review carefully.',
  liveEligible: 'Passed enterprise gates (liquidity, earnings blackout, chain confirmed) — eligible after desk approval.',
  posTicker: 'Filter open legs by underlying symbol.',
  posCalls: 'Open call positions only.',
  posPuts: 'Open put positions only.',
  posShort: 'Short / sold options (premium collected).',
  posLong: 'Long / bought options (debit paid).',
  posWorking: 'Legs still on plan — not flagged for defend/roll.',
} as const

export const OVERVIEW = {
  proposalCount: 'Ideas on desk after quality gates and strategy slots.',
  avgEdge: 'Mean edge score across current proposal set.',
  avgPop: 'Mean probability of profit across proposals.',
  incomeCc: 'Covered call proposals — income on owned shares.',
  putPlays: 'All put-related proposals (CSP, protective, spreads).',
  openPositions: 'Option legs held on linked Schwab accounts.',
  needsAction: 'Positions flagged roll/close/defend by monitor.',
  unrealizedPnl: 'Sum of mark-to-market P/L on open option legs.',
  itmOtm: 'In-the-money vs out-of-the-money open legs.',
  philosophy: 'Desk excludes low-edge noise. Monitor refreshes 5–15m market hours.',
} as const

export const POSITION = {
  status: 'WORKING = on plan. ACTION = roll/close recommended.',
  lifecycle: 'LET MATURE = hold toward expiry. HARVEST = take profit. DEFEND = roll/close risk.',
  recommended: 'Monitor recommendation from live mark, POP, and DTE rules.',
  moneyness: 'ITM = in the money. OTM = out of the money. ATM = at the strike.',
  maturityBox: 'Dynamic guidance on sell now vs let contract mature — updates each monitor pass.',
  expiryPnl: 'Payoff curve at expiration across underlying prices.',
  actionRequired: 'Alerts from position monitor — assignment or roll risk.',
  greeksPanel: 'Book-level delta and estimated theta from open legs.',
} as const

export const PROPOSAL = {
  deskTier: 'Enterprise desk tier: A (≥72 edge), B (≥62), C (below).',
  spreadPair: 'Credit spread strike pair: short leg / long leg (defined risk width).',
  dte: 'Days to expiration — theta decay accelerates under ~14 DTE.',
  liveBlocked: 'Enterprise block — earnings blackout, thin liquidity, or BS-only estimate.',
  liveOk: 'Passed enterprise gates — still needs desk approval before live submit.',
  recommended: 'Suggested broker action for this proposal.',
} as const

export const GREEKS = {
  title: 'Aggregated greeks across all open option legs on this account.',
  netDelta: 'Net share-equivalent delta — directional exposure of the options book.',
  shortDelta: 'Delta from short (sold) legs.',
  longDelta: 'Delta from long (bought) legs.',
  theta: 'Estimated daily time decay (advisory — not live chain theta).',
  footnote: 'Delta from Schwab chain when available. Theta is estimated from DTE decay.',
} as const

export const REVIEW = {
  aegis: 'Local Aegis covered-call screening (rules + local LLM) — catalyst and verdict context.',
  ensemble: 'Multi-LLM quality review: ensemble. Advisory only.',
  worker: 'Background worker processes ensemble jobs — refresh card to see verdict.',
  reviewedBy: 'Sources that screened this proposal before it reached your desk.',
} as const

export const NOVICE = {
  toggle: 'Shows plain-English explanations, risk flags, strike distance, and confirm modals.',
  banner: 'Collapsible primer on how this desk works and what each strategy means.',
  whatIf: 'Scenario guide — what happens if the stock moves up, down, or stays flat.',
} as const

export const ACTIONS = {
  hold: 'Dismiss — keep watching this proposal on desk.',
  reviewChain: 'Open Schwab option chain for live quotes before sizing.',
  preflightLocked: 'Execution locked — run options_pilot_arm.py --approve on server.',
  preflightManual: 'Manual execution at broker — use Executed manually to log.',
  manualLog: 'Log that you executed this trade manually at your broker.',
  closeRoll: 'Close or roll this leg — advisory until you confirm at broker.',
} as const