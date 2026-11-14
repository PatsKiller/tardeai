/** Home v010 — where each item deep-links (LQ-20261107-2992b). Pure. Every target is a route that exists in App.tsx;
 *  an item whose kind has no known page gets `null` (drawn as "no destination recorded"), never a guessed link. */

import { ACCOUNT_NAMES } from './accountLabels'

export interface Destination { to: string; label: string }

/** Priority kinds produced by scripts/lib/home_priorities_live.py -> the page that owns them. */
const BY_KIND: Record<string, Destination> = {
  INCIDENT: { to: '/ops/incidents', label: 'Open incidents' },
  APPROVALS: { to: '/approvals', label: 'Review approvals' },
  // stop advice (CIO brief) is drawn by SinceCloseStops on the Classic Home; no other page lists it
  STOP: { to: '/home-classic', label: 'Stop advice (Classic Home)' },
}

export function priorityDestination(kind: string | null | undefined): Destination | null {
  return BY_KIND[String(kind || '').toUpperCase()] ?? null
}

/**
 * CAMPAIGN-8H Home item 7: the page behind each Home fact the operator asked to be one click away.
 *
 * Every `to` names a route that exists in App.tsx. The Portfolio targets use the legacy hub params on purpose:
 * PortfolioV002 redirects any `?tab=`/`?acct=` to /portfolio-classic, which parses them (lib/portfolioDeepLink), and
 * that is the same target the shipped classic Home already links to ("Full Returns →" → `/portfolio?tab=Returns`).
 */
export const LINKS = {
  health: { to: '/health', label: 'Open Health' },
  returns: { to: '/portfolio?tab=Returns', label: 'Full Returns' },
  stopRead: { to: '/portfolio?tab=Stop Management', label: 'Stop Management' },
  news: { to: '/research-intelligence?tab=news', label: 'News' },
  opportunities: { to: '/trading?tab=Trade AI', label: 'Opportunities' },
  /** The Do-now queue is drawn by the classic Home (it has no route of its own); the ranking above is the server's. */
  doNow: { to: '/home-classic', label: 'Do now (Classic Home)' },
} as const satisfies Record<string, Destination>

/** The route part of a destination (the part App.tsx registers). */
export function routeOf(to: string): string {
  const i = to.indexOf('?')
  return i < 0 ? to : to.slice(0, i)
}

/**
 * A Portfolio hub filter for one account KEY (percent-encoded, so a key with a space or `&` cannot forge another
 * parameter). Null for an empty key — a link with no account would silently open "all", which is a different fact.
 */
function accountKeyLink(key: string, label: string): Destination {
  return { to: `/portfolio?acct=${encodeURIComponent(key)}`, label }
}

/**
 * The holdings STORE's one rename (`scripts/schwab_position_sync.py:1169 _HOLDINGS_ACCT` ==
 * `scripts/holdings_export.py:98 HOLDINGS_LABELS` == `positions_sync.HOLDINGS_ACCOUNT_ALIASES`, pinned by
 * `tests/test_holdings_db_first_20261106.py:331-345`): the Roth key is written as `schwab_roth`, every other key —
 * `schwab_taxable`, `schwab_rollover_ira` — passes through unchanged.
 *
 * `ACCOUNT_ALIASES` in ./accountLabels is a DISPLAY map (`config/account_display_names.json`), not the store's:
 * its `schwab_rollover` / `schwab_individual` are short names nothing in the store writes
 * (`holdings_export.py:98-104`), so inverting it puts un-matchable keys in `?acct=` (review -5, r2).
 */
const HOLDINGS_KEY: Readonly<Record<string, string>> = Object.freeze({ schwab_roth_ira: 'schwab_roth' })
const normAccount = (v: unknown) => String(v ?? '').trim().toLowerCase().replace(/\s+/g, ' ')

/**
 * An account expander: the Portfolio hub filtered to that account. The input is the account label the Home card
 * draws (a display name such as `Schwab Roth IRA`); the value carried is the KEY the destination compares — the
 * canonical key, renamed only where the holdings store renames it (`schwab_roth_ira` -> `schwab_roth`). Null when
 * the label names no configured account — including the synthetic `account unknown` bucket: its count is a count
 * of incidents, not holdings, and a filter the hub cannot match prints "No holdings match this filter", which
 * would be a false fact about the book (campaign item 7 C1, review -5).
 */
export function destinationForAccount(label: string | null | undefined): Destination | null {
  const name = String(label ?? '').trim()
  const want = normAccount(name)
  if (!want) return null
  for (const [canonical, display] of Object.entries(ACCOUNT_NAMES)) {
    if (normAccount(display) === want) return accountKeyLink(HOLDINGS_KEY[canonical] ?? canonical, name)
  }
  return null
}

/** The name item 7 shipped this seam under; the Home view calls it. Same contract as `destinationForAccount`. */
export const accountLink = destinationForAccount

/** The page behind each System-status row that has one (a row not listed is drawn without a row link). */
export const ROW_LINKS: Readonly<Record<string, ReadonlyArray<Destination>>> = {
  'row-portfolio': [{ to: '/portfolio', label: 'Holdings' }, LINKS.returns],
  'row-orders': [LINKS.stopRead],
  'row-alerts': [{ to: '/ops/incidents', label: 'Incidents' }],
}

/** The Details block: the page behind each System-status row. */
export const DETAILS: ReadonlyArray<{ id: string; label: string; to: string }> = [
  { id: 'row-portfolio', label: 'Portfolio', to: '/portfolio' },
  { id: 'row-orders', label: 'Stop read', to: LINKS.stopRead.to },
  { id: 'row-schedulers', label: 'Schedulers', to: '/ops/jobs' },
  { id: 'row-alerts', label: 'Alerts', to: '/ops/incidents' },
  { id: 'row-data', label: 'Data', to: '/health' },
  { id: 'approvals', label: 'Approvals', to: '/approvals' },
  { id: 'watch', label: 'Watch', to: '/watch' },
  { id: 'classic', label: 'Classic Home', to: '/home-classic' },
]

export const GATES_VISIBLE = 5

/** First GATES_VISIBLE gates in server order, but a gate that is not OK is never folded away: only OK gates collapse. */
export function gateOverflow<T extends { state: string }>(gates: T[], expanded: boolean): { shown: T[]; hidden: number } {
  if (expanded || gates.length <= GATES_VISIBLE) return { shown: gates, hidden: 0 }
  const shown = gates.filter((g, i) => i < GATES_VISIBLE || g.state !== 'OK')
  return { shown, hidden: gates.length - shown.length }
}

/** blocks_trading is tri-state; null/absent is "not declared", never "does not block". */
export function blocksText(v: boolean | null | undefined): string {
  return v === true ? 'blocks trading' : v === false ? 'does not block trading' : 'classification pending (UNKNOWN)'
}
