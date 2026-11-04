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
  if (s === 'BROKER_OBSERVED') {
    return 'Linked from matching Schwab activity (read-only). Nothing was placed from here and this is not approval.'
  }
  if (s === 'READY' || s === 'GENERATED') {
    return 'Draft readiness only: this says your ticket is complete to review. It is not approval and nothing has been sent.'
  }
  // codex B3 (2026-11-04): EXCEPTION and an unrecorded state used to inherit the completeness sentence.
  // An incomplete or unknown row must say so, in the same plain words the badge uses.
  if (s === 'EXCEPTION') {
    return 'This draft has an exception, so it is not ready to review. It is not approval and nothing has been sent.'
  }
  if (!s) {
    return 'No state is recorded for this draft, so this page cannot say the ticket is complete. Nothing has been sent.'
  }
  return `This draft is ${s.toLowerCase()}, not complete to review. It is not approval and nothing has been sent.`
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
