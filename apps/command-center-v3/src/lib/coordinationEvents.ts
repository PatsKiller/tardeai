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
  idempotency_key?: string
  event_id?: string
}

export interface CoordinationPayload {
  schema?: string
  as_of?: string | null
  ledger?: string | null
  items?: CoordinationReceipt[]
  count?: number
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
  status: 'OK' | 'NO_LEDGER' | 'UNAVAILABLE'
  statusLabel: string
  statusTone: Tone
  asOf: string | null
  asOfLabel: string
  note: string
  rows: CoordinationRow[]
  counts: Record<CoordinationRow['phase'], number>
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

export function toRow(r: CoordinationReceipt, nowMs: number): CoordinationRow {
  const state = String(r.state ?? 'UNKNOWN')
  const recordedAt = isoFromRecorded(r.recorded_at)
  const age = recordedAt ? Math.max(0, Math.round((nowMs - new Date(recordedAt).getTime()) / 60000)) : null
  return {
    key: String(r.idempotency_key ?? r.event_id ?? Math.random()),
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
  const gs = String(s.gateway_state || '')
  if (s.ok === false || gs === 'REFUSED' || gs === 'FAILED') return 'danger'
  if (gs === 'ACCEPTED' || gs === 'CONSUMED' || s.ok === true) return 'success'
  if (gs === 'DRY_RUN') return 'info'
  return 'neutral'
}

export function projectCoordination(
  data: CoordinationPayload | null | undefined,
  opts: { transport?: TransportState; stale?: boolean; nowMs?: number; laneFilter?: string | null } = {},
): CoordinationModel {
  const nowMs = opts.nowMs ?? Date.now()
  const counts: CoordinationModel['counts'] = { waiting: 0, 'in progress': 0, artifact: 0, consumed: 0, refused: 0, failed: 0, other: 0 }
  const transportLabel = opts.transport === 'ERROR' ? 'ERROR'
    : opts.transport === 'RETAINED' ? (opts.stale ? 'STALE · RETAINED' : 'RETAINED')
    : opts.stale ? 'STALE' : null
  const emptySpot: CoordinationSpotlightRow[] = []
  const emptyLanes: Record<string, number> = {}
  if (!data || typeof data !== 'object') {
    return { status: 'UNAVAILABLE', statusLabel: 'UNAVAILABLE', statusTone: 'danger', asOf: null, asOfLabel: 'UNDATED',
      note: 'the projection did not answer; nothing is known about waiting work', rows: [], counts, transportLabel,
      spotlights: emptySpot, waveBLanes: [...WAVE_B_LANES], laneCounts: emptyLanes }
  }
  const allRows = (Array.isArray(data.items) ? data.items : []).map(r => toRow(r, nowMs))
  const laneCounts: Record<string, number> = {}
  for (const row of allRows) {
    counts[row.phase] += 1
    if (row.lane) laneCounts[row.lane] = (laneCounts[row.lane] || 0) + 1
  }
  const filter = opts.laneFilter ? String(opts.laneFilter) : null
  const rows = filter ? allRows.filter(r => r.lane === filter) : allRows
  const status: CoordinationModel['status'] = data.status === 'OK' ? 'OK' : data.status === 'NO_LEDGER' ? 'NO_LEDGER' : 'UNAVAILABLE'
  const statusTone: Tone = status === 'OK' ? 'success' : status === 'NO_LEDGER' ? 'warning' : 'danger'
  const asOf = typeof data.as_of === 'string' && data.as_of ? data.as_of : null
  const waveBLanes = Array.isArray(data.wave_b_lanes) && data.wave_b_lanes.length
    ? data.wave_b_lanes.map(String) : [...WAVE_B_LANES]
  const spotlights: CoordinationSpotlightRow[] = (Array.isArray(data.spotlights) ? data.spotlights : []).map(s => {
    const asOfS = typeof s.as_of === 'string' && s.as_of ? s.as_of : null
    const age = asOfS && s.age_s != null && Number.isFinite(Number(s.age_s))
      ? Math.max(0, Math.round(Number(s.age_s) / 60))
      : (asOfS ? Math.max(0, Math.round((nowMs - new Date(asOfS).getTime()) / 60000)) : null)
    return {
      lane: String(s.lane_id ?? ''),
      source: String(s.source ?? ''),
      summary: String(s.summary ?? ''),
      asOf: asOfS,
      ageMinutes: age,
      tone: spotlightTone(s),
    }
  })
  return {
    status,
    statusLabel: status === 'NO_LEDGER' ? 'NO LEDGER' : status,
    statusTone,
    asOf,
    asOfLabel: asOf ? `projected ${asOf}` : 'UNDATED',
    note: data.note ? String(data.note) : '',
    rows,
    counts,
    transportLabel,
    spotlights,
    waveBLanes,
    laneCounts,
  }
}
