/** Plain-English names for the Hermes research overview (FQ-039).
 *
 * The overview is an operator surface: it says what the research system found and what that
 * prevents. Internal keys (finding types, table names, script names, endpoints) are still
 * available — in a `<details>` block or a `title` — never as the only label.
 *
 * An unknown key is never shown raw: `humanize` turns `some_new_type` into "Some new type" so a
 * future producer cannot leak an underscore key into the normal view.
 *
 * FQ-039 R2 (codex, P2607-R2): the lookups are `Map`s, not object literals. An object answers `__proto__`,
 * `constructor` and `toString` from Object.prototype, so an unknown key could return a function and React refused
 * to render it — a producer's new key could crash the page. A Map has no prototype chain: only the names entered
 * below resolve; everything else humanises.
 */

const FINDING_TYPES = new Map<string, string>([
  ['unsupported_thesis', 'Thesis not yet supported by evidence'],
  ['weak_evidence', 'Evidence is weak'],
  ['stale_data', 'Data went stale'],
  ['conflicting_data', 'Sources disagree'],
  ['missing_data', 'Data is missing'],
  ['low_confidence', 'Low confidence'],
  ['review_required', 'Needs a review'],
])

const SEVERITIES = new Map<string, string>([
  ['critical', 'Critical'],
  ['error', 'Error'],
  ['warning', 'Warning'],
  ['warn', 'Warning'],
  ['info', 'Note'],
  ['trend', 'Trend'],
  ['advisory', 'Advisory'],
])

const STAGING_TABLES = new Map<string, string>([
  ['hermes_research_intelligence', 'Research rows'],
  ['hermes_validation_findings', 'Validation findings'],
  ['hermes_alerts', 'Alerts'],
  ['hermes_memory_events', 'Memory events'],
  ['hermes_research_backlog', 'Backlog items'],
])

/** `some_key_here` → `Some key here`. Never returns an underscore or a bare identifier. */
export function humanize(key: string | null | undefined): string {
  const text = String(key ?? '').replace(/[_-]+/g, ' ').trim()
  if (!text) return 'Unknown'
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function findingTypeLabel(key: string | null | undefined): string {
  const raw = String(key ?? '').trim()
  return FINDING_TYPES.get(raw) ?? humanize(raw)
}

export function severityLabel(key: string | null | undefined): string {
  const raw = String(key ?? '').trim().toLowerCase()
  return SEVERITIES.get(raw) ?? humanize(raw || 'unknown')
}

export function stagingTableLabel(key: string | null | undefined): string {
  const raw = String(key ?? '').trim()
  return STAGING_TABLES.get(raw) ?? humanize(raw.replace(/^hermes_/, ''))
}

/** Count with thousands separators, or an em dash when the count is not known. */
export function countText(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-US') : '—'
}
