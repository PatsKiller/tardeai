/** Theme (dark | light | system) — PR1, 2026-09-27.
 *
 * The choice is written to <html data-theme="…"> (tokens.css keys off it), remembered per
 * viewer in localStorage, and persisted server-side through the existing /api/v2/ui/prefs
 * store (key "ui.theme") so it follows the operator across devices. "system" removes the
 * attribute and lets prefers-color-scheme decide. Rollback: force "dark" and today's look
 * returns exactly (the dark values are today's palette).
 */
import { useCallback, useEffect, useState } from 'react'
import type { ThemeName } from '../lib/designTokens'

export type ThemeChoice = ThemeName | 'system'
const LS_KEY = 'cc.ui.theme'
const PREF_KEY = 'ui.theme'
const EVENT = 'cc-ui-theme'

function readLocal(): ThemeChoice {
  try {
    const v = localStorage.getItem(LS_KEY)
    if (v === 'dark' || v === 'light' || v === 'system') return v
  } catch { /* private mode */ }
  return 'dark'
}

export function applyTheme(choice: ThemeChoice) {
  const el = document.documentElement
  if (choice === 'system') delete el.dataset.theme
  else el.dataset.theme = choice
}

/** Resolved theme (what is actually rendering), for chart hex lookups. */
export function resolvedTheme(choice: ThemeChoice): ThemeName {
  if (choice !== 'system') return choice
  try { return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark' } catch { return 'dark' }
}

/** Call once at app start (main.tsx) so the first paint is already themed. */
export function initTheme() {
  applyTheme(readLocal())
  // Server preference wins when it exists (async; a later paint is acceptable).
  fetch('/api/v2/ui/prefs/get?key=' + encodeURIComponent(PREF_KEY))
    .then(r => (r.ok ? r.json() : null))
    .then(j => {
      const v = j && (j.value ?? j.pref ?? j.data)
      if (v === 'dark' || v === 'light' || v === 'system') {
        try { localStorage.setItem(LS_KEY, v) } catch { /* ignore */ }
        applyTheme(v)
        window.dispatchEvent(new CustomEvent(EVENT, { detail: v }))
      }
    })
    .catch(() => { /* offline: local choice stands */ })
}

export function useTheme(): [ThemeChoice, (c: ThemeChoice) => void, ThemeName] {
  const [choice, setChoice] = useState<ThemeChoice>(readLocal)
  useEffect(() => {
    const onEvent = (e: Event) => setChoice((e as CustomEvent).detail)
    window.addEventListener(EVENT, onEvent)
    return () => window.removeEventListener(EVENT, onEvent)
  }, [])
  const set = useCallback((c: ThemeChoice) => {
    try { localStorage.setItem(LS_KEY, c) } catch { /* ignore */ }
    applyTheme(c)
    setChoice(c)
    window.dispatchEvent(new CustomEvent(EVENT, { detail: c }))
    fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: PREF_KEY, value: c }) }).catch(() => { /* best effort */ })
  }, [])
  return [choice, set, resolvedTheme(choice)]
}
