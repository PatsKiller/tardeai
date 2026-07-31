/**
 * Lazy re-entry levels chart (WP-R2 lite).
 * Uses Finviz Elite chart image proxy — no fan-out until expand.
 * Advisory only; levels captioned in text (image already has TA overlays).
 */
import { useState, type CSSProperties } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'

type Props = {
  symbol: string
  entryLow: number | null
  entryHigh: number | null
  stop: number | null
  resistance: number | null
  avgExit: number | null
}

function money(n: number | null): string {
  return n === null ? '—' : `$${n.toFixed(2)}`
}

export default function ReEntryMiniChart({
  symbol, entryLow, entryHigh, stop, resistance, avgExit,
}: Props) {
  const [err, setErr] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const chartable = /^[A-Za-z][A-Za-z0-9.-]{0,9}$/.test(symbol)

  const wrap: CSSProperties = {
    marginBottom: 10,
    border: '1px solid var(--border)',
    borderRadius: 5,
    padding: 8,
    background: 'var(--bg1)',
  }

  if (!chartable) {
    return <div style={{ ...wrap, fontSize: 10.5, color: BB.text3 }}>Chart not available for this instrument.</div>
  }

  const src = `/api/v2/finviz-chart?symbol=${encodeURIComponent(symbol)}&p=d`

  return (
    <div style={wrap} data-testid={`reentry-chart-${symbol}`}>
      <div style={{ fontSize: 10, fontWeight: 900, color: BB.text3, marginBottom: 6 }}>
        LEVELS CHART (daily) — advisory · lazy load
      </div>
      <div style={{ fontSize: 10, color: BB.text3, marginBottom: 6, lineHeight: 1.45 }}>
        Entry {entryLow === null && entryHigh === null ? '—' : `${money(entryLow)}–${money(entryHigh)}`}
        {' · '}stop {money(stop)}
        {' · '}res {money(resistance)}
        {' · '}avg exit {money(avgExit)}
      </div>
      {!loaded && !err && (
        <div style={{ fontSize: 10.5, color: BB.text3, marginBottom: 4 }}>Loading chart…</div>
      )}
      {err ? (
        <div style={{ fontSize: 10.5, color: BB.amber }}>
          Chart image unavailable (Finviz proxy). Open Watch for full technicals.
        </div>
      ) : (
        <img
          src={src}
          alt={`${symbol} daily chart`}
          loading="lazy"
          onLoad={() => setLoaded(true)}
          onError={() => setErr(true)}
          style={{
            width: '100%',
            maxWidth: 640,
            maxHeight: 280,
            objectFit: 'contain',
            display: loaded ? 'block' : 'none',
            borderRadius: 4,
            background: 'var(--bg0)',
          }}
        />
      )}
    </div>
  )
}
