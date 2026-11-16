// The display label for an account KEY, from what the read actually served.
//
// The reconciliation block (`reconciliation.accounts[]`) publishes each account's KEY and, on today's served
// build, no display label at all — while the holdings rows of the SAME payload carry `account_label`
// ("Alpaca Individual") beside the same key. Rendering the block's key alone is how the Account details table
// came to show `alpaca_taxable_live` where every other surface of the page showed the label (lead finding,
// 2026-11-15T05:09Z).
//
// Pure, no imports: `scripts/tests/shell-logic.test.mjs` loads this file directly. A label that merely repeats
// the key is NOT a label — it drops the distinction the two strings exist to make — so the row's label is
// preferred over it; with neither, the key is returned unchanged, because it is the only identifier served and
// inventing a label is forbidden.

export function accountDisplayLabel(key: string, servedLabel: string | null, rowLabel: string | null): string {
  for (const candidate of [servedLabel, rowLabel]) {
    const text = candidate?.trim() ?? ''
    if (text !== '' && text !== key) return text
  }
  return key
}

// Central account-key alias normalization (portfolio audit 2026-11-16, A). The same account is served under two
// keys on one payload — holdings rows say `schwab_roth`, the scope list and the measures say `schwab_roth_ira` —
// so a key compare reports a missing account and a "missing" row that is present. Data-driven, no hardcoded
// table: a key resolves to a served key that equals it, or to the ONE served key that extends it at an
// underscore boundary (or that it extends). Ambiguous or absent matches return null rather than guessing.
export function normalizeAccountKey(key: string, servedKeys: readonly string[]): string | null {
  const k = key.trim()
  if (k === '') return null
  if (servedKeys.includes(k)) return k
  const hits = servedKeys.filter(s => s.startsWith(k + '_') || k.startsWith(s + '_'))
  return hits.length === 1 ? hits[0] : null
}

// ---- Registry vs derived vs fallback (portfolio audit 2026-11-16, F2/A) ------------------------------------------
//
// `accountDisplayLabel` above is the legacy string join and keeps its contract (shell-logic pins it, including its
// last resort of returning the key). Surfaces that RENDER an account name use `resolveAccountDisplay` instead: it
// says where the name came from and never returns a raw key or anything that looks like an account number — when
// no usable name was served it prints the stable ref, which is a digest of the key and not the key.

/** Where an account's display name came from. Only `registry` is a resolved name; `derived` is the producer's name
 *  derived from the key (the account is not in the registry); `served` is a name served without provenance (an
 *  older backend); `fallback` prints the stable ref because no usable name was served. */
export type AccountLabelBasis = 'registry' | 'derived' | 'served' | 'fallback'

/** How two served keys were found to be one account: the producer's registry `account_aliases`, or the client's
 *  underscore-prefix heuristic (`normalizeAccountKey`), used only when no alias map is served. */
export type AccountAliasBasis = 'registry' | 'key-prefix'

export interface AccountDisplay {
  label: string
  basis: AccountLabelBasis
  /** `acct-xxxxxxxx`: stable across reads for the same key, and not the key. */
  ref: string
}

/** FNV-1a digest of the key. The same function as Income's `stableAccountRef`, so a ref names one account on both. */
export function stableAccountRef(key: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < key.length; i++) { h ^= key.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 }
  return 'acct-' + h.toString(16).padStart(8, '0')
}

/** True when text could leak an account number: a run of 3+ digits or a masked tail (`...258`, `··1234`, `**12`).
 *  The same rule as the producer's `account_display.looks_like_number`. */
export function looksLikeAccountNumber(text: string): boolean {
  return /\d{3,}/.test(text) || /(\.\.\.|··|…|\*\*|xx)\s*\w*\d/i.test(text)
}

/** The fallback text: no name was served, so the stable ref stands in. Same words as Income's fallback. */
export const accountFallbackLabel = (ref: string): string => `Account label unavailable · ${ref}`

/**
 * The one display name for an account key, with its provenance.
 *
 * `served` is this read's `account_labels[key]` with `account_label_source[key]` (null when the producer serves no
 * label map — an older backend); `rowLabel` is a row's own `account_label`. A candidate is usable only when it is
 * non-blank, is not the key itself, and does not look like an account number.
 */
export function resolveAccountDisplay(
  key: string,
  served: { label: string | null; source: string | null } | null,
  rowLabel: string | null,
): AccountDisplay {
  const ref = stableAccountRef(key)
  const usable = (t: string | null | undefined): string | null => {
    const s = t?.trim() ?? ''
    return s !== '' && s !== key && !looksLikeAccountNumber(s) ? s : null
  }
  const fallback: AccountDisplay = { label: accountFallbackLabel(ref), basis: 'fallback', ref }
  if (served !== null && served.source !== null) {
    // The producer said where its name came from: believe the provenance, never upgrade it.
    const label = usable(served.label)
    if (label === null || served.source === 'unlabelled') return fallback
    if (served.source === 'registry') return { label, basis: 'registry', ref }
    if (served.source === 'derived') return { label, basis: 'derived', ref }
    return fallback
  }
  const label = usable(served?.label) ?? usable(rowLabel)
  return label === null ? fallback : { label, basis: 'served', ref }
}

/** Words for a label basis, for a drawer `source` line. */
export function accountLabelSource(d: AccountDisplay): string {
  switch (d.basis) {
    case 'registry': return `resolved from the account registry · ${d.ref}`
    case 'derived': return `named from the account key by the producer; not in the account registry · ${d.ref}`
    case 'served': return `served name without registry provenance · ${d.ref}`
    default: return `no usable name served · stable reference ${d.ref} shown`
  }
}
