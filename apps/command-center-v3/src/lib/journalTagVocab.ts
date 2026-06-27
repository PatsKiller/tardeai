import { type VocabConfig } from './journalVocab'

/** Setup type chips — v2 journal + TradeZella / TradingView style patterns */
export const SETUP_TYPE_GROUPS: { label: string; items: string[] }[] = [
  {
    label: 'Core patterns',
    items: [
      'Breakout', 'Pullback', 'Trend Follow', 'Mean Reversion', 'Momentum',
      'Swing', 'Scalp', 'Range Trade', 'Reversal', 'Continuation',
    ],
  },
  {
    label: 'Day / intraday',
    items: [
      'Day Scalp', 'Day Momentum', 'Gap & Go', 'Opening Range Break', 'ORB',
      'VWAP Bounce', 'VWAP Reject', 'Failed Breakout', 'Level 2 / Tape Read',
      'Liquidity Sweep', 'Power Hour', 'Midday Chop', 'HOD/LOD Break',
    ],
  },
  {
    label: 'Swing / position',
    items: [
      'Swing Momentum', 'Swing Position', 'Position Trade', 'Pullback to MA',
      'Breakout + Retest', 'Squeeze Setup (BB/KC)', 'HTF Breakout', 'Base Breakout',
      'Long-Term Compounder', 'Value / Dip Buy', 'Sector Rotation',
    ],
  },
  {
    label: 'Catalyst & event',
    items: [
      'Earnings Play', 'News / Catalyst', 'Short Squeeze', 'FDA / Biotech Catalyst',
      'Macro / FOMC', 'Pre-Market Gap', 'Post-Earnings Drift',
    ],
  },
  {
    label: 'Income & dividend',
    items: [
      'Dividend Play', 'Dividend Capture', 'Covered Call', 'Wheel Strategy',
      'Cash-Secured Put', 'Yield / Income', 'Ex-Div Run', 'REIT Income',
    ],
  },
  {
    label: 'Short side',
    items: [
      'Short Momentum', 'Short Breakdown', 'Short Overextended', 'Fade / Short Rip',
      'Bear Flag', 'Distribution Short',
    ],
  },
  {
    label: 'Technical / structure',
    items: [
      'Supply & Demand Zone', 'Support / Resistance', 'Fibonacci Retracement',
      'Golden Cross', 'Death Cross', 'Cup & Handle', 'Head & Shoulders',
      'Double Bottom', 'Double Top', 'Trendline Break', 'Channel Trade',
      'ICT / Smart Money', 'Market Structure Shift',
    ],
  },
]

export const SETUP_TYPES_FLAT = [...new Set(SETUP_TYPE_GROUPS.flatMap(g => g.items))]

export const SETUP_TYPE_CONFIG: VocabConfig = {
  storageKey: 'tradeai.setupTypes.v1',
  defaults: SETUP_TYPES_FLAT,
  selectPlaceholder: 'Select setup type…',
  addTitle: 'Add setup type',
  addHint: 'Custom setup types are saved for this browser.',
  addPlaceholder: 'e.g. Dividend Play, ORB, Liquidity sweep',
  addConfirmLabel: 'Add setup',
  emptyError: 'Enter a setup type name.',
}

/** GICS sectors + common trading industry buckets */
export const INDUSTRY_DEFAULTS = [
  'Technology', 'Software', 'Semiconductors', 'AI / Cloud', 'Cybersecurity',
  'Healthcare', 'Biotech', 'Pharma', 'Medical Devices',
  'Financials', 'Banks', 'Insurance', 'Asset Management', 'REITs',
  'Energy', 'Oil & Gas', 'Renewables / Clean Energy',
  'Materials', 'Mining / Metals', 'Chemicals',
  'Industrials', 'Aerospace & Defense', 'Transportation', 'Machinery',
  'Consumer Discretionary', 'Retail', 'E-Commerce', 'Auto / EV', 'Restaurants',
  'Consumer Staples', 'Food & Beverage', 'Household Products',
  'Utilities', 'Communication Services', 'Media / Entertainment', 'Telecom',
  'Real Estate', 'Cannabis', 'Crypto / Digital Assets', 'ETF / Index',
  'Commodities', 'Futures / Macro', 'Multi-Sector', 'Other',
] as const

export const INDUSTRY_CONFIG: VocabConfig = {
  storageKey: 'tradeai.industryTypes.v1',
  defaults: INDUSTRY_DEFAULTS,
  selectPlaceholder: 'Select industry / sector…',
  addTitle: 'Add industry type',
  addHint: 'Saved for this browser — use for sector rotation and pivot reporting.',
  addPlaceholder: 'e.g. Biotech, Dividend ETF, Small-cap growth',
  addConfirmLabel: 'Add industry',
  emptyError: 'Enter an industry label.',
}

/** TradeZella + TradingView style mistake tags */
export const MISTAKE_DEFAULTS = [
  'FOMO', 'Revenge Trading', 'Oversized Position', 'Undersized Position',
  'Chased Entry', 'Bought the Top', 'Sold the Bottom',
  'Moved Stop Loss', 'Removed Stop', 'No Stop Loss', 'Stop Too Tight', 'Stop Too Wide',
  'Early Exit (fear)', 'Early Exit (greed)', 'Held Loser Too Long', 'Cut Winner Too Early',
  'Did Not Take Profit at Target', 'Ignored Take Profit', 'Ignored Stop Loss',
  'Overtrading', 'Undertrading', 'Trading Boredom', 'Impulsive Entry',
  'No Trade Plan', 'Ignored Plan', 'Deviated from Plan', 'Wrong Setup',
  'Poor Entry Timing', 'Poor Exit Timing', 'Bad Risk/Reward',
  'Averaged Down', 'Averaged Up', 'Added to Loser', 'Scaled In Too Fast',
  'Ignored Market Conditions', 'Traded Against Trend', 'Fought the Tape',
  'Hesitation', 'Lack of Patience', 'Overconfidence', 'Fear of Missing Move',
  'Held Through Earnings (unplanned)', 'Sized Up After Loss', 'Revenge Size',
  'No Pre-Market Prep', 'Ignored Volume', 'Ignored VWAP', 'Chased Breakout Late',
] as const

export const MISTAKE_CONFIG: VocabConfig = {
  storageKey: 'tradeai.mistakeTags.v1',
  defaults: MISTAKE_DEFAULTS,
  selectPlaceholder: 'Add mistake tag…',
  addTitle: 'Add mistake tag',
  addHint: 'Custom mistakes saved for this browser.',
  addPlaceholder: 'e.g. Chased green candle',
  addConfirmLabel: 'Add mistake',
  emptyError: 'Enter a mistake label.',
}

/** TradeZella-style strengths */
export const STRENGTH_DEFAULTS = [
  'Patient Entry', 'Good Size', 'Proper Position Size', 'Let Winner Run',
  'Cut Loss Fast', 'Followed Plan', 'Waited for Setup', 'Took Planned Exit',
  'Honored Stop', 'Scaled Out Correctly', 'Good Risk/Reward', 'Waited for Confirmation',
  'Respected VWAP', 'Respected Key Level', 'Avoided FOMO', 'Stayed Disciplined',
  'Took Profit at Target', 'Let Stop Do Its Job', 'Good Entry Timing', 'Good Exit Timing',
  'Pre-Market Prep', 'Journal Before Trade', 'Sized Down After Loss', 'No Revenge Trade',
  'Held Through Plan', 'Partial Profit at Resistance', 'Trailed Stop Correctly',
] as const

export const STRENGTH_CONFIG: VocabConfig = {
  storageKey: 'tradeai.strengthTags.v1',
  defaults: STRENGTH_DEFAULTS,
  selectPlaceholder: 'Add strength tag…',
  addTitle: 'Add strength tag',
  addHint: 'Custom strengths saved for this browser.',
  addPlaceholder: 'e.g. Waited for 5m close',
  addConfirmLabel: 'Add strength',
  emptyError: 'Enter a strength label.',
}

/** Plan adherence — TradeZella playbook / plan tracking */
export const TRADE_PLAN_DEFAULTS = [
  'Full plan follow',
  'Mostly followed plan',
  'Partial plan follow',
  'Deviated — entry',
  'Deviated — exit',
  'Deviated — size',
  'Deviated — stop',
  'No plan / impulsive',
  'Unplanned trade',
  'Playbook A',
  'Playbook B',
  'Playbook C',
  'Pre-market plan',
  'Intraday discretionary',
  'Rules-based / systematic',
  'Scratched valid setup',
  'Forced trade / boredom',
  'Earnings plan',
  'Dividend / income plan',
  'Swing plan',
  'Scalp plan',
] as const

export const TRADE_PLAN_CONFIG: VocabConfig = {
  storageKey: 'tradeai.tradePlans.v1',
  defaults: TRADE_PLAN_DEFAULTS,
  selectPlaceholder: 'Select plan adherence…',
  addTitle: 'Add plan type',
  addHint: 'Custom plan labels saved for this browser.',
  addPlaceholder: 'e.g. ORB playbook, Friday exit rule',
  addConfirmLabel: 'Add plan',
  emptyError: 'Enter a plan label.',
}

/** Map plan selection → followed_plan boolean for analytics */
export function planImpliesFollowed(plan: string): boolean | null {
  const p = (plan || '').toLowerCase()
  if (!p) return null
  if (p.includes('full plan') || p.includes('mostly followed') || p.startsWith('playbook') || p.includes('rules-based')) return true
  if (p.includes('no plan') || p.includes('impulsive') || p.includes('unplanned') || p.includes('forced') || p.includes('boredom')) return false
  if (p.includes('partial') || p.includes('deviated')) return false
  return null
}