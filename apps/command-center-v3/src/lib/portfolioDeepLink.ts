/**
 * Portfolio hub deep-link contract (enterprise maturity WP-A).
 *
 * Supported query params on /v3/portfolio:
 *   tab        — hub tab name (Holdings | Allocation | … | Stop Management)
 *   acct       — account key filter (or all when absent)
 *   sig        — signal bucket: All | Buy/Add | Hold | Watch | Trim/Sell
 *   symbol     — ticker to focus (case-insensitive)
 *   account    — optional lot account when symbol is multi-account
 *   drawer     — optional "SYM:account" to open the holdings drawer
 *   drawerTab  — optional drawer tab: overview | stops | …
 *
 * Callers already emit ?symbol= (HomeHub, Research Intel). PortfolioHub must honor them.
 */

export const PORTFOLIO_SIGNAL_TABS = ['All', 'Buy/Add', 'Hold', 'Watch', 'Trim/Sell'] as const
export type PortfolioSignalTab = (typeof PORTFOLIO_SIGNAL_TABS)[number]

export const PORTFOLIO_TABS = [
  'Holdings', 'Allocation', 'Look-through', 'Returns', 'Dividends',
  'Forecast', 'Tax', 'Stop Management',
] as const
export type PortfolioTab = (typeof PORTFOLIO_TABS)[number]

/** Retired hub tabs that now live on their own desk (design pages/jobs v002, operator-approved 2026-11-06: the
 *  Redeploy sub-tab became a link to the /redeploy desk). An old `?tab=` link is sent there instead of to Holdings. */
export const PORTFOLIO_TAB_REDIRECTS: Readonly<Record<string, string>> = { redeploy: '/redeploy' }
export function portfolioTabRedirect(raw: string | null | undefined): string | null {
  const t = String(raw ?? '').trim().replace(/\+/g, ' ').toLowerCase()
  return t ? PORTFOLIO_TAB_REDIRECTS[t] ?? null : null
}

/** The pre-v002 Portfolio hub (App.tsx declares it under this path; the UI-removal rule keeps it reachable
 *  while the tabs below are unimplemented in v002). One constant, so a test can pin the router's path. */
export const PORTFOLIO_CLASSIC_PATH = '/portfolio-classic'

/** Query params ONLY the classic hub implements. Live surfaces still emit these hrefs: Allocation's
 *  "Underlying stocks, sectors and industries →" and the Look-through desk emit `?tab=Look-through`;
 *  Home and HomeDoNow emit `?tab=Returns`; the Risk desk emits `?tab=Stop Management`; OpenTrades and
 *  Research Intel add `&symbol=`. */
export const LEGACY_PORTFOLIO_PARAMS = ['tab', 'drawer', 'drawerTab', 'sig', 'acct'] as const

/** OBS-P2a / OBS-P2b: where a legacy hub href must go, or null when the v002 page owns the link.
 *  v002 implements no tab, so a `?tab=` link that stayed here would render Holdings under a label it never
 *  honoured. The WHOLE query string is handed over unchanged — the classic hub understands all of it. */
export function legacyPortfolioRedirect(search: string | null | undefined): string | null {
  if (!search) return null
  const q = search.startsWith('?') ? search : `?${search}`
  const params = new URLSearchParams(q)
  return LEGACY_PORTFOLIO_PARAMS.some(k => params.has(k)) ? `${PORTFOLIO_CLASSIC_PATH}${q}` : null
}

export interface PortfolioDeepLink {
  tab: PortfolioTab
  acct: string | null
  sig: PortfolioSignalTab
  symbol: string | null
  account: string | null
  drawer: string | null
  drawerTab: string | null
}

export function resolvePortfolioTab(raw: string | null | undefined): PortfolioTab {
  if (!raw) return 'Holdings'
  const t = String(raw).trim()
  // Accept URL-encoded spaces and common aliases
  const normalized = t.replace(/\+/g, ' ')
  if ((PORTFOLIO_TABS as readonly string[]).includes(normalized)) return normalized as PortfolioTab
  // case-insensitive fallback
  const hit = PORTFOLIO_TABS.find(x => x.toLowerCase() === normalized.toLowerCase())
  return hit ?? 'Holdings'
}

export function resolvePortfolioSig(raw: string | null | undefined): PortfolioSignalTab {
  if (!raw) return 'All'
  const t = String(raw).trim().replace(/\+/g, ' ')
  if ((PORTFOLIO_SIGNAL_TABS as readonly string[]).includes(t)) return t as PortfolioSignalTab
  const hit = PORTFOLIO_SIGNAL_TABS.find(x => x.toLowerCase() === t.toLowerCase())
  return hit ?? 'All'
}

export function resolvePortfolioAcct(raw: string | null | undefined): string | null {
  if (!raw || raw === 'all' || raw === 'null') return null
  return String(raw).trim()
}

export function parsePortfolioDeepLink(params: URLSearchParams | { get: (k: string) => string | null }): PortfolioDeepLink {
  const g = (k: string) => params.get(k)
  const symbolRaw = g('symbol')
  const symbol = symbolRaw ? String(symbolRaw).trim().toUpperCase() : null
  const account = resolvePortfolioAcct(g('account'))
  // drawer may be full "SYM:acct" or omitted (then symbol+account used)
  let drawer = g('drawer')
  if (drawer) drawer = String(drawer).trim()
  else if (symbol && account) drawer = `${symbol}:${account}`
  else drawer = null

  return {
    tab: resolvePortfolioTab(g('tab')),
    acct: resolvePortfolioAcct(g('acct')),
    sig: resolvePortfolioSig(g('sig')),
    symbol: symbol || null,
    account,
    drawer,
    drawerTab: g('drawerTab') ? String(g('drawerTab')).trim().toLowerCase() : null,
  }
}

/** Pick a holding row for deep-link focus. Prefer exact account; else first non-cash match by MV. */
export function pickHoldingForDeepLink(
  holdings: any[],
  symbol: string | null,
  account: string | null,
): any | null {
  if (!symbol || !Array.isArray(holdings) || !holdings.length) return null
  const sym = symbol.toUpperCase()
  const matches = holdings.filter(h => String(h?.symbol || '').toUpperCase() === sym)
  if (!matches.length) return null
  if (account) {
    const exact = matches.find(h => String(h?.account || '') === account)
    if (exact) return exact
  }
  // Prefer non-cash lots when ambiguous
  const nonCash = matches.filter(h => !h?.is_cash && String(h?.symbol || '').toUpperCase() !== 'CASH')
  const pool = nonCash.length ? nonCash : matches
  return pool.slice().sort((a, b) => (Number(b?.market_value) || 0) - (Number(a?.market_value) || 0))[0] ?? null
}

export function holdingDomId(symbol: string, account: string): string {
  return `hold-${symbol}-${account}`
}
