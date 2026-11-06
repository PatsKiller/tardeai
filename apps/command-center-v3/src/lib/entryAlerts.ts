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

/** The identity of one entry-alert card: (symbol, account), never the bare symbol.
 *
 *  FQ-096 made the packet index serve one row per (symbol, account), so two accounts can hold a packet for the same
 *  symbol in the same state. Keying the lane by symbol alone collapsed the second card into the first (React keeps one
 *  child per key), and the Alerts Center ids collided the same way (codex-cloud P1 at buy_ready_packets_index). */
export function entryRowKey(row: { symbol?: string | null; account?: string | null } | null | undefined): string {
  const sym = String(row?.symbol ?? '').trim().toUpperCase()
  const acct = String(row?.account ?? '').trim()
  return acct ? `${sym}|${acct}` : sym
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
