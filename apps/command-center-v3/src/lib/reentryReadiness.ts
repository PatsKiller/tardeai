// Re-entry readiness in ordinary words (FQ-051).
//
// The page printed the writer's own codes as its operator text: the chip read BUY READY, the lane title announced
// "Telegram BUY_READY / ENTRY_NEAR", the summary counted "N buy-ready · M entry-near", and the empty state told the
// operator the runner "writes one per BUY_READY / ENTRY_NEAR symbol". Those are file-format names, not answers to the
// question the reader has ("is this ready to buy, or nearly?").
//
// The mapping is the only place the codes are interpreted. An unlisted state is NOT described as ready and NOT guessed
// into a neighbour's meaning — it says the page does not recognise it, and the code itself stays available as the chip's
// secondary detail.
export type Readiness = { words: string; recognises: boolean }

const WORDS: Record<string, string> = {
  BUY_READY: 'Ready to buy now',
  ENTRY_NEAR: 'Nearly at the entry zone',
  WATCH: 'Watching',
}

const clean = (v: unknown) => String(v ?? '').replace(/\s+/g, ' ').trim()

export function readinessOf(state: string | null | undefined): Readiness {
  const code = clean(state).toUpperCase()
  if (!code) return { words: 'No state recorded', recognises: false }
  const w = WORDS[code]
  return w ? { words: w, recognises: true } : { words: 'Unrecognised state', recognises: false }
}

/** The chip's words. Never the code itself. */
export function readinessWords(state: string | null | undefined): string {
  return readinessOf(state).words
}

/** The lane's own title: what the thing is, without the file-format names. */
export const LANE_TITLE = 'Entry alerts (buy-ready and entry-near packets)'

/** The one-line summary, in the reader's words rather than the writer's. */
export function readinessSummary(counts: Record<string, number> | null | undefined, rows: number): string {
  const c = counts ?? {}
  const ready = Number(c.BUY_READY ?? 0)
  const near = Number(c.ENTRY_NEAR ?? 0)
  const other = Math.max(0, rows - ready - near)
  const parts = [`${ready} ready to buy now`, `${near} nearly at the entry zone`]
  if (other > 0) parts.push(`${other} other`)
  return parts.join(' · ')
}

/** The empty state: what happened, not what the runner writes. */
export function emptyText(maxAgeHours: number | null | undefined): string {
  const h = typeof maxAgeHours === 'number' && Number.isFinite(maxAgeHours) ? `${maxAgeHours}h` : 'the window'
  return `No entry alert in the last ${h}. The entry runner saves one when a symbol becomes ready to buy or nears its entry zone.`
}
