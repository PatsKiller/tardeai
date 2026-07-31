/**
 * WP-T7 lite — lazy Finviz daily chart for trading surfaces.
 * Only mounts when parent expands; no fan-out on list load.
 */
import { useState, type CSSProperties } from 'react'

type Props = {
  symbol: string
  caption?: string
  stop?: number | null
  entry?: number | null
  target?: number | null
}

function money(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  return `$${Number(n).toFixed(2)}`
}

export default function TradingSymbolChart({ symbol, caption, stop, entry, target }: Props) {
  const [err, setErr] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const chartable = /^[A-Za-z][A-Za-z0-9.-]{0,9}$/.test(symbol)
  const wrap: CSSProperties = {
    marginTop: 8,
    border: '1px solid var(--border)',
    borderRadius: 6,
    padding: 8,
    background: 'var(--bg2)',
  }

  if (!chartable) {
    return <div style={{ ...wrap, fontSize: 10, color: 'var(--text3)' }}>Chart not available for this instrument.</div>
  }

  const src = `/api/v2/finviz-chart?symbol=${encodeURIComponent(symbol)}&p=d`

  return (
    <div style={wrap} data-testid={`trading-chart-${symbol}`}>
      <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', marginBottom: 4 }}>
        Daily chart · advisory · lazy load
      </div>
      {(entry != null || stop != null || target != null || caption) && (
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6, lineHeight: 1.4 }}>
          {caption || `Entry ${money(entry)} · stop ${money(stop)} · target ${money(target)}`}
        </div>
      )}
      {!loaded && !err && <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>Loading chart…</div>}
      {err ? (
        <div style={{ fontSize: 10, color: 'var(--text2)' }}>
          Chart unavailable (Finviz proxy). Open Watch for full technicals.
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
            maxWidth: 560,
            maxHeight: 240,
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
