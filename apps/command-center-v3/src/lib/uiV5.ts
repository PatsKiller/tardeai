/** ui_v5 — the runtime toggle for the 2026-09 redesign (rollback layer 1).
 *
 * Same shape as cardsV4.ts: a redesigned surface renders the new component only when this
 * is on and falls back to the pre-redesign component otherwise, so turning it off restores
 * the old UI for everyone without a release. Sources, in order: `?ui=v4` / `?ui=v5` in the
 * URL (per tab), localStorage (per viewer), the server pref "ui.v5" (per operator). Default
 * OFF until PR4 ships a surface; each phase flips its own surfaces behind this flag.
 */
import { useEffect, useState } from 'react'

const LS_KEY = 'cc.ui.v5'
const PREF_KEY = 'ui.v5'
const EVENT = 'cc-ui-v5'

export function readUiV5(): boolean {
  try {
    const q = new URLSearchParams(window.location.search).get('ui')
    if (q === 'v4') return false
    if (q === 'v5') return true
    return localStorage.getItem(LS_KEY) === '1'
  } catch { return false }
}

export function writeUiV5(on: boolean) {
  try { localStorage.setItem(LS_KEY, on ? '1' : '0') } catch { /* private mode */ }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: on }))
  fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key: PREF_KEY, value: on ? '1' : '0' }) }).catch(() => { /* best effort */ })
}

/** Call once at app start: adopt the server preference when the URL did not force one. */
export function initUiV5() {
  try {
    const q = new URLSearchParams(window.location.search).get('ui')
    if (q === 'v4' || q === 'v5') return
  } catch { return }
  fetch('/api/v2/ui/prefs/get?key=' + encodeURIComponent(PREF_KEY))
    .then(r => (r.ok ? r.json() : null))
    .then(j => {
      const v = j && (j.value ?? j.pref ?? j.data)
      if (v === '1' || v === '0') {
        try { localStorage.setItem(LS_KEY, v) } catch { /* ignore */ }
        window.dispatchEvent(new CustomEvent(EVENT, { detail: v === '1' }))
      }
    })
    .catch(() => { /* offline: local stands */ })
}

export function useUiV5(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState<boolean>(readUiV5)
  useEffect(() => {
    const onCustom = (e: Event) => setOn(!!(e as CustomEvent).detail)
    const onStorage = (e: StorageEvent) => { if (e.key === LS_KEY) setOn(e.newValue === '1') }
    window.addEventListener(EVENT, onCustom)
    window.addEventListener('storage', onStorage)
    return () => { window.removeEventListener(EVENT, onCustom); window.removeEventListener('storage', onStorage) }
  }, [])
  return [on, writeUiV5]
}
