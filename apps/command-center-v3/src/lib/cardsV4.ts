import { useEffect, useState } from 'react'

// Card family v4 — single GLOBAL evaluation toggle (operator decision 2026-07-04).
// One preference drives every surface that has a v4 variant (watchlist, broker
// proposals, open-trades positions, options desk). v3/current stays the default
// until the operator locks a winner. Reads legacy 'wl.card.v4' once as a migration.

const KEY = 'cc.cards.v4'
const LEGACY_KEY = 'wl.card.v4'

export function readCardsV4(): boolean {
  // v4 LOCKED as the approved format for all card surfaces (operator decision
  // 2026-07-04 evening) — default ON; the toggle remains only as a reference
  // escape hatch back to v3 during the transition.
  try {
    const v = localStorage.getItem(KEY)
    if (v != null) return v === '1'
    const legacy = localStorage.getItem(LEGACY_KEY)
    if (legacy != null) return legacy === '1'
    return true
  } catch {
    return true
  }
}

export function writeCardsV4(on: boolean) {
  try {
    localStorage.setItem(KEY, on ? '1' : '0')
    localStorage.removeItem(LEGACY_KEY)
    window.dispatchEvent(new CustomEvent('cc-cards-v4', { detail: on }))
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

/** Shared toggle UI — identical chrome on every hub that has a v4 variant. */
export const cardsV4ToggleTitle = 'Card design version — global evaluation toggle (v3/current stays default until locked)'
