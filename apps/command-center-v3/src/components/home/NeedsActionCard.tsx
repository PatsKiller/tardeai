import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { needsActionFrom, severityTone, SEVERITIES, type Severity } from '../../lib/needsAction'

// "Needs action" inbox (audit 2026-10-21) — one self-contained Home card over GET /api/v2/needs-action.
// Shows "Nothing needs action" only when every source answered (lib/needsAction.ts).

const TONE_VAR: Record<string, string> = {
  danger: 'var(--danger-color)', warning: 'var(--warning-color)', info: 'var(--info-color)', neutral: 'var(--text-2)', success: 'var(--success-color)',
}

function ageText(iso: string | null): string {
  if (!iso) return ''
  const s = (Date.now() - Date.parse(iso)) / 1000
  if (!Number.isFinite(s) || s < 0) return ''
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

export default function NeedsActionCard({ maxItems = 12 }: { maxItems?: number }) {
  const { data, loading, error } = useApi<any>('/api/v2/needs-action', 60_000)
  const m = needsActionFrom(data, { loading, error, nowMs: Date.now() })
  const shown = m.items.slice(0, maxItems)
  const headTone = m.counts.P0 || m.counts.P1 ? 'danger' : m.counts.P2 ? 'warning' : m.state === 'CLEAR' ? 'success' : 'neutral'
  return (
    <section
      data-testid="needs-action-card"
      aria-label="Needs action"
      style={{
        border: '1px solid var(--border-color)', borderLeft: `3px solid ${TONE_VAR[headTone]}`, borderRadius: 'var(--radius-md)',
        background: 'var(--bg-1)', padding: '10px 12px', marginBottom: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <strong style={{ color: 'var(--text-0)', fontSize: 13 }}>Needs action</strong>
        {SEVERITIES.map((s: Severity) => (
          <span
            key={s}
            data-testid={`needs-action-count-${s}`}
            style={{ fontSize: 11, fontWeight: 700, color: m.counts[s] ? TONE_VAR[severityTone(s)] : 'var(--text-3)' }}
          >
            {s} {m.state === 'LOADING' || (m.state === 'UNAVAILABLE' && !m.items.length) ? '—' : m.counts[s]}
          </span>
        ))}
        {m.unavailableSources.length > 0 && (
          <span style={{ fontSize: 11, color: 'var(--warning-color)' }}>
            {m.unavailableSources.length} source{m.unavailableSources.length > 1 ? 's' : ''} unavailable
          </span>
        )}
        {m.state === 'STALE' && <span style={{ fontSize: 11, color: 'var(--warning-color)', fontWeight: 700 }}>STALE{m.reason ? ` (${m.reason})` : ''}</span>}
      </div>
      {m.state === 'LOADING' && <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 6 }}>checking every source…</div>}
      {m.state === 'UNAVAILABLE' && (
        <div style={{ fontSize: 12, color: 'var(--warning-color)', marginTop: 6 }}>
          Needs-action UNAVAILABLE{m.reason ? ` · ${m.reason}` : ''} — this is not an all-clear.
        </div>
      )}
      {m.state === 'CLEAR' && (
        <div data-testid="needs-action-clear" style={{ fontSize: 12, color: 'var(--success-color)', marginTop: 6 }}>
          Nothing needs action — every source answered.
        </div>
      )}
      {shown.length > 0 && (
        <ul style={{ listStyle: 'none', margin: '8px 0 0', padding: 0, display: 'grid', gap: 4 }}>
          {shown.map((it, idx) => (
            <li key={`${it.source}-${idx}`} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 12 }}>
              <span style={{ fontWeight: 800, color: TONE_VAR[severityTone(it.severity)], minWidth: 22 }}>{it.severity}</span>
              <Link to={it.where} title={it.why} style={{ color: 'var(--text-0)', textDecoration: 'none', flex: 1, minWidth: 0 }}>
                {it.title}
                <span style={{ color: 'var(--text-3)' }}> · {it.source}{ageText(it.since) ? ` · ${ageText(it.since)}` : ''}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {m.items.length > shown.length && (
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>+{m.items.length - shown.length} more (lower severity)</div>
      )}
    </section>
  )
}
