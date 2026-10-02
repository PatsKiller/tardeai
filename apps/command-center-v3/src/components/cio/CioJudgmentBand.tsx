import { Link } from 'react-router-dom'
import { RADIUS } from '../../lib/designTokens'

type Props = {
  onPolicyClick?: () => void
  blockersTop?: string[]
  scorecardNote?: string | null
  healthSummary?: {
    status?: string | null
    overall_score?: number | null
    counts?: { critical?: number } | null
  } | null
  pin?: Record<string, unknown> | null
}

/**
 * Investment judgment band — light Overview slice.
 *
 * Does NOT call /api/v3/cio/brain. That projection nests home + many planes and
 * wedges the single-threaded portfolio-server under chrome fan-out ("server busy").
 * Full narrative lives under Evidence → Full brain / Capital & Policy.
 */
export default function CioJudgmentBand({ onPolicyClick, blockersTop, scorecardNote, healthSummary, pin }: Props) {
  const blockers = (blockersTop || []).filter(Boolean).slice(0, 5)
  const score = healthSummary?.overall_score
  const status = healthSummary?.status
  const crit = healthSummary?.counts?.critical
  const pinMatch = pin && typeof pin === 'object' ? (pin as any).pin_match : null

  return (
    <section data-testid="cio-judgment-band" aria-label="Investment judgment" style={{ borderTop: '1px solid var(--border)', paddingTop: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 14 }}>
        <div>
          <div style={{ color: 'var(--text0)', fontSize: 15, fontWeight: 700 }}>Investment judgment</div>
          <div style={{ color: 'var(--text3)', fontSize: 12, marginTop: 2 }}>
            Light band — full brain projection is deferred so the desk stays responsive.
          </div>
        </div>
        <Link to="/cio?tab=evidence-comms&sub=full-brain" style={{ color: 'var(--accent)', fontSize: 12 }}>
          Full brain projection →
        </Link>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 0, border: '1px solid var(--border)', borderRadius: RADIUS.md, overflow: 'hidden', marginBottom: 16 }}>
        {[
          { label: 'Health', value: score != null ? `${score}/100` : '—', note: status ? String(status) : null },
          { label: 'Criticals', value: crit != null ? String(crit) : '—', note: 'from live health snapshot' },
          { label: 'Pin match', value: pinMatch == null ? '—' : pinMatch ? 'YES' : 'NO', note: pinMatch === false ? 'served pin drift' : null },
        ].map((cell, i) => (
          <div key={cell.label} style={{ padding: '12px 14px', borderRight: i < 2 ? '1px solid var(--border)' : undefined, minWidth: 0 }}>
            <div style={{ color: 'var(--text3)', font: '700 10px/1.3 var(--mono)', textTransform: 'uppercase' }}>{cell.label}</div>
            <div style={{ color: 'var(--text0)', font: '700 14px/1.3 var(--sans)', marginTop: 6, overflowWrap: 'anywhere' }}>{cell.value}</div>
            {cell.note ? <div style={{ color: 'var(--text2)', fontSize: 10, marginTop: 4 }}>{cell.note}</div> : null}
          </div>
        ))}
      </div>

      <div style={{ color: 'var(--text1)', fontSize: 13, lineHeight: 1.55, marginBottom: 14 }}>
        Posture, recommendation, and capital stance stay on{' '}
        <Link to="/cio?tab=capital-policy" style={{ color: 'var(--accent)' }}>Capital & Policy</Link>
        {' '}and the full brain deep view — not rebuilt on every Overview paint.
        {scorecardNote ? <span style={{ color: 'var(--text3)' }}> · {scorecardNote}</span> : null}
      </div>

      {blockers.length > 0 ? (
        <div data-testid="cio-judgment-blockers">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
            <div style={{ color: 'var(--text2)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.4px' }}>Top blockers</div>
            <button
              type="button"
              onClick={onPolicyClick}
              style={{
                border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--accent)',
                fontSize: 11, padding: '4px 10px', borderRadius: RADIUS.sm, cursor: 'pointer',
              }}
            >
              Policy / ratify →
            </button>
          </div>
          <ul style={{ margin: '8px 0 0', paddingLeft: 18, color: 'var(--text1)', fontSize: 12, lineHeight: 1.5 }}>
            {blockers.map((b, i) => (
              <li key={`${i}-${String(b).slice(0, 40)}`}>{typeof b === 'string' ? b : JSON.stringify(b)}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div style={{ color: 'var(--text3)', fontSize: 12 }} data-testid="cio-judgment-blockers">
          No top blockers on the light scorecard path.
        </div>
      )}
    </section>
  )
}
