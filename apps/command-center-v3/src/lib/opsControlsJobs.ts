// Ops → Controls · Jobs & schedules readability (feat/ops-controls-jobs-readability-20261022).
// Operator 2026-10-22: "I have no idea how to interpret this. Is this cron jobs that's been retired, active? Is this
// actually N8N? There are no tooltips." This module turns one GET /state jobs row (docs/ops/OPS_CONTROLS_API.md) into a
// plain-language status, flags rows where the live crontab and config/lane_registry.json disagree, and renders cron
// expressions in words. Pure module: no React, no DOM, no fetch. The server decides every action; nothing here does.
//
// Semantics mirrored from scripts/lib/ops_controls_api.py jobs_view() and scripts/lib/ops_controls_core.py:
//   cron_state ACTIVE    = exactly one uncommented crontab line contains the registry's scheduler.match text
//   cron_state PAUSED    = no active line, exactly one `# PAUSED <date> <note> <line>` comment matches
//   cron_state ABSENT    = no line at all (active or paused)
//   cron_state AMBIGUOUS = several lines match; the server will not pick one, so the page offers no action
//   registry_state       = what config/lane_registry.json declares (ACTIVE · PAUSED · RETIRED · NEVER_SCHEDULED)
// PAUSED_RE on the server is `^#\s*PAUSED\s+(date)\s+(\S+)\s+(.+)$`: the note is ONE token, and resume re-installs
// group 3 verbatim. A paused line whose note carries a parenthetical (`schwab-app-deactivated (incident SPCX) 31 9 …`)
// would resume as `(incident SPCX) 31 9 …`, which is not a cron line — so the page offers no Resume for it.
import type { JobRow } from './opsControls'

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'
export type JobCategory = 'running' | 'paused' | 'retired' | 'off' | 'unclear'
export type JobFilter = 'all' | 'running' | 'paused' | 'retired' | 'attention' | 'broker'

/** Optional additive fields (server ≥ this PR). Absent on an older server: classification degrades, never guesses. */
export type JobRowX = JobRow & {
  dispatch_mode?: string | null
  registry_since?: string | null
  registry_reason?: string | null
  match_counts?: { active: number; paused: number } | null
}

export type JobView = {
  category: JobCategory
  /** Plain-language status, e.g. "Running", "Paused since 2026-10-14 (schwab-app-deactivated (incident SPCX))". */
  label: string
  tone: Tone
  /** One-line why when the live crontab and the registry disagree; null when they agree. */
  mismatch: string | null
  /** Collapsed by default under "All": retired / never-scheduled rows with no line. */
  quiet: boolean
  /** Human schedule ("weekdays 09:07–16:52 every 15 min") or null when it cannot be read with confidence. */
  scheduleText: string | null
  /** The cron expression shown beside it (5 fields or @keyword), or null. */
  cronExpr: string | null
  /** Pause / Resume the page may offer; null = no button, with `actionNote` saying why. */
  action: 'pause' | 'resume' | null
  actionNote: string | null
  pausedReason: string | null
}

// ── cron parsing ───────────────────────────────────────────────────────────────────────────────────────────────────
const NAMES: Record<string, number> = {
  sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6,
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
}
const ATOM = '(?:\\*|\\d{1,2}|[A-Za-z]{3})(?:-(?:\\d{1,2}|[A-Za-z]{3}))?(?:/\\d{1,2})?'
const FIELD_RE = new RegExp(`^${ATOM}(?:,${ATOM})*$`)
const KEYWORDS = ['@reboot', '@yearly', '@annually', '@monthly', '@weekly', '@daily', '@midnight', '@hourly']

function isField(tok: string): boolean {
  if (!FIELD_RE.test(tok)) return false
  // A 3-letter word is only a field when it is a day or month name ("cd", "set" are not).
  return tok.split(/[,/-]/).every(p => p === '*' || /^\d+$/.test(p) || p.toLowerCase() in NAMES)
}

/** True when `text` starts with a cron schedule (5 valid fields, or an @keyword) — what cron itself would accept. */
export function startsWithCron(text: string | null | undefined): boolean {
  const toks = String(text ?? '').trim().split(/\s+/)
  if (KEYWORDS.includes((toks[0] || '').toLowerCase())) return true
  return toks.length >= 6 && toks.slice(0, 5).every(isField)
}

/** The first cron expression in a crontab line or a `# PAUSED …` comment (skips a paused note of any length). */
export function extractCronExpr(text: string | null | undefined): string | null {
  const toks = String(text ?? '').trim().split(/\s+/).filter(Boolean)
  for (let i = 0; i < toks.length; i++) {
    if (KEYWORDS.includes(toks[i].toLowerCase())) return toks[i].toLowerCase()
    if (i + 5 <= toks.length && toks.slice(i, i + 5).every(isField)) return toks.slice(i, i + 5).join(' ')
  }
  return null
}

function num(p: string): number | null {
  if (/^\d+$/.test(p)) return Number(p)
  const v = NAMES[p.toLowerCase()]
  return v === undefined ? null : v
}

/** Expand one cron field to its sorted values in [lo, hi]; null when it cannot be read. */
export function expandField(field: string, lo: number, hi: number): number[] | null {
  const out = new Set<number>()
  for (const part of field.split(',')) {
    const [rng, stepS] = part.split('/')
    const step = stepS === undefined ? 1 : Number(stepS)
    if (!Number.isInteger(step) || step < 1) return null
    let a: number | null, b: number | null
    if (rng === '*') { a = lo; b = hi }
    else if (rng.includes('-')) { const [x, y] = rng.split('-'); a = num(x); b = num(y) }
    else { a = num(rng); b = stepS === undefined ? a : hi }
    if (a === null || b === null || a < lo || b > hi + (hi === 6 ? 1 : 0) || a > b) return null
    for (let v = a; v <= b; v += step) out.add(hi === 6 && v === 7 ? 0 : v)
  }
  return [...out].sort((x, y) => x - y)
}

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const DOW_LONG = ['Sundays', 'Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays']
const MON = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const pad = (n: number) => String(n).padStart(2, '0')
const hm = (h: number, m: number) => `${pad(h)}:${pad(m)}`
const contiguous = (xs: number[]) => xs.length > 1 && xs.every((x, i) => i === 0 || x === xs[i - 1] + 1)
function uniformStep(xs: number[]): number | null {
  if (xs.length < 2) return null
  const d = xs[1] - xs[0]
  return xs.every((x, i) => i === 0 || x - xs[i - 1] === d) ? d : null
}

function daysPhrase(dom: string, mon: string, dow: string): string | null {
  const parts: string[] = []
  if (dow !== '*') {
    const d = expandField(dow, 0, 6)
    if (!d) return null
    const key = d.join(',')
    if (key === '1,2,3,4,5') parts.push('weekdays')
    else if (key === '0,6') parts.push('weekends')
    else if (d.length === 7) parts.push('every day')
    else if (d.length === 1) parts.push(DOW_LONG[d[0]])
    else if (contiguous(d)) parts.push(`${DOW[d[0]]}–${DOW[d[d.length - 1]]}`)
    else parts.push(d.map(x => DOW[x]).join(', '))
  }
  if (dom !== '*') {
    const d = expandField(dom, 1, 31)
    if (!d) return null
    parts.push(d.length === 1 ? `on day ${d[0]} of the month` : `on days ${d.join(', ')} of the month`)
  }
  if (mon !== '*') {
    const m = expandField(mon, 1, 12)
    if (!m) return null
    parts.push(`in ${m.map(x => MON[x]).join(', ')}`)
  }
  return parts.length ? parts.join(' ') : 'every day'
}

function timePhrase(minute: string, hour: string): string | null {
  const mins = expandField(minute, 0, 59)
  const hours = expandField(hour, 0, 23)
  if (!mins || !hours) return null
  const stepM = mins.length === 60 ? 1 : uniformStep(mins)
  const everyM = stepM !== null && mins[0] < stepM && mins[mins.length - 1] + stepM >= 60 // covers the whole hour
  const allHours = hours.length === 24
  if (allHours) {
    if (mins.length === 60) return 'every minute'
    if (mins.length === 1) return `every hour at :${pad(mins[0])}`
    if (everyM) return `every ${stepM} min${mins[0] ? ` (from :${pad(mins[0])})` : ''}`
    return `every hour at ${mins.map(m => ':' + pad(m)).join(', ')}`
  }
  const first = hm(hours[0], mins[0])
  const last = hm(hours[hours.length - 1], mins[mins.length - 1])
  if (contiguous(hours)) {
    if (mins.length === 1) return `hourly ${first}–${last}`
    if (mins.length === 60) return `every minute ${first}–${last}`
    if (everyM) return `${first}–${last} every ${stepM} min`
  }
  if (hours.length * mins.length <= 6) return `at ${hours.flatMap(h => mins.map(m => hm(h, m))).join(', ')}`
  const stepH = uniformStep(hours)
  if (stepH && mins.length === 1) return `every ${stepH} h at :${pad(mins[0])} (${first}–${last})`
  if (stepH && everyM) return `every ${stepM} min in hours ${hours.map(pad).join(', ')}`
  return null
}

/** "weekdays 09:07–16:52 every 15 min" for `7,22,37,52 9-16 * * 1-5`; null when not confidently readable. Host TZ is ET. */
export function humanizeCron(expr: string | null | undefined): string | null {
  const e = String(expr ?? '').trim().toLowerCase()
  if (!e) return null
  const kw: Record<string, string> = {
    '@reboot': 'once at host boot', '@yearly': 'yearly, Jan 1 00:00', '@annually': 'yearly, Jan 1 00:00',
    '@monthly': 'monthly, day 1 00:00', '@weekly': 'Sundays at 00:00', '@daily': 'every day at 00:00',
    '@midnight': 'every day at 00:00', '@hourly': 'every hour at :00',
  }
  if (e.startsWith('@')) return kw[e] ?? null
  const f = e.split(/\s+/)
  if (f.length !== 5 || !f.every(isField)) return null
  const days = daysPhrase(f[2], f[3], f[4])
  const time = timePhrase(f[0], f[1])
  if (!days || !time) return null
  if (days === 'every day' && time.startsWith('every')) return time
  return `${days} ${time}`
}

// ── paused-line parsing (mirrors PAUSED_RE, plus the human reason) ────────────────────────────────────────────────
export type PausedLine = { date: string; note: string; reason: string; serverRest: string; resumable: boolean }

/** Parse `# PAUSED <date> <note…> <cron line>`. `resumable` = the text the server would re-install is a cron line. */
export function parsePausedLine(display: string | null | undefined): PausedLine | null {
  const m = /^#\s*PAUSED\s+(\d{4}-\d{2}-\d{2})\s+(\S+)\s+(.+)$/.exec(String(display ?? '').trim())
  if (!m) return null
  const [, date, note, serverRest] = m
  // The human reason is everything between the date and the schedule (the note may carry "(incident …)").
  const toks = serverRest.split(/\s+/)
  let i = 0
  while (i < toks.length && !startsWithCron(toks.slice(i).join(' '))) i++
  const extra = i < toks.length ? toks.slice(0, i).join(' ') : ''
  const reason = note.startsWith('ops-controls:') ? `paused from this page (${note.slice('ops-controls:'.length, 'ops-controls:'.length + 8)})`
    : extra ? `${note} ${extra}` : note
  return { date, note, reason, serverRest, resumable: startsWithCron(serverRest) }
}

// ── classification ─────────────────────────────────────────────────────────────────────────────────────────────────
const REG_WORD: Record<string, string> = {
  ACTIVE: 'should run', PAUSED: 'is paused', RETIRED: 'is retired', NEVER_SCHEDULED: 'was never scheduled',
}

/** Classify one jobs row: plain status, mismatch (live crontab vs registry), action and schedule text. */
export function classifyJob(row: JobRowX): JobView {
  const reg = String(row.registry_state || '').toUpperCase() || null
  const regSays = reg ? (REG_WORD[reg] || `is ${reg}`) : null
  const counts = row.match_counts || null
  const n8nLive = String(row.dispatch_mode || '').toLowerCase() === 'live'
  const paused = parsePausedLine(row.display)
  // A live/paused line wins; otherwise the registry expression, which may join several schedules with " + ".
  const fromLine = extractCronExpr(row.display)
  const regParts = fromLine ? [] : String(row.schedule ?? '').split(/\s+\+\s+/).map(extractCronExpr)
  const cronExpr = fromLine ?? (regParts.length && regParts.every(Boolean) ? regParts.join(' + ') : null)
  const humanParts = fromLine ? [humanizeCron(fromLine)] : regParts.map(humanizeCron)
  const scheduleText = cronExpr && humanParts.every(Boolean) ? humanParts.join('; ') : null
  const base = { cronExpr, scheduleText, pausedReason: paused?.reason ?? (row.paused_note || null) }

  // live: what the crontab does right now
  let live: 'running' | 'paused' | 'off' | 'unclear'
  if (row.cron_state === 'ACTIVE') live = 'running'
  else if (row.cron_state === 'PAUSED') live = 'paused'
  else if (row.cron_state === 'ABSENT') live = 'off'
  else live = counts ? (counts.active > 0 ? 'running' : counts.paused > 0 ? 'paused' : 'unclear') : 'unclear'

  const ambiguous = row.cron_state === 'AMBIGUOUS'
  const nLines = counts ? (live === 'running' ? counts.active : counts.paused) : null
  const many = ambiguous ? ` · ${nLines ?? 'several'} matching cron lines` : ''

  let action: JobView['action'] = null
  let actionNote: string | null = null
  if (row.cron_state === 'ACTIVE' && row.line_sha256) action = 'pause'
  else if (row.cron_state === 'PAUSED' && row.line_sha256) {
    if (paused && !paused.resumable) actionNote = 'Resume at the host terminal: this paused line carries a multi-word note, and the page would re-install it as a broken cron line'
    else action = 'resume'
  } else if (ambiguous) actionNote = 'Several crontab lines match this job; the page will not pick one — change it at the host terminal'
  else if (row.cron_state === 'ABSENT') actionNote = 'No crontab line to pause or resume'
  else actionNote = 'No line hash from the server'

  if (live === 'running') {
    const mismatch = reg && reg !== 'ACTIVE' ? `Cron runs it, but the registry says it ${regSays}` : null
    return { ...base, category: 'running', tone: mismatch ? 'danger' : 'success', mismatch, quiet: false, action, actionNote,
      label: (mismatch ? `Running — but registry says it ${regSays}` : 'Running') + (n8nLive ? ' · n8n also dispatches it (live)' : '') + many }
  }
  if (live === 'paused') {
    const since = paused?.date || row.paused_on
    const why = paused?.reason || row.paused_note
    const lbl = `Paused${since ? ` since ${since}` : ''}${why ? ` (${why})` : ''}${many}`
    if (reg === 'ACTIVE') {
      return { ...base, category: 'paused', tone: 'danger', quiet: false, action, actionNote,
        mismatch: 'Commented out in the crontab, but the registry says it should run', label: `${lbl} — but registry says it should run` }
    }
    if (reg === 'RETIRED' || reg === 'NEVER_SCHEDULED') {
      return { ...base, category: 'retired', tone: 'neutral', quiet: false, mismatch: null, action, actionNote,
        label: `Retired — paused line still kept${since ? ` (since ${since})` : ''}` }
    }
    return { ...base, category: 'paused', tone: 'warning', mismatch: null, quiet: false, action, actionNote, label: lbl }
  }
  if (live === 'off') {
    if (reg === 'RETIRED') return { ...base, category: 'retired', tone: 'neutral', mismatch: null, quiet: true, action, actionNote, label: 'Retired (off on purpose)' }
    if (reg === 'NEVER_SCHEDULED') return { ...base, category: 'retired', tone: 'neutral', mismatch: null, quiet: true, action, actionNote, label: 'Never scheduled (no line expected)' }
    if (reg === 'PAUSED') return { ...base, category: 'paused', tone: 'warning', mismatch: null, quiet: false, action,
      actionNote: 'No crontab line: resuming means re-adding the line at the host terminal', label: 'Paused in the registry (no crontab line at all)' }
    if (reg === 'ACTIVE' && n8nLive) return { ...base, category: 'running', tone: 'info', mismatch: null, quiet: false, action,
      actionNote: 'Runs on n8n — see the n8n lanes tab', label: 'Runs on n8n (no crontab line)' }
    if (reg === 'ACTIVE') return { ...base, category: 'off', tone: 'danger', quiet: false, action, actionNote,
      mismatch: 'No crontab line, and n8n is not running it live, but the registry says it should run', label: 'Off — but registry says it should run' }
    return { ...base, category: 'off', tone: 'warning', mismatch: null, quiet: false, action, actionNote, label: 'Off (no crontab line)' }
  }
  return { ...base, category: 'unclear', tone: 'warning', mismatch: null, quiet: false, action, actionNote,
    label: 'Several crontab lines match — check at the host terminal' }
}

export const FILTERS: Array<[JobFilter, string]> = [
  ['all', 'All'], ['attention', 'Needs attention'], ['running', 'Running'], ['paused', 'Paused'], ['retired', 'Retired'], ['broker', 'Broker jobs'],
]

export function matchesFilter(row: JobRowX, v: JobView, f: JobFilter): boolean {
  switch (f) {
    case 'all': return true
    case 'attention': return v.mismatch !== null
    case 'running': return v.category === 'running'
    case 'paused': return v.category === 'paused'
    case 'retired': return v.category === 'retired'
    case 'broker': return !!row.broker_class
  }
}

export function filterCounts(rows: JobRowX[]): Record<JobFilter, number> {
  const out: Record<JobFilter, number> = { all: 0, attention: 0, running: 0, paused: 0, retired: 0, broker: 0 }
  for (const r of rows) {
    const v = classifyJob(r)
    for (const [f] of FILTERS) if (matchesFilter(r, v, f)) out[f]++
  }
  return out
}

/** Case-insensitive substring search on the job name. */
export function matchesQuery(row: JobRowX, q: string): boolean {
  const s = q.trim().toLowerCase()
  return !s || String(row.lane_id || '').toLowerCase().includes(s)
}
