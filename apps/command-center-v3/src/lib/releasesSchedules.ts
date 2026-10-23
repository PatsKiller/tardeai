// Releases & Schedules (operator-approved 2026-10-22) — pure projection of GET /api/v2/ops/releases-schedules
// (scripts/lib/releases_schedules_view.py, contract docs/ops/RELEASES_SCHEDULES_PAGE.md). Every section carries its
// own freshness (as_of, age, source). Rules: an UNAVAILABLE section renders "UNAVAILABLE" with its reason, never 0,
// empty or green; an unknown schema, a failed request or a response older than STALE_AFTER_MS is not current.
import type { Tone } from './designTokens'

export const RELEASES_SCHEDULES_PATH = '/api/v2/ops/releases-schedules'
export const RELEASES_SCHEDULES_SCHEMA = 'ReleasesSchedules@v1'
export const STALE_AFTER_MS = 5 * 60_000

export type Freshness = 'OK' | 'STALE' | 'UNAVAILABLE'
export type Section<T> = { value: T | null; as_of: string | null; freshness: Freshness; source: string; reason: string | null; age_s?: number | null }

export type Kpi = { key: string; label: string; value: string | number | null; detail: string | null; tone: Tone; freshness: Freshness | null; as_of: string | null }
export type Serving = { sha: string; short_sha: string; release_name: string | null; since: string | null; since_basis: string | null; pins_agree: boolean
  pins: Record<string, { value: string | null; matches_current: boolean | null }>
  deploy_receipt: { ok?: boolean; mode?: string; health?: string; at?: string; deployed_sha?: string; readback_errors?: string[] } | null }
export type NextRelease = { sha: string; short_sha: string; subject: string | null; committed_at: string | null; fetched_at: string | null; is_serving: boolean
  commits_ahead: number | null; prs_since_serving: number[] | null; prs_reason: string | null
  ci: { state: 'OK' | 'NOT_GREEN' | 'UNAVAILABLE'; reason: string | null; checks?: number; success?: number; not_success?: Array<{ name?: string; conclusion?: string | null }> } }
export type TrainWindow = { window_id: string; local_time: string; starts_at: string; starts_in_seconds: number; role: string | null; enabled: boolean; note: string | null
  slot: string; state: 'LIVE' | 'SHADOW' | 'OFF' | 'STOPPED'; reason: string | null; last_shadow_request_at: string | null; last_shadow_receipt_state: string | null }
export type Windows = { windows: TrainWindow[]; armed: boolean | null; shadow_enabled: boolean | null; delegation: { state?: string; source?: string } | null
  stop: { state?: string; effective_stop?: boolean } | null; policy_version: string | null; manual_path: string }
export type QueueRow = { pr_number?: number; title?: string | null; state?: string; class?: string | null; census_bucket?: string | null; [k: string]: unknown }
export type OpenPr = { pr: number; title: string | null; bucket: string; why_not_riding: string; riding: boolean }
export type Queue = { store: { freshness?: string; reason?: string | null; as_of?: string | null; total?: number | null; rows?: QueueRow[] | null }
  census: { freshness?: string; reason?: string | null; as_of?: string | null; open_prs?: number | null; status?: string | null }; open_prs: OpenPr[] }
export type ReleaseRow = { receipt: string; mode: string | null; at: string | null; sha: string | null; short_sha?: string | null; sha_basis: string; release_name?: string | null
  serving?: boolean; prs: number[] | null; prs_reason: string | null; verify: { ok?: boolean; health?: string; rolled_back?: boolean; readback_errors?: string[] } | null
  verify_reason: string | null; error?: string }
export type ReleaseError = { at: string | null; kind: string; detail: string; source: string; url?: string | null }
export type LedgerToday = { day: string; total: number; by_mode: Record<string, number>; by_state: Record<string, number>; errors_total: number; skips_total: number
  errors: Array<{ run_id: string; lane: string; mode: string; state: string; at: string | null; exit_code: number | null; reason?: string | null; why?: string | null }>
  lock_skips: Array<{ lane: string; mode: string; count: number; last_at: string | null }>
  busiest: Array<{ lane: string; runs: number; errors: number; skips: number }>
  dead_letters: { available: boolean; unreleased: number | null; recent: Array<{ lane: string; dead_at: string; last_state: string | null; last_reason: string | null }> | null } }
export type TimelineRow = { at: string; lane: string; lane_id: string | null; runner: 'cron' | 'n8n'; schedule: string; stage: string; n8n_stage: string | null
  fires_in_horizon: number; cadence_label: string | null; paused_since: string | null; paused_note: string | null; in_relay_live_list?: boolean | null
  last_run: { at: string | null; state: string; mode: string } | null }
export type Timeline = { horizon_hours: number; from: string; to: string; rows: TimelineRow[]; recurring: TimelineRow[]; rows_total: number; recurring_total: number
  truncated: boolean; crontab: { source: string; error: string | null; active_lines: number; paused_lines: number }; live_lanes: { status: string; count: number | null }; notes: string[] }

export type ReleasesSchedulesWire = {
  schema?: string; generated_at?: string; status?: string; kpis?: Kpi[]
  serving?: Section<Serving>; next_release?: Section<NextRelease>; windows?: Section<Windows>; queue?: Section<Queue>; history?: Section<{ releases: ReleaseRow[]; receipts_total: number }>
  release_errors?: Section<{ rows: ReleaseError[]; window_hours: number; not_covered: string }>; n8n_today?: Section<LedgerToday>; timeline?: Section<Timeline>
  stop?: { state?: string; effective_stop?: boolean; latched_at?: string | null; reason?: string | null }
}

export const SECTION_KEYS = ['serving', 'next_release', 'windows', 'queue', 'history', 'release_errors', 'n8n_today', 'timeline'] as const
export type SectionKey = (typeof SECTION_KEYS)[number]

export function ageText(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return 'age unknown'
  if (seconds < 90) return `${Math.round(seconds)}s ago`
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 172_800) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86_400)}d ago`
}

export function etTime(iso: string | null | undefined): string {
  const t = Date.parse(String(iso ?? ''))
  if (!Number.isFinite(t)) return '—'
  return new Date(t).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false })
}

export function etDateTime(iso: string | null | undefined): string {
  const t = Date.parse(String(iso ?? ''))
  if (!Number.isFinite(t)) return '—'
  return new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET'
}

export type SectionView<T> = { state: Freshness; value: T | null; reason: string | null; source: string; asOf: string | null; ageS: number | null; label: string }

/** One section as the page shows it. A response that is not current downgrades every section: UNAVAILABLE when there is
 *  no usable response at all, STALE (value kept, labelled) when the last good response is old or the refetch failed. */
export function sectionView<T>(wire: ReleasesSchedulesWire | null | undefined, key: SectionKey, opts: { nowMs: number; error?: boolean; stale?: boolean }): SectionView<T> {
  const known = !!wire && wire.schema === RELEASES_SCHEDULES_SCHEMA
  const sec = known ? (wire![key] as Section<T> | undefined) : undefined
  if (!known || !sec || typeof sec !== 'object') {
    const reason = !wire ? (opts.error ? 'request failed' : 'loading') : !known ? `unknown schema ${wire.schema ?? 'none'}` : 'section missing'
    return { state: 'UNAVAILABLE', value: null, reason, source: '—', asOf: null, ageS: null, label: `UNAVAILABLE · ${reason}` }
  }
  const asOfMs = Date.parse(String(sec.as_of ?? ''))
  const ageS = Number.isFinite(asOfMs) && asOfMs <= opts.nowMs + 60_000 ? Math.max(0, Math.round((opts.nowMs - asOfMs) / 1000)) : null
  const genMs = Date.parse(String(wire!.generated_at ?? ''))
  const responseOld = !Number.isFinite(genMs) || opts.nowMs - genMs > STALE_AFTER_MS || genMs > opts.nowMs + 60_000
  let state: Freshness = sec.freshness === 'OK' || sec.freshness === 'STALE' || sec.freshness === 'UNAVAILABLE' ? sec.freshness : 'UNAVAILABLE'
  let reason = sec.reason ?? null
  if (state !== 'UNAVAILABLE' && (responseOld || opts.error || opts.stale)) {
    state = 'STALE'
    reason = [reason, opts.error ? 'refresh failed; showing the last response' : 'response is older than 5 minutes'].filter(Boolean).join('; ')
  }
  const value = state === 'UNAVAILABLE' ? null : (sec.value ?? null)
  const label = state === 'UNAVAILABLE' ? `UNAVAILABLE${reason ? ` · ${reason}` : ''}` : `${state} · ${ageText(ageS)} · ${sec.source}`
  return { state, value, reason, source: sec.source, asOf: sec.as_of ?? null, ageS, label }
}

export function freshnessTone(state: Freshness): Tone {
  return state === 'OK' ? 'neutral' : 'warning'
}

export function kpiDisplay(k: Kpi | undefined, current: boolean): { value: string; detail: string; tone: Tone } {
  if (!k) return { value: 'UNAVAILABLE', detail: 'not in response', tone: 'warning' }
  if (k.freshness === 'UNAVAILABLE' || k.value === null || k.value === undefined || k.value === '') {
    return { value: 'UNAVAILABLE', detail: k.detail ?? 'source unavailable', tone: 'warning' }
  }
  const value = typeof k.value === 'number' ? k.value.toLocaleString('en-US') : String(k.value)
  if (!current) return { value, detail: `STALE · ${k.detail ?? ''}`.trim(), tone: 'warning' }
  return { value, detail: k.detail ?? '', tone: k.freshness === 'STALE' ? 'warning' : k.tone }
}

export const WINDOW_TONE: Record<string, Tone> = { LIVE: 'success', SHADOW: 'info', OFF: 'neutral', STOPPED: 'danger' }
export const STAGE_TONE: Record<string, Tone> = { LIVE: 'success', CUTOVER: 'success', CANARY: 'info', SHADOW: 'ai', PAUSED: 'warning', 'NOT LIVE': 'neutral', UNKNOWN: 'warning' }
export function stageTone(stage: string | null | undefined): Tone { return STAGE_TONE[String(stage ?? 'UNKNOWN')] ?? 'neutral' }
export function windowTone(state: string | null | undefined): Tone { return WINDOW_TONE[String(state ?? '')] ?? 'warning' }

export function prList(prs: number[] | null | undefined, reason: string | null | undefined, max = 12): string {
  if (!Array.isArray(prs)) return reason ? `UNAVAILABLE · ${reason}` : 'UNAVAILABLE'
  if (!prs.length) return 'no PRs'
  const shown = prs.slice(0, max).map(n => '#' + String(n)).join(', ')
  return prs.length > max ? `${shown} +${prs.length - max} more` : shown
}

export function verifyLabel(r: ReleaseRow): { text: string; tone: Tone } {
  if (r.mode === 'rollback') return { text: 'ROLLBACK', tone: 'warning' }
  if (!r.verify) return { text: r.serving ? 'SERVING · verify not retained' : 'verify not retained', tone: r.serving ? 'success' : 'neutral' }
  const ok = r.verify.ok === true && !r.verify.rolled_back && !(r.verify.readback_errors ?? []).length
  return { text: ok ? (r.serving ? 'LIVE · VERIFIED' : 'VERIFIED') : 'NOT VERIFIED', tone: ok ? 'success' : 'danger' }
}

export function lastRunText(r: TimelineRow): string {
  if (r.stage === 'PAUSED') return `paused since ${r.paused_since ?? '?'}${r.paused_note ? ` · ${r.paused_note}` : ''}`
  if (!r.last_run) return r.runner === 'cron' ? 'last run not in the ledger (cron)' : 'no ledger run today'
  return `${r.last_run.state} ${etTime(r.last_run.at)} (${r.last_run.mode})`
}

export function countOrUnavailable(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('en-US') : 'UNAVAILABLE'
}
