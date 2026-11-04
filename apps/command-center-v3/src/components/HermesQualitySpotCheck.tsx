/** Weekly Hermes quality spot-check — compact desk for operator review.
 *  Advisory only. Pulls pipeline-quality findings + health kill-switch / gateway truth.
 *  Does not enable hermes-gateway (PHASE208D — fleet via timers).
 */
import { useApi } from '../hooks/useApi'
import { BB, T, TYPE } from '../lib/watchTokens'
import { countText, findingTypeLabel, severityLabel } from '../lib/hermesPlainLanguage'

type Props = {
  onDrill?: (ctx: { title: string; subtitle: string; endpoint: string; rows: any[] }) => void
}

const sevColor = (s?: string) => {
  const v = (s || '').toLowerCase()
  if (v === 'critical' || v === 'error') return BB.red
  if (v === 'warning' || v === 'warn') return BB.amber
  return 'var(--text2)'
}

export default function HermesQualitySpotCheck({ onDrill }: Props) {
  // ?limit=10 (memory 2026-10-25): the server returns the newest findings, the newest OPEN findings and both counts
  // instead of all ~31.6k rows; the full-list fallback below still works against an older server.
  const { data: pipeQual } = useApi<any>('/api/v2/hermes/pipeline-quality?limit=10', 120_000)
  const { data: health } = useApi<any>('/api/v2/hermes/health', 120_000)

  const pq = pipeQual?.findings ? pipeQual : (pipeQual?.data ?? pipeQual)
  const findings = (pq?.findings ?? []) as any[]
  const isOpen = (f: any) => {
    const st = String(f.status || '').toLowerCase()
    return st !== 'resolved' && st !== 'closed' && st !== 'archived'
  }
  const open = (Array.isArray(pq?.open_findings) ? pq.open_findings : findings.filter(isOpen)) as any[]
  // FQ-039 R1 (codex, P2607-R1): `open_count` is the producer's own count and 0 is a legitimate answer. The old
  // expression `openCount || recent.length` replaced a known zero with the length of the historical list, and the
  // sentence around it called that "still need attention" — resolved history misclassified as open work.
  const openKnown: boolean = typeof pq?.open_count === 'number'
  const openCount: number | null = openKnown ? (pq.open_count as number) : (Array.isArray(pq?.open_findings) ? pq.open_findings.length : null)
  const findingsTotal: number = typeof pq?.total === 'number' ? pq.total : findings.length
  const showingOpen = open.length > 0
  const recent = (showingOpen ? open : findings).slice(0, 8)
  // FQ-039 R3 (codex P2607-R3): "no open findings" is a claim about the whole queue, and only the producer's own
  // count can support it. A positive count with an empty returned slice is a gap between two reads — the count and
  // the rows are three separate reads on the server — and an unreported count is unknown. Both describe what the
  // list below actually is instead of asserting an absence they cannot see.
  const historyCaption: { testid: string; text: string } | null = showingOpen ? null
    : openCount === 0
      ? { testid: 'quality-history-caption', text: 'No open findings — showing the most recent resolved ones.' }
      : openCount != null
        ? { testid: 'quality-history-gap', text: `The count says ${countText(openCount)} still need attention, but the open list came back empty — the findings below are the most recent ones, not the open set.` }
        : { testid: 'quality-history-unknown', text: 'The open count was not reported, so the list below is the most recent findings — this is not proof that nothing is open.' }
  const crit = recent.filter(f => String(f.severity || '').toLowerCase() === 'critical').length
  const warn = recent.filter(f => String(f.severity || '').toLowerCase() === 'warning').length

  const kill = !!(health?.kill_switch_active ?? health?.kill_switch?.active)
  const gateway = String(health?.gateway_status || 'unknown')
  const staging = health?.staging_counts || {}
  const researchN = staging.hermes_research_intelligence ?? staging.research ?? '—'
  const findingsN = staging.hermes_validation_findings ?? findingsTotal

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
        Research so far: <b style={{ color: 'var(--text1)' }}>{countText(researchN)}</b> rows
        {' · '}<b style={{ color: 'var(--text1)' }}>{countText(findingsN)}</b> quality findings recorded
        {openCount === 0
          ? <>{' · '}<b style={{ color: 'var(--text1)' }}>nothing open</b></>
          : openCount != null
            ? <>{' · '}<b style={{ color: 'var(--text1)' }}>{countText(openCount)}</b> still need attention</>
            : <>{' · '}<b style={{ color: 'var(--text1)' }}>open count not reported</b></>}
      </div>

      {recent.length === 0 ? (
        <div style={{ color: 'var(--text3)', fontSize: TYPE.sm, padding: '6px 0' }}>No pipeline-quality findings loaded.</div>
      ) : (
        <>
        {/* FQ-039 R1: when nothing is open, say that the list below is history — never let resolved findings read as
            outstanding work. */}
        {historyCaption && (
          <div data-testid={historyCaption.testid} style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 4 }}>
            {historyCaption.text}
          </div>
        )}
        {recent.map((f, i) => (
          <div
            key={f.id ?? i}
            onClick={() => onDrill?.({
              title: f.finding_type ?? `Finding ${i}`,
              subtitle: f.severity ?? '',
              endpoint: '/api/v2/hermes/pipeline-quality',
              rows: [f],
            })}
            style={{
              padding: '6px 4px', borderBottom: '1px solid var(--border)',
              cursor: onDrill ? 'pointer' : 'default', fontSize: TYPE.sm,
            }}
          >
            <span style={{ color: sevColor(f.severity), fontWeight: 700 }}>{severityLabel(f.severity)}</span>
            <span style={{ marginLeft: 8, color: 'var(--text0)' }} title={f.finding_type ? `Finding type: ${f.finding_type}` : undefined}>· {findingTypeLabel(f.finding_type)}</span>
            {f.symbol && <span style={{ marginLeft: 8, color: T.link, fontFamily: 'monospace' }}>{f.symbol}</span>}
            <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 2, lineHeight: 1.4 }}>
              {String(f.description || f.recommended_action || '').slice(0, 160)}
              {String(f.description || '').length > 160 ? '…' : ''}
            </div>
          </div>
        ))}
        </>
      )}

      <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 10 }}>
        Operator checklist: (1) kill switch off (2) loop timer armed (3) no critical open findings (4) leave the Hermes
        gateway disabled.
        {/* FQ-039: the endpoints and the unit name stay available, behind a disclosure, not in the reading line. */}
        <details style={{ marginTop: 4 }}>
          <summary style={{ cursor: 'pointer' }}>Where these numbers come from</summary>
          <div style={{ marginTop: 4, fontFamily: 'monospace' }}>
            Sources: /api/v2/hermes/pipeline-quality · /api/v2/hermes/health · do not enable
            hermes-gateway.service.
          </div>
          {recent.length > 0 && (
            <div style={{ marginTop: 4, fontFamily: 'monospace' }}>
              {/* FQ-039: the raw finding type of every row above, so a support question can name the exact key
                  without it being the label the operator reads. */}
              Raw finding types: {Array.from(new Set(recent.map((f: any) => String(f.finding_type ?? 'unknown')))).join(' · ')}
            </div>
          )}
        </details>
      </div>
    </div>
  )
}
