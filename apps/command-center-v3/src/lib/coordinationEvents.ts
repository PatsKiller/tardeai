// Coordination projection (GET /api/v2/coordination/events) → page model. Pure, testable.
// 2026-10-07 roadmap Phase 1: the operator's "what is waiting" view. The ledger is written by the
// Trade AI gateway; n8n and the dispatcher only coordinate. Nothing here mutates anything.
import type { Tone } from './designTokens'
import type { TransportState } from './observationEnvelope'

export type CoordinationState =
  | 'EXPECTED' | 'ACCEPTED' | 'CLAIMED' | 'STARTED' | 'ARTIFACT_WRITTEN' | 'CONSUMED'
  | 'REFUSED' | 'FAILED' | 'CANCELLED' | 'EXPIRED' | 'SUPPRESSED' | 'SUPERSEDED' | 'DEAD_LETTER'

export interface CoordinationReceipt {
  state?: string
  reason?: string | null
  lane_id?: string
  event_id?: string
  idempotency_key?: string
  recorded_at?: number | string | null
  origin_sha?: string
  consumer?: string | null
  consumer_receipt_id?: string | null
  artifact_ref?: { store?: string; ref?: string; sha256?: string; as_of?: string } | string | null
  /** Projection historically used `artifact`; keep both. */
  artifact?: { store?: string; ref?: string; sha256?: string; as_of?: string } | string | null
  durable?: boolean
  duplicate?: boolean
  wave_b?: boolean
}

export interface CoordinationSpotlight {
  lane_id?: string
  source?: string
  as_of?: string | null
  mode?: string | null
  gateway_state?: string | null
  ok?: boolean | null
  summary?: string
  age_s?: number | null
  path?: string
  status?: string
  idempotency_key?: string
  event_id?: string
}

export interface CoordinationPayload {
  schema?: string
  as_of?: string | null
  ledger?: string | null
  items?: CoordinationReceipt[]
  count?: number | null
  total_count?: number | null
  summary?: { by_state?: Record<string, number>; by_lane?: Record<string, number> } | null
  coverage?: { aggregation_complete?: boolean; items_truncated?: boolean; scope?: string; since?: string | null; through?: string | null }
  last_good_at?: string | null
  status?: 'OK' | 'NO_LEDGER' | string
  note?: string
  wave_b_lanes?: string[]
  wave_b_run_lanes?: string[]
  spotlights?: CoordinationSpotlight[]
}

/** Wave B CC orchestrate lanes — Coordination receipt polish. */
export const WAVE_B_LANES = ['research-intake', 'watch-refresh', 'incident-fanin'] as const

export interface CoordinationRow {
  key: string
  state: string
  tone: Tone
  phase: 'waiting' | 'in progress' | 'artifact' | 'consumed' | 'refused' | 'failed' | 'other'
  lane: string
  eventId: string
  reason: string
  consumer: string
  recordedAt: string | null
  ageMinutes: number | null
  originSha: string
  artifact: string
  durable: boolean
}

export interface CoordinationSpotlightRow {
  lane: string
  source: string
  summary: string
  asOf: string | null
  ageMinutes: number | null
  tone: Tone
}

export interface CoordinationModel {
  status: 'OK' | 'NO_LEDGER' | 'UNAVAILABLE' | 'STALE' | 'PARTIAL'
  statusLabel: string
  statusTone: Tone
  asOf: string | null
  asOfLabel: string
  note: string
  rows: CoordinationRow[]
  counts: Record<CoordinationRow['phase'], number | null>
  countsAvailable: boolean
  coverageLabel: string
  totalCount: number | null
  lastGoodAgeMinutes: number | null
  transportLabel: string | null
  spotlights: CoordinationSpotlightRow[]
  waveBLanes: string[]
  laneCounts: Record<string, number>
}

const PHASE: Record<string, CoordinationRow['phase']> = {
  EXPECTED: 'waiting', ACCEPTED: 'waiting', CLAIMED: 'in progress', STARTED: 'in progress',
  ARTIFACT_WRITTEN: 'artifact', CONSUMED: 'consumed', REFUSED: 'refused',
  FAILED: 'failed', DEAD_LETTER: 'failed', EXPIRED: 'failed',
  CANCELLED: 'other', SUPPRESSED: 'other', SUPERSEDED: 'other',
}

export function toneForState(state: string): Tone {
  switch (state) {
    case 'CONSUMED': return 'success'
    case 'ARTIFACT_WRITTEN': return 'info'
    case 'CLAIMED': case 'STARTED': return 'warning'
    case 'EXPECTED': case 'ACCEPTED': return 'neutral'
    case 'REFUSED': case 'FAILED': case 'DEAD_LETTER': case 'EXPIRED': return 'danger'
    default: return 'neutral'
  }
}

export function phaseForState(state: string): CoordinationRow['phase'] {
  return PHASE[state] ?? 'other'
}

function isoFromRecorded(v: number | string | null | undefined): string | null {
  if (v === null || v === undefined || v === '') return null
  if (typeof v === 'number' && Number.isFinite(v)) return new Date(v * 1000).toISOString()
  const d = new Date(String(v))
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

function artifactLabel(a: CoordinationReceipt['artifact_ref'] | CoordinationReceipt['artifact']): string {
  if (!a) return ''
  if (typeof a === 'string') return a
  const store = a.store ?? ''
  const ref = a.ref ?? ''
  return store && ref ? `${store}:${ref}` : (ref || store)
}

export function toRow(r: CoordinationReceipt, nowMs: number, index = 0): CoordinationRow {
  const state = String(r.state ?? 'UNKNOWN')
  const recordedAt = isoFromRecorded(r.recorded_at)
  const age = recordedAt ? Math.max(0, Math.round((nowMs - new Date(recordedAt).getTime()) / 60000)) : null
  return {
    key: String(r.idempotency_key ?? r.event_id ?? `unidentified:${r.lane_id ?? ''}:${r.state ?? ''}:${r.recorded_at ?? ''}:${index}`),
    state,
    tone: toneForState(state),
    phase: phaseForState(state),
    lane: String(r.lane_id ?? ''),
    eventId: String(r.event_id ?? ''),
    reason: r.reason ? String(r.reason) : '',
    consumer: r.consumer ? `${r.consumer}${r.consumer_receipt_id ? ` · ${r.consumer_receipt_id}` : ''}` : '',
    recordedAt,
    ageMinutes: age,
    originSha: String(r.origin_sha ?? '').slice(0, 9),
    artifact: artifactLabel(r.artifact_ref ?? r.artifact),
    durable: r.durable === true,
  }
}

function spotlightTone(s: CoordinationSpotlight): Tone {
  if (s.status === 'STALE') return 'warning'
  if (s.status === 'UNAVAILABLE') return 'danger'
  const gs = String(s.gateway_state || '')
  if (s.ok === false || gs === 'REFUSED' || gs === 'FAILED') return 'danger'
  if (gs === 'ACCEPTED' || gs === 'CONSUMED' || s.ok === true) return 'success'
  if (gs === 'DRY_RUN') return 'info'
  return 'neutral'
}

export function projectCoordination(
  data: CoordinationPayload | null | undefined,
  opts: { transport?: TransportState; stale?: boolean; error?: boolean; nowMs?: number; laneFilter?: string | null } = {},
): CoordinationModel {
  const nowMs = opts.nowMs ?? Date.now()
  const counts: CoordinationModel['counts'] = { waiting: null, 'in progress': null, artifact: null, consumed: null, refused: null, failed: null, other: null }
  const knownVersion = !data?.schema || ['N8nCoordinationProjection@v1', 'N8nCoordinationProjection@v2'].includes(data.schema)
  const allRows = knownVersion && Array.isArray(data?.items) ? data.items.map((r, i) => toRow(r, nowMs, i)) : []
  const asOf = typeof data?.as_of === 'string' && Number.isFinite(Date.parse(data.as_of)) ? data.as_of : null
  const age = asOf ? (nowMs - Date.parse(asOf)) / 60_000 : null
  const failed = !!opts.error || opts.transport === 'ERROR'
  const stale = !!opts.stale || (data?.schema === 'N8nCoordinationProjection@v2' && (age == null || age < 0 || age > 3))
  let status: CoordinationModel['status'] = !data || !knownVersion ? 'UNAVAILABLE'
    : failed || stale ? (data ? 'STALE' : 'UNAVAILABLE')
    : data.status === 'OK' ? 'OK' : data.status === 'PARTIAL' ? 'PARTIAL' : data.status === 'NO_LEDGER' ? 'NO_LEDGER' : 'UNAVAILABLE'
  const countsAvailable = !failed && !stale && (status === 'OK' || status === 'PARTIAL')
  const laneCounts: Record<string, number> = {}
  let totalCount: number | null = null
  let coverageLabel = 'Source unavailable; totals unknown'
  if (countsAvailable) {
    for (const phase of Object.keys(counts)) counts[phase as CoordinationRow['phase']] = 0
    const summary = data?.summary
    const full = data?.schema === 'N8nCoordinationProjection@v2' && data.coverage?.aggregation_complete === true
      && typeof data.total_count === 'number' && Number.isSafeInteger(data.total_count) && data.total_count >= allRows.length
      && summary?.by_state && Object.values(summary.by_state).every(n => Number.isSafeInteger(n) && n >= 0)
      && Object.values(summary.by_state).reduce((a, b) => a + b, 0) === data.total_count
    if (full) {
      totalCount = data!.total_count!
      for (const [state, n] of Object.entries(summary!.by_state!)) {
        const phase = phaseForState(state); counts[phase] = (counts[phase] ?? 0) + n
      }
      Object.assign(laneCounts, summary?.by_lane ?? {})
      coverageLabel = `All ${totalCount} retained ledger rows; ${allRows.length} details shown${data?.coverage?.items_truncated ? ' (limited)' : ''}. Observed bounds ${data?.coverage?.since ?? 'empty'} → ${data?.coverage?.through ?? 'empty'}; no 24h filter.`
    } else if (data?.schema !== 'N8nCoordinationProjection@v2') {
      for (const row of allRows) { counts[row.phase] = (counts[row.phase] ?? 0) + 1; if (row.lane) laneCounts[row.lane] = (laneCounts[row.lane] || 0) + 1 }
      coverageLabel = `Legacy sample: ${allRows.length} returned rows only; full totals and aggregation window unavailable.`
    } else {
      for (const phase of Object.keys(counts)) counts[phase as CoordinationRow['phase']] = null
      status = 'PARTIAL'; coverageLabel = 'Aggregate coverage unavailable or inconsistent; totals unknown.'
    }
  }
  // Retained successful snapshots may predate last_good_at; failed captures are never proof.
  const last = data?.last_good_at === undefined ? (knownVersion && data?.status === 'OK' ? asOf : null) : data.last_good_at
  const lastGoodAgeMinutes = last && Number.isFinite(Date.parse(last)) && Date.parse(last) <= nowMs ? Math.round((nowMs - Date.parse(last)) / 60_000) : null
  const spotlights: CoordinationSpotlightRow[] = (Array.isArray(data?.spotlights) ? data.spotlights : []).map(s => ({
    lane: String(s.lane_id ?? ''), source: String(s.source ?? ''),
    summary: `${s.status === 'STALE' || s.status === 'UNAVAILABLE' ? s.status + ' · ' : ''}${s.summary ?? ''}`,
    asOf: typeof s.as_of === 'string' ? s.as_of : null,
    ageMinutes: typeof s.age_s === 'number' && Number.isFinite(s.age_s) && s.age_s >= 0 ? Math.round(s.age_s / 60) : null,
    tone: spotlightTone(s),
  }))
  return { status, statusLabel: status === 'NO_LEDGER' ? 'NO LEDGER · UNAVAILABLE' : status,
    statusTone: status === 'OK' ? 'success' : status === 'STALE' || status === 'PARTIAL' || status === 'NO_LEDGER' ? 'warning' : 'danger',
    asOf, asOfLabel: asOf ? `projected ${asOf}` : 'UNDATED', note: data?.note ? String(data.note) : '',
    rows: opts.laneFilter ? allRows.filter(r => r.lane === opts.laneFilter) : allRows,
    counts, countsAvailable: Object.values(counts).every(n => n !== null), coverageLabel, totalCount, lastGoodAgeMinutes,
    transportLabel: failed ? 'ERROR' : stale ? 'STALE · RETAINED' : opts.transport === 'RETAINED' ? 'RETAINED' : null,
    spotlights, waveBLanes: data?.wave_b_lanes?.length ? data.wave_b_lanes.map(String) : [...WAVE_B_LANES], laneCounts }
}
