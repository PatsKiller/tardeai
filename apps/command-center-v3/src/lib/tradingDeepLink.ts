/**
 * Trading hub deep-link contract (enterprise maturity WP-T1; tabs 8 → 4, operator-approved 2026-10-22).
 *
 * Visible tabs: Trade AI · Options · Open Trades · Proposals. Broker Orders is a desk, not a tab: it
 * opens only from its Telegram approval links (/v3/go/order/<intent>) and `?tab=Broker+Orders`.
 *
 * Supported query params on /v3/trading:
 *   tab       — hub tab name (Trade AI | Options | Open Trades | Proposals | Broker Orders)
 *   symbol    — ticker to focus (Open Trades, Proposals incl. Path A, Trade AI)
 *   proposal  — broker proposal id (Proposals tab)
 *   intent    — broker order intent id (Broker Orders)
 *   otab      — Options nested subtab when tab=Options
 *   section   — Proposals: `path-a` (Entry Desk) · Broker Orders: `schwab-accounts`
 *   drawer    — Open Trades drawer to open: `recon` | `writeoffs` | `small` | `help`
 *   account   — optional account disambiguation
 *
 * Retired tabs keep working as redirects (LEGACY_TAB_TARGETS): Entry Desk → Proposals · Path A,
 * Broker Recon → Open Trades · reconciliation drawer, Schwab Accounts → Broker Orders desk, Scalp →
 * /active-trader?tab=Scalp, ATM Controls → /system/broker-access, Execution → /journal.
 *
 * Telegram /go routes rewrite into these params (see App.tsx).
 * Tab changes must URL-sync so shared state survives refresh.
 */

export const TRADING_TABS = [
  'Trade AI',
  'Options',
  'Open Trades',
  'Proposals',
] as const

/** Desks the hub renders: the four tabs plus Broker Orders (approval-link only, never a tab). */
export type TradingTab = (typeof TRADING_TABS)[number] | 'Broker Orders'

const HUB_DESKS: readonly string[] = [...TRADING_TABS, 'Broker Orders']

/** Where a retired tab now lives. `path` leaves the hub (react-router path under /v3). */
export type LegacyTabTarget =
  | { tab: TradingTab; section?: string; drawer?: string }
  | { path: string; keepSymbol?: boolean }

export const LEGACY_TAB_TARGETS: Record<string, LegacyTabTarget> = {
  'Entry Desk': { tab: 'Proposals', section: 'path-a' },
  'Manual ToS': { tab: 'Proposals', section: 'path-a' },
  'Broker Recon': { tab: 'Open Trades', drawer: 'recon' },
  'Schwab Accounts': { tab: 'Broker Orders', section: 'schwab-accounts' },
  'Scalp': { path: '/active-trader?tab=Scalp', keepSymbol: true },
  'ATM Controls': { path: '/system/broker-access#automation-controls' },
  'Execution': { path: '/journal' },
}

/** Legacy / Telegram aliases → canonical tab name (before LEGACY_TAB_TARGETS applies). */
export const TRADING_TAB_ALIASES: Record<string, string> = {
  'Manual%20ToS': 'Manual ToS',
  'Broker+Orders': 'Broker Orders',
  'Broker%20Orders': 'Broker Orders',
  'Broker Proposals': 'Proposals',
  'Broker+Proposals': 'Proposals',
  'Broker%20Proposals': 'Proposals',
  'Open+Trades': 'Open Trades',
  'Trade+AI': 'Trade AI',
  'Entry+Desk': 'Entry Desk',
  'ATM+Controls': 'ATM Controls',
  'Schwab+Accounts': 'Schwab Accounts',
  'Broker+Recon': 'Broker Recon',
}

/** Canonical (possibly retired) tab name for a raw `tab` value, or null when unknown. */
function canonicalTabName(raw: string): string | null {
  const t = String(raw).trim()
  const normalized = t.replace(/\+/g, ' ')
  const aliased = TRADING_TAB_ALIASES[t] ?? TRADING_TAB_ALIASES[normalized]
  if (aliased) return aliased
  const known = [...HUB_DESKS, ...Object.keys(LEGACY_TAB_TARGETS)]
  return known.find(x => x.toLowerCase() === normalized.toLowerCase()) ?? null
}

export interface TradingDeepLink {
  tab: TradingTab
  symbol: string | null
  proposal: string | null
  intent: string | null
  otab: string | null
  account: string | null
  /** Proposals `path-a` (Entry Desk) · Broker Orders `schwab-accounts` */
  section: string | null
  /** Open Trades drawer to open on load */
  drawer: string | null
  /** Path B queue filters (WP-T5) — only meaningful when tab=Proposals */
  pq: ProposalQueueDeepLink
}

/** Deep-linkable Proposals queue filters (`pq_*` query keys). */
export type ProposalQueueDeepLink = {
  sort: string
  kind: string
  source: string
  zone: string
  rr: string
  view: 'active' | 'expired'
  held: boolean
  page: number
}

export const DEFAULT_PROPOSAL_QUEUE_LINK: ProposalQueueDeepLink = {
  sort: 'priority',
  kind: 'broker',
  source: '',
  zone: '',
  rr: '',
  view: 'active',
  held: false,
  page: 1,
}

export function parseProposalQueueLink(
  params: URLSearchParams | { get: (k: string) => string | null },
): ProposalQueueDeepLink {
  const g = (k: string) => params.get(k)
  const viewRaw = (g('pq_view') || 'active').toLowerCase()
  const page = Math.max(1, Number(g('pq_page') || 1) || 1)
  return {
    sort: g('pq_sort') || DEFAULT_PROPOSAL_QUEUE_LINK.sort,
    kind: g('pq_kind') || DEFAULT_PROPOSAL_QUEUE_LINK.kind,
    source: g('pq_source') || '',
    zone: g('pq_zone') || '',
    rr: g('pq_rr') || '',
    view: viewRaw === 'expired' ? 'expired' : 'active',
    held: g('pq_held') === '1' || g('pq_held') === 'true',
    page,
  }
}

/** Merge proposal queue filters into URLSearchParams (empty defaults omitted). */
export function writeProposalQueueParams(
  params: URLSearchParams,
  pq: Partial<ProposalQueueDeepLink> & {
    sort?: string
    kind?: string
    source?: string
    zone?: string
    rrPreset?: string
    account?: string
    symbol?: string
    page?: number
  },
  opts?: { held?: boolean; view?: 'active' | 'expired' },
): URLSearchParams {
  const next = new URLSearchParams(params)
  const setOrDel = (key: string, val: string | number | undefined | null, emptyDefault?: string) => {
    const s = val == null ? '' : String(val)
    if (!s || (emptyDefault !== undefined && s === emptyDefault)) next.delete(key)
    else next.set(key, s)
  }
  setOrDel('pq_sort', pq.sort, 'priority')
  setOrDel('pq_kind', pq.kind, 'broker')
  setOrDel('pq_source', pq.source, '')
  setOrDel('pq_zone', pq.zone, '')
  setOrDel('pq_rr', pq.rr ?? pq.rrPreset, '')
  const view = opts?.view ?? (pq as ProposalQueueDeepLink).view
  if (view && view !== 'active') next.set('pq_view', view)
  else next.delete('pq_view')
  const held = opts?.held ?? (pq as ProposalQueueDeepLink).held
  if (held) next.set('pq_held', '1')
  else next.delete('pq_held')
  const page = pq.page ?? 1
  if (page > 1) next.set('pq_page', String(page))
  else next.delete('pq_page')
  return next
}

export function clearProposalQueueParams(params: URLSearchParams): URLSearchParams {
  // Mutate in place so callers can chain without reassignment.
  for (const k of ['pq_sort', 'pq_kind', 'pq_source', 'pq_zone', 'pq_rr', 'pq_view', 'pq_held', 'pq_page']) {
    params.delete(k)
  }
  return params
}

export function resolveTradingTab(raw: string | null | undefined, hasProposal?: boolean): TradingTab {
  if (!raw && hasProposal) return 'Proposals'
  if (!raw) return 'Trade AI'
  const name = canonicalTabName(raw)
  if (!name) return 'Trade AI'
  const legacy = LEGACY_TAB_TARGETS[name]
  if (legacy) return 'tab' in legacy ? legacy.tab : 'Trade AI'
  return name as TradingTab
}

/**
 * Path outside the hub for a retired tab that moved to another page (Scalp, ATM Controls, Execution),
 * or null. Scalp keeps `symbol` so Telegram entry-alert links still focus the ticker.
 */
export function legacyTradingRedirect(
  params: URLSearchParams | { get: (k: string) => string | null },
): string | null {
  const raw = params.get('tab')
  if (!raw) return null
  const name = canonicalTabName(raw)
  const legacy = name ? LEGACY_TAB_TARGETS[name] : undefined
  if (!legacy || !('path' in legacy)) return null
  const sym = params.get('symbol')
  if (legacy.keepSymbol && sym) {
    const [path, hash] = legacy.path.split('#')
    const sep = path.includes('?') ? '&' : '?'
    return `${path}${sep}symbol=${encodeURIComponent(sym.trim().toUpperCase())}${hash ? `#${hash}` : ''}`
  }
  return legacy.path
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
  const rawTab = g('tab')
  const legacyName = rawTab ? canonicalTabName(rawTab) : null
  const legacy = legacyName ? LEGACY_TAB_TARGETS[legacyName] : undefined
  const legacyIn = legacy && 'tab' in legacy ? legacy : undefined
  const section = (g('section') ? String(g('section')).trim() : null) ?? legacyIn?.section ?? null
  const drawer = (g('drawer') ? String(g('drawer')).trim() : null) ?? legacyIn?.drawer ?? null
  return { tab, symbol, proposal, intent, otab, account, section, drawer, pq: parseProposalQueueLink(params) }
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
    next.delete('section')
    next.delete('drawer')
    return clearProposalQueueParams(next)
  }
  if (tab !== 'Proposals' && tab !== 'Broker Orders') next.delete('section')
  if (tab !== 'Open Trades') next.delete('drawer')
  // Drop keys that only apply to other desks to avoid confusing dual focus
  if (tab !== 'Proposals') {
    next.delete('proposal')
    clearProposalQueueParams(next)
  }
  if (tab !== 'Broker Orders') next.delete('intent')
  if (tab !== 'Options') next.delete('otab')
  // keep symbol only for desks that honor it (Scalp moved to /active-trader with its symbol)
  if (tab !== 'Open Trades' && tab !== 'Proposals' && tab !== 'Trade AI') next.delete('symbol')
  return next
}
