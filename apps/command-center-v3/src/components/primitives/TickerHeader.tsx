/** TickerHeader (PR2, 2026-09-27): company name large and bold, then ticker · sector ·
 *  industry · market cap, status chips, and the quick sentiment score. Fed by the
 *  `identity` / `status_chips` / `sentiment` block the API adds in PR3. */
import type { CSSProperties, ReactNode } from 'react'
import { TOKENS, TYPE, type Tone } from '../../lib/designTokens'
import { Chip, ChipRow } from './Chip'
import { Metric } from './Metric'

export type TickerIdentity = { symbol: string; name?: string | null; sector?: string | null; industry?: string | null; market_cap?: string | number | null; exchange?: string | null }
export type StatusChip = { label: string; tone: Tone; guideKey?: string }
export type Sentiment = { score: number; label?: string; tone: Tone; as_of?: string | null; provenance?: string | null }

function fmtCap(v: string | number | null | undefined): string | null {
  if (v === null || v === undefined || v === '') return null
  if (typeof v === 'string') return v
  const a = Math.abs(v)
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `$${(v / 1e6).toFixed(0)}M`
  return `$${v}`
}

export function TickerHeader({ identity, status = [], sentiment, asOf, right, children, style }: {
  identity: TickerIdentity
  status?: StatusChip[]
  sentiment?: Sentiment | null
  asOf?: string | null
  right?: ReactNode
  children?: ReactNode
  style?: CSSProperties
}) {
  const sub = [identity.symbol, identity.exchange, identity.sector, identity.industry, fmtCap(identity.market_cap)].filter(Boolean).join(' · ')
  return (
    <header style={{ display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap', ...style }}>
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ fontSize: TYPE.lg, fontWeight: 900, color: TOKENS.text[0], lineHeight: 1.15 }}>
          {identity.name || identity.symbol}
        </div>
        <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2], marginTop: 2 }}>{sub}</div>
        {status.length > 0 && (
          <ChipRow style={{ marginTop: 6 }}>
            {status.map((c, i) => <Chip key={i} tone={c.tone} guideKey={c.guideKey}>{c.label}</Chip>)}
          </ChipRow>
        )}
        {children}
      </div>
      {sentiment && (
        <Metric guideKey="sentiment.score" label="Sentiment" value={`${Math.round(sentiment.score)}${sentiment.label ? ` · ${sentiment.label}` : ''}`}
          tone={sentiment.tone} size="hero" asOf={sentiment.as_of || asOf || undefined} provenance={sentiment.provenance || undefined} />
      )}
      {right && <div onClick={e => e.stopPropagation()}>{right}</div>}
    </header>
  )
}
