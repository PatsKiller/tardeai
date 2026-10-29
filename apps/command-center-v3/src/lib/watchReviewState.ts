import type { ReviewState } from './watchProspectsModel.ts'

const stamp = (s?: ReviewState | null) => Math.max(...[s?.updated_at, s?.last_attempt?.at, s?.queued_at]
  .map(v => v ? Date.parse(v) : NaN).filter(Number.isFinite), 0)

/** The original queue/attempt clocks order states; polling time never does. */
export function newerReviewState(served?: ReviewState | null, local?: ReviewState | null): ReviewState | null {
  if (!served) return local || null
  if (!local) return served
  if (served.request_id && local.request_id && served.request_id !== local.request_id) {
    const a = Date.parse(served.queued_at || ''), b = Date.parse(local.queued_at || '')
    return Number.isFinite(a) && (!Number.isFinite(b) || a > b) ? served : local
  }
  return stamp(served) >= stamp(local) ? served : local
}
