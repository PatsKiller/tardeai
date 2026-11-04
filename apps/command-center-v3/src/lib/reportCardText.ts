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

/** What a never-generated card can honestly say, and where the operator can look. */
export function neverRunText(): string {
  return 'No report has been produced yet. If you expected one by now, check Ops → Jobs for this ' +
    'report\'s last scheduled run before treating it as a fault.'
}
