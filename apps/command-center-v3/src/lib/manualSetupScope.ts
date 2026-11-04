// FQ-044 (/manual-execution F) — READY must not read as approval.
//
// The audit saw one draft card carrying READY, TECH OK, DECISION PENDING and rating UNKNOWN with nothing
// stating what each label scopes. On this desk READY is about the draft the operator has written; the
// decision is advisory; nothing here places an order. These helpers name the scope in the label itself,
// so the words travel with the value instead of relying on a legend someone may not read.

export function stateBadgeWords(state: string | null | undefined): string {
  const s = String(state || '').toUpperCase()
  if (s === 'BROKER_OBSERVED') return 'AUTO-LINKED FROM SCHWAB READ-ONLY'
  if (s === 'READY') return 'READY · DRAFT — NOT SENT'
  if (s === 'GENERATED') return 'GENERATED · DRAFT — NOT SENT'
  return s || 'STATE NOT RECORDED'
}

export function stateScopeTitle(state: string | null | undefined): string {
  const s = String(state || '').toUpperCase()
  if (s === 'BROKER_OBSERVED') return 'This position was read from your Schwab account (read-only). Nothing was placed from here.'
  return 'Draft readiness only: this says your ticket is complete to review. It is not approval and nothing has been sent.'
}

export function decisionWords(decision: string | null | undefined, source: string | null | undefined): string {
  const d = String(decision ?? '').toUpperCase()
  const advisory = ' · advisory'
  if (d === 'GO' || d === 'WAIT') return d + advisory
  return String(source || '').toUpperCase() === 'WATCHLIST' ? 'WATCHLIST ADVISORY' : 'DECISION PENDING' + advisory
}

/** FQ-044: the TECH badge is a technical grade, never a decision; say so where the eye lands. */
export function techScopeTitle(grade: string | null | undefined): string {
  const g = String(grade || '').toUpperCase()
  return g
    ? 'Technical grade only — it is not a decision, an approval or an order. Nothing here places an order.'
    : 'No technical grade is recorded for this row.'
}

/** FQ-044: an absent rating is "not on file", not a bare UNKNOWN that reads like a system fault. */
export function ratingScopeWords(label: string | null | undefined): string {
  const text = String(label || '').trim()
  if (!text || text.toUpperCase() === 'UNKNOWN') return 'not on file'
  return text
}

export const RATING_SCOPE_TITLE = 'An opinion about the security — not permission to trade and not an order.'
