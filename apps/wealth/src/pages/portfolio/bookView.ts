// Where the book may be shown, and what the shell is allowed to say about it.
//
// One read, one snapshot (snapshot.tsx): the Holdings page publishes what it read and the shell's top bar renders
// it. The snapshot is only meaningful ON the route whose page performs that read. A dated number on any other route
// is still a claim about the current page, and the page that shows it never read the book — so the bar is
// route-aware, not only state-aware.
//
// Measured failure this closes (cc-deepseek-3 verdict 2026-11-15T04:48Z §8): load Portfolio › Holdings, click Home,
// and the bar kept both bound values and the clock, because nothing cleared the provider and nothing looked at the
// route. The intended "not read on this page" state was reachable only on a cold load. Two independent guards now
// stand: `usePublishBook` withdraws the snapshot when the page unmounts, and `barStatus` refuses to show a snapshot
// published on another route. Either alone closes it; both are cheap, and the bar then does not depend on unmount
// order.
//
// Pure: no React, no router import — the tests drive it with a pathname string.

import type { HoldingsProps } from './liveProps'

export const HOLDINGS_ROUTE = '/portfolio/holdings'
/**
 * The allocation view reads the same book through the same page-side reader (`AllocationLive`, one GET of
 * `/api/v2/portfolio/holdings`), so it publishes into the snapshot just as Holdings does and the bar may show
 * what that page read (operator finding 2026-11-15T1745Z, item 2). No other route joins this list: a route that
 * does not originate the read must keep saying "not read here".
 */
export const ALLOCATION_ROUTE = '/portfolio/allocation'
/**
 * The fundamentals view reads the same book through the same page-side reader (`FundamentalsLive`, one GET), so
 * it publishes into the snapshot too and the bar may show what that page read (LEAD-RULING-G1-BOOKVIEW-OPTION-A-
 * 20261115T1922Z; the same shape as the allocation line). No other route joins this list: a route that does not
 * originate the read must keep saying "not read here".
 */
export const FUNDAMENTALS_ROUTE = '/portfolio/fundamentals'

/** True only for a route whose page performs the heavy read. A trailing slash is tolerated; nothing else is. */
export function isBookRoute(pathname: string): boolean {
  const p = pathname.length > 1 && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname
  return p === HOLDINGS_ROUTE || p === ALLOCATION_ROUTE || p === FUNDAMENTALS_ROUTE
}

export type BarStatus =
  | { kind: 'not-read' }
  | { kind: 'loading' }
  | { kind: 'error'; reason: string }
  | { kind: 'book' }

/**
 * What the top bar may say for this route and this snapshot. A snapshot that exists but was published by another
 * route is NOT read here: the reason is structural (this page never originated the heavy read), not an age, and it
 * is never rendered as a number with a clock from a different page.
 */
export function barStatus(pathname: string, props: HoldingsProps | null): BarStatus {
  if (!isBookRoute(pathname)) return { kind: 'not-read' }
  if (props === null) return { kind: 'not-read' }
  if (props.error !== null) return { kind: 'error', reason: props.error }
  return props.book === null ? { kind: 'loading' } : { kind: 'book' }
}
