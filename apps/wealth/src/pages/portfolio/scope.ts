// Account scope for the Portfolio view — one selector, two consumers (the shell's top bar and the page).
//
// The scope is a FILTER over the served rows and nothing else. It never produces a number:
//   * "All accounts" is the served book, and the book measures are the producer's;
//   * a single account narrows the rows, and every book-level measure renders "not served per account",
//     because no measure is served per account on this read. The rows are NEVER summed to fill that gap:
//     summing is what the contract forbids and what would turn a scope filter into a fabricated total.
//
// Pure: no React, no fetch. The options come from the rows the producer served, so a scope that the book
// does not contain cannot be selected.

import type { BookMeasure, HoldingsBook, HoldingsRow } from './contract'
import { accountFallbackLabel, stableAccountRef } from './accountLabel'

/** `'ALL'` or a served `accountKey`. */
export type Scope = 'ALL' | string

export interface ScopeOption {
  key: Scope
  label: string
}

export function scopeOptions(book: HoldingsBook): ScopeOption[] {
  const seen = new Map<string, string>()
  for (const r of book.rows) {
    if (r.accountKey !== '' && !seen.has(r.accountKey)) seen.set(r.accountKey, r.accountLabel || accountFallbackLabel(r.accountRef ?? stableAccountRef(r.accountKey)))
  }
  const accounts = [...seen.entries()]
    .map(([key, label]) => ({ key: key as Scope, label }))
    .sort((a, b) => a.label.localeCompare(b.label))
  return [{ key: 'ALL', label: accounts.length > 0 ? `All accounts (${accounts.length})` : 'All accounts' }, ...accounts]
}

export function scopeExists(book: HoldingsBook, scope: Scope): boolean {
  return scope === 'ALL' || book.rows.some(r => r.accountKey === scope)
}

export function scopeLabel(book: HoldingsBook, scope: Scope): string {
  if (scope === 'ALL') {
    const n = new Set(book.rows.map(r => r.accountKey)).size
    return `all accounts${n > 0 ? ` (${n})` : ''}`
  }
  const row = book.rows.find(r => r.accountKey === scope)
  // F2: never the raw key. A fallback label already carries the stable ref, so it is printed once.
  if (!row) return accountFallbackLabel(stableAccountRef(scope))
  const ref = row.accountRef ?? stableAccountRef(row.accountKey)
  return row.accountLabelBasis === 'fallback' ? row.accountLabel : `${row.accountLabel} · ${ref}`
}

export function rowsInScope(book: HoldingsBook, scope: Scope): HoldingsRow[] {
  return scope === 'ALL' ? book.rows : book.rows.filter(r => r.accountKey === scope)
}

export interface ScopedMeasure {
  /** True when this measure may be read for the selected scope. */
  available: boolean
  valueUsd: number | null
  reason: string
  /** The measure as served, for the clock and the verified flag. Null only when no measure is served at all. */
  measure: BookMeasure | null
}

/**
 * What a book-level measure says under a scope. `'ALL'` is the producer's own book; any other scope is
 * UNAVAILABLE for every measure, by the served shape of this read — not by a page decision.
 */
export function scopedMeasure(book: HoldingsBook, id: BookMeasure['id'], scope: Scope): ScopedMeasure {
  const m = book.measures.find(x => x.id === id) ?? null
  if (scope !== 'ALL') {
    return { available: false, valueUsd: null, reason: 'Not served per account.', measure: m }
  }
  if (m === null) return { available: false, valueUsd: null, reason: 'No such measure is served.', measure: null }
  if (m.status !== 'MEASURED' || m.valueUsd === null) {
    return { available: false, valueUsd: null, reason: m.reason, measure: m }
  }
  return { available: true, valueUsd: m.valueUsd, reason: m.verified ? '' : 'measured, not verified', measure: m }
}
