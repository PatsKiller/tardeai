import type { RotationAvailability } from './rotationPublication'

export type ExpiryHost = {
  now: () => number
  setTimer: (callback: () => void, delayMs: number) => number
  clearTimer: (id: number) => void
  onFocus: (callback: () => void) => () => void
  onVisibility: (callback: () => void) => () => void
}

// Refresh the display at its proof deadline and on return to a background tab.
export function observeRotationExpiry(value: RotationAvailability, refresh: () => void, host: ExpiryHost): () => void {
  const stopFocus = host.onFocus(refresh)
  const stopVisibility = host.onVisibility(refresh)
  let timer: number | null = null
  let stopped = false
  function schedule() {
    if (stopped || !value.ready || value.expiresAtMs === null) return
    timer = host.setTimer(() => {
      if (stopped) return
      // Recheck validity as well as expiry: a clock before checked_at is invalid.
      refresh()
      // Browser timers use elapsed time; a wall-clock correction can make this
      // callback early. Keep a deadline check scheduled until the proof expires.
      if (host.now() <= value.expiresAtMs!) schedule()
    }, Math.max(1, value.expiresAtMs - host.now() + 1))
  }
  schedule()
  return () => {
    stopped = true
    if (timer !== null) host.clearTimer(timer)
    stopFocus()
    stopVisibility()
  }
}
