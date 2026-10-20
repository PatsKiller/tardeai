import { useEffect, useState } from 'react'
import { rotationAvailability } from '../lib/rotationPublication'
import { observeRotationExpiry } from '../lib/rotationExpiry'

export function useRotationAvailability(summary: unknown, error?: unknown) {
  const [, update] = useState(0)
  const value = rotationAvailability(summary, error)
  useEffect(() => observeRotationExpiry(value, () => update(n => n + 1), {
    now: Date.now,
    setTimer: (callback, delay) => window.setTimeout(callback, delay),
    clearTimer: id => window.clearTimeout(id),
    onFocus: callback => {
      window.addEventListener('focus', callback)
      return () => window.removeEventListener('focus', callback)
    },
    onVisibility: callback => {
      document.addEventListener('visibilitychange', callback)
      return () => document.removeEventListener('visibilitychange', callback)
    },
  }), [summary, error, value.ready, value.expiresAtMs])
  return value
}
