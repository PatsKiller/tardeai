/** Forecast tab — first-class panel (WP-E parity with Returns/Dividends). */
import { fmt$ } from '../lib/format'
import ProAnalystPill, { useProAnalystMap } from './ProAnalystPill'
import { hubPanel } from '../lib/terminalHubChrome'

type Props = {
  forecast: any
  loading?: boolean
  error?: string | null
  terminalUi?: boolean
}

export default function ForecastPanel({ forecast, loading, error, terminalUi }: Props) {
  const paMap = useProAnalystMap()
  const f = forecast?.data ?? forecast ?? {}
  const proj = f.projections ?? {}
  const payers = f.top_dividend_payers ?? []
  const asOf = f.as_of || f.generated_at || f.updated_at || null

  if (loading && !forecast) {
    return (
      <div data-testid="forecast-panel" style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>
        Loading forecast…
      </div>
    )
  }
  if (error && !forecast) {
    return (
      <div data-testid="forecast-panel" style={{ color: 'var(--text3)', fontSize: 12, padding: 20, border: '1px solid var(--border)', borderRadius: 8 }}>
        Forecast unavailable: {error}
      </div>
    )
  }
  const empty = !payers.length && !Object.keys(proj).length && f.annual_dividend_income == null
  if (empty) {
    return (
      <div data-testid="forecast-panel" style={{ color: 'var(--text3)', fontSize: 12, padding: 20, border: '1px solid var(--border)', borderRadius: 8 }}>
        No forecast data yet. Source: <code>/api/v2/forecast</code> (dividend-income projection).
      </div>
    )
  }

  return (
    <div data-testid="forecast-panel" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, alignItems: 'baseline' }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>Income forecast</div>
        {asOf && <div style={{ fontSize: 10, color: 'var(--text3)' }}>As of {String(asOf).slice(0, 19)}</div>}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 10 }}>
        {[
          { k: 'Annual dividend income', v: fmt$(f.annual_dividend_income ?? 0, 0) },
          { k: 'Monthly avg', v: fmt$(f.monthly_dividend_avg ?? 0, 0) },
          { k: 'Portfolio yield', v: `${(f.portfolio_yield_pct ?? 0).toFixed(2)}%` },
          { k: 'Retirement age', v: f.retirement_age ?? '—' },
        ].map(s => (
          <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 8px', textAlign: 'center' }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{s.v}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
          </div>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div className={terminalUi ? 'cc-panel' : undefined} style={terminalUi ? hubPanel(!!terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Projections (10y)</div>
          {Object.keys(proj).length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>No projection rows.</div>}
          {Object.entries(proj).map(([k, v]: any) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
              <span style={{ color: 'var(--text3)', textTransform: 'capitalize' }}>{k}</span>
              <span style={{ color: 'var(--text0)', fontWeight: 600 }}>
                {typeof v === 'object' ? fmt$(v.value ?? v.projected_value ?? v.total ?? 0, 0) : (typeof v === 'number' ? fmt$(v, 0) : String(v))}
              </span>
            </div>
          ))}
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, maxHeight: 280, overflowY: 'auto' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Top dividend payers</div>
          {payers.slice(0, 12).map((p: any, i: number) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 11, alignItems: 'center' }}>
              <span style={{ fontFamily: 'monospace', color: 'var(--text1)' }}>{p.symbol} <ProAnalystPill symbol={p.symbol} map={paMap} compact /></span>
              <span style={{ color: 'var(--text2)' }}>{Number(p.yield_pct ?? 0).toFixed(1)}%</span>
              <span style={{ color: 'var(--text2)' }}>{fmt$(p.annual_income ?? 0, 0)}/y</span>
            </div>
          ))}
        </div>
      </div>
      <div style={{ fontSize: 10, color: 'var(--text3)', lineHeight: 1.45 }}>
        Source: /api/v2/forecast — {f.assumptions?.basis ?? 'dividend-income projection'}.
        {f.assumptions?.limitations ? ` ${f.assumptions.limitations}` : ' Advisory model only; not a guarantee of income.'}
      </div>
    </div>
  )
}
