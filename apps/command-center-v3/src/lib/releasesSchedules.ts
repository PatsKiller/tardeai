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
  ci: MainCi }
// Exact-SHA CI of main HEAD: SUCCESS | FAILURE | PENDING from the main-ci-watch receipt (scripts/main_ci_watch.py),
// OK | NOT_GREEN from post_merge_ci.json, else UNAVAILABLE with the reason.
export type MainCi = { state: 'SUCCESS' | 'FAILURE' | 'PENDING' | 'OK' | 'NOT_GREEN' | 'UNAVAILABLE'; reason: string | null; source?: string
  checked_at?: string | null; age_s?: number | null; stale?: boolean; checks?: number; success?: number
  not_success?: Array<{ name?: string; conclusion?: string | null }>
  workflows?: Array<{ name?: string; state?: string; url?: string | null; updated_at?: string | null }> }
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
  serving?: Section<Serving>; next_release?: Section<NextRelease>; history?: Section<{ releases: ReleaseRow[]; receipts_total: number }>
  release_errors?: Section<{ rows: ReleaseError[]; window_hours: number; not_covered: string }>; n8n_today?: Section<LedgerToday>; timeline?: Section<Timeline>
  stop?: { state?: string; effective_stop?: boolean; latched_at?: string | null; reason?: string | null }
}

export const SECTION_KEYS = ['serving', 'next_release', 'history', 'release_errors', 'n8n_today', 'timeline'] as const
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

export const STAGE_TONE: Record<string, Tone> = { LIVE: 'success', CUTOVER: 'success', CANARY: 'info', SHADOW: 'ai', PAUSED: 'warning', 'NOT LIVE': 'neutral', UNKNOWN: 'warning' }
export function stageTone(stage: string | null | undefined): Tone { return STAGE_TONE[String(stage ?? 'UNKNOWN')] ?? 'neutral' }

export function prList(prs: number[] | null | undefined, reason: string | null | undefined, max = 12): string {
  if (!Array.isArray(prs)) return reason ? `UNAVAILABLE · ${reason}` : 'UNAVAILABLE'
  if (!prs.length) return 'no PRs'
  const shown = prs.slice(0, max).map(n => '#' + String(n)).join(', ')
  return prs.length > max ? `${shown} +${prs.length - max} more` : shown
}

/** The structured verdict behind the label. Callers must use THIS, never the label text: "NOT VERIFIED" ends with
 *  "VERIFIED", so a suffix test on the sentence reads a FAILED verification as a passed one (codex R1, PR 2541). */
export type VerifyVerdict = 'verified' | 'not_verified' | 'rollback' | 'not_recorded'
export function verifyVerdict(r: ReleaseRow): VerifyVerdict {
  if (r.mode === 'rollback') return 'rollback'
  if (!r.verify) return 'not_recorded'
  const ok = r.verify.ok === true && !r.verify.rolled_back && !(r.verify.readback_errors ?? []).length
  return ok ? 'verified' : 'not_verified'
}

export function verifyLabel(r: ReleaseRow): { text: string; tone: Tone } {
  const verdict = verifyVerdict(r)
  if (verdict === 'rollback') return { text: 'ROLLBACK', tone: 'warning' }
  if (verdict === 'not_recorded') return { text: r.serving ? 'SERVING · verify not retained' : 'verify not retained', tone: r.serving ? 'success' : 'neutral' }
  return verdict === 'verified'
    ? { text: r.serving ? 'LIVE · VERIFIED' : 'VERIFIED', tone: 'success' }
    : { text: 'NOT VERIFIED', tone: 'danger' }
}

export function lastRunText(r: TimelineRow): string {
  if (r.stage === 'PAUSED') return `paused since ${r.paused_since ?? '?'}${r.paused_note ? ` · ${r.paused_note}` : ''}`
  if (!r.last_run) return r.runner === 'cron' ? 'last run not in the ledger (cron)' : 'no ledger run today'
  return `${r.last_run.state} ${etTime(r.last_run.at)} (${r.last_run.mode})`
}

export function countOrUnavailable(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('en-US') : 'UNAVAILABLE'
}

/** Tone for main-HEAD CI: green only on SUCCESS/OK, red on FAILURE/NOT_GREEN, info while PENDING, warning otherwise. */
export function ciTone(state: string | null | undefined): Tone {
  if (state === 'SUCCESS' || state === 'OK') return 'success'
  if (state === 'FAILURE' || state === 'NOT_GREEN') return 'danger'
  if (state === 'PENDING') return 'info'
  return 'warning'
}

/** "PENDING · 12m ago" — the state with the age of the receipt it came from (no age for UNAVAILABLE). */
export function ciLabel(ci: MainCi | null | undefined): string {
  if (!ci) return 'UNAVAILABLE'
  if (ci.state === 'UNAVAILABLE' || ci.age_s == null) return ci.state
  return `${ci.state} · ${ageText(ci.age_s)}${ci.stale ? ' (stale)' : ''}`
}

/**
 * The deploy STOP latch as the page knows it. Tri-state on purpose: `false` means "a current response
 * measured the latch off", not "the field was missing". An unreadable response, a response that does not
 * state `effective_stop`, or a retained/stale read is `null` — unknown — and may never be rendered as "off,
 * promote allowed" (cx-openai-4 R2 at 8cd7fee69).
 */
export type StopFacts = { effective: boolean | null; state: string | null; label: string; reason: string | null }

export function stopFacts(wire: ReleasesSchedulesWire | null | undefined, opts: { error?: boolean; stale?: boolean } = {}): StopFacts {
  const stop = wire?.stop
  if (!wire || wire.schema !== RELEASES_SCHEDULES_SCHEMA) {
    return { effective: null, state: stop?.state ?? null, label: 'STOP not read', reason: opts.error ? 'request failed' : 'loading' }
  }
  if (!stop || typeof stop.effective_stop !== 'boolean') {
    return { effective: null, state: stop?.state ?? null, label: 'STOP state not stated', reason: 'the response did not state the STOP latch' }
  }
  if (opts.error || opts.stale) {
    return { effective: null, state: stop.state ?? null, label: 'STOP state stale', reason: opts.error ? 'refresh failed; showing the last response' : 'response is older than 5 minutes' }
  }
  return { effective: stop.effective_stop, state: stop.state ?? null, label: stop.effective_stop ? `STOP ${stop.state ?? 'on'}` : 'STOP off', reason: null }
}

/**
 * The coach strip's two facts, kept out of the JSX so they can be tested and so "unknown" cannot become a zero.
 *
 * A missing board (`inFlight` null) used to render "0 READY to Approve"; a missing next-release (`next` null) or an
 * unstaked `commits_ahead` used to fall through to a GREEN "Site matches main". Both are affirmative operational
 * conclusions drawn from an absence, on the strip that tells the operator what to do (codex-cloud F2 at 567486a98).
 *
 * Currentness is part of the fact, not decoration: a retained STALE board or a stale comparison is not present
 * readiness (cx-openai-4 R3 at 8cd7fee69). The historical value may still be shown, but it never drives "ready"
 * or "matches".
 */
export type CoachFacts = {
  ready: number | null          // null = the board did not state it (not "zero") or the read is not current
  open: number | null
  ahead: number | null          // retained distance; may be historical when aheadCurrent is false
  aheadCurrent: boolean         // the comparison is from a current OK section
  matches: boolean              // true only when the distance is known CURRENT and zero
  ciOk: boolean                 // current green, not a stale CI receipt
  ciCurrent: boolean
  stop: boolean | null          // null = the STOP latch was not read (not "off")
  unknown: string | null        // a sentence naming what could not be read, or null when everything is known
  recommend: string
}

export function coachFacts(args: {
  inFlight: { ready_count?: number | null; count?: number | null; freshness?: string } | null
  next: NextRelease | null
  stopEffective: boolean | null
  /** The next_release section state; defaults to OK so callers that only have the value stay honest. */
  nextFreshness?: Freshness
  /** The in-flight request state (useApi stale/error included); defaults to OK. */
  inFlightFreshness?: Freshness
}): CoachFacts {
  const { inFlight, next, stopEffective } = args
  const nextFresh: Freshness = args.nextFreshness ?? 'OK'
  const inFlightFresh: Freshness = inFlight == null ? 'UNAVAILABLE'
    : inFlight.freshness && inFlight.freshness !== 'OK' ? (inFlight.freshness === 'UNAVAILABLE' ? 'UNAVAILABLE' : 'STALE')
    : args.inFlightFreshness && args.inFlightFreshness !== 'OK' ? args.inFlightFreshness : 'OK'
  const inFlightCurrent = inFlight != null && inFlightFresh === 'OK'
  const ready = inFlightCurrent && inFlight.ready_count != null ? inFlight.ready_count : null
  const open = inFlightCurrent && inFlight.count != null ? inFlight.count : null
  const ahead = next == null ? null : next.is_serving ? 0 : (next.commits_ahead ?? null)
  const aheadCurrent = next != null && nextFresh === 'OK'
  const ciCurrent = aheadCurrent && next?.ci?.stale !== true
  const ciOk = ciCurrent && (next?.ci?.state === 'SUCCESS' || next?.ci?.state === 'OK')
  const missing: string[] = []
  if (inFlight == null) missing.push('the open-PR board')
  else if (!inFlightCurrent) missing.push(`a current open-PR board (the last read is ${inFlightFresh === 'UNAVAILABLE' ? 'unavailable' : 'stale'})`)
  else if (ready == null) missing.push('its READY count')
  if (next == null) missing.push('the next-release comparison')
  else if (!aheadCurrent) missing.push(`a current next-release comparison (the last read is ${nextFresh === 'UNAVAILABLE' ? 'unavailable' : 'stale'})`)
  else if (ahead == null) missing.push('how far main is ahead of the site')
  if (stopEffective == null) missing.push('the deploy STOP latch')
  const unknown = missing.length
    ? `Could not read ${missing.join(' or ')} — this strip is not saying "nothing needs you"; refresh before acting.`
    : null

  let recommend: string
  if (ready == null) {
    recommend = unknown ?? 'The READY count is not stated — refresh before approving anything.'
  } else if (ready > 0) {
    recommend = `${ready} change${ready === 1 ? '' : 's'} ready for your Approve (Job A). Approving queues a merge — it does not update the live site.`
  } else if (stopEffective === true) {
    recommend = 'Deploy STOP is on — Job B (put on site) is blocked until STOP is cleared in Ops → Controls.'
  } else if (stopEffective == null) {
    recommend = 'The deploy STOP state was not read — check Ops → Controls before Job B (put main on the site).'
  } else if (!aheadCurrent) {
    recommend = `The site-vs-main comparison is ${nextFresh === 'UNAVAILABLE' ? 'unavailable' : 'stale'} — refresh before promoting; this is not a "site matches main".`
  } else if (ahead == null) {
    recommend = unknown ?? 'Main-vs-site distance is not stated — the site may be behind main.'
  } else if (ahead > 0 && ciOk) {
    recommend = `main is ${ahead} commit${ahead === 1 ? '' : 's'} ahead of the site — Job B: promote when you are ready (or wait for auto-promote).`
  } else if (ahead > 0) {
    recommend = 'main is ahead of the site, but main CI is not green — wait for green before promote.'
  } else {
    recommend = 'Nothing needs you right now — the site is serving main and no PR is READY.'
  }
  return { ready, open, ahead, aheadCurrent, matches: ahead === 0 && aheadCurrent, ciOk, ciCurrent, stop: stopEffective, unknown, recommend }
}

/**
 * Job B's promote-readiness facts. Kept pure so an unread comparison or an unread STOP latch cannot be
 * rendered as green by a default in the JSX (cx-openai-4 R1/R2 at 8cd7fee69).
 */
export type PromoteFacts = {
  ahead: number | null          // retained distance; may be historical when aheadCurrent is false
  aheadCurrent: boolean
  matches: boolean              // current, measured zero
  ciGreen: boolean              // current green
  ciCurrent: boolean
  stop: boolean | null          // null = the STOP latch was not read (not "off")
  promoteReady: boolean         // false unless every ingredient is CURRENT and STOP is measured off
  headline: string
  badge: string
  badgeTone: Tone
  unknown: string | null
}

export function promoteFacts(args: {
  next: NextRelease | null
  stopEffective: boolean | null
  nextFreshness?: Freshness
}): PromoteFacts {
  const { next, stopEffective } = args
  const fresh: Freshness = args.nextFreshness ?? 'OK'
  const ahead = next == null ? null : next.is_serving ? 0 : (next.commits_ahead ?? null)
  const aheadCurrent = next != null && fresh === 'OK'
  const ciCurrent = aheadCurrent && next?.ci?.stale !== true
  const ciGreen = ciCurrent && (next?.ci?.state === 'SUCCESS' || next?.ci?.state === 'OK')
  const ciPending = ciCurrent && next?.ci?.state === 'PENDING'
  const matches = ahead === 0 && aheadCurrent
  const promoteReady = stopEffective === false && aheadCurrent && ahead != null && ahead > 0 && ciGreen
  const missing: string[] = []
  if (next == null) missing.push('the next-release comparison')
  else if (!aheadCurrent) missing.push(`a current next-release comparison (the last read is ${fresh === 'UNAVAILABLE' ? 'unavailable' : 'stale'})`)
  else if (ahead == null) missing.push('how far main is ahead of the site')
  if (stopEffective == null) missing.push('the deploy STOP latch')
  const unknown = missing.length
    ? `Could not read ${missing.join(' or ')} — not saying the site is aligned; refresh before promoting.`
    : null

  let headline: string
  if (stopEffective === true) {
    headline = 'Deploy STOP is latched — promote to the live site is blocked.'
  } else if (next == null) {
    headline = 'The next-release comparison was not read — cannot say whether the site and main are aligned.'
  } else if (!aheadCurrent) {
    headline = `The site-vs-main comparison is ${fresh === 'UNAVAILABLE' ? 'unavailable' : 'stale'} — not saying they are aligned; refresh before promoting.`
  } else if (ahead == null) {
    headline = 'How far main is ahead of the site is not stated — the site may be behind main.'
  } else if (ahead > 0 && ciGreen && stopEffective === false) {
    headline = `${ahead} commit${ahead === 1 ? '' : 's'} on main are not on the site yet — ready to promote when you choose.`
  } else if (ahead > 0 && ciGreen) {
    headline = `main is ${ahead} commit${ahead === 1 ? '' : 's'} ahead and CI is green, but the deploy STOP state was not read — check Ops → Controls before promote.`
  } else if (ahead > 0 && ciPending) {
    headline = 'main is ahead of the site, but exact-SHA CI on main is still pending.'
  } else if (ahead > 0) {
    headline = 'main is ahead of the site, but main CI is not green yet — wait before promote.'
  } else if (stopEffective == null) {
    headline = 'The site is serving main, but the deploy STOP state was not read — check before trusting auto-promote.'
  } else {
    headline = 'Site and main look aligned — nothing waiting to promote.'
  }

  const badge = promoteReady ? 'promote candidate'
    : stopEffective === true ? 'STOP'
      : !aheadCurrent || ahead == null ? 'unknown'
        : stopEffective == null ? 'STOP not read'
          : ahead === 0 ? 'serving main' : 'waiting'
  const badgeTone: Tone = promoteReady ? 'info' : stopEffective === true ? 'danger' : 'neutral'
  return { ahead, aheadCurrent, matches, ciGreen, ciCurrent, stop: stopEffective, promoteReady, headline, badge, badgeTone, unknown }
}
