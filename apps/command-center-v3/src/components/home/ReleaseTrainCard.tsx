import { Link } from 'react-router-dom'
import { useEffect, useState, type ReactNode } from 'react'
import { useApi } from '../../hooks/useApi'
import { Chip } from '../primitives/Chip'
import { RADIUS, TOKENS, TYPE, toneVars, numStyle } from '../../lib/designTokens'
import {
  freshness, freshnessText, freshnessTone, queueFrom, RELEASE_TRAIN_PATHS, summaryFrom,
  type ReleaseQueueWire, type ReleaseTrainSummaryWire, type SummaryItem,
} from '../../lib/releaseTrain'
import ReleaseStopControl from '../ReleaseStopControl'

// Release train (Release Train v2, 2026-10-21) — Home card over GET /api/v2/coordination/release-train (summary)
// and /queue (current train: the summary has no current-train field). Next window, ready/held counts, last outcome,
// current train, standing-policy state and STOP RELEASES. Missing or old data shows UNAVAILABLE / STALE with its age
// (lib/releaseTrain.ts), never 0 or green.

function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

function TrainFact({ label, item, children }: { label: string; item: SummaryItem; children?: ReactNode }) {
  const off = item.f.state === 'UNAVAILABLE' || item.f.state === 'STALE'
  return (
    <div style={{ minWidth: 120 }} title={item.f.reason ?? undefined}>
      <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 700 }}>{label}</div>
      <div style={{ ...numStyle, fontSize: TYPE.base, fontWeight: 650,
        color: off ? toneVars('warning').color : item.tone === 'neutral' ? TOKENS.text[0] : toneVars(item.tone).color }}>
        {item.text}{children}
      </div>
    </div>
  )
}

export default function ReleaseTrainCard() {
  const sumApi = useApi<ReleaseTrainSummaryWire>(RELEASE_TRAIN_PATHS.summary, 60_000)
  const qApi = useApi<ReleaseQueueWire>(RELEASE_TRAIN_PATHS.queue, 60_000)
  const now = useNow(15_000)
  const sumF = freshness(sumApi.data?.generated_at, !!sumApi.data, { nowMs: now, loading: sumApi.loading, error: sumApi.error })
  const qF = freshness(qApi.data?.generated_at, !!qApi.data, { nowMs: now, loading: qApi.loading, error: qApi.error })
  const s = summaryFrom(sumApi.data, sumF, now, queueFrom(qApi.data, qF, now))
  return (
    <section data-testid="release-train-card" aria-label="Release train"
      style={{ border: `1px solid ${TOKENS.border}`, borderLeft: `3px solid ${toneVars('danger').color}`, borderRadius: RADIUS.md,
        background: TOKENS.bg[1], padding: '10px 12px', marginBottom: 12, display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <strong style={{ color: TOKENS.text[0], fontSize: TYPE.md }}>Release train</strong>
        <Chip tone={freshnessTone(sumF)} title={sumF.reason ?? undefined}>{freshnessText(sumF)}</Chip>
        {s.degraded.length > 0 && sumF.state !== 'UNAVAILABLE' && (
          <Chip tone="warning" title={s.degraded.join(' · ')}>{s.degraded.length} field{s.degraded.length > 1 ? 's' : ''} STALE/UNAVAILABLE</Chip>
        )}
        <span style={{ flex: 1 }} />
        <Link to="/coordination?tab=release" style={{ fontSize: TYPE.xs, fontWeight: 700, color: TOKENS.info, textDecoration: 'none' }}>Coordination → Release train</Link>
      </div>
      {sumF.state === 'UNAVAILABLE' && (
        <div style={{ fontSize: TYPE.sm, color: TOKENS.warning }}>
          Release-train read model UNAVAILABLE{sumF.reason ? ` (${sumF.reason})` : ''} — nothing below is known to be ready or healthy. STOP still works.
        </div>
      )}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <TrainFact label="next window" item={s.nextWindow} />
        <TrainFact label="ready" item={s.ready} />
        <TrainFact label="held" item={s.held} />
        <TrainFact label="last outcome" item={s.lastOutcome} />
        <TrainFact label="current train" item={s.currentTrain} />
        <TrainFact label="standing policy" item={s.policy} />
      </div>
      <ReleaseStopControl compact />
    </section>
  )
}
