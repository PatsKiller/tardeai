/**
 * Source-clock attribution for /risk Exposure (operator finding FQ-112).
 *
 * The position sync lanes are cron lanes; their registry output_signal is `file_mtime`, which the
 * desk-sources projection refuses by design, and the n8n ledger holds no runs for them. So the clock
 * can honestly say "no run receipt recorded" — but a bare "not measured" left the operator unable to
 * tell WHICH writer produced the 11:30 positions. This note names the writing lanes and the time the
 * source was written (the positions `as_of`), beside that honest gap. It never claims a successful
 * run that the evidence does not record.
 */
import { fmtAsOf } from './asOfDisplay.ts'

export const POSITION_WRITER_LANES = ['schwab-position-sync', 'snaptrade-sync'] as const

export function positionWriterNote(asOf: unknown): string | null {
  const lanes = POSITION_WRITER_LANES.join(' / ')
  if (typeof asOf === 'string' && Number.isFinite(Date.parse(asOf))) {
    const at = fmtAsOf(asOf)
    if (at) {
      return `Written by the position sync lanes (${lanes}) at ${at}. `
        + 'The lane’s own run receipt is not recorded, so its last successful run cannot be confirmed; '
        + 'the source clock above is the time the positions were written.'
    }
  }
  // The writer is still identifiable when the source clock is missing; say exactly what is missing.
  return `Written by the position sync lanes (${lanes}). The source has no recorded write time, and the `
    + 'lane’s own run receipt is not recorded, so its last successful run cannot be confirmed.'
}
