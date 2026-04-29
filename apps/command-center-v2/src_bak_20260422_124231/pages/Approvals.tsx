import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'

interface QueueItem {
  id: number
  recommendation_id: number
  symbol: string | null
  action: string
  rationale: string
  confidence: number
  urgency: string
  status: string
  expires_at: string | null
  dedupe_key: string
  created_at: string
}

interface ApprovalData { count: number; pending: QueueItem[] }

const urgencyColor: Record<string, string> = { urgent: 'var(--red)', normal: 'var(--amber)', low: 'var(--text3)' }

export default function Approvals() {
  const { data: resp } = useApi<ApprovalData>('/api/v2/approvals/pending')
  const pending = resp?.pending ?? []

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle={`${pending.length} pending review${pending.length !== 1 ? 's' : ''}`}
        actions={
          <span style={{ fontSize: 10, color: 'var(--text3)', padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
            Read-only — approve/reject coming in Phase 2
          </span>
        }
      />

      {pending.length === 0 ? (
        <Card>
          <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 40 }}>
            No pending action items. All caught up.
          </div>
        </Card>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {pending.map(item => (
            <div key={item.id} style={{
              background: 'var(--bg2)',
              border: `1px solid ${item.urgency === 'urgent' ? 'var(--red)' : 'var(--border)'}`,
              borderRadius: 'var(--radius-lg)',
              padding: '14px 18px',
              borderLeft: `3px solid ${urgencyColor[item.urgency] || 'var(--border)'}`,
            }}>
              {/* Header row */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3, textTransform: 'uppercase',
                  background: `color-mix(in srgb, ${urgencyColor[item.urgency]} 15%, transparent)`,
                  color: urgencyColor[item.urgency],
                }}>
                  {item.urgency}
                </span>
                <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>
                  {item.action.replace(/_/g, ' ')}
                </span>
                {item.symbol && (
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)' }}>{item.symbol}</span>
                )}
                <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text3)' }}>
                  {timeAgo(item.created_at)}
                </span>
              </div>

              {/* Rationale */}
              {item.rationale && (
                <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5, marginBottom: 10 }}>
                  {item.rationale}
                </div>
              )}

              {/* Meta row */}
              <div style={{ display: 'flex', gap: 16, fontSize: 10, color: 'var(--text3)' }}>
                <span>Confidence: <strong style={{ color: item.confidence >= 0.9 ? 'var(--green)' : 'var(--text1)' }}>{(item.confidence * 100).toFixed(0)}%</strong></span>
                <span>Status: <strong style={{ color: 'var(--amber)' }}>{item.status}</strong></span>
                <span>Rec ID: {item.recommendation_id}</span>
                {item.expires_at && <span>Expires: {item.expires_at}</span>}
              </div>

              {/* Explicit no-action banner */}
              <div style={{
                marginTop: 10, padding: '6px 10px', borderRadius: 'var(--radius)',
                background: 'var(--bg3)', fontSize: 10, color: 'var(--text3)',
                borderLeft: '2px solid var(--text3)',
              }}>
                Draft pending review — not actioned, not approved. Approve/reject controls will be added in Phase 2.
              </div>
            </div>
          ))}
        </div>
      )}

      <SectionHeader title="Decision History" />
      <Card>
        <div style={{ color: 'var(--text3)', fontSize: 11, padding: 16, textAlign: 'center' }}>
          Approval log will be displayed here once decisions are recorded.
          No decisions exist yet — this is a read-only view of the pending queue.
        </div>
      </Card>
    </>
  )
}
