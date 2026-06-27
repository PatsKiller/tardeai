const MISSING_LABEL: Record<string, string> = {
  strategy: 'Strategy / setup family',
  setup: 'Setup type',
  market_regime: 'Market regime',
  psychology: 'Psychology (before)',
  operator_review: 'Operator sign-off (AI stub)',
  review: 'Review row',
}

const REPORT_LINKS: Record<string, { name: string; tab: string }[]> = {
  strategy: [{ name: 'Pivot grid (row axis)', tab: 'Advanced' }],
  setup: [{ name: 'Setup breakdown', tab: 'Analytics' }],
  market_regime: [{ name: 'Pivot grid (column axis)', tab: 'Advanced' }, { name: 'Regime cross-tabs', tab: 'Advanced' }],
  psychology: [{ name: 'Zella discipline score', tab: 'Analytics' }, { name: 'Behavioral / tilt', tab: 'Behavioral' }],
  operator_review: [{ name: 'Tagging queue clearance', tab: 'Tagging Queue' }],
  review: [{ name: 'All tagged reports', tab: 'Analytics' }],
}

export default function TradeReportReadiness({ score }: {
  score?: {
    complete?: boolean
    score?: number
    missing?: string[]
    summary?: string
    auto_stub?: boolean
  } | null
}) {
  if (!score) {
    return (
      <div style={{ background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.35)', borderRadius: 8, padding: 12, marginBottom: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#fca5a5' }}>No review — reports not generated for this trade</div>
        <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 4 }}>Save a review with tags to include this trade in pivot, behavioral, and Zella analytics.</div>
      </div>
    )
  }

  const missing = score.missing || []
  const complete = score.complete
  const pct = score.score ?? 0

  if (complete) {
    return (
      <div style={{ background: 'rgba(34,197,94,.08)', border: '1px solid rgba(34,197,94,.35)', borderRadius: 8, padding: 12, marginBottom: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#86efac' }}>✓ Reports ready — trade included in analytics</div>
        <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 4 }}>
          Tagging score {pct}% · {score.summary || 'tagged'}
        </div>
      </div>
    )
  }

  const blocked = new Map<string, string>()
  for (const m of missing) {
    for (const r of REPORT_LINKS[m] || []) {
      blocked.set(`${r.tab}:${r.name}`, `${r.name} (${r.tab})`)
    }
  }

  return (
    <div style={{ background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.4)', borderRadius: 8, padding: 12, marginBottom: 14 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#fcd34d' }}>
        Reports incomplete — {pct}% ready
        {score.auto_stub && <span style={{ fontWeight: 500, color: 'var(--text2)' }}> · AI stub needs operator review</span>}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text1)', marginTop: 8, fontWeight: 600 }}>Still needed:</div>
      <ul style={{ margin: '6px 0 10px', paddingLeft: 18, fontSize: 12, color: 'var(--text1)', lineHeight: 1.5 }}>
        {missing.map(m => (
          <li key={m}>{MISSING_LABEL[m] || m}</li>
        ))}
      </ul>
      {blocked.size > 0 && (
        <>
          <div style={{ fontSize: 12, color: 'var(--text1)', fontWeight: 600 }}>Blocked or degraded reports:</div>
          <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4, lineHeight: 1.45 }}>
            {[...blocked.values()].map(b => <div key={b}>• {b}</div>)}
          </div>
        </>
      )}
      <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 8 }}>
        System-wide audit: Tagging Queue → <strong>Run reporting audit</strong>
      </div>
    </div>
  )
}