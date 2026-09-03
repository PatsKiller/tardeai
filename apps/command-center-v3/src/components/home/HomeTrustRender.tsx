/** Drop-in Home trust render helpers — keeps HomeHub patches small and testable. */
import { Link } from 'react-router-dom'
import { isValidBriefingProse, briefingProse } from '../../lib/homeLabels'
import { BB, T, TYPE } from '../../lib/watchTokens'

export function HermesGatewayLine({ status, loopActive }: { status?: string; loopActive?: boolean }) {
  const ok = status === 'ok'
  const byDesign = !ok && !!loopActive
  const color = ok ? BB.green : byDesign ? BB.amber : BB.red
  const label = ok ? (status || 'ok') : byDesign ? 'disabled (fleet via timers)' : (status || 'offline')
  const tip = ok
    ? 'Hermes gateway healthy'
    : 'Intentionally disabled — research fleet runs via hermes-*.timer + scripts (PHASE208D). Do not enable to "fix".'
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: TYPE.xs, color: 'var(--text2)' }}>
      <span>Gateway</span>
      <span style={{ color, fontWeight: 700 }} title={tip}>{label}</span>
    </div>
  )
}

export function AiIntelligenceBriefing({ llm }: { llm: any }) {
  if (!llm) return null
  const sections: [string, any][] = [
    ['Portfolio Risk', llm.portfolio_risk],
    ['Morning Synthesis', llm.morning_synthesis],
  ]
  const rendered = sections.map(([k, v]) => {
    const prose = briefingProse(v)
    const ok = isValidBriefingProse(prose)
    return { k, prose, ok, had: v != null && String(v).trim() !== '' }
  }).filter(s => s.had)

  if (!rendered.length) return null

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginTop: 14 }}>
      <div style={{ fontSize: TYPE.base, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>AI Intelligence Briefing</div>
      {rendered.map(({ k, prose, ok }) => (
        <div key={k} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: TYPE.xs, color: T.link, textTransform: 'uppercase', marginBottom: 3 }}>{k}</div>
          {ok ? (
            <div style={{ fontSize: TYPE.xs, color: 'var(--text2)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{prose}</div>
          ) : (
            <div style={{ fontSize: TYPE.xs, color: BB.amber, lineHeight: 1.55 }}>
              {k} unavailable — last generation failed quality checks (corrupt or empty LLM output was rejected).
              Re-run enrichment weekday 7:20 AM or: <code style={{ fontSize: TYPE.xs }}>.venv/bin/python scripts/llm_intelligence_enrichment.py --section {k === 'Morning Synthesis' ? 'morning_synthesis' : 'portfolio_risk'}</code>
            </div>
          )}
        </div>
      ))}
      <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 6 }}>
        Source: /api/v2/command → llm_intelligence (free local Ollama first · quality-gated)
      </div>
    </div>
  )
}

export function EquityThinNote({ days }: { days: number }) {
  if (days >= 10) return null
  return (
    <div style={{ fontSize: TYPE.xs, color: BB.amber, marginTop: 6, lineHeight: 1.4 }}>
      Thin history ({days} days) — prefer 30–90d metrics. Check System → metrics-history / pipeline backfill.
      <Link to="/system?tab=pipeline" style={{ marginLeft: 6, color: T.link, fontWeight: 700, textDecoration: 'none' }}>System → Pipeline →</Link>
    </div>
  )
}
