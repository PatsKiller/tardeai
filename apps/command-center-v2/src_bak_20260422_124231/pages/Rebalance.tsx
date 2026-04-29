import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import { useApi } from '../hooks/useApi'

interface RebalData { generated_at: string; status: string; ground_truth: Record<string, unknown>; recommendations: unknown[]; summary: string }

export default function Rebalance() {
  const { data: r } = useApi<RebalData>('/api/v2/rebalance')
  if (!r) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>

  return (
    <>
      <PageHeader title="Rebalance" subtitle={r.generated_at ? `Generated ${r.generated_at.slice(0, 16)}` : ''} />

      {r.status && (
        <div style={{ fontSize: 10, color: r.status === 'complete' ? 'var(--green)' : 'var(--amber)', marginBottom: 12 }}>
          Status: {r.status}
        </div>
      )}

      <SectionHeader title="AI Rebalance Summary" />
      <Card>
        <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap', maxHeight: 400, overflowY: 'auto' }}>
          {r.summary || 'No rebalance summary available. Run the portfolio pipeline to generate recommendations.'}
        </div>
      </Card>

      {Array.isArray(r.recommendations) && r.recommendations.length > 0 && (
        <>
          <SectionHeader title="Recommendations" count={r.recommendations.length} />
          {r.recommendations.map((rec, i) => (
            <Card key={i} compact>
              <div style={{ fontSize: 11, color: 'var(--text1)', whiteSpace: 'pre-wrap' }}>
                {typeof rec === 'string' ? rec : JSON.stringify(rec, null, 2)}
              </div>
            </Card>
          ))}
        </>
      )}

      {r.ground_truth && Object.keys(r.ground_truth).length > 0 && (
        <>
          <SectionHeader title="Ground Truth" />
          <Card compact>
            <div style={{ fontSize: 10, color: 'var(--text2)', whiteSpace: 'pre-wrap', maxHeight: 300, overflowY: 'auto' }}>
              {JSON.stringify(r.ground_truth, null, 2)}
            </div>
          </Card>
        </>
      )}

      <div style={{ marginTop: 16, padding: '8px 12px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 10, color: 'var(--text3)', borderLeft: '2px solid var(--text3)' }}>
        Rebalance recommendations are advisory only. No execution authority. All actions require manual approval.
      </div>
    </>
  )
}
