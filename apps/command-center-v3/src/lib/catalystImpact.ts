/**
 * Catalyst impact — the model behind the watch card's "Catalyst impact" panel (LQ-20261107-135).
 *
 * Data: GET /api/v3/catalyst/symbol-impact?symbol=&days=90&limit=25
 * Server: scripts/lib/catalyst_impact_reader.py (CatalystSymbolImpact@v1), fed by
 * scripts/catalyst_symbol_impact_writer.py — one row per (catalyst event, symbol), for tracked names.
 *
 * The rule this module exists to keep: an empty answer and an unread answer are different sentences.
 * `no_rows` means the writer has recorded nothing for this symbol; `no_rows_in_window` means it has, but
 * none recently (and names when); a failed read is UNAVAILABLE — never "0 catalysts" and never a zero.
 */

export type CatalystImpactRow = {
  id?: number | null
  symbol?: string | null
  strategy_type?: string | null
  catalyst_type?: string | null
  headline?: string | null
  severity?: string | null
  expected_direction?: string | null
  expected_magnitude?: number | null
  price_at_event?: number | null
  portfolio_impact_pct?: number | null
  impact_score?: number | null
  source_url?: string | null
  event_at?: string | null
  recorded_at?: string | null
}

export type CatalystImpactPayload = {
  ok?: boolean
  schema?: string
  symbol?: string | null
  days?: number
  limit?: number
  status?: 'ok' | 'no_rows_in_window' | 'no_rows' | string
  count?: number
  last_row_at?: string | null
  rows_written_total?: number | null
  note?: string | null
  rows?: CatalystImpactRow[]
  authority?: Record<string, unknown>
}

export type CatalystImpactView =
  | { state: 'loading' }
  | { state: 'unavailable'; sentence: string }
  | { state: 'empty'; sentence: string; detail: string | null }
  | { state: 'rows'; sentence: string; rows: CatalystImpactRow[] }

export type ImpactTone = 'up' | 'down' | 'neutral' | 'unknown'

/** UP / DOWN / NEUTRAL as the writer derives it from the catalyst type. Anything else is unknown, not neutral. */
export function directionTone(direction: string | null | undefined): ImpactTone {
  const d = String(direction ?? '').trim().toUpperCase()
  if (d === 'UP') return 'up'
  if (d === 'DOWN') return 'down'
  if (d === 'NEUTRAL') return 'neutral'
  return 'unknown'
}

/** The event's impact_score as recorded; null stays null (an unrecorded magnitude is not 0). */
export function magnitudeText(row: CatalystImpactRow): string {
  const v = row.expected_magnitude
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(1) : '—'
}

/** Weight of the name in the portfolio, as the writer stored it (0 = not held). */
export function weightText(row: CatalystImpactRow): string {
  const v = row.portfolio_impact_pct
  if (typeof v !== 'number' || !Number.isFinite(v)) return 'weight unknown'
  return v > 0 ? `${v.toFixed(1)}% of portfolio` : 'not held'
}

export function priceText(row: CatalystImpactRow): string {
  const v = row.price_at_event
  return typeof v === 'number' && Number.isFinite(v) ? `$${v.toFixed(2)} at event` : 'price at event unknown'
}

export function dayText(iso: string | null | undefined): string {
  const s = String(iso ?? '')
  // The server sends an ISO timestamp; the panel shows the day, and nothing when it cannot read one.
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${m[1]}-${m[2]}-${m[3]}` : '—'
}

/** One plain sentence per row, for the phone-width card. */
export function describeRow(row: CatalystImpactRow): string {
  const type = String(row.catalyst_type ?? 'catalyst').replace(/_/g, ' ')
  const dir = directionTone(row.expected_direction)
  const dirWord = dir === 'unknown' ? 'direction not recorded' : dir.toUpperCase()
  return `${type} · ${dirWord} · impact ${magnitudeText(row)} · ${weightText(row)}`
}

function countWord(n: number): string {
  return `${n} catalyst${n === 1 ? '' : 's'}`
}

/**
 * The panel's single entry point: turn a payload, an error and a loading flag into exactly one statement.
 * `error` is the useApi error (a transport/HTTP failure) — when present the panel says UNAVAILABLE.
 */
export function impactView(
  payload: CatalystImpactPayload | null | undefined,
  opts: { error?: string | null; loading?: boolean } = {},
): CatalystImpactView {
  if (opts.loading && !payload) return { state: 'loading' }
  if (opts.error) return { state: 'unavailable', sentence: `Catalyst impact unavailable — ${opts.error}` }
  if (!payload || typeof payload !== 'object') return { state: 'unavailable', sentence: 'Catalyst impact unavailable — no answer' }
  const rows = Array.isArray(payload.rows) ? payload.rows.filter(r => r && typeof r === 'object') : []
  if (rows.length > 0) {
    const days = typeof payload.days === 'number' ? payload.days : null
    return {
      state: 'rows',
      sentence: `${countWord(rows.length)} in the last ${days ?? 90} days`,
      rows,
    }
  }
  if (payload.status === 'no_rows_in_window') {
    return {
      state: 'empty',
      sentence: `No catalyst impact recorded in the last ${payload.days ?? 90} days`,
      detail: payload.note || (payload.last_row_at ? `last recorded ${dayText(payload.last_row_at)}` : null),
    }
  }
  if (payload.status === 'no_rows' || payload.ok === true) {
    return {
      state: 'empty',
      sentence: payload.note || 'No catalyst impact has been recorded for this symbol',
      detail: null,
    }
  }
  return { state: 'unavailable', sentence: 'Catalyst impact unavailable — the answer carried no status' }
}
