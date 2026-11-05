// FQ-051: the Source clocks panel answers one question — is this source still being refreshed, and what it costs if not.
//
// The writer's own state code is not the answer a person reads; it moves into the Diagnostics disclosure. What stays on the
// panel is one sentence per state. Mapping only four of the five declared states, and letting the rest fall through to
// "State unavailable", states something untrue: PAUSED and NONE are both read successfully, and both are answers.
//
// Kept as a pure function so every declared state is provable without rendering the page.
export type DeskWriterState = 'ACTIVE' | 'PAUSED' | 'RETIRED' | 'NONE' | null | undefined

/** The one sentence the panel shows for a writer state. Null/unknown is the only case that is genuinely unreadable. */
export function writerStateWords(state: DeskWriterState, loading = false): string {
  switch (state) {
    case 'ACTIVE': return 'Refreshing'
    case 'PAUSED': return 'Paused — not refreshing this source'
    case 'RETIRED': return 'Retired — not refreshing this source'
    case 'NONE': return 'No writer is scheduled for this source'
    default: return loading ? 'Checking' : 'State unavailable'
  }
}
