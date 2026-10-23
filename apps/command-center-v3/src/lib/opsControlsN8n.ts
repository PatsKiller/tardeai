// Ops → Controls · n8n lanes dashboard (feat/ops-controls-n8n-outcomes-20261022).
// Operator 2026-10-22: "Why do some of these say live? Some of them say dry runs. I don't know if the last one was
// success or failure. This is not a real dashboard... When is everything going live?"
// This module turns one GET /state n8n row (docs/ops/OPS_CONTROLS_API.md; the server's additive `outcome` and
// `readiness` blocks from scripts/lib/ops_controls_n8n_outcomes.py) into plain words: what the lane does today, how its
// last run went, when it runs next, and whether the documented ladder lets it climb. Pure: no React, no DOM, no fetch.
// The server decides every verdict; nothing here re-derives health or readiness. An older server (no `outcome`) degrades
// to "not measured", never to a green.
import type { N8nRow } from './opsControls'

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'
export type Health = 'OK' | 'FAILING' | 'STALE' | 'NEVER_RAN' | 'OFF' | 'UNKNOWN'
export type Verdict = 'READY_FOR_CANARY' | 'READY_FOR_CUTOVER' | 'NOT_READY' | 'BLOCKED' | 'CUT_OVER' | 'N_A'
export type N8nFilter = 'all' | 'failing' | 'ready' | 'shadow' | 'live'

export type LastRun = { run_id?: string; mode?: string; outcome?: string; exit_code?: number | null; reason?: string | null; at?: string }
export type Outcome = {
  effective_mode?: 'off' | 'dry_run' | 'live' | 'unknown'
  health?: Health; health_reason?: string | null
  last_run?: LastRun | null; last_run_at?: string | null; last_outcome?: string | null
  last_success_at?: string | null; last_live_success_at?: string | null
  failures_24h?: number; failures_7d?: number
  runs_7d?: { dry_run?: number; live?: number; other?: number }
  outcomes_7d?: Record<string, number>
  dead_letters_open?: number; breaker_open?: boolean
  next_run_at?: string | null; schedule?: string[]; tz?: string
}
export type Readiness = {
  verdict: Verdict; target?: 'canary' | 'cutover' | null
  missing?: string[]; blocked_by?: string[]; evidence?: string[]; owed?: string[]
  p1_last?: boolean; risk_tier?: number; risk_tier_name?: string; sender?: boolean
}
export type N8nRowX = N8nRow & {
  registry_state?: string | null; scheduler_kind?: string | null; dispatch_class?: string | null
  outcome?: Outcome; readiness?: Readiness
}
export type N8nSummary = {
  live_healthy: number; live_failing: number; rehearsing: number; ready_to_promote: number; never_ran: number
  off?: number; cut_over?: number
}

// ── glossary: what each word on the tab means (accurate to the platform, AGENTS.md §23.11/§23.12/§23.21) ─────────────
export const GLOSSARY: Record<string, string> = {
  shadow: 'Rehearsing. n8n runs the lane with its dry-run argument — it computes and checks but writes nothing and sends nothing — while the cron line keeps doing the real work. The shadow stage forces dry_run whatever the mode says.',
  canary: 'Live, watched. The cron line is still there and n8n also fires the lane live; both take the same lock, so only one runs per slot (the other records SKIPPED). A canary lane runs live only if it is on the live list — otherwise n8n still runs it as a dry run.',
  cutover: 'Fully moved to n8n. The cron line was commented out as “# RETIRED … n8n-cutover” and kept as the rollback; n8n’s dispatcher is the only scheduler.',
  native: 'An n8n-native workflow (no stage): n8n owns it outright and there is no cron twin.',
  dry_run: 'dry_run: the lane runs with its dry-run argument. Write-free by contract (no DB write, no file, no send, no model call).',
  live: 'live: a real run — it writes its output the way the cron job would.',
  live_list: 'The relay live list (TRADEAI_N8N_RELAY_LIVE_LANES in ~/.config/tradeai/n8n-live-lanes.env). The relay refuses a live fire for any lane not on it, and the dispatcher posts that lane’s slots as dry_run. Adding or removing a lane is a passkey action.',
  promotion: 'Promotion is an operator decision made by a reviewed registry PR (AGENTS.md §23.11). This column only shows the evidence. Shadow → canary needs a REVIEWED health contract, an allowlist entry, a clean n8n dry run and the cron line’s flock lock equal to the allowlist lock. Canary → cutover (§23.21) needs the defect fixed, a clean dry run, the lane’s regression tests, and at least one successful live n8n run with the cron line present under the shared lock that advanced its output (a SKIPPED run does not count). No number of soak days is required.',
}

export type StageView = { label: string; tone: Tone; tip: string; key: 'shadow' | 'canary' | 'canary_dry' | 'cutover' | 'native' | 'off' | 'unknown' }
/** The stage in plain words, corrected by what a fire actually does today (effective_mode). */
export function stageView(r: N8nRowX): StageView {
  const eff = r.outcome?.effective_mode
  const st = String(r.stage || '')
  if (eff === 'off' || (r.registry_state && r.registry_state !== 'ACTIVE') || r.mode === 'off') {
    const why = r.registry_state && r.registry_state !== 'ACTIVE' ? `registry ${r.registry_state}` : 'dispatch mode off'
    return { key: 'off', label: `Off — ${why}`, tone: 'neutral', tip: `Not dispatched: ${why}.` }
  }
  if (st === 'shadow') return { key: 'shadow', label: 'Rehearsing — not doing real work yet', tone: 'info', tip: GLOSSARY.shadow }
  if (st === 'canary') {
    if (eff === 'dry_run' || r.on_live_list === false) {
      return { key: 'canary_dry', label: 'Canary on paper — not on the live list, still a dry run', tone: 'warning', tip: `${GLOSSARY.canary} This lane is not on the live list.` }
    }
    return { key: 'canary', label: 'Live, watched (canary)', tone: 'success', tip: GLOSSARY.canary }
  }
  if (st === 'cutover') return { key: 'cutover', label: 'Fully moved to n8n', tone: 'success', tip: GLOSSARY.cutover }
  if (!st && r.scheduler_kind === 'n8n') {
    return eff === 'live' || r.on_live_list
      ? { key: 'native', label: 'n8n-native — live', tone: 'success', tip: GLOSSARY.native }
      : { key: 'native', label: 'n8n-native — dry run', tone: 'info', tip: GLOSSARY.native }
  }
  return { key: 'unknown', label: st ? `Stage ${st}` : 'No stage', tone: 'neutral', tip: 'The registry row names no known stage.' }
}

// ── time ───────────────────────────────────────────────────────────────────────────────────────────────────────────
export function timeAgo(iso: string | null | undefined, nowMs: number): string | null {
  const t = Date.parse(String(iso ?? ''))
  if (!Number.isFinite(t)) return null
  const s = Math.round((nowMs - t) / 1000)
  if (s < 0) return timeUntil(iso, nowMs)
  if (s < 60) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}
export function timeUntil(iso: string | null | undefined, nowMs: number): string | null {
  const t = Date.parse(String(iso ?? ''))
  if (!Number.isFinite(t)) return null
  const s = Math.round((t - nowMs) / 1000)
  if (s <= 60) return 'now'
  const m = Math.round(s / 60)
  if (m < 60) return `in ${m} min`
  const h = Math.round(m / 60)
  if (h < 48) return `in ${h} h`
  return `in ${Math.round(h / 24)} d`
}
export function etTime(iso: string | null | undefined): string | null {
  const t = Date.parse(String(iso ?? ''))
  if (!Number.isFinite(t)) return null
  return new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET'
}

// ── last run / health ─────────────────────────────────────────────────────────────────────────────────────────────
export type LastRunView = { icon: '✓' | '✗' | '↷' | '·' | '?'; text: string; tone: Tone; tip: string }
export function lastRunView(r: N8nRowX, nowMs: number): LastRunView {
  const o = r.outcome
  if (!o || o.health === 'UNKNOWN') return { icon: '?', text: 'not measured', tone: 'neutral', tip: o?.health_reason || 'This server does not report run outcomes yet.' }
  const lr = o.last_run
  if (!lr) return { icon: '·', text: 'never ran', tone: o.health === 'OFF' ? 'neutral' : 'warning', tip: 'No run of this lane in the n8n coordination ledger.' }
  const ago = timeAgo(lr.at, nowMs) || String(lr.at || '')
  const mode = lr.mode === 'dry_run' ? 'dry run' : lr.mode === 'live' ? 'live' : String(lr.mode || '')
  const tipBase = `${lr.outcome}${lr.reason ? ` — ${lr.reason}` : ''} · ${mode} · ${etTime(lr.at) || lr.at} · ${lr.run_id || ''}`.trim()
  if (lr.outcome === 'SUCCESS') return { icon: '✓', text: `${ago} · ${mode}`, tone: 'success', tip: tipBase }
  if (lr.outcome === 'SKIPPED') {
    return { icon: '↷', text: `${ago} · skipped`, tone: 'neutral', tip: `${tipBase}. Skipped because the other scheduler held the shared lock — expected at canary; not a failure, and not a live proof.` }
  }
  return { icon: '✗', text: `${ago} · ${String(lr.outcome || 'failed').toLowerCase()}`, tone: 'danger', tip: tipBase }
}

export const HEALTH_VIEW: Record<Health, { label: string; tone: Tone; tip: string }> = {
  OK: { label: 'OK', tone: 'success', tip: 'Last run succeeded (or was a lock skip), no open dead letter or breaker, and no scheduled slot has gone unanswered.' },
  FAILING: { label: 'Failing', tone: 'danger', tip: 'The last run failed or timed out, a dead-lettered slot is not released, or the circuit breaker is open.' },
  STALE: { label: 'Stale', tone: 'warning', tip: 'A slot the schedule says should have run (45 min grace) has no run in the ledger.' },
  NEVER_RAN: { label: 'Never ran', tone: 'warning', tip: 'Active in the registry but no run in the n8n coordination ledger.' },
  OFF: { label: 'Off', tone: 'neutral', tip: 'Not dispatched (registry state not ACTIVE, or dispatch mode off).' },
  UNKNOWN: { label: 'Not measured', tone: 'neutral', tip: 'The coordination ledger could not be read; nothing is assumed.' },
}
export function healthView(r: N8nRowX) {
  const h = (r.outcome?.health || 'UNKNOWN') as Health
  const v = HEALTH_VIEW[h] || HEALTH_VIEW.UNKNOWN
  return { ...v, health: h, reason: r.outcome?.health_reason || null }
}

/** "3 failed in 24 h · 5 in 7 d" or null when clean. */
export function failuresBadge(r: N8nRowX): { text: string; tone: Tone } | null {
  const d1 = r.outcome?.failures_24h ?? 0, d7 = r.outcome?.failures_7d ?? 0
  if (!d7) return null
  return { text: d1 ? `${d1} failed in 24 h · ${d7} in 7 d` : `${d7} failed in 7 d`, tone: d1 ? 'danger' : 'warning' }
}

export function runsText(r: N8nRowX): string | null {
  const x = r.outcome?.runs_7d
  if (!x) return null
  return `${x.live ?? 0} live · ${x.dry_run ?? 0} dry`
}

export function nextRunView(r: N8nRowX, nowMs: number): { text: string; tip: string } | null {
  const o = r.outcome
  if (!o || o.effective_mode === 'off') return null
  if (!o.next_run_at) return { text: o.schedule?.length ? '—' : 'event-driven', tip: o.schedule?.length ? `No fire in the next 8 days for ${o.schedule.join(', ')}.` : 'No cron schedule on the registry row (the workflow runs on its own trigger).' }
  return { text: `${timeUntil(o.next_run_at, nowMs) || ''} · ${etTime(o.next_run_at) || ''}`.trim(), tip: `Next fire of ${(o.schedule || []).join(', ')} (${o.tz || 'America/New_York'}).` }
}

// ── promotion readiness ───────────────────────────────────────────────────────────────────────────────────────────
export function readinessView(r: N8nRowX): { label: string; tone: Tone; tip: string } {
  const x = r.readiness
  if (!x) return { label: '—', tone: 'neutral', tip: 'This server does not report promotion readiness yet.' }
  const list = (a?: string[]) => (a || []).map(s => `• ${s}`).join('\n')
  switch (x.verdict) {
    case 'READY_FOR_CANARY': return { label: 'Ready for canary', tone: 'info', tip: `Every documented shadow → canary condition is met.\n${list(x.evidence)}\nStill the operator’s call: a reviewed registry PR.` }
    case 'READY_FOR_CUTOVER': return { label: 'Ready for cutover', tone: 'info', tip: `Every measurable §23.21 condition is met.\n${list(x.evidence)}\nOwed in the cutover PR:\n${list(x.owed)}` }
    case 'NOT_READY': return { label: `Not ready · ${(x.missing || []).length} missing`, tone: 'warning', tip: `Missing for ${x.target}:\n${list(x.missing)}` }
    case 'BLOCKED': return { label: 'Blocked', tone: 'danger', tip: `Cannot climb until resolved:\n${list(x.blocked_by)}${(x.missing || []).length ? `\nAlso missing:\n${list(x.missing)}` : ''}` }
    case 'CUT_OVER': return { label: 'Done', tone: 'success', tip: 'Already cut over to n8n. Natural-schedule evidence is monitored, not awaited (§23.12).' }
    default: return { label: '—', tone: 'neutral', tip: 'Not on the shadow → canary → cutover ladder (n8n-native workflow or no stage).' }
  }
}

// ── filters + summary ────────────────────────────────────────────────────────────────────────────────────────────
export const N8N_FILTERS: Array<[N8nFilter, string]> = [
  ['all', 'All'], ['failing', 'Failing'], ['ready', 'Ready to promote'], ['shadow', 'Shadow'], ['live', 'Live'],
]
export function isFailing(r: N8nRowX): boolean {
  const h = r.outcome?.health
  return h === 'FAILING' || h === 'STALE'
}
export function isReady(r: N8nRowX): boolean {
  const v = r.readiness?.verdict
  return v === 'READY_FOR_CANARY' || v === 'READY_FOR_CUTOVER'
}
export function matchesN8nFilter(r: N8nRowX, f: N8nFilter): boolean {
  switch (f) {
    case 'failing': return isFailing(r)
    case 'ready': return isReady(r)
    case 'shadow': return r.stage === 'shadow' || r.outcome?.effective_mode === 'dry_run'
    case 'live': return r.outcome?.effective_mode === 'live'
    default: return true
  }
}
export function n8nFilterCounts(rows: N8nRowX[]): Record<N8nFilter, number> {
  const out = { all: 0, failing: 0, ready: 0, shadow: 0, live: 0 } as Record<N8nFilter, number>
  for (const r of rows) for (const [k] of N8N_FILTERS) if (matchesN8nFilter(r, k)) out[k]++
  return out
}
export function matchesN8nQuery(r: N8nRowX, q: string): boolean {
  const s = q.trim().toLowerCase()
  return !s || r.lane_id.toLowerCase().includes(s)
}

/** The server's summary when present; otherwise the same rules over the rows (an older server has neither). */
export function summaryOf(rows: N8nRowX[], server?: Partial<N8nSummary> | null): N8nSummary | null {
  if (server && typeof server.live_healthy === 'number') return server as N8nSummary
  if (!rows.some(r => r.outcome)) return null
  const s: N8nSummary = { live_healthy: 0, live_failing: 0, rehearsing: 0, ready_to_promote: 0, never_ran: 0 }
  for (const r of rows) {
    const eff = r.outcome?.effective_mode, h = r.outcome?.health
    if (eff === 'live' && h === 'OK') s.live_healthy++
    else if (eff === 'live' && (h === 'FAILING' || h === 'STALE')) s.live_failing++
    if (eff === 'dry_run') s.rehearsing++
    if (isReady(r)) s.ready_to_promote++
    if (h === 'NEVER_RAN') s.never_ran++
  }
  return s
}

/** Sort: failing first, then ready to promote, then by lane id. */
export function sortRows(rows: N8nRowX[]): N8nRowX[] {
  const rank = (r: N8nRowX) => (isFailing(r) ? 0 : r.outcome?.health === 'NEVER_RAN' && r.outcome?.effective_mode !== 'off' ? 1 : isReady(r) ? 2 : r.outcome?.effective_mode === 'off' ? 4 : 3)
  return [...rows].sort((a, b) => rank(a) - rank(b) || a.lane_id.localeCompare(b.lane_id))
}
