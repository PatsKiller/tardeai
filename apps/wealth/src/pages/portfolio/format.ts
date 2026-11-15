// Presentation helpers. Every one of these formats a SERVED value; none derives one.
//
// Unit traps pinned here (measured 2026-11-14 on the live wire):
//   * portfolioPct / gainLossPct / dayChangePct / yieldPct / retracementFromHighPct arrive as PERCENTS.
//     The formatter appends "%" and never multiplies by 100.
//   * marketCapB arrives in MILLIONS. `marketCapText` divides by 1000 to reach billions and never
//     multiplies into dollars.

import type { HoldingsFreshness, ServedFreshness } from './contract'

const MONEY = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const MONEY_WHOLE = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
// A PRICE below one dollar. Four decimals is the floor of this format: a served price smaller than
// half of 0.0001 still cannot print as zero (see `price`), it prints as a bound.
const PRICE_SUB = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
const SHARES = new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 })
const PCT2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const PCT1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** "N/A — <reason>". Missing is never printed as 0. */
export function unavailable(reason: string): string {
  return `N/A — ${reason}`
}

/**
 * A dollar amount. The SIGN precedes the currency symbol: "-$1,841.22", never "$-1,841.22" — the
 * second is what `$${format(n)}` produces for a negative, and it reads as a currency symbol followed
 * by a stray minus rather than as a signed amount (measured on the live header, 2026-11-15T1555Z).
 */
export function money(n: number | null): string {
  if (n === null) return unavailable('not served')
  // Intl prints a negative zero as "-0.00"; a served zero is zero and carries no sign (n === 0 is true of -0).
  if (n === 0) return `$${MONEY.format(0)}`
  return n < 0 ? `-$${MONEY.format(Math.abs(n))}` : `$${MONEY.format(n)}`
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

/**
 * A served PRICE. Unlike a dollar amount this can be sub-cent, so it is not forced to two decimals:
 * a non-zero price below $1 keeps up to four decimals (0.0003 -> "$0.0003") and never collapses to
 * "$0.00", which is the one price-like string the page reserves for a served zero. Below 0.00005 the
 * format cannot express it, and the honest rendering is a bound ("<$0.0001"), never a zero.
 * `money()` is deliberately NOT affected: a dollar amount (value, cost, P&L, a total) is in cents.
 */
export function price(n: number | null): string {
  if (n === null) return unavailable('no price served')
  if (n === 0) return `$${MONEY.format(0)}`
  const abs = Math.abs(n)
  if (abs >= 1) return n < 0 ? `-$${MONEY.format(abs)}` : `$${MONEY.format(n)}`
  const body = PRICE_SUB.format(abs)
  if (body === PRICE_SUB.format(0)) return `${n < 0 ? '-' : ''}<$0.0001`
  return `${n < 0 ? '-' : ''}$${body}`
}

// ---- One colour policy, one place (operator visual-semantic route 2026-11-15T1555Z) --------------
// Loss is red, gain is green, and an unknown or unverified value is NEITHER: it stays neutral. Colour is
// never the only carrier — the sign, the word "Unknown" and the caption beside every number still say
// what the colour says. The class names live in semantic.css, which maps them to the shell's tokens
// (var(--red) / var(--green) / var(--muted)); no second palette is introduced here.

export type MoneyTone = 'gain' | 'loss' | 'flat' | 'unknown'

/**
 * The tone a signed amount may carry. `null` is UNKNOWN and never a tone that implies a direction; zero
 * is flat (a served zero is a measurement, but it is neither a gain nor a loss to colour).
 */
export function moneyTone(n: number | null): MoneyTone {
  if (n === null || !Number.isFinite(n)) return 'unknown'
  return n > 0 ? 'gain' : n < 0 ? 'loss' : 'flat'
}

/** The class for a tone, or '' for flat — an unsigned or zero amount keeps the surrounding ink. */
export function toneClass(tone: MoneyTone): string {
  if (tone === 'gain') return 'money-gain'
  if (tone === 'loss') return 'money-loss'
  if (tone === 'unknown') return 'money-unknown'
  return ''
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

/** A served ratio (PEG, beta). Printed as served, two decimals; no threshold and no verdict is derived from it. */
export function decimal(value: number | null): string {
  return value === null ? unavailable('not published for this instrument') : PCT2.format(value)
}

/** The producer's verdict over its SOURCE clocks: which clock, how old, and the limit it applied. */
export function servedFreshnessLine(f: ServedFreshness): string {
  const clock = f.clockLabel ?? f.clock ?? 'source'
  const aged = f.ageSeconds === null ? 'age not served' : `${age(f.ageSeconds)} old`
  const limit = f.limitSeconds === null ? 'limit not served' : age(f.limitSeconds)
  if (f.status === 'UNKNOWN') return `${clock} clock · freshness cannot be computed${f.gap === null ? '' : ` (${f.gap})`}`
  if (f.status === 'FRESH') return `${clock} clock ${aged} · stale after ${limit}`
  return `Last known good — ${clock} clock ${aged}, past the ${limit} limit. These values are not current.`
}

/**
 * Whether the book is withdrawn from "current" — by the producer's verdict over its source clocks when it serves
 * one, and by this page's own rule (a failed or unproven read) otherwise. The cache verdict alone never withdraws
 * a book whose source clocks are current: cache age is how old the RESPONSE is.
 */
export function notCurrent(f: HoldingsFreshness): boolean {
  if (f.withdrawn) return true
  return f.served !== null ? f.served.status !== 'FRESH' : f.stale
}

/** The one sentence the last-known-good alert prints, for whichever verdict the book carries. */
export function lastKnownSentence(f: HoldingsFreshness): string {
  const s = f.served
  if (s !== null && s.status === 'FRESH') {
    // The producer's clocks are current; it is this READ that could not be proven, and the notice says why.
    return 'This is last-known-good data; the read that produced it is not a current one.'
  }
  if (s === null) {
    // No producer verdict: the numbers are the RESPONSE's cache facts, so whatever is printed says cache age.
    const aged = f.ageSeconds === null ? 'of unknown age' : `${age(f.ageSeconds)} old`
    return `This is last-known-good data, ${aged} in the cache, past the ${f.staleAfterSeconds === null ? 'stale limit — limit not served.' : `${age(f.staleAfterSeconds)} limit.`}`
  }
  if (s.status === 'UNKNOWN') {
    // The producer published no verdict and said why. The session strip and the Read status notice already print
    // that reason; an alert box that replaced it with a generic sentence was the one place the page withheld it.
    return 'This is last-known-good data; the producer could not compute a freshness verdict'
      + `${s.gap === null ? ' for it.' : ` (${s.gap}).`}`
  }
  const clock = s.clockLabel ?? s.clock ?? 'source'
  const aged = s.ageSeconds === null ? 'of unknown age' : `${age(s.ageSeconds)} old`
  return `This is last-known-good data; the ${clock} clock is ${aged}, past the ${s.limitSeconds === null ? 'stale limit — limit not served.' : `${age(s.limitSeconds)} limit.`}`
}
