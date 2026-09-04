import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { inboxDetailPlain } from '../lib/homeLabels'

const TYPE_CTA: Record<string, { label: string; to: string; reports?: string }> = {
  stop: { label: 'Risk', to: '/risk', reports: '/reports?super=ops&category=advisories' },
  proposal: { label: 'Proposals', to: '/trading?tab=Proposals', reports: '/reports?super=ops&category=paper' },
  siem: { label: 'System', to: '/system', reports: '/reports?super=ops&category=system' },
  escalation: { label: 'Agents → Workflow', to: '/agents?tab=workflow', reports: '/reports?super=ops&category=escalations' },
  cio_review: { label: 'Intelligence', to: '/intelligence', reports: '/reports?super=intel' },
  auto_research: { label: 'Research', to: '/intelligence?tab=research', reports: '/reports?super=intel&category=research' },
}

interface Props {
  compact?: boolean
  maxItems?: number
}

export default function OperatorInboxPanel({ compact, maxItems = 8 }: Props) {
  const { data, loading } = useApi<any>('/api/v2/inbox', 60_000)
  const items: any[] = data?.items ?? []
  const shown = items.slice(0, maxItems)

  if (loading && !data) {
    return <div style={{ fontSize: 11, color: 'var(--text3)', padding: compact ? 6 : 12 }}>Loading operator inbox…</div>
  }

  const priColor = (p?: string) => p === 'P0' ? '#ef4444' : p === 'P1' ? '#f59e0b' : 'var(--text2)'

  return (
    <div style={{ background: compact ? undefined : 'var(--bg1)', border: compact ? undefined : '1px solid var(--border)', borderRadius: compact ? 0 : 10, padding: compact ? 0 : 16 }}>
      {!compact && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Operator Inbox</span>
          <span style={{ fontSize: 9, color: 'var(--text3)' }}>
            {/* `count` is the whole queue; `items` was a page of 80. The panel
                rendered "82 items" above 80 rows with nothing saying so. */}
            {data?.total_count ?? data?.count ?? 0} items
            {data?.truncated ? ` (${data?.displayed_count} shown)` : ''}
            {' · P0 '}{data?.p0_count ?? 0} · auto-research {data?.auto_research ?? 0} · stops {data?.stops ?? 0} · proposals {data?.proposals ?? 0}
          </span>
        </div>
      )}
      {shown.length === 0 ? (
        <div style={{ fontSize: 11, color: 'var(--text3)', padding: compact ? 4 : 8 }}>No P0 actions, auto-research, escalations, or CIO reviews in the last 14 days.</div>
      ) : shown.map((it: any, i: number) => {
        const fallback = TYPE_CTA[it.type] ?? { label: 'Open Health', to: '/health' }
        const cta = it.cta
          ? { label: it.cta.label, to: (it.cta.route || '/').replace(/^\/v3/, ''), reports: it.cta.reports?.replace(/^\/v3/, '') }
          : fallback
        const color = priColor(it.priority) || (it.type === 'escalation' ? '#ef4444' : it.type === 'cio_review' ? '#a855f7' : it.type === 'auto_research' ? '#22c55e' : 'var(--text2)')
        const line = inboxDetailPlain(it.detail ?? it.summary ?? it.message, it)
        const maxLen = compact ? 72 : 140
        const display = line.length > maxLen ? `${line.slice(0, maxLen)}…` : line
        return (
          <div key={`${it.type}-${it.symbol}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 11, flexWrap: 'wrap' }}>
            {it.priority && <span style={{ fontSize: 8, fontWeight: 800, color: priColor(it.priority), minWidth: 18 }}>{it.priority}</span>}
            <span style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--text0)', minWidth: 48 }}>{it.symbol ?? '—'}</span>
            <span style={{ flex: 1, minWidth: 120, color, lineHeight: 1.35 }} title={it.detail || line}>
              {display}
            </span>
            <span style={{ fontSize: 8, color: 'var(--text3)', whiteSpace: 'nowrap' }}>{it.source}</span>
            <Link to={cta.to} style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none', whiteSpace: 'nowrap' }}>{cta.label} →</Link>
            {cta.reports && <Link to={cta.reports} style={{ fontSize: 9, fontWeight: 600, color: 'var(--text3)', textDecoration: 'none', whiteSpace: 'nowrap' }}>Reports</Link>}
          </div>
        )
      })}
      {!compact && <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/inbox · P0 = stops, proposals, SIEM · lines curated for operators (hover for raw)</div>}
    </div>
  )
}
