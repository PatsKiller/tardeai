// Release Train v2 (2026-10-21) — projections for Coordination → Release train and the Home card.
//
// Read shapes: docs/ops/RELEASE_TRAIN_API.md (feat/release-train-queue-20261021, commit 67f83711a): summary, /queue,
// /trains/{id}, /events; every summary field is a Field envelope {value, as_of, freshness, source, reason}.
// STOP shapes: docs/ops/RELEASE_TRAIN_UI_CONTRACT.md (this branch; scripts/lib/release_train_stop.py).
// Every path lives in RELEASE_TRAIN_PATHS so a path change is one edit.
//
// The rule this file enforces: missing, failed or old data is UNAVAILABLE or STALE with its age — never 0, never green.
// A count is a number only when the server measured it; the census gauge is INCOMPLETE unless the server says COMPLETE
// AND open PRs = sum(buckets). History keeps merged-not-live, verified, observing, rolled-back and rollback-failed
// distinct. A STOP that cannot be read is shown as an effective STOP (API rule 3: STOP fails closed).
// No imports: this module runs under `node --experimental-strip-types` (releaseTrain.test.ts).

export const RELEASE_TRAIN_PATHS = Object.freeze({
  summary: '/api/v2/coordination/release-train',
  queue: '/api/v2/coordination/release-train/queue',
  events: '/api/v2/coordination/release-train/events?limit=500',
  stop: '/api/v2/coordination/release-train/stop',
})
export const TRAIN_ID_RE = /^rt-[0-9]{8}-[0-9]{4}-[a-z0-9]{4,12}$/
export function trainDetailPath(trainId: string): string {
  return `/api/v2/coordination/release-train/trains/${encodeURIComponent(trainId)}`
}

export const RESUME_COMMAND_FALLBACK = 'python3 scripts/release_window.py clear-stop --reason "<why it is safe to resume>"'
export const HOST_STOP_FALLBACK = 'python3 scripts/lib/release_train_stop.py stop --reason "<why>"'
/** A response generated longer ago than this (a kept payload after failed polls) is STALE. */
export const RESPONSE_STALE_AFTER_S = 15 * 60
/** The STOP latch read is live per request; older than this is STALE. */
export const STOP_STALE_AFTER_S = 120

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'
export type DataState = 'LOADING' | 'OK' | 'STALE' | 'UNAVAILABLE'

// ── wire shapes: RELEASE_TRAIN_API.md ────────────────────────────────────────────────────────────

export interface Field<T> { value: T | null; as_of?: string | null; freshness?: 'OK' | 'STALE' | 'UNAVAILABLE' | string; source?: string; reason?: string | null }

export interface WindowWire {
  window_id?: string; local_time?: string; timezone?: string; starts_at?: string; starts_in_seconds?: number | null
  role?: string; enable_order?: number; enabled?: boolean; note?: string
}
export interface QueueCountsWire { ready?: number | null; held?: number | null; needs_operator?: number | null; blocked?: number | null; in_train?: number | null; other?: number | null; total?: number | null }
export interface LastOutcomeWire {
  train_id?: string; window_id?: string; outcome?: string; finished_at?: string | null; members?: number[]
  candidate_sha?: string | null; main_sha?: string | null; served_sha?: string | null
}
export interface SummaryStopWire { state?: 'CLEAR' | 'LATCHED' | 'UNREADABLE' | string; effective_stop?: boolean; latched_at?: string | null; window_id?: string | null; latch_reason?: string | null; reader?: string; path?: string; note?: string }
export interface CensusBucketWire { name: string; count: number | null; prs?: Array<number | string>; as_of?: string | null }
export interface CensusWire {
  status?: 'COMPLETE' | 'INCOMPLETE' | string
  open_prs?: number | null
  bucket_total?: number | null
  invariant?: string
  invariant_holds?: boolean | null
  incomplete_reasons?: string[] | null
  precedence?: string[]
  buckets?: CensusBucketWire[] | null
  receipt?: Record<string, unknown> | null
}
export interface ReleaseTrainSummaryWire {
  schema?: string
  authority?: string
  generated_at?: string | null
  status?: 'OK' | 'DEGRADED' | string
  armed?: Field<boolean>
  standing_policy?: Field<{ state?: string; detail?: string }>
  next_window?: Field<WindowWire>
  windows?: Field<WindowWire[]>
  queue_counts?: Field<QueueCountsWire>
  last_outcome?: Field<LastOutcomeWire>
  stop?: Field<SummaryStopWire>
  census?: Field<CensusWire>
  store?: Field<{ state?: string; tables?: Record<string, boolean> }>
  policy?: Field<Record<string, unknown>>
}
export interface QueueRowWire {
  pr_number: number
  repo?: string
  title?: string | null
  agent?: string | null
  head_sha?: string | null
  state?: string | null
  risk_class?: string | null
  risk_reasons?: Array<{ rule?: string; class?: string; path?: string; detail?: string }> | null
  depends_on?: number[] | null
  intended_window?: string | null
  blocker?: string | null
  next_action?: string | null
  train_id?: string | null
  submitted_at?: string | null
  as_of?: string | null
  age_seconds?: number | null
  last_event_seq?: number | null
  census_bucket?: string | null
}
export interface ReleaseQueueWire {
  schema?: string; generated_at?: string | null; as_of?: string | null; freshness?: string; source?: string; reason?: string | null
  store_state?: string; total?: number | null; rows?: QueueRowWire[] | null; census?: Field<CensusWire>
}
export interface TrainEventWire {
  schema?: string; seq?: number; event_id?: string; event_type?: string; subject_kind?: string; subject_id?: string
  pr_number?: number | null; train_id?: string | null; state_after?: string | null; actor?: string | null
  occurred_at?: string | null; recorded_at?: string | null; payload?: Record<string, unknown> | null
}
export interface ReleaseEventsWire {
  schema?: string; generated_at?: string | null; as_of?: string | null; freshness?: string; reason?: string | null
  events?: TrainEventWire[] | null; next_after_seq?: number | null
}
export interface TrainWire {
  train_id: string; window_id?: string | null; phase?: string | null; history_class?: string | null
  members?: Array<{ pr_number: number; head_sha?: string | null; risk_class?: string | null; order?: number }> | null
  base_sha?: string | null; candidate_sha?: string | null; main_sha?: string | null; served_sha?: string | null
  artifact_digest?: string | null; policy_version?: string; classifier_version?: string; check_manifest?: string[] | null
  frozen_at?: string | null; started_at?: string | null; finished_at?: string | null; elapsed_seconds?: number | null
  rollback_target?: string | null; outcome?: { outcome?: string } | null; evidence?: unknown[] | null; events?: TrainEventWire[] | null
}
export interface ReleaseTrainDetailWire {
  schema?: string; generated_at?: string | null; as_of?: string | null; freshness?: string; reason?: string | null; train?: TrainWire | null
}

// ── wire shapes: STOP (this branch, docs/ops/RELEASE_TRAIN_UI_CONTRACT.md) ──────────────────────

export interface StopLatchWire { status?: 'SET' | 'ABSENT' | 'UNREADABLE' | string; body?: Record<string, unknown> | null; path?: string; mtime?: string | null }
export interface StopStatusWire {
  schema?: string
  as_of?: string | null
  state_dir?: string
  latch?: StopLatchWire | null
  window_run_lock?: 'HELD' | 'FREE' | 'UNKNOWN' | string
  phase?: 'stopped' | 'settling' | 'running' | 'unknown' | string
  runner_reader?: string
  reader_note?: string | null
  audit_tail?: Array<Record<string, unknown>> | null
  resume?: { policy?: string; command?: string } | null
  separate_from_trading_kill_switch?: boolean
  kill_switch_note?: string
}
export interface StopResultWire {
  ok?: boolean
  schema?: string
  outcome?: 'STOP_SET' | 'ALREADY_STOPPED' | 'STOP_NOT_CONFIRMED' | 'REFUSED' | string
  refusal?: string
  error?: string
  phase?: string
  stop_id?: string | null
  actor?: string
  reason?: string
  requested_at?: string
  acknowledged_at?: string | null
  latch?: StopLatchWire | null
  replayed?: boolean
  resume?: { policy?: string; command?: string } | null
}

// ── freshness ────────────────────────────────────────────────────────────────────────────────────

export interface Freshness { state: DataState; asOf: string | null; ageS: number | null; ageLabel: string; reason: string | null }

export function ageLabel(ageS: number | null): string {
  if (ageS == null || !Number.isFinite(ageS)) return 'age unknown'
  if (ageS < -5) return 'clock skew'
  if (ageS < 90) return `${Math.max(0, Math.round(ageS))}s ago`
  if (ageS < 5400) return `${Math.round(ageS / 60)}m ago`
  if (ageS < 172800) return `${Math.round(ageS / 3600)}h ago`
  return `${Math.round(ageS / 86400)}d ago`
}

function ageOf(iso: string | null | undefined, nowMs: number): number | null {
  const t = iso ? Date.parse(iso) : NaN
  return Number.isFinite(t) ? (nowMs - t) / 1000 : null
}

/** Transport-level freshness of one response: LOADING / UNAVAILABLE (no payload) / STALE (kept after a failed poll,
 *  undated, or older than staleAfterS) / OK. `clock` is the response's own timestamp (generated_at or as_of). */
export function freshness(
  clock: string | null | undefined,
  hasPayload: boolean,
  opts: { nowMs: number; loading?: boolean; error?: unknown; staleAfterS?: number },
): Freshness {
  if (!hasPayload) {
    if (opts.loading && !opts.error) return { state: 'LOADING', asOf: null, ageS: null, ageLabel: '', reason: null }
    return { state: 'UNAVAILABLE', asOf: null, ageS: null, ageLabel: 'never read', reason: opts.error ? String(opts.error) : 'no payload' }
  }
  const asOf = typeof clock === 'string' ? clock : null
  const ageS = ageOf(asOf, opts.nowMs)
  const label = ageLabel(ageS)
  if (opts.error) return { state: 'STALE', asOf, ageS, ageLabel: label, reason: `refresh failed: ${String(opts.error)}` }
  if (ageS == null) return { state: 'STALE', asOf, ageS, ageLabel: label, reason: 'undated response' }
  if (ageS > (opts.staleAfterS ?? RESPONSE_STALE_AFTER_S)) return { state: 'STALE', asOf, ageS, ageLabel: label, reason: `as of ${asOf}` }
  return { state: 'OK', asOf, ageS, ageLabel: label, reason: null }
}

/** Freshness of one Field envelope inside a response: the server's own freshness verdict, capped by the transport. */
export function fieldFresh(field: Field<unknown> | null | undefined, transport: Freshness, nowMs: number): Freshness {
  if (transport.state === 'LOADING' || transport.state === 'UNAVAILABLE') return transport
  if (!field || typeof field !== 'object') return { state: 'UNAVAILABLE', asOf: null, ageS: null, ageLabel: 'never read', reason: 'field missing from response' }
  const asOf = typeof field.as_of === 'string' ? field.as_of : null
  const ageS = ageOf(asOf, nowMs)
  const label = ageLabel(ageS)
  const fr = String(field.freshness || '').toUpperCase()
  if (fr === 'UNAVAILABLE') return { state: 'UNAVAILABLE', asOf, ageS, ageLabel: label, reason: field.reason || 'unavailable' }
  if (fr === 'STALE') return { state: 'STALE', asOf, ageS, ageLabel: label, reason: field.reason || `as of ${asOf ?? 'unknown'}` }
  if (fr !== 'OK') return { state: 'UNAVAILABLE', asOf, ageS, ageLabel: label, reason: `unknown freshness ${JSON.stringify(field.freshness ?? null)}` }
  if (transport.state === 'STALE') return { ...transport, asOf: asOf ?? transport.asOf }
  return { state: 'OK', asOf, ageS, ageLabel: label, reason: field.reason || null }
}

export function freshnessTone(f: Freshness): Tone {
  return f.state === 'OK' || f.state === 'LOADING' ? 'neutral' : 'warning'
}
export function freshnessText(f: Freshness): string {
  return f.state === 'OK' ? `as of ${f.ageLabel}` : f.state === 'LOADING' ? 'reading…' : f.state === 'STALE' ? `STALE · ${f.ageLabel}` : 'UNAVAILABLE'
}

/** A count is shown only when measured on usable data; otherwise the data state word. Never a fabricated 0. */
export function countLabel(n: number | null | undefined, f: Freshness): string {
  if (f.state === 'LOADING') return '…'
  if (f.state === 'UNAVAILABLE') return 'UNAVAILABLE'
  if (typeof n !== 'number' || !Number.isFinite(n)) return 'UNAVAILABLE'
  return f.state === 'STALE' ? `${n} (STALE)` : String(n)
}

export function shortSha(sha: string | null | undefined): string {
  return typeof sha === 'string' && /^[0-9a-f]{7,40}$/i.test(sha) ? sha.slice(0, 9) : 'UNAVAILABLE'
}

export function durationLabel(s: number | null | undefined): string {
  if (typeof s !== 'number' || !Number.isFinite(s)) return 'UNAVAILABLE'
  if (s < 0) return 'past'
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`
  return `${Math.round(s / 86400)}d`
}

// ── outcomes (history_class / TrainOutcome@v1) ───────────────────────────────────────────────────

export type HistoryOutcome = 'MERGED_NOT_LIVE' | 'VERIFIED' | 'OBSERVING' | 'ROLLED_BACK' | 'ROLLBACK_FAILED' | 'NOT_SHIPPED' | 'IN_PROGRESS' | 'UNKNOWN'
export const HISTORY_OUTCOMES: HistoryOutcome[] = ['MERGED_NOT_LIVE', 'OBSERVING', 'VERIFIED', 'ROLLED_BACK', 'ROLLBACK_FAILED', 'NOT_SHIPPED', 'IN_PROGRESS', 'UNKNOWN']
export const DESIGN_OUTCOMES: HistoryOutcome[] = ['MERGED_NOT_LIVE', 'VERIFIED', 'OBSERVING', 'ROLLED_BACK', 'ROLLBACK_FAILED']
export const OUTCOME_LABEL: Record<HistoryOutcome, string> = {
  MERGED_NOT_LIVE: 'merged, not live', VERIFIED: 'verified', OBSERVING: 'observing', ROLLED_BACK: 'rolled back',
  ROLLBACK_FAILED: 'rollback FAILED', NOT_SHIPPED: 'not shipped', IN_PROGRESS: 'in progress', UNKNOWN: 'unknown',
}
export const OUTCOME_TONE: Record<HistoryOutcome, Tone> = {
  MERGED_NOT_LIVE: 'warning', VERIFIED: 'success', OBSERVING: 'info', ROLLED_BACK: 'warning', ROLLBACK_FAILED: 'danger',
  NOT_SHIPPED: 'neutral', IN_PROGRESS: 'info', UNKNOWN: 'neutral',
}

/** TrainOutcome@v1.outcome, history_class, or a train state_after → category. Each design outcome is its own. */
export function historyOutcome(raw: string | null | undefined): HistoryOutcome {
  const s = String(raw || '').toUpperCase().replace(/[\s-]+/g, '_')
  if (s === 'ROLLBACK_FAILED') return 'ROLLBACK_FAILED'
  if (s === 'ROLLED_BACK') return 'ROLLED_BACK'
  if (s === 'RELEASED_VERIFIED' || s === 'VERIFIED') return 'VERIFIED'
  if (s === 'RELEASED_OBSERVING' || s === 'OBSERVING') return 'OBSERVING'
  if (s === 'MERGED_NOT_LIVE') return 'MERGED_NOT_LIVE'
  if (s === 'NOT_SHIPPED' || s === 'NO_OP' || s === 'FAILED_PRE_MERGE' || s === 'CANCELLED' || s === 'STOPPED') return 'NOT_SHIPPED'
  if (['IN_PROGRESS', 'SELECTED', 'INTEGRATING', 'QUALIFIED', 'WAITING_WINDOW', 'MERGED', 'PROMOTING', 'RELEASED', 'FROZEN'].includes(s)) return 'IN_PROGRESS'
  return 'UNKNOWN'
}

// ── census ───────────────────────────────────────────────────────────────────────────────────────

export interface CensusModel {
  state: 'OK' | 'INCOMPLETE' | 'STALE' | 'UNAVAILABLE' | 'LOADING'
  openPrs: number | null
  bucketSum: number
  buckets: Array<{ name: string; n: number; share: number }>
  reason: string | null
  f: Freshness
}

export function censusFrom(field: Field<CensusWire> | null | undefined, transport: Freshness, nowMs: number): CensusModel {
  const f = fieldFresh(field, transport, nowMs)
  const c = field?.value
  if (f.state === 'LOADING') return { state: 'LOADING', openPrs: null, bucketSum: 0, buckets: [], reason: null, f }
  if (f.state === 'UNAVAILABLE' || !c) return { state: 'UNAVAILABLE', openPrs: null, bucketSum: 0, buckets: [], reason: f.reason ?? 'no census', f }
  const raw = Array.isArray(c.buckets) ? c.buckets : []
  const bad = raw.filter(b => !b || typeof b.count !== 'number' || !Number.isFinite(b.count) || b.count < 0).map(b => String(b?.name ?? '?'))
  const buckets = raw.filter(b => b && typeof b.count === 'number' && Number.isFinite(b.count) && b.count >= 0)
    .map(b => ({ name: String(b.name), n: b.count as number, share: 0 }))
  const bucketSum = buckets.reduce((a, b) => a + b.n, 0)
  for (const b of buckets) b.share = bucketSum > 0 ? b.n / bucketSum : 0
  const openPrs = typeof c.open_prs === 'number' && Number.isFinite(c.open_prs) ? c.open_prs : null
  const reasons: string[] = []
  if (String(c.status || '').toUpperCase() !== 'COMPLETE') reasons.push(`server status ${c.status ?? 'missing'}`)
  if (Array.isArray(c.incomplete_reasons) && c.incomplete_reasons.length) reasons.push(c.incomplete_reasons.join(', '))
  if (c.invariant_holds !== true) reasons.push('invariant not confirmed')
  if (openPrs == null) reasons.push('open PR count missing')
  if (bad.length) reasons.push(`unmeasured bucket ${bad.join(', ')}`)
  if (openPrs != null && openPrs !== bucketSum) reasons.push(`open PRs ${openPrs} ≠ bucket sum ${bucketSum}`)
  const shown = buckets.filter(b => b.n > 0).sort((a, b) => b.n - a.n || a.name.localeCompare(b.name))
  if (reasons.length) return { state: 'INCOMPLETE', openPrs, bucketSum, buckets: shown, reason: [...new Set(reasons)].join('; '), f }
  if (f.state === 'STALE') return { state: 'STALE', openPrs, bucketSum, buckets: shown, reason: f.reason, f }
  return { state: 'OK', openPrs, bucketSum, buckets: shown, reason: null, f }
}

// ── queue ────────────────────────────────────────────────────────────────────────────────────────

export interface QueueRow {
  key: string; pr: number; title: string; agent: string; state: string; stateTone: Tone; risk: string; riskTone: Tone
  riskWhy: string; dependencies: string; ageS: number | null; age: string; blocker: string; nextAction: string
  window: string; trainId: string | null; bucket: string
}

export function riskTone(risk: string): Tone {
  const r = risk.toLowerCase()
  if (r === 'eligible') return 'success'
  if (r === 'needs_operator') return 'warning'
  if (r === 'held' || r === 'blocked') return 'danger'
  return 'warning' // unknown risk is held (Release Train v2 policy) — never shown as safe
}

export function queueStateTone(state: string): Tone {
  const s = state.toLowerCase()
  if (s === 'ready' || s === 'released') return 'success'
  if (s === 'held' || s === 'blocked' || s === 'rollback_failed' || s === 'quarantined') return 'danger'
  if (['selected', 'integrating', 'qualified', 'waiting_window', 'merged', 'promoting', 'observing'].includes(s)) return 'info'
  return 'warning'
}

export const IN_TRAIN_STATES = ['selected', 'integrating', 'qualified', 'waiting_window', 'merged', 'promoting']

export function queueFrom(payload: ReleaseQueueWire | null | undefined, transport: Freshness, nowMs: number): {
  rows: QueueRow[]; counts: Record<string, number>; usable: boolean; f: Freshness; currentTrainId: string | null; storeState: string | null
} {
  const f = payload ? fieldFresh({ value: payload.rows ?? null, as_of: payload.as_of, freshness: payload.freshness, reason: payload.reason }, transport, nowMs) : transport
  const storeState = payload?.store_state ?? null
  if (!payload || f.state === 'UNAVAILABLE' || f.state === 'LOADING' || !Array.isArray(payload.rows)) return { rows: [], counts: {}, usable: false, f, currentTrainId: null, storeState }
  const counts: Record<string, number> = {}
  let currentTrainId: string | null = null
  const rows = payload.rows.filter(i => i && Number.isInteger(i.pr_number)).map(i => {
    const state = String(i.state || 'UNKNOWN')
    const risk = String(i.risk_class || 'unknown')
    const ageS = typeof i.age_seconds === 'number' && Number.isFinite(i.age_seconds) ? i.age_seconds : ageOf(i.submitted_at, nowMs)
    counts[state] = (counts[state] || 0) + 1
    if (i.train_id && IN_TRAIN_STATES.includes(state.toLowerCase())) currentTrainId = currentTrainId ?? i.train_id
    return {
      key: `pr-${i.pr_number}`, pr: i.pr_number, title: i.title ? String(i.title) : '(title UNAVAILABLE)', agent: String(i.agent || 'unknown'),
      state, stateTone: queueStateTone(state), risk, riskTone: riskTone(risk),
      riskWhy: Array.isArray(i.risk_reasons) ? i.risk_reasons.map(r => r?.detail || r?.rule || '').filter(Boolean).join(' · ') : '',
      dependencies: Array.isArray(i.depends_on) && i.depends_on.length ? i.depends_on.map(d => `#${d}`).join(' ') : '—',
      ageS, age: ageS == null ? 'UNDATED' : ageLabel(ageS).replace(' ago', ''),
      blocker: String(i.blocker || '—'), nextAction: String(i.next_action || '—'), window: String(i.intended_window || 'unassigned'),
      trainId: i.train_id || null, bucket: String(i.census_bucket || '—'),
    }
  })
  return { rows, counts, usable: true, f, currentTrainId, storeState }
}

// ── history (from /events: TrainEvent@v1 rows grouped by train) ─────────────────────────────────

export interface HistoryRow {
  key: string; trainId: string; window: string; outcome: HistoryOutcome; outcomeRaw: string; started: string; finished: string
  candidate: string; served: string; members: string; events: number
}

function pstr(p: Record<string, unknown> | null | undefined, k: string): string | null {
  const v = p ? p[k] : undefined
  return typeof v === 'string' && v ? v : null
}

export function historyFrom(payload: ReleaseEventsWire | null | undefined, transport: Freshness, nowMs: number): {
  rows: HistoryRow[]; counts: Record<HistoryOutcome, number>; usable: boolean; f: Freshness
} {
  const counts = Object.fromEntries(HISTORY_OUTCOMES.map(o => [o, 0])) as Record<HistoryOutcome, number>
  const f = payload ? fieldFresh({ value: payload.events ?? null, as_of: payload.as_of, freshness: payload.freshness, reason: payload.reason }, transport, nowMs) : transport
  if (!payload || f.state === 'UNAVAILABLE' || f.state === 'LOADING' || !Array.isArray(payload.events)) return { rows: [], counts, usable: false, f }
  const byTrain = new Map<string, TrainEventWire[]>()
  for (const e of payload.events) {
    const id = e && (e.train_id || (e.subject_kind === 'train' && e.subject_id ? String(e.subject_id).replace(/^train:/, '') : null))
    if (!id) continue
    if (!byTrain.has(id)) byTrain.set(id, [])
    byTrain.get(id)!.push(e)
  }
  const rows: HistoryRow[] = []
  for (const [trainId, evs] of byTrain) {
    evs.sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
    const last = evs[evs.length - 1]
    let outcomeRaw: string | null = null
    let window: string | null = null, cand: string | null = null, served: string | null = null, members: number | null = null
    for (const e of evs) {
      const p = e.payload || null
      outcomeRaw = pstr(p, 'outcome') || pstr(p, 'history_class') || outcomeRaw
      window = pstr(p, 'window_id') || window
      cand = pstr(p, 'candidate_sha') || cand
      served = pstr(p, 'served_sha') || served
      const m = p ? p['members'] : null
      if (Array.isArray(m)) members = m.length
    }
    const outcome = historyOutcome(outcomeRaw || last.state_after || null)
    counts[outcome]++
    rows.push({
      key: trainId, trainId, window: window || '—', outcome, outcomeRaw: outcomeRaw || last.state_after || 'UNKNOWN',
      started: evs[0].occurred_at || 'UNDATED', finished: outcomeRaw ? (last.occurred_at || 'UNDATED') : '—',
      candidate: shortSha(cand), served: shortSha(served), members: members == null ? 'UNAVAILABLE' : String(members), events: evs.length,
    })
  }
  rows.sort((a, b) => b.started.localeCompare(a.started))
  return { rows, counts, usable: true, f }
}

// ── train detail ─────────────────────────────────────────────────────────────────────────────────

export interface TrainDetail {
  trainId: string; window: string; phase: string; outcome: HistoryOutcome; frozenAt: string; elapsed: string
  members: Array<{ pr: number; head: string; risk: string }>
  base: string; candidate: string; main: string; served: string; servedMatchesCandidate: boolean | null
  artifact: string; rollbackTarget: string; checks: string
  timeline: Array<{ at: string; step: string; detail: string; actor: string }>
}

export function trainDetailFrom(t: TrainWire | null | undefined): TrainDetail | null {
  if (!t || typeof t.train_id !== 'string') return null
  const cand = shortSha(t.candidate_sha), served = shortSha(t.served_sha)
  return {
    trainId: t.train_id, window: String(t.window_id || '—'), phase: String(t.phase || 'UNKNOWN'),
    outcome: historyOutcome(t.outcome?.outcome || t.history_class || t.phase || null),
    frozenAt: t.frozen_at || 'not frozen', elapsed: durationLabel(t.elapsed_seconds),
    members: (Array.isArray(t.members) ? t.members : []).filter(m => m && Number.isInteger(m.pr_number))
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
      .map(m => ({ pr: m.pr_number, head: shortSha(m.head_sha), risk: String(m.risk_class || 'unknown') })),
    base: shortSha(t.base_sha), candidate: cand, main: shortSha(t.main_sha), served,
    servedMatchesCandidate: cand === 'UNAVAILABLE' || served === 'UNAVAILABLE' ? null : cand === served,
    artifact: t.artifact_digest ? String(t.artifact_digest).slice(0, 19) : 'UNAVAILABLE',
    rollbackTarget: String(t.rollback_target || 'UNAVAILABLE'),
    checks: Array.isArray(t.check_manifest) && t.check_manifest.length ? t.check_manifest.join(', ') : 'UNAVAILABLE',
    timeline: (Array.isArray(t.events) ? t.events : []).map(e => ({
      at: e.occurred_at || 'UNDATED', step: String(e.event_type || ''), detail: e.state_after ? `→ ${e.state_after}` : '', actor: String(e.actor || ''),
    })).sort((a, b) => a.at.localeCompare(b.at)),
  }
}

// ── Home summary ─────────────────────────────────────────────────────────────────────────────────

export interface SummaryItem { text: string; tone: Tone; f: Freshness }
export interface SummaryModel {
  transport: Freshness
  degraded: string[]
  nextWindow: SummaryItem
  ready: SummaryItem
  held: SummaryItem
  lastOutcome: SummaryItem
  currentTrain: SummaryItem
  policy: SummaryItem
  stop: SummaryItem & { effective: boolean }
}

function stateWord(f: Freshness): string {
  return f.state === 'LOADING' ? '…' : 'UNAVAILABLE'
}
function staleTag(f: Freshness): string { return f.state === 'STALE' ? ' (STALE)' : '' }

export function policyTone(state: string): Tone {
  const s = state.toUpperCase()
  if (s === 'ACTIVE') return 'info'
  if (s === 'REVOKED') return 'danger'
  return 'warning'  // NOT_CONFIGURED, PAUSED, anything unknown: never success
}

export function summaryFrom(
  payload: ReleaseTrainSummaryWire | null | undefined,
  transport: Freshness,
  nowMs: number,
  queue?: { usable: boolean; currentTrainId: string | null; f: Freshness },
): SummaryModel {
  const p = payload || {}
  const ff = (k: keyof ReleaseTrainSummaryWire) => fieldFresh(p[k] as Field<unknown> | undefined, transport, nowMs)
  const usable = (f: Freshness) => f.state === 'OK' || f.state === 'STALE'

  const nwF = ff('next_window'), nw = p.next_window?.value
  const armedF = ff('armed'), armed = p.armed?.value
  const nextWindow: SummaryItem = !usable(nwF) || !nw ? { text: stateWord(nwF), tone: 'warning', f: nwF } : {
    text: `${nw.local_time ?? nw.window_id ?? '?'}${nw.timezone === 'America/New_York' ? ' ET' : nw.timezone ? ` ${nw.timezone}` : ''}`
      + `${nw.role ? ` ${nw.role}` : ''}${typeof nw.starts_in_seconds === 'number' ? ` · in ${durationLabel(nw.starts_in_seconds)}` : ''}`
      + `${nw.enabled === true && armed === true ? '' : ' · not armed'}${staleTag(nwF)}`,
    tone: nw.enabled === true && armed === true ? 'info' : 'warning', f: nwF,
  }

  const qcF = ff('queue_counts'), qc = p.queue_counts?.value
  const ready: SummaryItem = { text: countLabel(usable(qcF) ? qc?.ready : null, qcF), tone: usable(qcF) && qc ? 'success' : 'warning', f: qcF }
  const held: SummaryItem = { text: countLabel(usable(qcF) ? qc?.held : null, qcF), tone: 'warning', f: qcF }
  if (qcF.state === 'UNAVAILABLE' && p.queue_counts?.reason) { ready.text = held.text = `UNAVAILABLE (${p.queue_counts.reason})` }

  const loF = ff('last_outcome'), lo = p.last_outcome?.value
  let lastOutcome: SummaryItem
  if (!usable(loF)) lastOutcome = { text: stateWord(loF), tone: 'warning', f: loF }
  else if (!lo) lastOutcome = { text: `${p.last_outcome?.reason === 'no_outcome_recorded' ? 'none recorded' : 'UNAVAILABLE'}${staleTag(loF)}`, tone: 'neutral', f: loF }
  else {
    const o = historyOutcome(lo.outcome)
    lastOutcome = { text: `${OUTCOME_LABEL[o]} · ${shortSha(lo.served_sha || lo.candidate_sha)}${lo.finished_at ? ` · ${lo.finished_at}` : ''}${staleTag(loF)}`, tone: OUTCOME_TONE[o], f: loF }
  }

  // The summary has no current-train field: derive it from the queue (a row in an in-train state carries train_id).
  const ctF = queue ? queue.f : { state: 'UNAVAILABLE' as DataState, asOf: null, ageS: null, ageLabel: '', reason: 'queue not read' }
  const currentTrain: SummaryItem = !queue || !queue.usable ? { text: stateWord(ctF), tone: 'warning', f: ctF }
    : { text: `${queue.currentTrainId ?? 'none running'}${staleTag(ctF)}`, tone: queue.currentTrainId ? 'info' : 'neutral', f: ctF }

  const spF = ff('standing_policy'), sp = p.standing_policy?.value
  const policy: SummaryItem = !usable(spF) || !sp?.state ? { text: stateWord(spF), tone: 'warning', f: spF }
    : { text: `${String(sp.state).toUpperCase()}${armed === false ? ' · not armed' : armed === true ? ' · armed' : usable(armedF) ? '' : ' · armed UNAVAILABLE'}${staleTag(spF)}`, tone: policyTone(String(sp.state)), f: spF }

  // API rule 3: STOP fails closed — UNAVAILABLE, UNREADABLE or effective_stop true reads as STOPPED.
  const stF = ff('stop'), st = p.stop?.value
  const effective = !usable(stF) || !st || st.effective_stop === true || String(st.state).toUpperCase() !== 'CLEAR'
  const stop = {
    text: !usable(stF) || !st ? (stF.state === 'LOADING' ? '…' : 'STOP state UNAVAILABLE — treat as STOPPED')
      : st.effective_stop || String(st.state).toUpperCase() !== 'CLEAR' ? `STOPPED (${String(st.state ?? 'UNKNOWN')})${staleTag(stF)}` : `not stopped${staleTag(stF)}`,
    tone: (effective ? 'danger' : 'neutral') as Tone, f: stF, effective: stF.state === 'LOADING' ? false : effective,
  }

  const degraded: string[] = []
  for (const k of ['next_window', 'queue_counts', 'last_outcome', 'standing_policy', 'stop', 'census', 'store', 'armed'] as const) {
    const f = ff(k)
    if (f.state === 'STALE' || f.state === 'UNAVAILABLE') degraded.push(`${k.replace('_', ' ')} ${f.state}${f.reason ? ` (${f.reason})` : ''}`)
  }
  return { transport, degraded, nextWindow, ready, held, lastOutcome, currentTrain, policy, stop }
}

// ── STOP: requested → acknowledged → (settling) → stopped ───────────────────────────────────────

export interface StopRequestState {
  requestedAt: string | null       // client clock when the POST was sent
  inFlight: boolean
  result: StopResultWire | null    // server answer (acknowledged = latch read back by the server)
  httpStatus: number | null
  error: string | null             // transport failure: unknown whether the request arrived
}
export const NO_STOP_REQUEST: StopRequestState = { requestedAt: null, inFlight: false, result: null, httpStatus: null, error: null }

export type StopStepKey = 'requested' | 'acknowledged' | 'settling' | 'stopped'
export interface StopStep { key: StopStepKey; label: string; done: boolean; at: string | null; detail: string }
export interface StopModel {
  latch: 'SET' | 'ABSENT' | 'UNREADABLE' | 'UNKNOWN'
  latchTone: Tone
  headline: string
  steps: StopStep[]
  refused: string | null
  unconfirmed: string | null
  statusFresh: Freshness
  latchedAt: string | null
  latchedBy: string | null
  latchReason: string | null
  latchOutcome: string | null
  readerNote: string | null
  resumeCommand: string
}

function str(v: unknown): string | null { return typeof v === 'string' && v ? v : null }

export function stopModelFrom(status: StopStatusWire | null | undefined, req: StopRequestState, statusFresh: Freshness): StopModel {
  const usable = !!status && (statusFresh.state === 'OK' || statusFresh.state === 'STALE')
  const raw = usable ? String(status!.latch?.status || '') : ''
  const latch: StopModel['latch'] = raw === 'SET' || raw === 'ABSENT' || raw === 'UNREADABLE' ? raw : 'UNKNOWN'
  const body = ((usable && status!.latch?.body) || {}) as Record<string, unknown>
  const res = req.result
  const acknowledged = !!res && res.ok === true && res.latch?.status === 'SET'
  const ackAt = acknowledged ? (res!.acknowledged_at || null) : null
  // "stopped" needs an INDEPENDENT read of the latch (the status poll): fresh, SET, no window holding its run lock,
  // and — after a press — taken at or after the server's acknowledgement (both are server clocks).
  const readAt = usable && status!.as_of ? Date.parse(status!.as_of) : NaN
  const afterAck = !ackAt || (Number.isFinite(readAt) && readAt >= Date.parse(ackAt))
  const independentSet = usable && statusFresh.state === 'OK' && latch === 'SET' && afterAck
  const lock = usable ? String(status!.window_run_lock || 'UNKNOWN') : 'UNKNOWN'
  const settling = independentSet && lock === 'HELD'
  const stopped = independentSet && lock === 'FREE'
  const steps: StopStep[] = [
    { key: 'requested', label: 'Stop requested', done: !!req.requestedAt, at: req.requestedAt,
      detail: req.inFlight ? 'sent; waiting for the server' : req.requestedAt ? 'sent from this browser' : 'not requested from this page' },
    { key: 'acknowledged', label: 'Acknowledged (latch read back)', done: acknowledged, at: ackAt,
      detail: acknowledged ? `${res!.outcome === 'ALREADY_STOPPED' ? 'a STOP was already latched' : 'STOP.json written and read back'}${res!.replayed ? ' · replay of the same press' : ''}` : 'server has not confirmed a latch' },
    { key: 'settling', label: 'Settling', done: settling, at: settling ? (status!.as_of || null) : null,
      detail: settling ? 'a release window is mid-run: it finishes its bounded verify / rollback, then nothing new starts' : lock === 'UNKNOWN' ? 'run lock unreadable' : 'no window running' },
    { key: 'stopped', label: 'Stopped', done: stopped, at: stopped ? (status!.as_of || null) : null,
      detail: stopped ? 'independent read: latch SET, no window running; every later window refuses (REFUSED_STOP_LATCHED)' : 'not yet confirmed by an independent read' },
  ]
  let refused: string | null = null
  if (res && (res.outcome === 'REFUSED' || res.ok === false) && res.refusal) refused = `${res.refusal}: ${res.error || 'refused'}`
  let unconfirmed: string | null = null
  if (req.error) unconfirmed = `No answer (${req.error}). The STOP may or may not have arrived — the latch state below is the truth. Retry uses the same key.`
  else if (res && res.outcome === 'STOP_NOT_CONFIRMED') unconfirmed = 'Server could not read the latch back. Use the host fallback.'
  const headline = latch === 'SET' ? (settling ? 'RELEASES STOPPING (window settling)' : statusFresh.state === 'STALE' ? 'RELEASES STOPPED (STALE read)' : 'RELEASES STOPPED')
    : latch === 'ABSENT' ? (statusFresh.state === 'STALE' ? 'Releases not stopped (STALE read)' : 'Releases not stopped')
      : latch === 'UNREADABLE' ? (status!.runner_reader === 'main_fail_open'
        ? 'STOP latch UNREADABLE — the served runner reads it as NOT SET: press STOP'
        : 'STOP latch UNREADABLE — effective STOP')
        : statusFresh.state === 'LOADING' ? 'reading STOP latch…' : 'STOP state UNAVAILABLE — treat as STOPPED'
  return {
    latch, latchTone: latch === 'ABSENT' ? 'neutral' : latch === 'SET' || latch === 'UNREADABLE' ? 'danger' : 'warning', headline, steps, refused, unconfirmed, statusFresh,
    latchedAt: str(body.latched_at), latchedBy: str(body.actor),
    latchReason: str(body.reason) || str(body.detail), latchOutcome: str(body.outcome),
    readerNote: usable ? (status!.reader_note || null) : null,
    resumeCommand: (usable && status!.resume?.command) || res?.resume?.command || RESUME_COMMAND_FALLBACK,
  }
}

export const STOP_REASON_MIN = 8
export const STOP_REASON_MAX = 500
export function stopReasonError(reason: string): string | null {
  const r = reason.trim()
  if (r.length < STOP_REASON_MIN) return `reason required (at least ${STOP_REASON_MIN} characters)`
  if (r.length > STOP_REASON_MAX) return `reason too long (max ${STOP_REASON_MAX})`
  return null
}
/** One key per button press, reused on a retry of that press (server dedupes). */
export function newIdempotencyKey(rand: () => string): string {
  return `cc-stop-${rand()}`.replace(/[^A-Za-z0-9._:-]/g, '').slice(0, 128)
}
