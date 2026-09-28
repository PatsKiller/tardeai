/** Entry alerts (repair 2026-09-28) — the pure half of EntryAlertsLane's options chip.
 *  The chip is green ONLY for a server status of OPTIONS_ALT_OK with a qualified count above
 *  zero; STALE_PRE_FIX / PACKET_UNVERIFIED are warnings that say "re-evaluate", never a
 *  suggestion. No React import so `node src/lib/entryAlerts.test.ts` runs it. */
import type { Tone } from './designTokens'

export type OptionsAltVerdict = {
  status?: string | null; reason?: string | null; detail?: string | null; qualified_count?: number | null; considered?: number | null
  gate_version?: string | null; evaluated_at?: string | null; strategy?: string | null
  claimed?: { status?: string | null; qualified?: string[] } | null
}

export function optionsAltChip(v: OptionsAltVerdict | null | undefined): { tone: Tone; label: string; title: string } {
  const status = String(v?.status || '').toUpperCase()
  const n = Number(v?.qualified_count || 0)
  const considered = v?.considered ? ` · ${v.considered} considered` : ''
  if (status === 'OPTIONS_ALT_OK' && n > 0) {
    return { tone: 'success', label: `options: ${n} qualified${v?.strategy ? ` (${String(v.strategy).replace(/_/g, ' ')})` : ''}${considered}`, title: `gate ${v?.gate_version || '?'} · evaluated ${v?.evaluated_at || '?'}` }
  }
  if (status === 'STALE_PRE_FIX') {
    const claimed = v?.claimed?.qualified?.length ? ` · file claimed ${v.claimed.qualified.length} qualified, not trusted` : ''
    return { tone: 'warning', label: `options: stale, pre-fix packet — re-evaluate${claimed}`, title: v?.reason || 'stored verdicts predate the running earnings gate' }
  }
  if (status === 'PACKET_UNVERIFIED') return { tone: 'warning', label: 'options: unverified — withheld', title: v?.reason || 'this build cannot verify the stored verdicts' }
  if (status === 'OPTIONS_ALT_OK' || status === 'OK') return { tone: 'neutral', label: `options: none qualified after checks${considered}`, title: v?.reason || '' }
  return { tone: 'neutral', label: `options: ${(v?.reason || status || 'not scanned').toLowerCase().replace(/_/g, ' ')}${considered}`, title: v?.detail || '' }
}
