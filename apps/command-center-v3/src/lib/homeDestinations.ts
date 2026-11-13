/** Home v010 — where each item deep-links (LQ-20261107-2992b). Pure. Every target is a route that exists in App.tsx;
 *  an item whose kind has no known page gets `null` (drawn as "no destination recorded"), never a guessed link. */

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

/** The Details block: the page behind each System-status row. */
export const DETAILS: ReadonlyArray<{ id: string; label: string; to: string }> = [
  { id: 'row-portfolio', label: 'Portfolio', to: '/portfolio' },
  { id: 'row-orders', label: 'Stop read', to: '/home-classic' },
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
