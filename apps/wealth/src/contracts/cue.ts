// Status cue contract (John, 2026-11-14): GREEN/AMBER/RED must be meaningful, and colour is never
// the only carrier. A cue that has no text label, icon or tooltip cannot be built.
export type CueLevel = 'GREEN' | 'AMBER' | 'RED' | 'NEUTRAL'

export interface Cue {
  level: CueLevel
  /** Visible text. Required: colour is never the only signal. */
  label: string
  /** Icon token; rendered alongside the label. */
  icon: 'ok' | 'caution' | 'alert' | 'info' | 'unassessed'
  /** Tooltip: why this level, against what evidence or benchmark, and as of when. */
  tooltip: string
}

export function cue(level: CueLevel, label: string, icon: Cue['icon'], tooltip: string): Cue {
  if (!label.trim()) throw new Error('cue: label is required (colour is never the only signal)')
  if (!tooltip.trim()) throw new Error('cue: tooltip is required')
  return { level, label, icon, tooltip }
}
