/** Weekly Hermes quality spot-check — compact desk for operator review.
 *  Advisory only. Pulls pipeline-quality findings + health kill-switch / gateway truth.
 *  Does not enable hermes-gateway (PHASE208D — fleet via timers).
 */
import { useApi } from '../hooks/useApi'
import { BB, T, TYPE } from '../lib/watchTokens'
import { humanizeFinding, FINDING_SEVERITY_COLOR } from '../lib/intelFindingLabels'

type Props = {
  onDrill?: (ctx: { title: string; subtitle: string; endpoint: string; rows: any[] }) => void
}

export default function HermesQualitySpotCheck({ onDrill }: Props) {
  const { data: pipeQual } = useApi<any>('/api/v2/hermes/pipeline-quality', 120_000)
  const { data: health } = useApi<any>('/api/v2/hermes/health', 120_000)

  const findings = (pipeQual?.findings ?? pipeQual?.data?.findings ?? []) as any[]
  const open = findings.filter(f => {
    const st = String(f.status || '').toLowerCase()
    return st !== 'resolved' && st !== 'closed' && st !== 'archived'
  })
  const recent = (open.length ? open : findings).slice(0, 8)
  const crit = recent.filter(f => String(f.severity || '').toLowerCase() === 'critical').length
  const warn = recent.filter(f => String(f.severity || '').toLowerCase() === 'warning').length

  const kill = !!(health?.kill_switch_active ?? health?.kill_switch?.active)
  const gateway = String(health?.gateway_status || 'unknown')
  const staging = health?.staging_counts || {}
  const researchN = staging.hermes_research_intelligence ?? staging.research ?? '—'
  const findingsN = staging.hermes_validation_findings ?? findings.length

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Weekly quality spot-check</div>
        <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>advisory · local Hermes · no broker</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 8, textAlign: 'center' }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: crit ? BB.red : BB.green }}>{crit}</div>
          <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>Critical open</div>
        </div>
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 8, textAlign: 'center' }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: warn ? BB.amber : 'var(--text0)' }}>{warn}</div>
          <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>Warnings</div>
        </div>
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 8, textAlign: 'center' }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: kill ? BB.red : BB.green }}>{kill ? 'ON' : 'off'}</div>
          <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>Kill switch</div>
        </div>
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 8, textAlign: 'center' }}>
          <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: gateway === 'ok' ? BB.green : BB.amber }} title="PHASE208D: gateway intentionally disabled; fleet via hermes-*.timer">
            {gateway === 'ok' ? 'ok' : 'disabled by design'}
          </div>
          <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>Gateway</div>
        </div>
      </div>

      <div style={{ fontSize: TYPE.xs, color: 'var(--text2)', marginBottom: 8 }}>
        Staging: research rows <b style={{ color: 'var(--text1)' }}>{researchN}</b>
        {' · '}findings <b style={{ color: 'var(--text1)' }}>{findingsN}</b>
        {' · '}open in view <b style={{ color: 'var(--text1)' }}>{open.length || recent.length}</b>
      </div>

      {recent.length === 0 ? (
        <div style={{ color: 'var(--text3)', fontSize: TYPE.sm, padding: '6px 0' }}>No pipeline-quality findings loaded.</div>
      ) : (
        recent.map((f, i) => {
          const h = humanizeFinding(f)
          const c = FINDING_SEVERITY_COLOR[h.severity]
          return (
            <div
              key={f.id ?? i}
              onClick={() => onDrill?.({
                title: h.title,
                subtitle: h.severity,
                endpoint: '/api/v2/hermes/pipeline-quality',
                rows: [{ ...f, humanized_title: h.title, humanized_meaning: h.meaning, humanized_resolve: h.resolve }],
              })}
              style={{
                padding: '7px 4px', borderBottom: '1px solid var(--border)',
                cursor: onDrill ? 'pointer' : 'default', fontSize: TYPE.sm,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ width: 6, height: 6, borderRadius: 3, background: c, flexShrink: 0 }} />
                <span style={{ color: 'var(--text0)', fontWeight: 700 }}>{h.title}</span>
              </div>
              <div style={{ fontSize: TYPE.xs, color: 'var(--text2)', marginTop: 3, lineHeight: 1.4 }}>
                {h.meaning}
              </div>
              <div style={{ fontSize: TYPE.xs, color: c, marginTop: 3 }}>
                → {h.resolve}{h.where ? <span style={{ color: 'var(--text3)' }}>  ·  {h.where}</span> : null}
              </div>
            </div>
          )
        })
      )}

      <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 10 }}>
        Sources: /api/v2/hermes/pipeline-quality · /api/v2/hermes/health.
        Operator checklist: (1) kill switch off (2) loop timer armed (3) no critical open findings (4) do not enable hermes-gateway.service.
      </div>
    </div>
  )
}
