import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import InlineDualOpinionPanel from '../components/InlineDualOpinionPanel'

interface Packet {
  filename: string; symbol: string; company: string; sector: string
  thesis_summary: string; strategy_fit: string; timeframe: string; direction: string
  composite_score: number; quality_scores: Record<string, number>
  catalyst: string; technical: string
  why_not_trade: string[]; review_checklist: string[]
  risk: { entry_price: number | null; stop_price: number | null; target_price: number | null; invalidation: string }
  portfolio_fit: { account_type: string; position_size_rationale: string; conflicts: string }
  generated_by: string; generated_at: string; execution_statement: string
}

interface SandboxData {
  packets: Packet[]; total: number; sandbox_type: string; level7: string; advisory_notice: string
}

function ScoreBadge({ score }: { score: number }) {
  const color = score >= 6.5 ? '#0ecb81' : score >= 5.5 ? '#f6be00' : '#ea3943'
  return <span style={{ fontSize: 16, fontWeight: 800, color }}>{score.toFixed(1)}</span>
}

export default function ProposalSandbox() {
  const { data } = useApi<SandboxData>('/api/v2/hermes/proposal-sandbox')
  const [selected, setSelected] = useState<Packet | null>(null)

  if (!data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>

  return (
    <div style={{ display: 'flex', gap: 16, padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <PageHeader title="Proposal Sandbox" subtitle={`${data.total} file-only draft packets · Level 7 PROHIBITED`} />

        {/* Safety banner */}
        <div style={{ padding: '10px 14px', marginBottom: 16, background: 'rgba(234,57,67,.06)', border: '1px solid rgba(234,57,67,.2)', borderRadius: 8, fontSize: 11, color: '#ea3943' }}>
          <strong>FILE-ONLY SANDBOX</strong> — These are Hermes research drafts, NOT proposals, NOT trades. No execution controls. No broker access. Human review required. {data.advisory_notice}
        </div>

        {/* Packet cards */}
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
          {data.packets.map(p => {
            const cls = p.composite_score >= 6.5 ? 'PASS' : p.composite_score >= 5.5 ? 'IMPROVE' : 'REJECT'
            const clsColor = cls === 'PASS' ? '#0ecb81' : cls === 'IMPROVE' ? '#f6be00' : '#ea3943'
            return (
              <div key={p.filename} onClick={() => setSelected(p)} style={{
                padding: '14px 16px', background: selected?.filename === p.filename ? 'var(--bg2)' : 'var(--bg1)',
                border: `1px solid ${selected?.filename === p.filename ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 10, cursor: 'pointer', transition: 'border-color .15s'
              }}>
                {/* Top badges */}
                <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 4, fontWeight: 700, background: `${clsColor}15`, color: clsColor }}>{cls}</span>
                  <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 4, background: 'rgba(234,57,67,.08)', color: '#ea3943' }}>SANDBOX</span>
                  <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 4, background: 'rgba(74,144,244,.08)', color: '#4a90f4' }}>{p.strategy_fit?.replace(/_/g, ' ')}</span>
                </div>

                {/* Symbol + score */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)' }}>{p.symbol}</div>
                    <div style={{ fontSize: 9, color: 'var(--text3)' }}>{p.company}</div>
                  </div>
                  <ScoreBadge score={p.composite_score} />
                </div>

                {/* Thesis */}
                <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 6, lineHeight: 1.4, height: 28, overflow: 'hidden' }}>{p.thesis_summary}</div>

                {/* Why not trade (first item) */}
                {p.why_not_trade?.[0] && (
                  <div style={{ fontSize: 9, color: '#ea3943', lineHeight: 1.3, height: 12, overflow: 'hidden' }}>
                    ⚠ {p.why_not_trade[0]}
                  </div>
                )}

                {/* Footer */}
                <div style={{ display: 'flex', gap: 6, fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>
                  <span>{p.direction} · {p.timeframe}</span>
                  <span>· {p.sector}</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Detail drawer */}
      {selected && (
        <div style={{ width: 340, flexShrink: 0, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, position: 'sticky', top: 12, maxHeight: '88vh', overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text0)' }}>{selected.symbol}</div>
            <button onClick={() => setSelected(null)} style={{ fontSize: 11, width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>✕</button>
          </div>

          <div style={{ fontSize: 9, color: '#ea3943', marginBottom: 10, padding: '4px 8px', background: 'rgba(234,57,67,.06)', borderRadius: 6, fontWeight: 600 }}>
            {selected.execution_statement}
          </div>

          {/* Thesis */}
          <Section title="Thesis">
            <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5, marginBottom: 4 }}>{selected.thesis_summary}</div>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>{selected.direction} · {selected.strategy_fit?.replace(/_/g, ' ')} · {selected.timeframe}</div>
          </Section>

          {/* Evidence */}
          <Section title="Evidence">
            <Field label="Catalyst" value={selected.catalyst} />
            <Field label="Technical" value={selected.technical} />
          </Section>

          {/* Risk */}
          <Section title="Risk / Invalidation">
            <Field label="Invalidation" value={selected.risk?.invalidation} />
            {selected.risk?.entry_price && <Field label="Entry" value={`$${selected.risk.entry_price}`} />}
            {selected.risk?.stop_price && <Field label="Stop" value={`$${selected.risk.stop_price}`} />}
            {!selected.risk?.entry_price && <div style={{ fontSize: 9, color: '#f6be00' }}>No live quote — prices not set</div>}
          </Section>

          {/* Portfolio fit */}
          <Section title="Portfolio Fit">
            <Field label="Account" value={selected.portfolio_fit?.account_type} />
            <Field label="Sizing" value={selected.portfolio_fit?.position_size_rationale} />
            <Field label="Conflicts" value={selected.portfolio_fit?.conflicts} />
          </Section>

          {/* Why NOT trade */}
          <Section title="Why Not Trade">
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 10, color: '#ea3943', lineHeight: 1.6 }}>
              {selected.why_not_trade?.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          </Section>

          {/* Quality scorecard */}
          <Section title="Quality Scorecard">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 10, color: 'var(--text2)' }}>Composite:</span>
              <ScoreBadge score={selected.composite_score} />
            </div>
            {selected.quality_scores && Object.entries(selected.quality_scores).filter(([k]) => k !== 'composite').map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, padding: '2px 0', color: 'var(--text3)' }}>
                <span>{k.replace(/_/g, ' ')}</span>
                <span style={{ color: (v as number) >= 7 ? '#0ecb81' : (v as number) >= 5 ? '#f6be00' : '#ea3943', fontWeight: 600 }}>{v as number}/10</span>
              </div>
            ))}
          </Section>

          {/* Review checklist */}
          <Section title="Human Review Required">
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 9, color: 'var(--text2)', lineHeight: 1.6 }}>
              {selected.review_checklist?.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          </Section>

          {/* Hermes Second Opinion */}
          <InlineDualOpinionPanel symbol={selected.symbol} strategy={selected.strategy_fit} compact={false} />

          {/* Metadata */}
          <div style={{ fontSize: 8, color: 'var(--text3)', borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 8 }}>
            <div>Agent: {selected.generated_by}</div>
            <div>Generated: {selected.generated_at}</div>
            <div>File: {selected.filename}</div>
          </div>
        </div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10, padding: '8px 10px', background: 'var(--bg2)', borderRadius: 6 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', marginBottom: 4 }}>{title}</div>
      {children}
    </div>
  )
}

function Field({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null
  return <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5, marginBottom: 2 }}><strong>{label}:</strong> {value}</div>
}
