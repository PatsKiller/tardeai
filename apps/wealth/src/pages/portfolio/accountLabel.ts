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
