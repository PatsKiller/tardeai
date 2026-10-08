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
        Source: /api/v2/command → llm_intelligence (cloud free OAuth Grok→ChatGPT · quality-gated · last-good cache retained on fail)

      </div>
    </div>
  )
}

/** AEC Executive Brief — hourly, Command Center only (operator 2026-10-07; no Telegram). Source: /api/v2/command
 *  → executive_brief, the newest cycle.narrator.brief on the agent bus. Read-only. */
export function ExecutiveBriefCard({ brief }: { brief: any }) {
  if (!brief) return null
  const age = typeof brief.age_s === 'number' ? brief.age_s : null
  const ageLabel = age == null ? '' : age < 3600 ? `${Math.round(age / 60)}m ago` : `${Math.round(age / 3600)}h ago`
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <div style={{ fontSize: TYPE.base, fontWeight: 700, color: 'var(--text0)' }}>Executive Brief</div>
        {ageLabel && <span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>{ageLabel}</span>}
        {brief.stale && <span style={{ fontSize: TYPE.xs, color: BB.amber, fontWeight: 700 }}>STALE</span>}
        {brief.suppressed_repeat && <span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>unchanged since last hour</span>}
      </div>
      {brief.body ? (
        <pre style={{ fontSize: TYPE.xs, color: 'var(--text2)', lineHeight: 1.5, whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'var(--font-mono, monospace)' }}>
          {String(brief.body).split('\n').filter((l: string) => !l.startsWith('Trade AI — Executive Brief')).join('\n').trim()}
        </pre>
      ) : (
        <div style={{ fontSize: TYPE.xs, color: BB.amber }}>
          Executive Brief unavailable{brief.error ? ` — ${brief.error}` : ' — no brief on the agent bus yet (hourly AEC cycle)'}.
        </div>
      )}
      <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/command → executive_brief ({brief.source})</div>
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
