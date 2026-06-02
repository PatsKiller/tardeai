import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface Opinion {
  object_type: string; object_id: string; symbol: string; strategy: string
  tradeai_original: { score: number; decision: string; strategy: string; summary: string }
  hermes_audit: { missing_context: string[]; risk_flags: string[]; learning_links: number }
  hermes_enhancement: { shadow_score: number; delta: number; lesson_types: string[]; summary: string }
  hermes_agreement_status: string; hermes_confidence: number
  recommended_operator_choice: string; operator_choice: string | null
  no_overwrite: boolean; advisory_only: boolean
}

interface DualData {
  total: number; agrees: number; agrees_with_caution: number
  needs_more_evidence: number; disagrees: number; opinions: Opinion[]
}

const agreeColor: Record<string, string> = {
  AGREE: '#22c55e', AGREE_WITH_CAUTION: '#f59e0b',
  NEEDS_MORE_EVIDENCE: '#3b82f6', DISAGREE: '#ef4444',
}

export default function DualOpinionAdvisory() {
  const { data } = useApi<DualData>('/api/v2/hermes/dual-opinion', 60_000)
  const [selected, setSelected] = useState<Opinion | null>(null)
  const [filter, setFilter] = useState<string>('')

  if (!data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>

  const filtered = filter ? data.opinions.filter(o => o.hermes_agreement_status === filter) : data.opinions

  return (
    <div style={{ display: 'flex', gap: 16, padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <PageHeader title="Dual-Opinion Advisory" subtitle={`${data.total} candidates · TradeAI Original vs Hermes Enhancement`} />

        <div style={{ padding: '8px 14px', marginBottom: 16, background: 'rgba(59,130,246,.06)', border: '1px solid rgba(59,130,246,.15)', borderRadius: 8, fontSize: 11, color: 'rgba(147,197,253,.8)' }}>
          Hermes audits and enhances TradeAI's output without overwriting it. The operator chooses which opinion to trust. No live scoring changes.
        </div>

        {/* KPI — clickable filters */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10, marginBottom: 16 }}>
          {[
            { label: 'All', value: data.total, color: 'var(--text0)', key: '' },
            { label: 'Agrees', value: data.agrees, color: '#22c55e', key: 'AGREE' },
            { label: 'Caution', value: data.agrees_with_caution, color: '#f59e0b', key: 'AGREE_WITH_CAUTION' },
            { label: 'Needs Evidence', value: data.needs_more_evidence, color: '#3b82f6', key: 'NEEDS_MORE_EVIDENCE' },
            { label: 'Disagrees', value: data.disagrees, color: '#ef4444', key: 'DISAGREE' },
          ].map(k => (
            <div key={k.label} onClick={() => setFilter(filter === k.key ? '' : k.key)} style={{
              background: 'var(--bg1)', borderRadius: 10, padding: '12px 16px', textAlign: 'center', cursor: 'pointer',
              border: `1px solid ${filter === k.key ? k.color : 'var(--border)'}`, transition: 'border-color .15s',
            }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: k.color }}>{k.value}</div>
              <div style={{ fontSize: 10, color: filter === k.key ? k.color : 'var(--text3)', marginTop: 2, fontWeight: filter === k.key ? 700 : 400 }}>{k.label}</div>
            </div>
          ))}
        </div>

        {/* Opinion cards */}
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
          {filtered.map(o => (
            <div key={o.object_id} onClick={() => setSelected(o)} style={{
              padding: '14px 16px', background: selected?.object_id === o.object_id ? 'var(--bg2)' : 'var(--bg1)',
              border: `1px solid ${selected?.object_id === o.object_id ? 'var(--accent)' : 'var(--border)'}`,
              borderRadius: 10, cursor: 'pointer', borderLeft: `3px solid ${agreeColor[o.hermes_agreement_status] || '#888'}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <div>
                  <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--text0)' }}>{o.symbol}</span>
                  <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 8 }}>{o.strategy?.replace(/_/g, ' ')}</span>
                </div>
                <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, fontWeight: 700, background: `${agreeColor[o.hermes_agreement_status]}15`, color: agreeColor[o.hermes_agreement_status] }}>
                  {o.hermes_agreement_status.replace(/_/g, ' ')}
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 11 }}>
                <div style={{ padding: '6px 8px', background: 'var(--bg2)', borderRadius: 6 }}>
                  <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600, marginBottom: 2 }}>TRADEAI</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>{o.tradeai_original.score}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>{o.tradeai_original.decision}</div>
                </div>
                <div style={{ padding: '6px 8px', background: 'var(--bg2)', borderRadius: 6 }}>
                  <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600, marginBottom: 2 }}>HERMES</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: o.hermes_enhancement.delta < 0 ? '#ef4444' : o.hermes_enhancement.delta > 0 ? '#22c55e' : 'var(--text0)' }}>
                    {o.hermes_enhancement.shadow_score}
                  </div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>{o.hermes_enhancement.delta >= 0 ? '+' : ''}{o.hermes_enhancement.delta}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Detail drawer */}
      {selected && (
        <div style={{ width: 340, flexShrink: 0, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, position: 'sticky', top: 12, maxHeight: '88vh', overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--text0)' }}>{selected.symbol}</span>
            <button onClick={() => setSelected(null)} style={{ fontSize: 11, width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>✕</button>
          </div>

          <div style={{ fontSize: 9, color: '#f59e0b', marginBottom: 10, padding: '4px 8px', background: 'rgba(246,190,0,.06)', borderRadius: 6, fontWeight: 600 }}>
            Advisory Only — No overwrite — Operator chooses
          </div>

          {/* TradeAI Original */}
          <div style={{ padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8, marginBottom: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', marginBottom: 4 }}>TradeAI Original</div>
            <div style={{ fontSize: 11, color: 'var(--text2)' }}>{selected.tradeai_original.summary}</div>
          </div>

          {/* Hermes Enhancement */}
          <div style={{ padding: '10px 12px', background: 'rgba(59,130,246,.05)', borderRadius: 8, marginBottom: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa', marginBottom: 4 }}>Hermes Enhancement</div>
            <div style={{ fontSize: 11, color: 'var(--text2)' }}>{selected.hermes_enhancement.summary}</div>
            {selected.hermes_enhancement.lesson_types.length > 0 && (
              <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {selected.hermes_enhancement.lesson_types.map(t => (
                  <span key={t} style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(59,130,246,.1)', color: '#60a5fa' }}>{t.replace(/_/g, ' ')}</span>
                ))}
              </div>
            )}
          </div>

          {/* Risk flags */}
          {selected.hermes_audit.risk_flags.length > 0 && (
            <div style={{ padding: '8px 10px', background: 'rgba(239,68,68,.05)', borderRadius: 6, marginBottom: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#ef4444', marginBottom: 4 }}>Risk Flags</div>
              <ul style={{ margin: 0, paddingLeft: 16, fontSize: 10, color: '#fca5a5', lineHeight: 1.5 }}>
                {selected.hermes_audit.risk_flags.map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            </div>
          )}

          {/* Operator choices (disabled — read-only display) */}
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, marginTop: 12 }}>Operator Choice (read-only)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {['Keep TradeAI Original', 'Use Hermes Enhancement', 'Keep Both', 'Reject Both', 'Escalate'].map(choice => (
              <button key={choice} disabled style={{ fontSize: 10, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text3)', cursor: 'not-allowed', textAlign: 'left', opacity: 0.5 }}>
                {choice}
              </button>
            ))}
            <div style={{ fontSize: 9, color: 'var(--text3)', fontStyle: 'italic', marginTop: 4 }}>Choice tracking requires separate approval. Currently read-only display.</div>
          </div>

          {/* Metadata */}
          <div style={{ fontSize: 9, color: 'var(--text3)', borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 12, lineHeight: 1.7 }}>
            <div><strong>Agreement:</strong> <span style={{ color: agreeColor[selected.hermes_agreement_status] }}>{selected.hermes_agreement_status}</span></div>
            <div><strong>Hermes confidence:</strong> {(selected.hermes_confidence * 100).toFixed(0)}%</div>
            <div><strong>Learning links:</strong> {selected.hermes_audit.learning_links}</div>
            <div><strong>Recommended:</strong> {selected.recommended_operator_choice.replace(/_/g, ' ')}</div>
          </div>
        </div>
      )}
    </div>
  )
}
