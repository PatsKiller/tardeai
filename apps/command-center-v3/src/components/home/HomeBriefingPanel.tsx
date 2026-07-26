import { Link } from 'react-router-dom'
import { briefingProse, isValidBriefingProse } from '../../lib/homeLabels'

/** Home AI Intelligence Briefing — fail-closed on corrupt LLM cache bodies. */
export default function HomeBriefingPanel({ llm }: { llm: any }) {
  if (!llm) return null
  const sections: [string, any][] = [
    ['Portfolio Risk', llm.portfolio_risk],
    ['Morning Synthesis', llm.morning_synthesis],
  ]
  const rendered = sections.map(([k, v]) => {
    const prose = briefingProse(v)
    const ok = isValidBriefingProse(prose)
    return { k, prose, ok, hasAny: v != null && String(v).trim() !== '' }
  }).filter(s => s.hasAny)

  if (!rendered.length) return null

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginTop: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>AI Intelligence Briefing</div>
      {rendered.map(({ k, prose, ok }) => (
        <div key={k} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 9, color: '#60a5fa', textTransform: 'uppercase', marginBottom: 3 }}>{k}</div>
          {ok ? (
            <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{prose}</div>
          ) : (
            <div style={{ fontSize: 10, color: '#f59e0b', lineHeight: 1.5 }}>
              {k} unavailable — last generation failed quality checks (corrupt or empty local-LLM output).
              Prior good text was retained server-side when possible. Re-run weekday 7:20 enrichment after GPU is healthy.
            </div>
          )}
        </div>
      ))}
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>
        Source: /api/v2/command → llm_intelligence (free local Ollama / gemma daily · fail-closed quality)
      </div>
    </div>
  )
}

/** Compact Hermes gateway status with resolution guidance. */
export function HermesGatewayLine({ status, autonomousOn, staged }: {
  status?: string
  autonomousOn?: boolean
  staged?: number
}) {
  const ok = status === 'ok' || status === 'active' || status === 'running'
  if (ok) {
    return <span style={{ color: '#22c55e' }}>{status}</span>
  }
  // Not a false positive: gateway_status is systemd is-active of hermes-gateway.service.
  // Research can still stage via autonomous loop / coordinator without the gateway daemon.
  const label = status || 'offline'
  return (
    <span style={{ color: '#ef4444' }} title="hermes-gateway.service inactive (systemd). Not a UI false positive. Autonomous loop can still stage research into Postgres.">
      {label}
      {autonomousOn && (staged ?? 0) > 0 ? ' · research still staging via loop' : ''}
    </span>
  )
}

export function HermesGatewayCta() {
  return (
    <Link to="/health" style={{ fontSize: 9, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>
      System / Health → resolve gateway
    </Link>
  )
}
