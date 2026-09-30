import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'

type Brain = {
  as_of?: string
  operator_value?: any
  portfolio_state?: any
  portfolio_thesis?: any
  capital_plan?: any
  capital_situation?: any
  market_context?: any
  proactive_cio?: any
}

function money(value: number | null | undefined): string {
  if (value == null) return 'UNVERIFIED'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value)
}

function valueOf(field: any): string {
  if (!field || field.value == null) return '—'
  if (typeof field.value === 'object') return JSON.stringify(field.value)
  return String(field.value)
}

type Props = {
  onPolicyClick?: () => void
  blockersTop?: string[]
}

/**
 * Investment judgment band — compressed Brain investment slice for Overview below-fold.
 * Full policy laundry list lives in Capital & Policy + modal.
 */
export default function CioJudgmentBand({ onPolicyClick, blockersTop }: Props) {
  const { data, loading, error } = useApi<Brain>('/api/v3/cio/brain')

  if (loading && !data) {
    return <div data-testid="cio-judgment-loading" style={{ padding: '12px 0', color: 'var(--text2)', fontSize: 13 }}>Loading investment judgment…</div>
  }
  if (error && !data) {
    return <div data-testid="cio-judgment-error" style={{ padding: '12px 0', color: 'var(--amber)', fontSize: 13 }}>Judgment unavailable: {String(error)}</div>
  }

  const brain = data || {}
  const ov = brain.operator_value || {}
  const thesis = brain.portfolio_thesis || {}
  const capital = brain.capital_plan || {}
  const situation = brain.capital_situation || {}
  const portfolio = brain.portfolio_state || {}
  const market = brain.market_context || {}
  const marketFields = market.fields || {}
  const blockers = (blockersTop && blockersTop.length
    ? blockersTop
    : [...(ov.uncertainty || []), ...(situation.blockers || []), ...(ov.missing_policy || []).slice(0, 3)]
  ).filter(Boolean).slice(0, 5)

  const recommendation = ov.current_recommendation || capital.stance || situation.conclusion || 'NONE'
  const posture = thesis.current_posture || 'INSUFFICIENT DATA'

  return (
    <section data-testid="cio-judgment-band" aria-label="Investment judgment" style={{ borderTop: '1px solid var(--border)', paddingTop: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 14 }}>
        <div>
          <div style={{ color: 'var(--text0)', fontSize: 15, fontWeight: 700 }}>Investment judgment</div>
          <div style={{ color: 'var(--text3)', fontSize: 12, marginTop: 2 }}>Posture, thesis, and capital stance — advisory only.</div>
        </div>
        <Link to="/v3/cio?tab=evidence-comms&sub=full-brain" style={{ color: 'var(--accent)', fontSize: 12 }}>
          Full brain projection →
        </Link>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 0, border: '1px solid var(--border)', borderRadius: RADIUS.md, overflow: 'hidden', marginBottom: 16 }}>
        {[
          { label: 'Portfolio', value: money(portfolio.total_portfolio_value_usd), note: portfolio.truth_quality },
          { label: 'Observed cash', value: money(portfolio.observed_cash_usd), note: portfolio.investable_cash_status },
          { label: 'CIO posture', value: String(posture), note: thesis.state },
          { label: 'Capital stance', value: String(capital.stance || situation.conclusion || '—'), note: capital.next_review ? `Next: ${capital.next_review}` : null },
        ].map((cell, i) => (
          <div key={cell.label} style={{ padding: '12px 14px', borderRight: i < 3 ? '1px solid var(--border)' : undefined, minWidth: 0 }}>
            <div style={{ color: 'var(--text3)', font: '700 10px/1.3 var(--mono)', textTransform: 'uppercase' }}>{cell.label}</div>
            <div style={{ color: 'var(--text0)', font: '700 14px/1.3 var(--sans)', marginTop: 6, overflowWrap: 'anywhere' }}>{cell.value}</div>
            {cell.note ? <div style={{ color: 'var(--text2)', fontSize: 10, marginTop: 4 }}>{String(cell.note)}</div> : null}
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 24 }}>
        <div>
          <div style={{ color: 'var(--text2)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 6 }}>Current recommendation</div>
          <div style={{ color: 'var(--text0)', fontSize: 14, lineHeight: 1.55 }}>{String(recommendation)}</div>
          <div style={{ color: 'var(--text1)', fontSize: 12, lineHeight: 1.5, marginTop: 10 }}>
            {typeof ov.why === 'string' ? ov.why : (thesis.core_thesis || 'No thesis narrative in this snapshot.')}
          </div>
          <div style={{ color: 'var(--text3)', fontSize: 12, marginTop: 10 }}>
            Next: {String(ov.what_happens_next || capital.next_review || 'UNSCHEDULED')}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text2)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 6 }}>Market context</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', fontSize: 12 }}>
            <span style={{ color: 'var(--text3)' }}>Regime <strong style={{ color: 'var(--text0)', display: 'block' }}>{valueOf(marketFields.regime)}</strong></span>
            <span style={{ color: 'var(--text3)' }}>VIX <strong style={{ color: 'var(--text0)', display: 'block' }}>{valueOf(marketFields.vix_close)}</strong></span>
            <span style={{ color: 'var(--text3)' }}>Breadth <strong style={{ color: 'var(--text0)', display: 'block' }}>{valueOf(marketFields.breadth)}</strong></span>
            <span style={{ color: 'var(--text3)' }}>Valuation <strong style={{ color: 'var(--text0)', display: 'block' }}>{valueOf(marketFields.valuation)}</strong></span>
          </div>
        </div>
      </div>

      {blockers.length > 0 ? (
        <div style={{ marginTop: 18 }} data-testid="cio-judgment-blockers">
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
          <div style={{ marginTop: 8 }}>
            <Link to="/v3/cio?tab=capital-policy" style={{ color: 'var(--accent)', fontSize: 12 }}>
              Open Capital & Policy →
            </Link>
          </div>
        </div>
      ) : null}
    </section>
  )
}
