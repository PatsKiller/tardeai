// Migration board projection (GET /api/v2/coordination/migration-board) → page model. Pure, testable.
// 2026-10-08 n8n scheduler-of-record program, stream G: per lane the scheduler of record, phase
// (NOT_STARTED → SHADOW → CANARY → CUT_OVER | ROLLED_BACK), last run, output-signal age, readiness
// and risk flags, as written by scripts/n8n_migration_board.py. Read-only: nothing here cuts over.
import type { Tone } from './designTokens'

export type MigrationPhase = 'NOT_STARTED' | 'SHADOW' | 'CANARY' | 'CUT_OVER' | 'ROLLED_BACK'
export const MIGRATION_PHASES: MigrationPhase[] = ['NOT_STARTED', 'SHADOW', 'CANARY', 'CUT_OVER', 'ROLLED_BACK']

export interface MigrationLastRun {
  run_id?: string | null
  mode?: string | null
  state?: string | null
  exit_code?: number | null
  duration_s?: number | null
  finished_at?: string | null
}

export interface MigrationLane {
  lane_id?: string
  tranche?: string
  registry_row?: boolean
  registry_state?: string | null
  scheduler_of_record?: string
  phase?: MigrationPhase | string
  run_count?: number
  last_run?: MigrationLastRun | null
  expected_cadence_hours?: number | null
  output_signal_age_h?: number | null
  rollback_ready?: boolean
  readiness?: string | null
  readiness_reasons?: string[]
  risk_flags?: string[]
  note?: string | null
}

export interface MigrationBoardPayload {
  schema?: string
  as_of?: string | null
  status?: 'OK' | 'NO_BOARD' | string
  note?: string
  lane_count?: number
  sources?: Record<string, unknown>
  summary?: {
    per_tranche?: Record<string, { lanes?: number; by_phase?: Record<string, number>; risks?: number; no_registry_row?: number }>
    by_phase?: Record<string, number>
    open_risks?: Array<{ lane_id?: string; tranche?: string; flag?: string; phase?: string }>
    open_risk_count?: number
    no_registry_row?: number
  }
  lanes?: MigrationLane[]
}

export interface MigrationRow {
  key: string
  tranche: string
  lane: string
  scheduler: string
  phase: string
  phaseTone: Tone
  lastRun: string
  lastRunTone: Tone
  signalAgeLabel: string
  signalAgeHours: number | null
  signalStale: boolean
  readiness: string
  readinessTone: Tone
  rollbackReady: boolean
  risks: string[]
  riskLabel: string
  registryRow: boolean
  note: string
}

export interface TrancheCount { tranche: string; lanes: number; cutOver: number; risks: number; tone: Tone }

export interface MigrationBoardModel {
  status: 'OK' | 'NO_BOARD' | 'UNAVAILABLE'
  statusLabel: string
  statusTone: Tone
  asOfLabel: string
  note: string
  byPhase: Array<{ phase: string; n: number; tone: Tone }>
  tranches: TrancheCount[]
  openRiskCount: number
  noRegistryRow: number
  rows: MigrationRow[]
}

export function toneForPhase(phase: string): Tone {
  switch (phase) {
    case 'CUT_OVER': return 'success'
    case 'CANARY': return 'info'
    case 'SHADOW': return 'ai'
    case 'ROLLED_BACK': return 'danger'
    default: return 'neutral'
  }
}

export function toneForRunState(state: string | null | undefined): Tone {
  switch (state) {
    case 'RUN_DONE': return 'success'
    case 'RUNNING': case 'REQUESTED': return 'info'
    case 'RUN_SKIPPED_LOCK': return 'warning'
    case 'RUN_FAILED': case 'RUN_TIMEOUT': case 'RUN_REFUSED': return 'danger'
    default: return 'neutral'
  }
}

export function toneForReadiness(verdict: string | null | undefined): Tone {
  switch (verdict) {
    case 'GO': return 'success'
    case 'GO_WITH_NOTES': return 'warning'
    case 'NO_GO': return 'danger'
    default: return 'neutral'
  }
}

export function signalAgeLabel(hours: number | null | undefined): string {
  if (typeof hours !== 'number' || !Number.isFinite(hours)) return 'unverified'
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 48) return `${hours.toFixed(1)} h`
  return `${(hours / 24).toFixed(1)} d`
}

export function lastRunLabel(run: MigrationLastRun | null | undefined): string {
  if (!run || !run.state) return 'no run'
  const bits = [run.mode ?? '?', run.state]
  if (typeof run.exit_code === 'number') bits.push(`exit ${run.exit_code}`)
  if (typeof run.duration_s === 'number') bits.push(`${run.duration_s.toFixed(1)} s`)
  return bits.join(' · ')
}

export function projectMigrationBoard(payload: MigrationBoardPayload | null | undefined): MigrationBoardModel {
  if (!payload || typeof payload !== 'object') {
    return {
      status: 'UNAVAILABLE', statusLabel: 'UNAVAILABLE', statusTone: 'danger', asOfLabel: 'UNDATED',
      note: 'the board did not answer', byPhase: [], tranches: [], openRiskCount: 0, noRegistryRow: 0, rows: [],
    }
  }
  const status: MigrationBoardModel['status'] = payload.status === 'OK' ? 'OK' : payload.status === 'NO_BOARD' ? 'NO_BOARD' : 'UNAVAILABLE'
  const lanes = Array.isArray(payload.lanes) ? payload.lanes : []
  const rows: MigrationRow[] = lanes.map(l => {
    const phase = String(l.phase ?? 'NOT_STARTED')
    const risks = (l.risk_flags ?? []).map(String)
    const age = typeof l.output_signal_age_h === 'number' ? l.output_signal_age_h : null
    const cadence = typeof l.expected_cadence_hours === 'number' ? l.expected_cadence_hours : null
    return {
      key: `${l.tranche ?? '?'}:${l.lane_id ?? '?'}`,
      tranche: String(l.tranche ?? ''), lane: String(l.lane_id ?? ''),
      scheduler: String(l.scheduler_of_record ?? 'unregistered'),
      phase, phaseTone: toneForPhase(phase),
      lastRun: lastRunLabel(l.last_run), lastRunTone: toneForRunState(l.last_run?.state),
      signalAgeLabel: signalAgeLabel(age), signalAgeHours: age,
      signalStale: age !== null && cadence !== null && age > 2 * cadence,
      readiness: String(l.readiness ?? ''), readinessTone: toneForReadiness(l.readiness),
      rollbackReady: l.rollback_ready === true,
      risks, riskLabel: risks.join(', '),
      registryRow: l.registry_row !== false,
      note: String(l.note ?? ''),
    }
  })
  const byPhaseRaw = payload.summary?.by_phase ?? {}
  const byPhase = MIGRATION_PHASES.map(p => ({ phase: p, n: Number(byPhaseRaw[p] ?? 0), tone: toneForPhase(p) }))
  const tranches: TrancheCount[] = Object.entries(payload.summary?.per_tranche ?? {})
    .map(([tranche, t]): TrancheCount => {
      const risks = Number(t?.risks ?? 0)
      const cutOver = Number(t?.by_phase?.CUT_OVER ?? 0)
      const lanesN = Number(t?.lanes ?? 0)
      return { tranche, lanes: lanesN, cutOver, risks, tone: risks > 0 ? 'danger' : cutOver === lanesN && lanesN > 0 ? 'success' : cutOver > 0 ? 'info' : 'neutral' }
    })
    .sort((a, b) => a.tranche.localeCompare(b.tranche))
  const openRiskCount = Number(payload.summary?.open_risk_count ?? (payload.summary?.open_risks ?? []).length)
  return {
    status,
    statusLabel: status === 'OK' ? `OK · ${payload.lane_count ?? rows.length} lanes` : status === 'NO_BOARD' ? 'NO BOARD' : status,
    statusTone: status === 'OK' ? (openRiskCount > 0 ? 'warning' : 'success') : status === 'NO_BOARD' ? 'warning' : 'danger',
    asOfLabel: payload.as_of ? String(payload.as_of).slice(0, 16).replace('T', ' ') : 'UNDATED',
    note: String(payload.note ?? ''),
    byPhase, tranches, openRiskCount,
    noRegistryRow: Number(payload.summary?.no_registry_row ?? rows.filter(r => !r.registryRow).length),
    rows,
  }
}
