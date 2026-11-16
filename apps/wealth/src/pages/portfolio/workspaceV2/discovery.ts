// Portfolio audit 2026-11-16 (B, C): discoverability and normalized protection for the Holdings workspace.
//
// Pure functions over the workspace view model; no arithmetic on money and no new population. The workspace
// collapses small (< $100, no material loss) securities and cash into summary groups. That rule stays, but a
// collapsed row must never be unfindable:
//   * `hv_show=all` expands every display group, so each security and cash line is rendered.
//   * A non-empty search reveals the collapsed groups that contain a match (substring, same rule as selectRows).
//   * The disclosure line counts total, matching, filtered-out, visible and collapsed rows and names the collapsed
//     securities, so "where did NVDA go" has an on-screen answer.
// Protection (C): the raw producer state PROTECTED covers recorded stops that are pending, undated or stale. The
// filter therefore works on ONE normalized class per row, derived with the same rule protectionSummary uses for
// "active", and a parent whose accounts disagree says so with counts.

import type { HoldingsRow } from '../contract'
import type { Group } from './adapter'

export type ProtectionClass = 'active' | 'pending' | 'stale' | 'gap' | 'unknown' | 'n/a'

export const PROTECTION_CLASSES: { value: ProtectionClass; label: string }[] = [
  { value: 'active', label: 'Active · verified current' },
  { value: 'pending', label: 'Pending · recorded, not yet active' },
  { value: 'stale', label: 'Stale or unverified record' },
  { value: 'gap', label: 'Gap · no stop reported' },
  { value: 'unknown', label: 'Unknown' },
  { value: 'n/a', label: 'Not applicable (cash)' },
]

const LEGACY: Record<string, ProtectionClass> = {
  // Old links keep working, but a legacy `PROTECTED` link now means verified-active only: it was the filter that
  // returned eight rows that each displayed "Recorded · pending or not current".
  PROTECTED: 'active', GAP: 'gap', UNKNOWN: 'unknown', 'not-applicable': 'n/a',
}

/** Map a URL filter value (normalized or legacy raw state) to a class, or '' for no filter. */
export function protectionFilterValue(raw: string): ProtectionClass | '' {
  if (!raw) return ''
  if (PROTECTION_CLASSES.some(c => c.value === raw)) return raw as ProtectionClass
  return LEGACY[raw] ?? ''
}

/** One class per row. Only a dated, current, non-pending recorded stop above zero is `active`. */
export function protectionClass(r: HoldingsRow): ProtectionClass {
  if (r.kind === 'CASH') return 'n/a'
  const p = r.protection
  if (!p) return 'unknown'
  if (p.state === 'GAP') return 'gap'
  if (p.state !== 'PROTECTED') return 'unknown'
  const pendingText = /pending|activation/i.test((p.reason ?? '') + ' ' + (p.nextStep ?? ''))
  const dated = p.asOf !== null && Number.isFinite(Date.parse(p.asOf))
  const priced = p.stop !== null && Number.isFinite(p.stop) && p.stop > 0
  if (p.stale === true || !dated || p.stale !== false) return pendingText ? 'pending' : 'stale'
  if (pendingText || !priced) return 'pending'
  return 'active'
}

/** Empty = no filter. An unrecognized non-empty value matches nothing (fail closed, never "all rows"). */
export function matchesProtection(r: HoldingsRow, raw: string): boolean {
  if (!raw) return true
  const want = protectionFilterValue(raw)
  return want !== '' && protectionClass(r) === want
}

/** Counts per class for a set of account rows; `mixed` when more than one applicable class is present. */
export function protectionMix(rows: HoldingsRow[]) {
  const counts = new Map<ProtectionClass, number>()
  for (const r of rows) counts.set(protectionClass(r), (counts.get(protectionClass(r)) ?? 0) + 1)
  const applicable = [...counts.keys()].filter(c => c !== 'n/a')
  const order: ProtectionClass[] = ['active', 'pending', 'stale', 'gap', 'unknown']
  const parts = order.filter(c => counts.has(c)).map(c => `${counts.get(c)} ${c}`)
  const byAccount = rows.filter(r => r.kind !== 'CASH').map(r => `${r.accountLabel}: ${protectionClass(r)}`)
  return { counts, mixed: applicable.length > 1, label: applicable.length > 1 ? 'Mixed · ' + parts.join(' · ') : null, byAccount }
}

// ---- B: discoverability -----------------------------------------------------------------------------------------

/** `hv_show=all` — the only accepted value; anything else is the default collapsed view. */
export function showAllFrom(p: URLSearchParams): boolean {
  return p.get('hv_show') === 'all'
}
export function withShowAll(p: URLSearchParams, on: boolean): URLSearchParams {
  const n = new URLSearchParams(p)
  if (on) n.set('hv_show', 'all')
  else n.delete('hv_show')
  return n
}

/** Groups whose own rows are hidden until expanded (summary sections and multi-account securities). */
const collapsible = (g: Group) => g.kind === 'small' || g.kind === 'cash' || (g.kind === 'security' && g.children.length > 1)

/** Every expandable key: what Show all opens. */
export function allGroupKeys(groups: Group[]): string[] {
  return groups.filter(collapsible).map(g => g.key)
}

/** Collapsed summary sections that contain a search match; a search must reveal the row, not just count it. */
export function queryRevealKeys(groups: Group[], query: string): string[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  const hit = (r: HoldingsRow) => [r.symbol, r.name ?? '', r.accountLabel].some(s => s.toLowerCase().includes(q))
  return groups.filter(g => (g.kind === 'small' || g.kind === 'cash') && g.rows.some(hit)).map(g => g.key)
}

export interface Disclosure {
  /** Account rows in the book (all accounts, no filters). */
  total: number
  /** Account rows that pass the filters. */
  matching: number
  /** Removed by filters (total − matching). */
  filteredOut: number
  /** Matching rows rendered as their own line or inside an open group. */
  visible: number
  /** Matching rows only summarized inside a closed Small / Cash section. */
  collapsed: number
  /** Distinct symbols in closed summary sections, so the hidden names are on screen. */
  collapsedSymbols: string[]
}

export function disclosure(totalRows: number, groups: Group[], expanded: ReadonlySet<string>): Disclosure {
  let matching = 0, collapsed = 0
  const hidden = new Set<string>()
  for (const g of groups) {
    matching += g.rows.length
    if ((g.kind === 'small' || g.kind === 'cash') && !expanded.has(g.key)) {
      collapsed += g.rows.length
      for (const r of g.rows) hidden.add(r.symbol)
    }
  }
  return {
    total: totalRows, matching, filteredOut: totalRows - matching, visible: matching - collapsed, collapsed,
    collapsedSymbols: [...hidden].sort(),
  }
}

export function disclosureText(d: Disclosure): string {
  const parts = [`${d.matching} of ${d.total} account rows match`]
  if (d.filteredOut) parts.push(`${d.filteredOut} filtered out`)
  parts.push(`${d.visible} shown`)
  if (d.collapsed) parts.push(`${d.collapsed} collapsed (${d.collapsedSymbols.join(', ')})`)
  return parts.join(' · ')
}
