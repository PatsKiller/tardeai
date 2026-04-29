import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import { DoughnutChart } from '../components/charts'
import { useApi } from '../hooks/useApi'

interface CorrData { has_data: boolean; sector_exposure: Record<string, number>; geographic: Record<string, number>; rate_sensitivity: Record<string, number>; rate_interpretation: string; defense_cluster_pct: number }

export default function Correlation() {
  const { data: c } = useApi<CorrData>('/api/v2/correlation')
  if (!c) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>
  if (!c.has_data) return <><PageHeader title="Correlation" /><Card><div style={{ color: 'var(--text3)', padding: 20 }}>No correlation data available</div></Card></>

  const sectors = Object.entries(c.sector_exposure).sort((a, b) => b[1] - a[1])
  const geo = Object.entries(c.geographic).sort((a, b) => b[1] - a[1])
  const rate = Object.entries(c.rate_sensitivity).sort((a, b) => b[1] - a[1])

  return (
    <>
      <PageHeader title="Correlation & Diversification" subtitle={c.rate_interpretation} />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        <div>
          <SectionHeader title="Sector Exposure" count={sectors.length} />
          <Card>
            <div style={{ height: 180 }}><DoughnutChart labels={sectors.map(([s]) => s)} data={sectors.map(([, v]) => v)} /></div>
            <div style={{ marginTop: 8 }}>
              {sectors.map(([s, v]) => (
                <div key={s} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '2px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                  <span style={{ color: 'var(--text2)' }}>{s}</span>
                  <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{v.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div>
          <SectionHeader title="Geographic" count={geo.length} />
          <Card>
            <div style={{ height: 180 }}><DoughnutChart labels={geo.map(([g]) => g)} data={geo.map(([, v]) => v)} /></div>
            <div style={{ marginTop: 8 }}>
              {geo.map(([g, v]) => (
                <div key={g} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '2px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                  <span style={{ color: 'var(--text2)' }}>{g}</span>
                  <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{v.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div>
          <SectionHeader title="Rate Sensitivity" count={rate.length} />
          <Card>
            <div style={{ height: 180 }}><DoughnutChart labels={rate.map(([r]) => r)} data={rate.map(([, v]) => v)} /></div>
            <div style={{ marginTop: 8 }}>
              {rate.map(([r, v]) => (
                <div key={r} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '2px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                  <span style={{ color: 'var(--text2)' }}>{r}</span>
                  <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{v.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </Card>
          {c.defense_cluster_pct > 0 && (
            <Card compact title="Defense Cluster" subtitle={`${c.defense_cluster_pct.toFixed(1)}%`}>
              <div style={{ fontSize: 10, color: 'var(--text2)' }}>Portfolio concentration in defense sector</div>
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
