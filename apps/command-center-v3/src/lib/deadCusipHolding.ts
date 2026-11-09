/** Same rule as scripts/lib/security_identity.py is_dead_cusip_holding.

 * A holding known only by a CUSIP, with no current price and no market value,
 * is ignored on the page. A CUSIP-shaped row that still has a price is kept.
 * Synthetic fixtures only. This does not write a store.
 */

const CUSIP_RE = /^[0-9]{3}[0-9A-Z]{5}[0-9]$/

export function isCusipLike(value: unknown): boolean {
  const s = String(value ?? '').trim().toUpperCase().replace(/ /g, '')
  return CUSIP_RE.test(s) && !/^[A-Z]+$/.test(s)
}

function num(value: unknown): number {
  if (value === null || value === undefined || value === '') return 0
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

export function isDeadCusipHolding(
  row: { symbol?: unknown; current_price?: unknown; market_value?: unknown } | null | undefined,
): boolean {
  if (!row || !isCusipLike(row.symbol)) return false
  return num(row.current_price) <= 0 && num(row.market_value) <= 0
}
