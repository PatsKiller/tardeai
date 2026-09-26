import { REVIEW } from '../lib/optionsTooltips'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import type { OptionProposal } from './OptionProposalCard'

const MUTED = 'var(--text3)'
const TEXT2 = 'var(--text2)'
const BLUE = '#60a5fa'
const AMBER = '#f59e0b'

function ensembleContent(p: OptionProposal): string {
  return [
    `OPTIONS PROPOSAL — ${p.strategy.replace(/_/g, ' ')}`,
    `Symbol: ${p.symbol} · Account: ${p.account || '—'}`,
    `Strike: $${p.strike} · Exp: ${p.expiration} · DTE: ${p.dte}`,
    `Contracts: ${p.contracts} · Premium: $${p.premium} · Credit: $${p.premium_total}`,
    `POP: ${p.pop_pct}% · Edge: ${p.edge_score} · IV: ${p.iv_rank}% · R:R: ${p.risk_reward}`,
    p.aegis_note ? `Aegis: ${p.aegis_note}` : '',
    p.reasoning || '',
    // House facts from stored memory (2026-09-26): review against the thesis, not the numbers alone.
    ...(() => {
      const m = (p as any).committee_memo
      if (!m || m.error) return []
      return [
        'HOUSE FACTS (deterministic, from stored memory):',
        `Classification: ${m.classification_label} · Research: ${m.research_status} · Confidence: ${m.confidence}`,
        `Symbol thesis ${(p as any).thesis_version_at_decision || 'none'}: ${m.investment_thesis}`,
        `Counter-evidence: ${m.contrarian_view}`,
        `Why now: ${m.why_now}`,
        `Thesis invalid when: ${(m.exit_plan?.thesis_invalid_when || []).join('; ')}`,
        'Judge only against these facts; name any missing fact rather than assume it.',
      ]
    })(),
  ].filter(Boolean).join('\n')
}

export default function OptionReviewBar({ proposal: p, autoRequest }: { proposal: OptionProposal; autoRequest?: boolean }) {
  const aegis = p.aegis_note || (p.reasoning?.includes('Aegis:') ? p.reasoning.split('Aegis:')[1]?.split('·')[0]?.trim() : null)

  return (
    <div style={{ marginTop: 10, padding: '9px 10px', borderRadius: 8, background: 'rgba(168,85,247,.06)', border: '1px solid rgba(168,85,247,.22)' }}>
      <div title={REVIEW.reviewedBy} style={{ fontSize: 9, fontWeight: 900, color: MUTED, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 6, cursor: 'help' }}>
        Reviewed by ⓘ
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 8 }}>
        <span title={REVIEW.aegis} style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: 'var(--bg2)', color: TEXT2, border: '1px solid var(--border)', cursor: 'help' }}>
          🛡 Aegis{p.aegis_verdict ? ` · ${p.aegis_verdict}` : ''}
        </span>
        {aegis && <span style={{ fontSize: 9.5, color: MUTED, flex: '1 1 180px', lineHeight: 1.35 }}>{aegis}</span>}
      </div>
      <div title={REVIEW.ensemble} style={{ fontSize: 9, color: MUTED, marginBottom: 4, cursor: 'help' }}>
        Aegis model review: <b style={{ color: BLUE }}>Grok</b> + <b style={{ color: '#10a37f' }}>ChatGPT</b> (OAuth) + <b style={{ color: '#2dd4bf' }}>DeepSeek</b>. It checks this card against the house thesis; it does not fetch news, earnings or filings, and a model vote is not research or a CIO decision. ⓘ
      </div>
      <EnsembleValidationInline
        targetType="options_proposal"
        targetId={p.id}
        subject={`${p.symbol} ${p.strategy} $${p.strike}`}
        content={ensembleContent(p)}
        task="options_proposal_quality"
        autoRequest={autoRequest}
        compact
      />
      {!autoRequest && (
        <div title={REVIEW.worker} style={{ fontSize: 8.5, color: MUTED, marginTop: 6, fontStyle: 'italic', cursor: 'help' }}>
          Worker processes ~10–40s per proposal — use “Validate all” to queue every card. ⓘ
        </div>
      )}
    </div>
  )
}