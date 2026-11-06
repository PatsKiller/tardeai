// FQ-056 / FQ-057 (/reports C + E) — the report card in ordinary language.
//
// Measured live 2026-11-04 on the served release: /api/v2/reports/catalog returns 10 report types;
// 4 are `never-generated` (aegis_morning_brief, weekly_review, enterprise_reports, live_readiness),
// and every card printed `t.generator` verbatim — "system_rollup_snapshot.py (20:40 nightly)",
// "portfolio_orchestrator (07:30 controller)" — script identifiers and controller shorthand. A
// never-run card said "NEVER RUN" and a dash, with no explanation and nothing to do next.

export function cadenceWords(cadence: string | null | undefined): string {
  switch (String(cadence || '').toLowerCase()) {
    case 'daily': return 'Every day'
    case 'weekly': return 'Every week'
    case 'monthly': return 'Every month'
    case 'on-event': return 'When an event occurs'
    default: return 'Schedule not stated'
  }
}

/** A time in the generator string, in words. Never claims a time zone the data does not carry. */
export function scheduleWords(generator: string | null | undefined): string | null {
  const m = String(generator || '').match(/\b([01]?\d|2[0-3]):([0-5]\d)\b/)
  if (!m) return null
  return `around ${m[1].padStart(2, '0')}:${m[2]}`
}

/** The run state a catalog entry actually carries, or null when it carries none. Nothing is inferred. */
export type RunState = 'disabled' | 'awaiting-first-run' | 'failing' | null

export function runStateOf(row: any): RunState {
  if (!row || typeof row !== 'object') return null
  if (row.disabled === true || row.enabled === false) return 'disabled'
  const status = String(row.last_run_status || row.last_status || '').toLowerCase()
  if (row.last_error || ['failed', 'failure', 'error', 'timeout'].includes(status)) return 'failing'
  if (row.scheduled === true || row.next_run_at) return 'awaiting-first-run'
  return null
}

/** What a never-generated card can honestly say, and where the operator can look.
 *
 * The catalog does not always carry a run state (measured 2026-11-04: the four never-generated types carry
 * status, cadence, generator and an empty history — nothing about disabled/failing). When it does, say which
 * it is; when it does not, say that it does not rather than guessing one of the three.
 */
export function neverRunText(state: RunState = null): string {
  if (state === 'disabled') {
    return 'This report is switched off, so it will not run. Turn it back on where its schedule is managed.'
  }
  if (state === 'failing') {
    return 'This report has never been produced and its last attempt failed. Check Ops → Jobs for the failure.'
  }
  if (state === 'awaiting-first-run') {
    return 'This report is scheduled but has not produced its first run yet. Ops → Jobs shows when it is next due.'
  }
  return 'No report has been produced yet, and the catalog records no run state, so it is not possible to say ' +
    'whether this is switched off, waiting for a first run, or failing. Ops → Jobs is where that state would appear.'
}
