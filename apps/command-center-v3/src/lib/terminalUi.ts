/** Bloomberg Terminal UI — always on for CC v3 (no toggle). Legacy fallbacks live in _archive/terminal-redesign-20260711. */
import { useEffect, useState } from 'react'

export const TERMINAL_UI_KEY = 'cc.terminal.ui'
export const TERMINAL_UI_EVENT = 'cc-terminal-ui'

/** Terminal density is the only shipped chrome; localStorage override removed. */
export function readTerminalUi(): boolean {
  return true
}

export function writeTerminalUi(_on: boolean): void {
  /* no-op — terminal is always on */
}

export function useTerminalUi(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(true)
  useEffect(() => {
    try { localStorage.removeItem(TERMINAL_UI_KEY) } catch { /* private mode */ }
  }, [])
  return [on, writeTerminalUi]
}