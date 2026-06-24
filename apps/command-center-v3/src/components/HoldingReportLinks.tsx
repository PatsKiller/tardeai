/** Inline prospectus report links for portfolio holding cards and drawer. */
import type { AnalystReportEntry } from '../hooks/useAnalystReportMap'

type Props = {
  symbol: string
  entry?: AnalystReportEntry
  compact?: boolean
  reportType?: 'symbol_holding' | 'symbol_watchlist'
}

const linkStyle = {
  fontSize: 9,
  fontWeight: 800,
  textDecoration: 'none' as const,
  padding: '2px 7px',
  borderRadius: 4,
  cursor: 'pointer' as const,
}

export default function HoldingReportLinks({ symbol, entry, compact, reportType }: Props) {
  const sym = symbol.toUpperCase()
  const stop = (e: React.MouseEvent) => e.stopPropagation()
  const rtype = reportType || entry?.report_type || 'symbol_holding'
  const buildHref = `/v3/reports?symbol=${encodeURIComponent(sym)}&type=${rtype}`
  const dateHint = entry?.generated_at
    ? `Generated ${new Date(entry.generated_at).toLocaleString()}${entry.grok_edited ? ' · Grok edited' : ''}`
    : 'Generate summary prospectus'

  if (!entry?.docx && !entry?.pdf) {
    return (
      <a
        href={buildHref}
        onClick={stop}
        title="Open Analyst Reports — generate holding prospectus"
        style={{ ...linkStyle, color: '#94a3b8', background: 'rgba(148,163,184,.1)', border: '1px solid rgba(148,163,184,.25)' }}
      >
        {compact ? '📄 Report' : '📄 Generate report →'}
      </a>
    )
  }

  return (
    <span
      onClick={stop}
      title={dateHint}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}
    >
      <span style={{ fontSize: 8.5, fontWeight: 850, color: '#22c55e', letterSpacing: '.03em' }}>PROSPECTUS</span>
      {entry.pdf && (
        <a
          href={entry.pdf}
          target="_blank"
          rel="noreferrer"
          onClick={stop}
          style={{ ...linkStyle, color: '#f59e0b', background: 'rgba(245,158,11,.12)', border: '1px solid rgba(245,158,11,.35)' }}
        >
          PDF
        </a>
      )}
      {entry.docx && (
        <a
          href={entry.docx}
          target="_blank"
          rel="noreferrer"
          onClick={stop}
          style={{ ...linkStyle, color: '#60a5fa', background: 'rgba(96,165,250,.12)', border: '1px solid rgba(96,165,250,.35)' }}
        >
          Word
        </a>
      )}
      <a
        href={buildHref}
        onClick={stop}
        title="Regenerate or preview in Reports"
        style={{ ...linkStyle, color: '#94a3b8', background: 'transparent', border: '1px solid var(--border)', fontSize: 8 }}
      >
        ↻
      </a>
    </span>
  )
}