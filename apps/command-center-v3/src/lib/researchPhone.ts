/**
 * /research-intelligence phone contract (operator page audit 2026-11-04, FQ-058).
 *
 * The phone capture was >100,000 px: the priority order was buried under a full filter stack and
 * every research card expanded in place. A phone opens a short prioritized wire (12 rows), the
 * secondary filters fold behind one summary, and a row opens the existing full-screen record.
 * Desktop keeps the article view and every control visible. Pure, so the contract is testable.
 */
export type ResearchView = 'cards' | 'list' | 'compact'

export const PHONE_BREAKPOINT_PX = 820
export const PHONE_WIRE_LIMIT = 12

/** The view a fresh visit should show: the wire on a phone, the article list on a desktop. */
export function defaultResearchView(phone: boolean): ResearchView {
  return phone ? 'compact' : 'list'
}

/** The rows rendered before "Show all": a short prioritized wire on a phone, everything elsewhere. */
export function wireRows<T>(items: T[], phone: boolean, showAll: boolean, limit = PHONE_WIRE_LIMIT): T[] {
  return phone && !showAll ? items.slice(0, limit) : items
}

/** Whether the secondary filter block starts open (desktop yes; phone folds it behind a summary). */
export function secondaryFiltersOpen(phone: boolean): boolean {
  return !phone
}

/** Viewport probe used only for first paint; the live hook re-evaluates on resize. */
export function isPhoneViewport(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia(`(max-width: ${PHONE_BREAKPOINT_PX}px)`).matches
}
