/** The null-rendering primitive for the Defense Desk redesign — the `unk` class
 * from the visual contract §3.
 *
 * A null renders as italic dim "unknown" with its reason on hover. NEVER an
 * em-dash, never a zero, never a blank. That contract exists because the page it
 * replaces shipped `breadth 55% (56/— covered)` — a missing denominator rendered
 * as punctuation inside an otherwise confident sentence.
 *
 * Note the distinction the contract draws and this component preserves: an
 * ABSENT VALUE is `unk`. An absence of COMMENTARY — the Read column when no rule
 * fires — is an empty cell, because there is nothing missing.
 */
import type { ReactNode } from 'react'
import { S } from '../../../lib/defenseRedesign'

export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

export function Unk({ reason }: { reason?: string | null }) {
  return (
    <span
      title={reason || 'no source for this value'}
      style={{ color: S.t3, fontStyle: 'italic', fontSize: 12 }}
    >
      unknown
    </span>
  )
}

export function Val({ value, fmt, suffix = '', reason }: {
  value: number | null | undefined
  fmt?: (v: number) => string
  suffix?: string
  reason?: string | null
}): ReactNode {
  if (!isNum(value)) return <Unk reason={reason} />
  const f = fmt || ((v: number) => v.toFixed(1))
  return <>{f(value)}{suffix}</>
}

export const pct = (v: number, d = 1) => `${v > 0 ? '+' : ''}${v.toFixed(d)}%`
export const signColor = (v: unknown) =>
  !isNum(v) ? S.t3 : v > 0 ? S.green : v < 0 ? S.red : S.t2
export const compact = (v: unknown): string | null =>
  !isNum(v) ? null
    : v >= 1e9 ? `${(v / 1e9).toFixed(1)}B`
      : v >= 1e6 ? `${Math.round(v / 1e6)}M`
        : v >= 1e3 ? `${Math.round(v / 1e3)}K`
          : String(v)
export const money = (v: unknown): string | null =>
  !isNum(v) ? null : v >= 1000 ? `$${Math.round(v / 1000)}K` : `$${Math.round(v)}`
