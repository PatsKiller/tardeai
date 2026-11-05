// FQ-092 (HQ-08): a market-movers capture must show its DATE and AGE, not just a clock time.
//
// Measured on the served release 105df180e: the board rendered `(captured_at || '').slice(11, 16)` + "Z" — e.g.
// "finviz elite capture 17:45Z" — so a capture from three days ago and one from twelve minutes ago produced the same
// words. The live capture was fresh (12 min) when measured, so this is a latent defect: the same code path is what
// renders an old capture as if it were today's.
//
// The eliteness of the source does not make its value current. Age is always shown; a capture older than the RTH
// cadence is marked stale rather than printed as a bare time.

export const RTH_CADENCE_MINUTES = 12
export const STALE_AFTER_MINUTES = 30

export type CaptureStamp = {
  /** Full timestamp as the source recorded it (UTC), or the honest statement that it did not. */
  at: string
  /** "12 min old" / "3 h old" / "2 d old"; null when undatable. */
  age: string | null
  /** True when the value must not read as current: undatable, or older than the stale threshold. */
  stale: boolean
}

function parse(value: string | null | undefined): Date | null {
  const text = String(value ?? '').trim()
  if (!text) return null
  const d = new Date(text)
  return Number.isNaN(d.getTime()) ? null : d
}

function ageWords(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} min old`
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h old`
  return `${Math.round(minutes / (24 * 60))} d old`
}

export function captureStamp(capturedAt: string | null | undefined, nowMs: number = Date.now()): CaptureStamp {
  const d = parse(capturedAt)
  if (!d) return { at: 'capture time not recorded', age: null, stale: true }
  const minutes = (nowMs - d.getTime()) / 60_000
  const future = minutes < -5
  const at = `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)}Z`
  if (future) return { at, age: 'time is in the future', stale: true }
  return { at, age: ageWords(Math.max(0, minutes)), stale: minutes > STALE_AFTER_MINUTES }
}

/** The one line the board prints about its source. Never a bare clock time. */
export function captureLine(capturedAt: string | null | undefined, nowMs: number = Date.now()): { text: string; stale: boolean } {
  const s = captureStamp(capturedAt, nowMs)
  const age = s.age ? ` · ${s.age}` : ''
  return { text: `finviz elite capture ${s.at}${age}`, stale: s.stale }
}
