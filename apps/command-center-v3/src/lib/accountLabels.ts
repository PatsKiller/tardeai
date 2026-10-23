// accountLabels — the one short human name for each account (operator 2026-10-23).
//
// "you need to actually put which account right here. Like, for example, there are two SpaceX and two
//  different accounts." … "just a name, not the account numbers."
//
// NAMES ONLY. Never an account number, never masked digits. The map mirrors
// config/account_display_names.json (tests/test_account_display_labels_20261023.py asserts they agree);
// a server-sent `account_label` wins when it is digit-free.

export const UNLABELLED = 'Unlabelled account'

export const ACCOUNT_ALIASES: Record<string, string> = {
  schwab_roth: 'schwab_roth_ira',
  schwab_individual: 'schwab_taxable',
  alpaca_paper: 'tradeai_automated',
}

export const ACCOUNT_NAMES: Record<string, string> = {
  schwab_rollover_ira: 'Schwab Rollover IRA',
  schwab_roth_ira: 'Schwab Roth IRA',
  schwab_taxable: 'Schwab Individual',
  fidelity_rollover_ira: 'Fidelity Rollover IRA',
  alpaca_taxable_live: 'Alpaca Individual',
  alpaca_ira_live: 'Alpaca IRA',
  moomoo_taxable_live: 'moomoo Taxable',
  tradeai_automated: 'Alpaca Paper',
}

/** True when text would leak an account number: a run of 3+ digits or a masked tail (…258, ··1234, **12). */
export function looksLikeAccountNumber(text: unknown): boolean {
  const s = String(text ?? '')
  return /\d{3,}/.test(s) || /(\.\.\.|··|…|\*\*|xx)\s*\w*\d/i.test(s)
}

export function canonicalAccountKey(raw: unknown): string {
  const k = String(raw ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_')
  return ACCOUNT_ALIASES[k] ?? k
}

/** The short human name for an account key (or a digit-free server label). Never an account number. */
export function accountName(raw: unknown, serverLabel?: unknown): string {
  if (serverLabel != null && String(serverLabel).trim() && !looksLikeAccountNumber(serverLabel)) return String(serverLabel).trim()
  const key = canonicalAccountKey(raw)
  if (!key) return UNLABELLED
  const known = ACCOUNT_NAMES[key]
  if (known) return known
  if (looksLikeAccountNumber(key)) return UNLABELLED
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/\bIra\b/g, 'IRA')
}

/** The account key of a row, from the usual fields (account_id, account, account_key …), digit-free only. */
export function rowAccountKey(row: any): string {
  for (const f of ['account_id', 'account', 'account_key', 'accountId', 'broker_account']) {
    const v = row?.[f]
    if (v != null && String(v).trim() && !looksLikeAccountNumber(v)) return canonicalAccountKey(v)
  }
  return ''
}

/** The label to print beside a row. */
export function rowAccountName(row: any): string {
  const key = rowAccountKey(row)
  return key || row?.account_label ? accountName(key, row?.account_label) : UNLABELLED
}

export interface AccountPart<T> { account: string; label: string; row: T }
export interface SymbolGroup<T> { sym: string; parts: AccountPart<T>[]; multi: boolean }

/** Group rows (one per account holding) by symbol, keeping every account part. Never drops the account:
 *  a symbol in two accounts is one group with two labelled parts and `multi: true`. Order of first sight. */
export function groupBySymbol<T>(rows: T[], symOf: (r: T) => string, acctOf: (r: T) => string = rowAccountKey): SymbolGroup<T>[] {
  const out = new Map<string, SymbolGroup<T>>()
  for (const r of rows || []) {
    const sym = String(symOf(r) ?? '').trim().toUpperCase()
    if (!sym) continue
    const account = acctOf(r)
    const g = out.get(sym) ?? { sym, parts: [], multi: false }
    g.parts.push({ account, label: accountName(account, (r as any)?.account_label), row: r })
    g.multi = new Set(g.parts.map(p => p.account || p.label)).size >= 2
    out.set(sym, g)
  }
  return [...out.values()]
}

/** Symbols held in two or more accounts → their account keys. */
export function multiAccountSymbols(rows: any[], symField = 'symbol'): Map<string, string[]> {
  const m = new Map<string, string[]>()
  for (const r of rows || []) {
    const sym = String(r?.[symField] ?? '').trim().toUpperCase()
    const a = rowAccountKey(r)
    if (!sym || !a) continue
    const list = m.get(sym) ?? []
    if (!list.includes(a)) list.push(a)
    m.set(sym, list)
  }
  for (const [k, v] of [...m]) if (v.length < 2) m.delete(k)
  return m
}

/** "2 accounts" badge text. */
export function accountsBadge(n: number): string {
  return `${n} account${n === 1 ? '' : 's'}`
}
