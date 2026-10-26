// Deploy hold strip — Mergify merges; host poller promotes (AGENTS.md §25.10 soft-add).
// Replaces ReleaseTrainCard / Run now UI. STOP here holds promote; kill switch stays on Ops → Controls.
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { Chip, ChipRow } from '../primitives'
import { RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import { RELEASE_TRAIN_PATHS, freshness, type ReleaseTrainSummaryWire } from '../../lib/releaseTrain'

const panel = {
  background: TOKENS.bg[1],
  border: `1px solid ${TOKENS.border}`,
  borderRadius: RADIUS.md,
  padding: 14,
  display: 'grid' as const,
  gap: 8,
  minWidth: 0,
}

/** Observe deploy STOP + links. No Run now / Arm / Resume. */
export default function DeployHoldStrip() {
  const sumApi = useApi<ReleaseTrainSummaryWire>(RELEASE_TRAIN_PATHS.summary, 60_000)
  const f = freshness(sumApi.data?.generated_at, !!sumApi.data, {
    nowMs: Date.now(),
    loading: sumApi.loading,
    error: sumApi.error,
  })
  const stop = sumApi.data?.stop?.value
  const latch = stop?.state ?? '—'
  const effective = !!stop?.effective_stop
  return (
    <section data-testid="deploy-hold-strip" aria-label="Deploy hold" style={panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <div>
          <div style={{ fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }}>Deploy on main</div>
          <p style={{ margin: '4px 0 0', fontSize: TYPE.sm, color: TOKENS.text[2] }}>
            Mergify merges to main on the ET schedule. The host poller promotes CURRENT when tip ≠ pin and this STOP is clear.
            Emergency promote is host CLI only (release-write naming the SHA).
          </p>
        </div>
        <ChipRow>
          <Chip tone={f.state === 'OK' ? 'neutral' : 'warning'} title={f.reason || ''}>{f.state}</Chip>
          <Chip tone={effective ? 'danger' : 'neutral'}>STOP {String(latch)}</Chip>
        </ChipRow>
      </div>
      <ChipRow>
        <Link to="/system/ops-controls?tab=jobs" data-testid="deploy-hold-ops-link"
          style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.primary, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>
          Ops → Controls · Deploy hold &amp; kill switch →
        </Link>
        <Link to="/system/releases" data-testid="deploy-hold-releases-link"
          style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.primary, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>
          Releases &amp; schedules →
        </Link>
        <a href="https://dashboard.mergify.com" target="_blank" rel="noreferrer" data-testid="deploy-hold-mergify-link"
          style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.primary, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>
          Mergify dashboard ↗
        </a>
      </ChipRow>
    </section>
  )
}
