/** Priced realized P&L, and the proceeds of sells whose cost basis is unknown.

The priced figure is never increased by those proceeds. A missing unpriced read
stays missing. Callers format the proceeds; this module does not invent a basis
and does not embed a book figure.
*/

export type RealizedJournal = {
  realized_pnl?: number | null
  priced_realized?: number | null
  unpriced_count?: number | null
  unpriced_proceeds?: number | null
  realized_excluded_basis_unknown?: { count?: number | null; proceeds?: number | null } | null
}

export type RealizedScope = {
  priced: number | null
  count: number | null
  proceeds: number | null
}

function num(v: unknown): number | null {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export function realizedScope(journal: RealizedJournal | null | undefined): RealizedScope {
  const priced = num(journal?.priced_realized) ?? num(journal?.realized_pnl)
  const named = journal != null && ('unpriced_count' in journal || 'unpriced_proceeds' in journal)
  if (named) {
    return { priced, count: num(journal?.unpriced_count), proceeds: num(journal?.unpriced_proceeds) }
  }
  const legacy = journal?.realized_excluded_basis_unknown
  return { priced, count: num(legacy?.count), proceeds: num(legacy?.proceeds) }
}

export function realizedScopeNote(scope: RealizedScope, fmt: (n: number) => string): string {
  if (scope.count == null || scope.proceeds == null) return 'priced sells only · unpriced proceeds not reported'
  if (scope.count === 0 && scope.proceeds === 0) return 'priced sells only'
  return `priced sells only · ${fmt(scope.proceeds)} of proceeds have no cost basis`
}
