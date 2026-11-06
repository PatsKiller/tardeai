/**
 * Source-clock attribution for /risk Exposure (operator finding FQ-112; review of PR 2641 at 4e9dad0a5 by
 * cx-openai-3, P2 F1/F2).
 *
 * What the positions clock actually is: `positions.as_of` is the positions snapshot's evidence clock —
 * `positions_built_at` when the loader stamped one, otherwise the oldest contributing data clock. It is
 * NOT a writer-event timestamp, and nothing here says which lane wrote the file.
 *
 * So the note names the CONFIGURED source lanes (what the source registry declares for this source) and
 * describes the clock by that basis. It does not assert a writer, and it makes no claim about a lane's
 * last run: the DeskPage source row renders that from the execution evidence (`desk_sources`) beside
 * this note, and a second, frozen statement of it here can contradict that evidence. Unknown provenance
 * stays unknown.
 */
import { fmtAsOf } from './asOfDisplay.ts'

/** The lanes the source registry configures for the positions source — configuration, not provenance. */
export const POSITION_WRITER_LANES = ['schwab-position-sync', 'snaptrade-sync'] as const

export function positionWriterNote(asOf: unknown): string | null {
  const lanes = POSITION_WRITER_LANES.join(' / ')
  const at = typeof asOf === 'string' && Number.isFinite(Date.parse(asOf)) ? fmtAsOf(asOf) : null
  if (at) {
    return `The positions snapshot is dated ${at}. Its configured source lanes are ${lanes}; that date is `
      + 'the positions evidence clock, not a record of which lane wrote the file or when it last ran.'
  }
  return `The positions snapshot carries no recorded clock. Its configured source lanes are ${lanes}; `
    + 'which lane wrote the file, and when it last ran, is not recorded here.'
}
