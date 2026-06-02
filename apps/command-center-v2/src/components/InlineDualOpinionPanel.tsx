import { useState } from 'react'
import { useApi } from '../hooks/useApi'

interface DualOpinion {
  symbol: string; strategy: string
  tradeai_original: { score: number; decision: string; summary: string }
  hermes_enhancement: { shadow_score: number; delta: number; lesson_types: string[]; summary: string }
  hermes_audit: { missing_context: string[]; risk_flags: string[]; learning_links: number }
  hermes_agreement_status: string; hermes_confidence: number
  recommended_operator_choice: string
}

interface Props {
  symbol?: string
  strategy?: string
  compact?: boolean
}

const agreeColor: Record<string, string> = {
  AGREE: '#22c55e', AGREE_WITH_CAUTION: '#f59e0b',
  NEEDS_MORE_EVIDENCE: '#3b82f6', DISAGREE: '#ef4444',
}

export default function InlineDualOpinionPanel({ symbol, strategy, compact = false }: Props) {
  const { data } = useApi<{ opinions: DualOpinion[] }>(`/api/v2/hermes/dual-opinion/inline?symbol=${symbol || ''}&strategy=${strategy || ''}`, 120_000)

  if (!data?.opinions?.length) return null

  const opinion = data.opinions[0]
  const color = agreeColor[opinion.hermes_agreement_status] || '#888'
  const [showEvidence, setShowEvidence] = useState(false)

  // Evidence quality label
  const evidenceQuality = opinion.hermes_audit.risk_flags.length > 2 ? 'WEAK'
    : opinion.hermes_audit.missing_context.length > 1 ? 'MISSING'
    : opinion.hermes_audit.risk_flags.length > 0 ? 'ACCEPTABLE'
    : opinion.hermes_confidence >= 0.6 ? 'STRONG' : 'ACCEPTABLE'
  const eqColor = evidenceQuality === 'STRONG' ? '#22c55e' : evidenceQuality === 'ACCEPTABLE' ? '#f59e0b' : '#ef4444'

  if (compact) {
    return (
      <div style={{ display: 'flex', gap: 8, padding: '6px 10px', background: `${color}08`, border: `1px solid ${color}20`, borderRadius: 8, fontSize: 10, alignItems: 'center' }}>
        <span style={{ fontWeight: 700, color }}>Hermes: {opinion.hermes_agreement_status.replace(/_/g, ' ')}</span>
        <span style={{ color: 'var(--text3)' }}>|</span>
        <span style={{ color: 'var(--text2)' }}>TradeAI {opinion.tradeai_original.score} → Shadow {opinion.hermes_enhancement.shadow_score} ({opinion.hermes_enhancement.delta >= 0 ? '+' : ''}{opinion.hermes_enhancement.delta})</span>
        {opinion.hermes_audit.risk_flags.length > 0 && <span style={{ color: '#ef4444' }}>⚠ {opinion.hermes_audit.risk_flags.length} risk flag{opinion.hermes_audit.risk_flags.length > 1 ? 's' : ''}</span>}
      </div>
    )
  }

  return (
    <div style={{ border: `1px solid ${color}30`, borderRadius: 10, overflow: 'hidden', marginTop: 8 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: `${color}08` }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)' }}>Hermes Second Opinion</span>
        <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, fontWeight: 700, background: `${color}15`, color }}>{opinion.hermes_agreement_status.replace(/_/g, ' ')}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
        {/* TradeAI */}
        <div style={{ padding: '10px 12px', borderRight: '1px solid var(--border)' }}>
          <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600, marginBottom: 4 }}>TRADEAI ORIGINAL</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)', marginBottom: 2 }}>{opinion.tradeai_original.score}</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>{opinion.tradeai_original.decision}</div>
          <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.4 }}>{opinion.tradeai_original.summary}</div>
        </div>

        {/* Hermes */}
        <div style={{ padding: '10px 12px' }}>
          <div style={{ fontSize: 9, color: '#60a5fa', fontWeight: 600, marginBottom: 4 }}>HERMES ENHANCEMENT</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: opinion.hermes_enhancement.delta < 0 ? '#ef4444' : opinion.hermes_enhancement.delta > 0 ? '#22c55e' : 'var(--text0)', marginBottom: 2 }}>
            {opinion.hermes_enhancement.shadow_score}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>{opinion.hermes_enhancement.delta >= 0 ? '+' : ''}{opinion.hermes_enhancement.delta} delta</div>
          <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.4 }}>{opinion.hermes_enhancement.summary}</div>
        </div>
      </div>

      {/* Evidence summary bar */}
      <div style={{ padding: '4px 12px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, fontWeight: 700, background: `${eqColor}15`, color: eqColor }}>Evidence: {evidenceQuality}</span>
          {opinion.hermes_enhancement.lesson_types.map(t => (
            <span key={t} style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(59,130,246,.1)', color: '#60a5fa' }}>{t.replace(/_/g, ' ')}</span>
          ))}
        </div>
        <button onClick={() => setShowEvidence(!showEvidence)} style={{ fontSize: 8, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: showEvidence ? 'var(--bg2)' : 'transparent', color: 'var(--text3)', cursor: 'pointer' }}>
          {showEvidence ? 'Hide' : 'Show'} Evidence
        </button>
      </div>

      {/* Expandable evidence drawer */}
      {showEvidence && (
        <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border)', background: 'var(--bg0)', fontSize: 10 }}>
          {opinion.hermes_audit.risk_flags.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#ef4444', marginBottom: 2 }}>Risk Flags</div>
              {opinion.hermes_audit.risk_flags.map((f, i) => (
                <div key={i} style={{ color: '#fca5a5', lineHeight: 1.4, paddingLeft: 8 }}>⚠ {f}</div>
              ))}
            </div>
          )}
          {opinion.hermes_audit.missing_context.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#f59e0b', marginBottom: 2 }}>Missing Context</div>
              {opinion.hermes_audit.missing_context.map((m, i) => (
                <div key={i} style={{ color: '#fde68a', lineHeight: 1.4, paddingLeft: 8 }}>○ {m}</div>
              ))}
            </div>
          )}
          <div style={{ marginBottom: 4 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text2)', marginBottom: 2 }}>Evidence Summary</div>
            <div style={{ color: 'var(--text3)', lineHeight: 1.4 }}>
              Confidence: {(opinion.hermes_confidence * 100).toFixed(0)}% · Learning links: {opinion.hermes_audit.learning_links} · Lessons: {opinion.hermes_enhancement.lesson_types.join(', ') || 'none'}
            </div>
          </div>
        </div>
      )}

      {/* Operator choice controls */}
      <div style={{ padding: '6px 12px', borderTop: '1px solid var(--border)', display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {['Keep TradeAI', 'Use Hermes', 'Keep Both', 'Reject', 'Escalate'].map(ch => {
          const choiceKey = ch === 'Keep TradeAI' ? 'KEEP_TRADEAI_ORIGINAL' : ch === 'Use Hermes' ? 'USE_HERMES_ENHANCEMENT' : ch === 'Keep Both' ? 'KEEP_BOTH' : ch === 'Reject' ? 'REJECT_BOTH' : 'ESCALATE_HIGH_LLM'
          return (
            <button key={ch} onClick={() => {
              fetch('/api/v2/hermes/advisory-choice', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ opinion_id: `${opinion.symbol}_${opinion.strategy}`, object_type: 'advisory', object_id: opinion.symbol, symbol: opinion.symbol, strategy: opinion.strategy, operator_choice: choiceKey }),
              }).then(() => alert(`Choice saved: ${ch}`)).catch(console.error)
            }} style={{ fontSize: 8, padding: '3px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>
              {ch}
            </button>
          )
        })}
      </div>

      {/* Footer */}
      <div style={{ padding: '4px 12px 6px', borderTop: '1px solid var(--border)', fontSize: 8, color: 'var(--text3)', display: 'flex', justifyContent: 'space-between' }}>
        <span>Confidence: {(opinion.hermes_confidence * 100).toFixed(0)}% · Links: {opinion.hermes_audit.learning_links}</span>
        <span>Advisory only — no overwrite — no execution</span>
      </div>
    </div>
  )
}
