import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface AttributionData {
  has_data: boolean
  benchmark_label: string
  port_cagr: number | null
  bench_cagr: number | null
  alpha_annualized: number | null
  inception_return: number | null
  port_sharpe: number | null
  bench_sharpe: number | null
  port_sortino: number | null
  bench_sortino: number | null
  port_maxdd: number | null
  bench_maxdd: number | null
  top_gainers: { symbol: string; gain: number }[]
  top_losers: { symbol: string; loss: number }[]
  note?: string
  last_updated?: string
  snapshot_count?: number
}

export default function Attribution() {
  const { data } = useApi<AttributionData>('/api/v2/attribution')
  if (!data) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading attribution…</div>

  const missingBench = data.bench_cagr == null
  const missingAlpha = data.alpha_annualized == null
  const unavailableReason = !data.has_data ? 'Attribution data not yet generated. Run the attribution pipeline.'
    : missingBench && missingAlpha ? 'Benchmark price history unavailable — benchmark CAGR and alpha cannot be computed.'
    : missingAlpha ? 'Alpha requires both portfolio and benchmark CAGR.'
    : null

  return (
    <>
      <PageHeader title={`Performance Attribution vs ${data.benchmark_label || 'Benchmark'}`} subtitle={data.last_updated ? `Updated ${data.last_updated}${data.snapshot_count ? ` (${data.snapshot_count} days)` : ''}` : 'Attribution context'} />
      {unavailableReason && (
        <div style={{ background: 'rgba(234,179,8,0.1)', border: '1px solid rgba(234,179,8,0.3)', borderRadius: 8, padding: '10px 14px', marginBottom: 12, fontSize: 11, color: 'var(--amber)' }}>
          {unavailableReason}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, marginBottom: 12 }}>
        <MetricTile label="Alpha (annualized)" value={data.alpha_annualized != null ? fmtPct(data.alpha_annualized, 1) : 'Unavailable'} deltaColor={data.alpha_annualized != null ? deltaColor(data.alpha_annualized) : 'var(--text3)'} tooltip={data.alpha_annualized == null ? 'Alpha unavailable — requires both portfolio and benchmark CAGR from real return data.' : 'Excess return vs blended benchmark (portfolio CAGR minus benchmark CAGR)'} />
        <MetricTile label="Portfolio CAGR" value={data.port_cagr != null ? fmtPct(data.port_cagr, 1) + '/yr' : 'Unavailable'} deltaColor={data.port_cagr != null ? 'var(--green)' : 'var(--text3)'} tooltip="Compound Annual Growth Rate from price-cache reconstruction" />
        <MetricTile label="Benchmark CAGR" value={data.bench_cagr != null ? fmtPct(data.bench_cagr, 1) + '/yr' : 'Unavailable'} deltaColor={data.bench_cagr != null ? undefined : 'var(--text3)'} tooltip={data.bench_cagr == null ? 'Benchmark CAGR unavailable — benchmark prices not cached. Run attribution refresh.' : `Blended: ${data.benchmark_label}`} />
        <MetricTile label="Sharpe (port / bench)" value={data.port_sharpe != null ? `${data.port_sharpe.toFixed(2)}${data.bench_sharpe != null ? ' / ' + data.bench_sharpe.toFixed(2) : ''}` : 'Unavailable'} tooltip="Sharpe >1.0 = good risk-adjusted return. Measures return per unit of total risk." />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1.15fr 0.85fr', gap: 12 }}>
        <Card title="Top Contributors / Detractors">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>Top Gainers</div>
              {data.top_gainers?.length ? data.top_gainers.slice(0, 8).map((row, idx) => <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}><strong>{row.symbol}</strong><span style={{ color: 'var(--green)' }}>{fmt$(row.gain)}</span></div>) : <div style={{ color: 'var(--text3)' }}>No gainers available</div>}
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>Top Losers</div>
              {data.top_losers?.length ? data.top_losers.slice(0, 8).map((row, idx) => <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}><strong>{row.symbol}</strong><span style={{ color: 'var(--red)' }}>{fmt$(row.loss)}</span></div>) : <div style={{ color: 'var(--text3)' }}>No losers available</div>}
            </div>
          </div>
        </Card>
        <Card title="Benchmark Context">
          <div style={{ color: 'var(--text2)', fontSize: 11, lineHeight: 1.6 }}>
            {data.note || 'Position-level attribution for understanding what drove portfolio returns.'}
            <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text3)' }}>
              Benchmark: <strong style={{ color: 'var(--text1)' }}>{data.benchmark_label || 'Blended'}</strong> — weighted blend matching your allocation (60% SPY + 25% ITA + 15% AGG). Chosen to reflect your sector tilt toward defense/income.
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
              Returns span all 4 accounts (401k, Roll IRA, Roth, Taxable) combined. Individual account attribution not yet available.
            </div>
          </div>
          <div style={{ marginTop: 12, display: 'grid', gap: 6 }}>
            <SmallStat label="Sortino (port / bench)" value={data.port_sortino != null ? `${data.port_sortino.toFixed(2)}${data.bench_sortino != null ? ' / ' + data.bench_sortino.toFixed(2) : ''}` : 'Unavailable'} />
            <SmallStat label="Max Drawdown (port / bench)" value={data.port_maxdd != null ? `${fmtPct(data.port_maxdd, 1)}${data.bench_maxdd != null ? ' / ' + fmtPct(data.bench_maxdd, 1) : ''}` : 'Unavailable'} color="var(--red)" />
            <SmallStat label="Inception Return" value={data.inception_return != null ? fmtPct(data.inception_return, 1) : 'Unavailable'} color="var(--green)" />
          </div>
          {data.port_maxdd != null && (
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>
              Max drawdown of {fmtPct(data.port_maxdd, 1)} means the portfolio dropped that much peak-to-trough. {Math.abs(data.port_maxdd) > 15 ? 'This is significant — review stop discipline and position sizing.' : 'Within normal range for a diversified portfolio.'}
            </div>
          )}
        </Card>
      </div>
    </>
  )
}

function SmallStat({ label, value, color = 'var(--text0)' }: { label: string; value: string; color?: string }) {
  return <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: 6, borderBottom: '1px solid var(--border-subtle)', fontSize: 11 }}><span style={{ color: 'var(--text3)' }}>{label}</span><span style={{ color }}>{value}</span></div>
}
