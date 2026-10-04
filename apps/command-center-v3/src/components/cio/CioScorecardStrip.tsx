import { Link } from 'react-router-dom'
import { RADIUS } from '../../lib/designTokens'
import { cioLabel } from '../../lib/cioLabels'
import { routerPath } from '../../lib/cioDecisionLineage'

export type ScorecardMetric = {
  key?: string
  label?: string
  value: number | string | null
  unit?: string | null
}

export type ScorecardEvidenceRef = {
  kind?: string
  label?: string
  path?: string
  href?: string
  detail?: string
  summary?: string
  id?: string
}

export type ScorecardTile = {
  id: string
  title: string
  status: 'working' | 'degraded' | 'blocked' | 'dark' | string
  verdict: string
  metrics?: ScorecardMetric[]
  evidence_refs?: ScorecardEvidenceRef[]
  working?: boolean | null
  href?: string | null
}

export type ScorecardPayload = {
  ok?: boolean
  as_of?: string
  summary?: { working?: number; degraded?: number; blocked_or_dark?: number; tile_count?: number }
  tiles?: ScorecardTile[]
  blockers_top?: string[]
  health_summary?: { status?: string | null; overall_score?: number | null; counts?: { critical?: number } | null }
  pin?: Record<string, unknown>
  note?: string
}

const STATUS_COLOR: Record<string, string> = {
  working: 'var(--green)',
  degraded: 'var(--amber)',
  blocked: 'var(--red)',
  dark: 'var(--text3)',
}

const STATUS_GLYPH: Record<string, string> = {
  working: '█',
  degraded: '▓',
  blocked: '✗',
  dark: '░',
}

type Props = {
  data: ScorecardPayload | null
  loading?: boolean
  error?: string | null
  onTileClick?: (tile: ScorecardTile) => void
}

export default function CioScorecardStrip({ data, loading, error, onTileClick }: Props) {
  if (loading && !data) {
    return <div data-testid="cio-scorecard-loading" style={{ padding: '12px 0', color: 'var(--text2)', fontSize: 13 }}>Loading desk scorecard…</div>
  }
  if (error && !data) {
    return <div data-testid="cio-scorecard-error" style={{ padding: '12px 0', color: 'var(--amber)', fontSize: 13 }}>Scorecard unavailable: {error}</div>
  }

  const tiles = Array.isArray(data?.tiles) ? data!.tiles! : []
  const summary = data?.summary || {}

  return (
    <section data-testid="cio-scorecard-strip" aria-label="CIO ops scorecard" style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, marginBottom: 10 }}>
        <div>
          <div style={{ color: 'var(--text0)', fontSize: 15, fontWeight: 700 }}>Desk scorecard</div>
          <div style={{ color: 'var(--text3)', fontSize: 12, marginTop: 2 }}>
            What Alex’s desk is doing live — working vs not. Not a maturity gap wall.
          </div>
        </div>
        <div style={{ color: 'var(--text2)', font: '600 11px/1.3 var(--mono)', textAlign: 'right' }}>
          {summary.working ?? 0} working · {summary.degraded ?? 0} degraded · {summary.blocked_or_dark ?? 0} blocked/dark
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          gap: 10,
          borderTop: '1px solid var(--border)',
          paddingTop: 12,
        }}
      >
        {tiles.map((tile) => {
          const color = STATUS_COLOR[tile.status] || STATUS_COLOR.dark
          const glyph = STATUS_GLYPH[tile.status] || STATUS_GLYPH.dark
          const metrics = (tile.metrics || []).slice(0, 2)
          return (
            <button
              key={tile.id}
              type="button"
              data-testid={`cio-scorecard-tile-${tile.id}`}
              onClick={() => onTileClick?.(tile)}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: RADIUS.md,
                border: '1px solid var(--border)',
                background: 'var(--bg2)',
                cursor: onTileClick ? 'pointer' : 'default',
                minWidth: 0,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                <span style={{ color: 'var(--text0)', fontSize: 13, fontWeight: 700 }}>{tile.title}</span>
                <span style={{ color, font: '700 11px/1.2 var(--mono)', whiteSpace: 'nowrap' }}>
                  {glyph} {String(tile.status).toUpperCase()}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 14, marginTop: 10, flexWrap: 'wrap' }}>
                {metrics.map((m) => (
                  <div key={m.key || m.label || String(m.value)} style={{ minWidth: 0 }}>
                    <div style={{ color: 'var(--text3)', font: '700 9px/1.2 var(--mono)', textTransform: 'uppercase' }}>
                      {m.label || cioLabel(m.key)}
                    </div>
                    <div style={{ color: 'var(--text0)', font: '700 16px/1.2 var(--sans)', marginTop: 2 }}>
                      {m.value == null || m.value === '' ? '—' : String(m.value)}
                      {m.unit ? <span style={{ color: 'var(--text3)', fontSize: 11, marginLeft: 3 }}>{m.unit}</span> : null}
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ color: 'var(--text1)', fontSize: 12, lineHeight: 1.45, marginTop: 10 }}>{tile.verdict}</div>
              {tile.href ? (
                <div style={{ marginTop: 8 }} onClick={(e) => e.stopPropagation()}>
                  <Link to={routerPath(tile.href)} style={{ color: 'var(--accent)', fontSize: 11 }}>
                    Open related surface →
                  </Link>
                </div>
              ) : null}
            </button>
          )
        })}
      </div>

      {Array.isArray(data?.blockers_top) && data!.blockers_top!.length > 0 ? (
        <div style={{ marginTop: 14, color: 'var(--text2)', fontSize: 12 }} data-testid="cio-scorecard-blockers">
          <span style={{ color: 'var(--text3)', fontWeight: 700, marginRight: 8 }}>Top blockers</span>
          {data!.blockers_top!.slice(0, 4).join(' · ')}
        </div>
      ) : null}
    </section>
  )
}
