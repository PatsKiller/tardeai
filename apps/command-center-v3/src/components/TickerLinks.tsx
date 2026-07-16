import { Link } from 'react-router-dom'

// Watch Desk v2 (C2): ONE shared outbound-links row for every ticker surface.
// URL templates live here only — extend (e.g. Finviz Elite deep links) in one place.
export const TICKER_LINKS: { label: string; url: (s: string) => string }[] = [
  { label: 'Finviz', url: s => `https://finviz.com/quote.ashx?t=${s}` },
  { label: 'Yahoo', url: s => `https://finance.yahoo.com/quote/${s}` },
  { label: 'EDGAR', url: s => `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=${s}` },
  { label: 'TradingView', url: s => `https://www.tradingview.com/chart/?symbol=${s}` },
]

export default function TickerLinks({ symbol, internal = true, muted = '#8b93a7', accent = '#7dd3fc' }:
  { symbol?: string; internal?: boolean; muted?: string; accent?: string }) {
  if (!symbol) return null
  const s = symbol.toUpperCase()
  return (
    <span style={{ display: 'inline-flex', gap: 7, alignItems: 'baseline' }} onClick={e => e.stopPropagation()}>
      {TICKER_LINKS.map(l => (
        <a key={l.label} href={l.url(s)} target="_blank" rel="noopener noreferrer"
          style={{ fontSize: 9.5, color: muted, textDecoration: 'none', borderBottom: `1px dotted ${muted}55` }}>
          {l.label}↗
        </a>
      ))}
      {internal && (
        <Link to={`/watch?symbol=${s}`} style={{ fontSize: 9.5, color: accent, textDecoration: 'none' }}>Watchlist</Link>
      )}
    </span>
  )
}
