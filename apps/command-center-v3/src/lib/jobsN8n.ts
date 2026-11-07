// Ops › Jobs & n8n (design pages/jobs v002, operator-approved 2026-11-06, asks 1-2). One read-only page for "did it
// run, did it fail, did it get fixed": five tabs over two existing GETs — /api/v2/jobs-history (run history, the same
// wire /ops/jobs reads) and /api/v2/ops/controls/state (n8n.summary + lane rows) — plus the incident list
// (/api/v2/ops/incidents). Pure: no React, no DOM, no fetch. Nothing here writes; the switches stay in Ops Controls.
import type { HistoryFilter, HistoryListWire } from './jobRunHistory.ts'
import {
  healthView, isFailing, isReady, lastRunView, nextRunView, readinessView, stageView, type N8nRowX, type N8nSummary, type Tone,
} from './opsControlsN8n.ts'

export const JOBS_N8N_PATH = '/ops/jobs-n8n'
export const OPS_CONTROLS_PATH = '/system/ops-controls'

export type JobsN8nTab = 'needs' | 'all' | 'n8n' | 'incidents' | 'fixes'
export const JOBS_N8N_TABS: ReadonlyArray<readonly [JobsN8nTab, string]> = [
  ['needs', 'Needs you'], ['all', 'All jobs'], ['n8n', 'n8n lanes'], ['incidents', 'Incidents'], ['fixes', 'Fixes'],
] as const

/** `?tab=` → a known tab; anything else (absent, typo, old link) opens the default "Needs you". */
export function resolveJobsN8nTab(raw: string | null | undefined): JobsN8nTab {
  const t = String(raw ?? '').trim().toLowerCase()
  return (JOBS_N8N_TABS.find(([k]) => k === t)?.[0]) ?? 'needs'
}

/** The run-history filter each job tab reads. "All jobs" starts on all and offers the scheduler filters. */
export const TAB_HISTORY_FILTER: Record<'needs' | 'all' | 'fixes', HistoryFilter> = { needs: 'attention', all: 'all', fixes: 'fixed' }
export const ALL_JOBS_FILTERS: ReadonlyArray<readonly [HistoryFilter, string]> = [
  ['all', 'All'], ['n8n', 'n8n'], ['cron', 'Host cron'], ['systemd', 'systemd'], ['other', 'Event / none'],
] as const

/** "Needs you · 22". A count shows only once it was read; an unread count is left off, never shown as 0. */
export function tabLabel(label: string, count: number | null | undefined): string {
  return typeof count === 'number' && Number.isFinite(count) ? `${label} · ${count}` : label
}

/** Tiles for the job tabs, from the jobs-history summary. A missing key renders "—", never 0. */
/** `key` is the `?status=` value the tile filters to (tapping it again clears it). */
export type Tile = { label: string; value: number | null; tone: Tone; key?: string }
export function historyTiles(s: HistoryListWire['summary'] | null | undefined, tab: 'needs' | 'all' | 'fixes'): Tile[] {
  const v = (k: string): number | null => (s && typeof s[k] === 'number' ? s[k] : null)
  if (tab === 'fixes') {
    return [
      { label: 'Fixed · 14 d', value: v('fixed_14d'), tone: 'success', key: 'fixed' },
      { label: 'Failed now', value: v('failed'), tone: 'danger', key: 'failed' },
      { label: 'Missed a run', value: v('with_missed'), tone: 'warning', key: 'missed' },
    ]
  }
  return [
    { label: 'Failed', value: v('failed'), tone: 'danger', key: 'failed' },
    { label: 'Missed a run', value: v('with_missed'), tone: 'warning', key: 'missed' },
    { label: 'Late', value: v('late'), tone: 'warning', key: 'late' },
    { label: 'Ran OK', value: v('ok'), tone: 'success', key: 'ok' },
    { label: 'Ran, unproven', value: v('ok_unverified'), tone: 'neutral', key: 'ok_unverified' },
    { label: 'Fixed · 14 d', value: v('fixed_14d'), tone: 'success', key: 'fixed' },
  ]
}

// ── n8n lanes tab ───────────────────────────────────────────────────────────────────────────────────────────────
/** The six lane tiles in the mockup's order. Cut over comes from the server summary or the rows' stage. */
export function n8nTiles(summary: N8nSummary | null, rows: N8nRowX[]): Tile[] {
  const cutOver = typeof summary?.cut_over === 'number' ? summary.cut_over : rows.length ? rows.filter(r => r.stage === 'cutover').length : null
  return [
    { label: 'Live, healthy', value: summary?.live_healthy ?? null, tone: 'success', key: 'live_healthy' },
    { label: 'Live, failing', value: summary?.live_failing ?? null, tone: 'danger', key: 'live_failing' },
    { label: 'Rehearsing', value: summary?.rehearsing ?? null, tone: 'info', key: 'rehearsing' },
    { label: 'Cut over', value: cutOver, tone: 'neutral', key: 'cut_over' },
    { label: 'Ready to promote', value: summary?.ready_to_promote ?? null, tone: 'info', key: 'ready_to_promote' },
    { label: 'Never ran', value: summary?.never_ran ?? null, tone: 'warning', key: 'never_ran' },
  ]
}

/** The n8n tile keys (`?status=` on the n8n lanes tab). */
export const N8N_STATUS_KEYS = ['live_healthy', 'live_failing', 'rehearsing', 'cut_over', 'ready_to_promote', 'never_ran'] as const
export type N8nStatusKey = typeof N8N_STATUS_KEYS[number]
export const isN8nStatus = (s: string | null | undefined): s is N8nStatusKey => !!s && (N8N_STATUS_KEYS as readonly string[]).includes(s)
/** A lane is in a tile's set by the same rules summaryOf counts it (so the list length equals the tile). */
export function matchesN8nStatus(r: N8nRowX, key: N8nStatusKey): boolean {
  const eff = r.outcome?.effective_mode, h = r.outcome?.health
  switch (key) {
    case 'live_healthy': return eff === 'live' && h === 'OK'
    case 'live_failing': return eff === 'live' && (h === 'FAILING' || h === 'STALE')
    case 'rehearsing': return eff === 'dry_run'
    case 'cut_over': return r.stage === 'cutover'
    case 'ready_to_promote': return isReady(r)
    case 'never_ran': return h === 'NEVER_RAN'
  }
}

/** "71 of 131 lanes run for real through n8n; 54 rehearse (dry run) while cron still does the work; 16 are fully cut
 *  over." Counted from the rows' effective mode and stage; null when no row reports an outcome (nothing is assumed). */
export function moveToN8nSentence(rows: N8nRowX[]): string | null {
  if (!rows.length || !rows.some(r => r.outcome)) return null
  const live = rows.filter(r => r.outcome?.effective_mode === 'live').length
  const dry = rows.filter(r => r.outcome?.effective_mode === 'dry_run').length
  const cut = rows.filter(r => r.stage === 'cutover').length
  return `${live} of ${rows.length} lanes run for real through n8n; ${dry} rehearse (dry run) while cron still does the work; ${cut} ${cut === 1 ? 'is' : 'are'} fully cut over (cron line removed).`
}

/** One lane as a phone card: stage, health, last/next run and, in plain words, why it is not live or not healthy. */
export type LaneCard = {
  id: string; stage: { label: string; tone: Tone }; health: { label: string; tone: Tone }
  liveList: { label: string; tone: Tone }
  lastRun: { text: string; tone: Tone }; nextRun: string | null; promotion: { label: string; tone: Tone }
  why: string | null
}
export function laneCard(r: N8nRowX, nowMs: number): LaneCard {
  const st = stageView(r), hv = healthView(r), lr = lastRunView(r, nowMs), nx = nextRunView(r, nowMs), rv = readinessView(r)
  const exclusion = r.on_live_list === false ? (r.live_exclusion_text || r.live_exclusion || null) : null
  const blocked = r.readiness?.blocked_by?.[0]
  const why = exclusion ? `Not on the live list: ${exclusion}`
    : isFailing(r) && hv.reason ? hv.reason
      : blocked ? `Blocked: ${blocked}` : null
  return {
    id: r.lane_id,
    stage: { label: st.label, tone: st.tone },
    health: { label: hv.label, tone: hv.tone },
    liveList: r.on_live_list === true ? { label: 'On live list', tone: 'info' }
      : r.on_live_list === false ? { label: 'Not live', tone: 'neutral' } : { label: 'Live list unknown', tone: 'neutral' },
    lastRun: { text: lr.icon === '?' ? 'Not measured' : lr.text, tone: lr.tone },
    nextRun: nx?.text ?? null,
    promotion: { label: rv.label, tone: rv.tone },
    why,
  }
}

/** Phone list order: failing first, then never ran, ready to promote, the rest, off last (opsControlsN8n.sortRows). */
export { sortRows as sortLanes, matchesN8nFilter, matchesN8nQuery, N8N_FILTERS, n8nFilterCounts, summaryOf } from './opsControlsN8n.ts'
