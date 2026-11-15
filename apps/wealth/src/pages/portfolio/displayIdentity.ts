// The display identity of an instrument — ONE name per symbol, resolved at read time.
//
// Measured defect (SPCX display-identity spec R3, stored live read): one symbol held in two accounts printed two
// identities, because `row.name` is per row — `str(name) ?? str(company) ?? symbol` — and one row's `name` is the
// ticker itself while the other's is empty. This module resolves the name once per symbol over the two raw sources
// the adapter carries (`nameRaw`, `companyName`) plus an optional server-resolved `identity` verdict, so every row
// of a symbol shows the same name and the same status.
//
// What it can and cannot claim:
//   * No exchange-standard identifier is served on any row today, so the CONFIRMED branch is unreachable in
//     production and every enrichment name carries R4's label. If a route ever serves a server-resolved
//     `identity`, this module reads the verdict — it never reads the registry, never matches an identifier and
//     never does check-digit arithmetic.
//   * `security_guid` is symbol-keyed enrichment plumbing (assigned by symbol lookup), not an identity basis; it
//     is not carried on the client row at all and its presence never opens the confirmed branch.
//   * Nothing here writes, fetches or stores: the resolution is a pure function of the rows already in hand.
//   * With both raw sources absent the row shows its symbol alone (R8) — never a blank line, never a guessed name,
//     and never the ticker twice (R4b).

import type { HoldingsRow, IdentitySource, ResolvedIdentity, ServedIdentity } from './contract'

/** R4's caveat, exact. One definition: every surface that prints it prints this constant. */
export const IDENTITY_UNVERIFIED_LABEL = 'identity unverified (ticker-keyed)'

/** Trimmed, or null: the wire's empty string and a blank string are the same absence to a human reader. */
function text(v: string | null | undefined): string | null {
  const t = typeof v === 'string' ? v.trim() : ''
  return t === '' ? null : t
}

/** Case-insensitive: `Cash` and `CASH` are the same ticker written two ways, not two instruments. */
function isTicker(name: string, symbol: string): boolean {
  return name.toLowerCase() === symbol.toLowerCase()
}

/**
 * R2's ladder for one row's raw sources. The adapter uses this for the row's `nameSource`; the book resolver uses
 * the same rule over the symbol's rows — one definition, so a row's stated source cannot drift from its name.
 */
export function nameSourceFrom(
  nameRaw: string | null | undefined,
  companyName: string | null | undefined,
  symbol: string,
): IdentitySource {
  const raw = text(nameRaw)
  if (raw !== null && !isTicker(raw, symbol)) return 'carried'
  return text(companyName) !== null ? 'company' : 'symbol'
}

/**
 * The name a server-resolved identity block earns, or null when the block cannot be read as confirmed (R8).
 *
 * The only checks are of SHAPE: the verdict must be the literal `CONFIRMED`, the basis the literal `cusip`, the
 * name non-empty and the identifier nine characters (a CUSIP's length). Whether the identifier is correct, or
 * whether it is that instrument's, is the server's resolution — a client that re-derived it would be performing
 * the match R5 forbids. A block that fails the shape renders under R4's label: malformed is not confirmed.
 */
function confirmedName(served: ServedIdentity | null | undefined): string | null {
  if (!served || served.status !== 'CONFIRMED' || served.basis !== 'cusip') return null
  const identifier = text(served.identifier)
  const name = text(served.name)
  if (identifier === null || identifier.length !== 9 || name === null) return null
  return name
}

/**
 * Resolve the display identity of every symbol in the book. Keyed by SYMBOL (R1): the only row-level
 * identifier-like field is symbol-derived, so grouping by anything else adds nothing. Book order decides ties (N1):
 * the first row that can name the instrument wins, a server confirmation outranking the raw-source ladder.
 * Rows stay account-scoped — nothing is merged, weighted or valued here.
 */
export function resolveDisplayIdentity(
  rows: Pick<HoldingsRow, 'symbol' | 'nameRaw' | 'companyName' | 'servedIdentity'>[],
): Map<string, ResolvedIdentity> {
  const groups = new Map<string, (typeof rows)[number][]>()
  for (const row of rows) {
    const group = groups.get(row.symbol)
    if (group) group.push(row)
    else groups.set(row.symbol, [row])
  }
  const out = new Map<string, ResolvedIdentity>()
  for (const [symbol, group] of groups) {
    let found: string | null = null
    for (const row of group) {
      found = confirmedName(row.servedIdentity)
      if (found !== null) break
    }
    if (found !== null) {
      // The server named this instrument. `carried` is the source the name physically is (served, not derived);
      // the status, not the source, is what says the identity is confirmed.
      out.set(symbol, { nameText: found, status: 'CONFIRMED', label: null, source: 'carried' })
      continue
    }
    for (const row of group) {
      const raw = text(row.nameRaw)
      if (raw !== null && !isTicker(raw, symbol)) {
        found = raw
        break
      }
    }
    if (found !== null) {
      // (a) A broker-carried name that is not just the ticker. It is the row's own field; no caveat is added here,
      // and none is claimed: this says the name was carried, not that the instrument behind it was proven.
      out.set(symbol, { nameText: found, status: 'UNVERIFIED', label: null, source: 'carried' })
      continue
    }
    for (const row of group) {
      found = text(row.companyName)
      if (found !== null) break
    }
    if (found !== null) {
      // (b) The enrichment's company name — an enrichment is keyed by ticker, so the name identifies the TICKER,
      // not the instrument. R4's label says exactly that and rides the cell's title too.
      out.set(symbol, { nameText: found, status: 'UNVERIFIED', label: IDENTITY_UNVERIFIED_LABEL, source: 'company' })
      continue
    }
    // (c) R8: nothing names it. The symbol alone, and R4b keeps the second line from repeating it.
    out.set(symbol, { nameText: symbol, status: 'UNVERIFIED', label: null, source: 'symbol' })
  }
  return out
}

/**
 * Attach the resolved identity to every row. Rows are copied with the identity added — callers use the returned
 * rows, so nothing downstream can hold an unresolved one by accident.
 */
export function attachDisplayIdentity<T extends Pick<HoldingsRow, 'symbol' | 'nameRaw' | 'companyName' | 'servedIdentity'>>(
  rows: T[],
): (T & { identity: ResolvedIdentity })[] {
  const bySymbol = resolveDisplayIdentity(rows)
  return rows.map(row => ({ ...row, identity: bySymbol.get(row.symbol) ?? symbolOnly(row.symbol) }))
}

function symbolOnly(symbol: string): ResolvedIdentity {
  return { nameText: symbol, status: 'UNVERIFIED', label: null, source: 'symbol' }
}

/**
 * The identity a surface renders. A row that never passed through the resolver has none: it renders its symbol
 * alone (R8) rather than falling back to `row.name`, which is the per-row value this work exists to stop printing.
 */
export function displayOf(row: Pick<HoldingsRow, 'symbol' | 'identity'>): ResolvedIdentity {
  return row.identity ?? symbolOnly(row.symbol)
}

/** R4b: the second line repeats the ticker only when the resolved name IS the ticker — and then it does not. */
export function identityShowsName(identity: ResolvedIdentity, symbol: string): boolean {
  return !isTicker(identity.nameText, symbol)
}

/**
 * The second line of a row: the resolved name, then R4's label when it applies, then the account label. When the
 * name is the symbol (R4b) the line is the account label alone — `AMANX · AMANX` is never printed. One function
 * builds the visible line, the cell title and the drawer eyebrow, so the three cannot disagree.
 */
export function identitySecondLine(identity: ResolvedIdentity, symbol: string, accountLabel: string): string {
  if (!identityShowsName(identity, symbol)) return accountLabel
  return [identity.nameText, identity.label, accountLabel].filter((part): part is string => part !== null && part !== '').join(' · ')
}
