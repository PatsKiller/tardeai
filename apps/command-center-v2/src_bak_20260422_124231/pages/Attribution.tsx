import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'
import { fmtPct, deltaColor } from '../lib/format'

interface AttrData { has_data: boolean; benchmark: string; benchmark_label: string; port_cagr: number; bench_cagr: number; alpha_annualized: number; inception_return: number; bench_3yr_return: number; [key: string]: unknown }

export default function Attribution() {
  const { data: a } = useApi<AttrData>('/api/v2/attribution')
  if (!a) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>
  if (!a.has_data) return <><PageHeader title="Attribution" /><Card><div style={{ color: 'var(--text3)', padding: 20 }}>No attribution data available</div></Card></>

  return (
    <>
      <PageHeader title="Performance Attribution" subtitle={`vs ${a.benchmark_label || a.benchmark || 'Benchmark'}`} />
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <MetricTile label="Portfolio CAGR" value={fmtPct(a.port_cagr)} deltaColor={deltaColor(a.port_cagr)} />
        <MetricTile label={`${a.benchmark_label || 'Bench'} CAGR`} value={fmtPct(a.bench_cagr)} deltaColor={deltaColor(a.bench_cagr)} />
        <MetricTile label="Alpha (Ann.)" value={fmtPct(a.alpha_annualized)} deltaColor={deltaColor(a.alpha_annualized)} />
        <MetricTile label="Inception Return" value={fmtPct(a.inception_return)} deltaColor={deltaColor(a.inception_return)} />
        {a.bench_3yr_return != null && <MetricTile label="Bench 3Y" value={fmtPct(a.bench_3yr_return)} deltaColor={deltaColor(a.bench_3yr_return)} />}
      </div>

      <Card title="Attribution Detail">
        <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.6 }}>
          {Object.entries(a).filter(([k]) => !['has_data', 'benchmark', 'benchmark_label', 'port_cagr', 'bench_cagr', 'alpha_annualized', 'inception_return', 'bench_3yr_return'].includes(k)).map(([k, v]) => (
            <div key={k} style={{ display: 'flex', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ width: 160, color: 'var(--text3)', fontSize: 10 }}>{k.replace(/_/g, ' ')}</span>
              <span style={{ color: 'var(--text1)' }}>{typeof v === 'number' ? v.toFixed(2) : String(v)}</span>
            </div>
          ))}
        </div>
      </Card>
    </>
  )
}
