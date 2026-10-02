import { Link } from 'react-router-dom'
import type { ScorecardTile, ScorecardEvidenceRef } from './CioScorecardStrip'
import { RADIUS, SHADOW } from '../../lib/designTokens'
import { cioLabel } from '../../lib/cioLabels'
import { routerPath } from '../../lib/cioDecisionLineage'

type Props = {
  tile: ScorecardTile | null
  onClose: () => void
  onOpenTab?: (tab: string, sub?: string) => void
}

const STATUS_COLOR: Record<string, string> = {
  working: 'var(--green)',
  degraded: 'var(--amber)',
  blocked: 'var(--red)',
  dark: 'var(--text3)',
}

function evidenceHref(ref: ScorecardEvidenceRef): string | null {
  if (ref.href) return routerPath(ref.href)
  if (ref.path && String(ref.path).startsWith('/')) return routerPath(String(ref.path))
  return null
}

/**
 * Modal drill for scorecard tiles — receipts/evidence list + deep links.
 * Reuses DetailDrawer-style presentation without inventing new truth stores.
 */
export default function CioEvidenceModal({ tile, onClose, onOpenTab }: Props) {
  if (!tile) return null

  const color = STATUS_COLOR[tile.status] || STATUS_COLOR.dark
  const refs = Array.isArray(tile.evidence_refs) ? tile.evidence_refs : []
  const metrics = Array.isArray(tile.metrics) ? tile.metrics : []

  const deepLinks: { label: string; action: () => void }[] = []
  if (tile.id === 'desk_telegram') {
    deepLinks.push({ label: 'Telegram receipts', action: () => onOpenTab?.('evidence-comms', 'telegram-receipts') })
    deepLinks.push({ label: 'Notification gate', action: () => onOpenTab?.('evidence-comms', 'notification-gate') })
  } else if (tile.id === 'hermes_research') {
    deepLinks.push({ label: 'Research ops', action: () => onOpenTab?.('research') })
  } else if (tile.id === 'decisions') {
    deepLinks.push({ label: 'Decisions', action: () => onOpenTab?.('decisions') })
  } else if (tile.id === 'outcomes_learning') {
    deepLinks.push({ label: 'Full brain / learning', action: () => onOpenTab?.('evidence-comms', 'full-brain') })
  } else if (tile.id === 'platform_pin') {
    deepLinks.push({ label: 'Health hub', action: () => { window.location.href = '/v3/health' } })
  } else if (tile.id === 'shared_spine') {
    deepLinks.push({ label: 'Research', action: () => onOpenTab?.('research') })
  }

  return (
    <div
      data-testid="cio-evidence-modal"
      role="dialog"
      aria-modal="true"
      aria-label={`${tile.title} evidence`}
      style={{
        position: 'fixed', inset: 0, zIndex: 80,
        background: 'rgba(2, 6, 23, 0.72)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        padding: '48px 16px',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: 'min(720px, 100%)',
          maxHeight: 'calc(100vh - 96px)',
          overflow: 'auto',
          background: 'var(--bg1)',
          border: '1px solid var(--border)',
          borderRadius: RADIUS.lg,
          padding: 20,
          boxShadow: SHADOW[3],
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
          <div>
            <div style={{ color: 'var(--text0)', fontSize: 16, fontWeight: 700 }}>{tile.title}</div>
            <div style={{ color, font: '700 11px/1.3 var(--mono)', marginTop: 4 }}>{String(tile.status).toUpperCase()}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
              borderRadius: RADIUS.sm, padding: '4px 10px', cursor: 'pointer', fontSize: 12,
            }}
          >
            Close
          </button>
        </div>

        <p style={{ color: 'var(--text1)', fontSize: 13, lineHeight: 1.55, marginTop: 12 }}>{tile.verdict}</p>

        {metrics.length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10, marginTop: 16 }}>
            {metrics.map((m) => (
              <div key={m.key || m.label || String(m.value)} style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: RADIUS.md, background: 'var(--bg2)' }}>
                <div style={{ color: 'var(--text3)', font: '700 9px/1.2 var(--mono)', textTransform: 'uppercase' }}>{m.label || cioLabel(m.key)}</div>
                <div style={{ color: 'var(--text0)', font: '700 15px/1.2 var(--sans)', marginTop: 4 }}>
                  {m.value == null || m.value === '' ? '—' : String(m.value)}
                  {m.unit ? <span style={{ color: 'var(--text3)', fontSize: 11, marginLeft: 3 }}>{m.unit}</span> : null}
                </div>
              </div>
            ))}
          </div>
        ) : null}

        <div style={{ marginTop: 18 }}>
          <div style={{ color: 'var(--text2)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 8 }}>Evidence</div>
          {refs.length === 0 ? (
            <div style={{ color: 'var(--text3)', fontSize: 12 }}>No receipt rows attached for this tile in the current snapshot.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
                  <th style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>Kind</th>
                  <th style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>Label</th>
                  <th style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>Detail</th>
                </tr>
              </thead>
              <tbody>
                {refs.map((ref, i) => {
                  const href = evidenceHref(ref)
                  return (
                    <tr key={i}>
                      <td style={{ padding: '8px 0', borderBottom: '1px solid var(--border)', color: 'var(--text2)', verticalAlign: 'top' }}>
                        {cioLabel(ref.kind || 'ref')}
                      </td>
                      <td style={{ padding: '8px 0', borderBottom: '1px solid var(--border)', color: 'var(--text0)', verticalAlign: 'top' }}>
                        {href ? <Link to={href} style={{ color: 'var(--accent)' }}>{ref.label || href}</Link> : (ref.label || ref.path || ref.summary || '—')}
                      </td>
                      <td style={{ padding: '8px 0', borderBottom: '1px solid var(--border)', color: 'var(--text2)', verticalAlign: 'top' }}>
                        {ref.detail || (ref.id ? String(ref.id) : '—')}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {(deepLinks.length > 0 || tile.href) ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 18 }}>
            {deepLinks.map((d) => (
              <button
                key={d.label}
                type="button"
                onClick={() => { d.action(); onClose() }}
                style={{
                  border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--accent)',
                  fontSize: 12, padding: '6px 12px', borderRadius: RADIUS.sm, cursor: 'pointer',
                }}
              >
                {d.label}
              </button>
            ))}
            {tile.href ? (
              <Link
                to={routerPath(tile.href)}
                onClick={onClose}
                style={{
                  border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--accent)',
                  fontSize: 12, padding: '6px 12px', borderRadius: RADIUS.sm, textDecoration: 'none',
                }}
              >
                Related surface
              </Link>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
