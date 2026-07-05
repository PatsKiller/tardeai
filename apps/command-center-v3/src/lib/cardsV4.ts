import { useEffect, useState } from 'react'

// Card family v4 — LIVE for all surfaces (operator decision 2026-07-05).
// Watchlist, broker proposals, open-trades positions, and options desk all
// render v4 unconditionally. v3 components remain in-tree for reference only.

const KEY = 'cc.cards.v4'

export function readCardsV4(): boolean {
  return true
}

export function writeCardsV4(on: boolean) {
  if (!on) return
  try {
    localStorage.setItem(KEY, '1')
    window.dispatchEvent(new CustomEvent('cc-cards-v4', { detail: true }))
  } catch { /* private mode */ }
}

/** Global v3/v4 card preference — stays in sync across hubs in the same tab
 *  (custom event) and across tabs (storage event). */
export function useCardsV4(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState<boolean>(readCardsV4)
  useEffect(() => {
    const onCustom = (e: Event) => setOn(!!(e as CustomEvent).detail)
    const onStorage = (e: StorageEvent) => { if (e.key === KEY) setOn(e.newValue === '1') }
    window.addEventListener('cc-cards-v4', onCustom)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener('cc-cards-v4', onCustom)
      window.removeEventListener('storage', onStorage)
    }
  }, [])
  return [on, writeCardsV4]
}

/** Badge copy — v4 is live; v3 escape hatch removed. */
export const cardsV4ToggleTitle = 'Card v4 — live on all desk surfaces'
