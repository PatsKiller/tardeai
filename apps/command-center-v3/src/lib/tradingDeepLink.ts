/**
 * Trading hub deep-link contract (enterprise maturity WP-T1).
 *
 * Supported query params on /v3/trading:
 *   tab       — hub tab name (Trade AI | Open Trades | Proposals | …)
 *   symbol    — ticker to focus (Open Trades, Entry Desk, Proposals)
 *   proposal  — broker proposal id (Proposals tab)
 *   intent    — broker order intent id (Broker Orders)
 *   otab      — Options nested subtab when tab=Options
 *   account   — optional account disambiguation
 *
 * Telegram /go routes rewrite into these params (see App.tsx).
 * Tab changes must URL-sync so shared state survives refresh.
 */

export const TRADING_TABS = [
  'Trade AI',
  'Options',
  'Open Trades',
  'Proposals',
  'Entry Desk',
  'Execution',
  'Broker Recon',
  'Scalp',
  'ATM Controls',
  'Broker Orders',
  'Schwab Accounts',
] as const

export type TradingTab = (typeof TRADING_TABS)[number]

/** Legacy / Telegram aliases → canonical tab. */
export const TRADING_TAB_ALIASES: Record<string, TradingTab> = {
  'Manual ToS': 'Entry Desk',
  'Manual%20ToS': 'Entry Desk',
  'Broker+Orders': 'Broker Orders',
  'Broker%20Orders': 'Broker Orders',
  'Broker Proposals': 'Proposals',
  'Broker+Proposals': 'Proposals',
  'Open+Trades': 'Open Trades',
  'Trade+AI': 'Trade AI',
  'Entry+Desk': 'Entry Desk',
  'ATM+Controls': 'ATM Controls',
  'Schwab+Accounts': 'Schwab Accounts',
  'Broker+Recon': 'Broker Recon',
}

export interface TradingDeepLink {
  tab: TradingTab
  symbol: string | null
  proposal: string | null
  intent: string | null
  otab: string | null
  account: string | null
}

export function resolveTradingTab(raw: string | null | undefined, hasProposal?: boolean): TradingTab {
  if (!raw && hasProposal) return 'Proposals'
  if (!raw) return 'Trade AI'
  const t = String(raw).trim()
  const normalized = t.replace(/\+/g, ' ')
  if (TRADING_TAB_ALIASES[t]) return TRADING_TAB_ALIASES[t]
  if (TRADING_TAB_ALIASES[normalized]) return TRADING_TAB_ALIASES[normalized]
  if ((TRADING_TABS as readonly string[]).includes(normalized)) return normalized as TradingTab
  const hit = TRADING_TABS.find(x => x.toLowerCase() === normalized.toLowerCase())
  return hit ?? 'Trade AI'
}

export function parseTradingDeepLink(
  params: URLSearchParams | { get: (k: string) => string | null },
): TradingDeepLink {
  const g = (k: string) => params.get(k)
  const proposal = g('proposal') ? String(g('proposal')).trim() : null
  const intent = g('intent') ? String(g('intent')).trim() : null
  const symbolRaw = g('symbol')
  const symbol = symbolRaw ? String(symbolRaw).trim().toUpperCase() : null
  const account = g('account') ? String(g('account')).trim() : null
  const otab = g('otab') ? String(g('otab')).trim() : null
  // intent without tab → Broker Orders
  let tab = resolveTradingTab(g('tab'), Boolean(proposal))
  if (intent && !g('tab') && !proposal) tab = 'Broker Orders'
  return { tab, symbol, proposal, intent, otab, account }
}

/** Build query params for a tab change, preserving focus keys when relevant. */
export function tradingTabSearchParams(
  prev: URLSearchParams,
  tab: TradingTab,
  opts?: { clearFocus?: boolean },
): URLSearchParams {
  const next = new URLSearchParams(prev)
  next.set('tab', tab)
  if (opts?.clearFocus) {
    next.delete('symbol')
    next.delete('proposal')
    next.delete('intent')
    next.delete('otab')
    next.delete('account')
  } else {
    // Drop keys that only apply to other desks to avoid confusing dual focus
    if (tab !== 'Proposals') next.delete('proposal')
    if (tab !== 'Broker Orders') next.delete('intent')
    if (tab !== 'Options') next.delete('otab')
    if (tab !== 'Open Trades' && tab !== 'Entry Desk' && tab !== 'Proposals') {
      // keep symbol only for desks that honor it
      if (tab !== 'Trade AI') next.delete('symbol')
    }
  }
  return next
}
