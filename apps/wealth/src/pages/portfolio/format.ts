// Presentation helpers. Every one of these formats a SERVED value; none derives one.
//
// Unit traps pinned here (measured 2026-11-14 on the live wire):
//   * portfolioPct / gainLossPct / dayChangePct / yieldPct / retracementFromHighPct arrive as PERCENTS.
//     The formatter appends "%" and never multiplies by 100.
//   * marketCapB arrives in MILLIONS. `marketCapText` divides by 1000 to reach billions and never
//     multiplies into dollars.

const MONEY = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const MONEY_WHOLE = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const SHARES = new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 })
const PCT2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const PCT1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** "N/A — <reason>". Missing is never printed as 0. */
export function unavailable(reason: string): string {
  return `N/A — ${reason}`
}

export function money(n: number | null): string {
  return n === null ? unavailable('not served') : `$${MONEY.format(n)}`
}

export function signedMoney(n: number | null): string {
  if (n === null) return unavailable('not served')
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  return `${sign}$${MONEY.format(Math.abs(n))}`
}

/** Input is already a percent. */
export function signedPct(pct: number | null, digits: 1 | 2 = 2): string {
  if (pct === null) return unavailable('not served')
  const f = digits === 1 ? PCT1 : PCT2
  const sign = pct > 0 ? '+' : pct < 0 ? '-' : ''
  return `${sign}${f.format(Math.abs(pct))}%`
}

/** Input is already a percent (portfolioPct / yield). Never x100. */
export function pct(pct: number | null, digits: 1 | 2 = 2): string {
  if (pct === null) return unavailable('not served')
  return `${(digits === 1 ? PCT1 : PCT2).format(pct)}%`
}

export function shares(n: number): string {
  return SHARES.format(n)
}

export function price(n: number | null): string {
  return n === null ? unavailable('no price served') : `$${MONEY.format(n)}`
}

/**
 * Market cap: the wire is in MILLIONS (`market_cap_b`). 230500 -> "$230.5B". A value under 1000 M
 * renders in millions. Null renders as a reason, never as zero.
 */
export function marketCapText(millions: number | null, reason = 'not published for this instrument'): string {
  if (millions === null) return unavailable(reason)
  if (millions >= 1000) return `$${PCT1.format(millions / 1000)}B`
  return `$${MONEY_WHOLE.format(millions)}M`
}

/** Age of a served clock, as a short human string. The producer supplies the seconds; we do not diff clocks. */
export function age(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} s`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`
  if (seconds < 172800) return `${PCT1.format(seconds / 3600)} h`
  return `${PCT1.format(seconds / 86400)} d`
}

/**
 * A served multiple, DISPLAY-rounded to one decimal (18.75 -> "18.8x"). The rounding is presentational only:
 * the contract value is untouched, and no cell compares it to a threshold. No colour, no verdict.
 */
export function multiple(value: number | null): string {
  return value === null ? unavailable('no multiple served') : `${PCT1.format(value)}x`
}
