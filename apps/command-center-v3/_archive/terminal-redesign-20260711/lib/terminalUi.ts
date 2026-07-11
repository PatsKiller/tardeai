/** Global Bloomberg Terminal UI mode for CC v3. Toggle off to restore legacy chrome (archived 2026-07-11). */
import { useEffect, useState } from 'react'

export const TERMINAL_UI_KEY = 'cc.terminal.ui'
export const TERMINAL_UI_EVENT = 'cc-terminal-ui'

export function readTerminalUi(): boolean {
  try {
    const v = localStorage.getItem(TERMINAL_UI_KEY)
    if (v === '0' || v === 'false') return false
    return true
  } catch {
    return true
  }
}

export function writeTerminalUi(on: boolean): void {
  try {
    localStorage.setItem(TERMINAL_UI_KEY, on ? '1' : '0')
    window.dispatchEvent(new CustomEvent(TERMINAL_UI_EVENT, { detail: on }))
  } catch { /* private mode */ }
}

export function useTerminalUi(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(readTerminalUi)
  useEffect(() => {
    const onCustom = (e: Event) => setOn(!!(e as CustomEvent).detail)
    const onStorage = (e: StorageEvent) => { if (e.key === TERMINAL_UI_KEY) setOn(e.newValue !== '0' && e.newValue !== 'false') }
    window.addEventListener(TERMINAL_UI_EVENT, onCustom)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(TERMINAL_UI_EVENT, onCustom)
      window.removeEventListener('storage', onStorage)
    }
  }, [])
  return [on, writeTerminalUi]
}