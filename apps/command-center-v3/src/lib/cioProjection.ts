/**
 * Read-only view helpers for CIO projection blocks (brain sub-projections,
 * office-home blocks, product health, thesis & delegation).
 *
 * Every label shown is copied from the payload. Nothing here infers a state:
 * a block without a state field says so (NOT_IN_PAYLOAD) instead of being
 * called OK/LIVE, and a missing clock stays missing.
 */

export const NOT_IN_PAYLOAD = 'NOT_IN_PAYLOAD'

/** Payload fields that carry a state/status label, in display order. */
const STATE_FIELDS = [
  'state', 'status', 'truth_quality', 'evidence_class', 'runtime_state', 'maturity', 'verdict',
  'freshness', 'mode', 'lane_state',
] as const

/** Payload clock fields, in display order. */
const CLOCK_FIELDS = ['source_as_of', 'composition_as_of', 'as_of', 'generated_at', 'updated_at'] as const

export type ProjectionLabels = {
  schema: string
  states: Array<[string, string]>
  clocks: Array<[string, string]>
  ok: boolean | null
  error: string | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

/** Labels straight from the block: schema, every state-like field, every clock, ok/error. */
export function projectionLabels(block: unknown): ProjectionLabels {
  if (!isRecord(block)) {
    return { schema: NOT_IN_PAYLOAD, states: [], clocks: [], ok: null, error: null }
  }
  const states: Array<[string, string]> = []
  for (const key of STATE_FIELDS) {
    const v = block[key]
    if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') states.push([key, String(v)])
  }
  const clocks: Array<[string, string]> = []
  for (const key of CLOCK_FIELDS) {
    const v = block[key]
    if (typeof v === 'string' && v) clocks.push([key, v])
  }
  const schema = typeof block.schema === 'string' ? block.schema
    : typeof block.schema_version === 'string' ? block.schema_version
      : NOT_IN_PAYLOAD
  const ok = typeof block.ok === 'boolean' ? block.ok : null
  const error = typeof block.error === 'string' ? block.error : null
  return { schema, states, clocks, ok, error }
}

const SKIP_FACT_KEYS = new Set<string>([
  'schema', 'schema_version', 'ok', 'error', 'authority', ...STATE_FIELDS, ...CLOCK_FIELDS,
])

/** Compact facts: scalars verbatim, arrays as "n items", objects as "n fields". */
export function projectionFacts(block: unknown, limit = 12): Array<[string, string]> {
  if (!isRecord(block)) return []
  const out: Array<[string, string]> = []
  for (const [key, value] of Object.entries(block)) {
    if (SKIP_FACT_KEYS.has(key)) continue
    if (value === null || value === undefined) out.push([key, 'null'])
    else if (Array.isArray(value)) out.push([key, `${value.length} item${value.length === 1 ? '' : 's'}`])
    else if (typeof value === 'object') out.push([key, `${Object.keys(value as object).length} fields`])
    else {
      const text = String(value)
      out.push([key, text.length > 140 ? `${text.slice(0, 137)}…` : text])
    }
    if (out.length >= limit) break
  }
  return out
}

/** First rows of a list field, each rendered from the row's own label-ish fields. */
export function projectionRows(rows: unknown, limit = 8): string[] {
  if (!Array.isArray(rows)) return []
  return rows.slice(0, limit).map((row) => {
    if (row === null || row === undefined) return 'null'
    if (typeof row !== 'object') return String(row)
    const r = row as Record<string, unknown>
    const head = r.symbol ?? r.title ?? r.name ?? r.label ?? r.id ?? r.plan_id ?? r.lesson_id ?? r.field ?? r.key
    const tail = r.state ?? r.status ?? r.verdict ?? r.summary ?? r.reason ?? r.claim
    const parts = [head, tail].filter((x) => x !== undefined && x !== null && x !== '').map(String)
    return parts.length ? parts.join(' · ') : JSON.stringify(row).slice(0, 140)
  })
}

/** Human status line for a fetch: never an endless spinner. */
export function loadLine(opts: { loading: boolean; error: string | null; hasData: boolean }): string | null {
  if (opts.hasData) return null
  if (opts.error) return `UNAVAILABLE — ${opts.error}`
  if (opts.loading) return 'Loading…'
  return 'NO PAYLOAD'
}
