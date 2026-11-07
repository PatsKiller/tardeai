// FQ-051: the Source clocks panel answers one question — is this source still being refreshed, and what it costs if not.
//
// The writer's own state code is not the answer a person reads; it moves into the Diagnostics disclosure. What stays on the
// panel is one sentence per state. Mapping only four of the five declared states, and letting the rest fall through to
// "State unavailable", states something untrue: PAUSED and NONE are both read successfully, and both are answers.
//
// ACTIVE is a registry state, not proof of execution. Rendered tests also check the actual panel labels.
export type DeskWriterState = 'ACTIVE' | 'PAUSED' | 'RETIRED' | 'NONE' | null | undefined

/** The one sentence the panel shows for a writer state. Null/unknown is the only case that is genuinely unreadable. */
export function writerStateWords(state: DeskWriterState, loading = false): string {
  switch (state) {
    case 'ACTIVE': return 'Enabled'
    case 'PAUSED': return 'Paused — not refreshing this source'
    case 'RETIRED': return 'Retired — not refreshing this source'
    case 'NONE': return 'No writer is scheduled for this source'
    default: return loading ? 'Checking' : 'State unavailable'
  }
}

/** The newest successful run among a source's writers (ISO instant), or null. Used as the headline clock when the page
 *  supplies no update time of its own: it is labelled as the writer's run, never as the source's update time. */
export function newestWriterRun(writers: ReadonlyArray<{ last_success_at?: string | null } | undefined>): string | null {
  let best: string | null = null, bestAt = -Infinity
  for (const w of writers) {
    const v = w?.last_success_at
    if (!v || !/T.*(?:Z|[+-]\d\d:\d\d)$/.test(v)) continue
    const at = Date.parse(v)
    if (Number.isFinite(at) && at > bestAt) { best = v; bestAt = at }
  }
  return best
}
