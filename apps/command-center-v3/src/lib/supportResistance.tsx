import { useEffect, useState } from 'react'
import { BB } from './holdingsTerminalTokens'
import { fmt$ } from './format'

/**
 * One closed-session support/resistance read, shared by Portfolio, Re-Entry, Defense,
 * Watch and Proposals so every desk quotes the same level. Source is the cache the
 * Re-Entry rotation gates already use, so a level shown next to a position is the same
 * level a gate would test — not a second opinion computed a different way.
 *
 * Levels are advisory evidence. An intraday cross is never a hold or a break.
 */
export const RESISTANCE_KEY = 'portfolio.reentry.resistance.v1'

export interface LevelRow {
  state?: string
  resistance?: number | null
  distance_pct?: number | null
  hold_days?: number | null
  support_state?: string
  support?: number | null
  support_distance_pct?: number | null
  support_hold_days?: number | null
}

export type LevelMap = Record<string, LevelRow>

let cached: { at: number; map: LevelMap } | null = null

/** Fetches the level cache once per 5 minutes per tab, shared across all callers. */
export function useLevels(): LevelMap {
  const [map, setMap] = useState<LevelMap>(() => cached?.map ?? {})
  useEffect(() => {
    let alive = true
    if (cached && Date.now() - cached.at < 300_000) { setMap(cached.map); return }
    fetch(`/api/v2/ui/prefs/get?key=${encodeURIComponent(RESISTANCE_KEY)}`)
      .then(response => response.json())
      .then(payload => {
        const value = payload?.value ?? payload?.data?.value ?? {}
        const next: LevelMap = value?.symbols && typeof value.symbols === 'object' ? value.symbols : {}
        cached = { at: Date.now(), map: next }
        if (alive) setMap(next)
      })
      .catch(() => { /* levels are advisory; absence degrades to no line, never an error */ })
    return () => { alive = false }
  }, [])
  return map
}

function tone(state: string | undefined, kind: 'resistance' | 'support'): string {
  const value = String(state || '').toUpperCase()
  if (value === 'TESTING') return BB.amberAlt
  if (kind === 'resistance') return value === 'ABOVE' ? BB.green : value === 'BELOW' ? BB.red : BB.text3
  return value === 'ABOVE' ? BB.green : value === 'BROKEN' ? BB.red : BB.text3
}

function pct(value: number | null | undefined): string {
  return value == null || !Number.isFinite(Number(value)) ? '' : `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(1)}%`
}

/**
 * Compact `R $x +y%` / `S $x +y%` pair. Renders nothing when the symbol has no
 * closed-session series — a missing level stays missing rather than showing a zero.
 */
export function LevelLines({ symbol, row, fontSize = 10 }: { symbol: string; row?: LevelRow; fontSize?: number }) {
  const resistance = row?.resistance == null ? null : Number(row.resistance)
  const support = row?.support == null ? null : Number(row.support)
  const hasR = resistance !== null && Number.isFinite(resistance)
  const hasS = support !== null && Number.isFinite(support)
  if (!hasR && !hasS) return null
  const base: React.CSSProperties = { fontSize, color: BB.text3, whiteSpace: 'nowrap', lineHeight: 1.35 }
  return (
    <>
      {hasR && (
        <div
          style={base}
          title={`${symbol}: closed-session resistance ${fmt$(resistance!, 2)}${row?.distance_pct == null ? '' : ` · price ${pct(row.distance_pct)} versus it`}${row?.hold_days ? ` · held above ${row.hold_days} closes` : ''}. Intraday crosses never count. Advisory only.`}
        >
          R {fmt$(resistance!, 2)} <span style={{ color: tone(row?.state, 'resistance'), fontWeight: 800 }}>{pct(row?.distance_pct)}</span>
        </div>
      )}
      {hasS && (
        <div
          style={base}
          title={`${symbol}: closed-session support ${fmt$(support!, 2)}${row?.support_distance_pct == null ? '' : ` · price ${pct(row.support_distance_pct)} versus it`}${row?.support_hold_days ? ` · broken for ${row.support_hold_days} closes` : ''}. Intraday undercuts never count. Advisory only.`}
        >
          S {fmt$(support!, 2)} <span style={{ color: tone(row?.support_state, 'support'), fontWeight: 800 }}>{pct(row?.support_distance_pct)}</span>
        </div>
      )}
    </>
  )
}
