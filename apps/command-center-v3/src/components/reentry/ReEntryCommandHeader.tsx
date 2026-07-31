/**
 * Sticky re-entry command strip — NOW / NEAR / WATCH lanes + provenance.
 */
import { useEffect, useState, type CSSProperties } from 'react'
import type { ReEntryLane } from '../../lib/reentryDecisionScorecard'

export type ReEntryLaneCounts = {
  now: number
  near: number
  watch: number
  all: number
  armed?: number
  sourcesOk?: number
  sourcesTotal?: number
}

type Props = {
  lane: ReEntryLane
  onLane: (lane: ReEntryLane) => void
  counts: ReEntryLaneCounts
  regimeLabel?: string
  onRefresh?: () => void
  refreshing?: boolean
}

export default function ReEntryCommandHeader({
  lane, onLane, counts, regimeLabel, onRefresh, refreshing,
}: Props) {
  const [build, setBuild] = useState<string>('')
  useEffect(() => {
    fetch('/v3/build-meta.json', { cache: 'no-store' })
      .then(r => r.json())
      .then(j => {
        const sha = j?.source_commit ? String(j.source_commit).slice(0, 12) : ''
        setBuild([j?.ui_version, sha].filter(Boolean).join(' · '))
      })
      .catch(() => setBuild(''))
  }, [])

  const chip = (active: boolean): CSSProperties => ({
    fontSize: 11, fontWeight: 850, padding: '6px 12px', borderRadius: 5, cursor: 'pointer',
    border: `1px solid ${active ? 'var(--text1)' : 'var(--border)'}`,
    background: active ? 'var(--bg2)' : 'var(--bg1)',
    color: 'var(--text0)',
  })

  return (
    <div
      data-testid="reentry-command-header"
      style={{
        position: 'sticky', top: 0, zIndex: 20,
        background: 'var(--bg0, var(--bg1))', border: '1px solid var(--border)',
        borderRadius: 8, padding: '10px 12px', marginBottom: 4,
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: 'var(--text0)' }}>Re-Entry command</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>
            {regimeLabel ? `Regime ${regimeLabel}` : 'Regime —'}
            {' · '}advisory only · never auto-buys
            {counts.sourcesTotal != null && (
              <> · evidence {counts.sourcesOk ?? 0}/{counts.sourcesTotal} sources</>
            )}
            {typeof counts.armed === 'number' && counts.armed > 0 && (
              <> · {counts.armed} composite monitor{counts.armed === 1 ? '' : 's'} armed</>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }} role="tablist" aria-label="Re-entry lanes">
          {([
            ['NOW', counts.now, 'READY TO REVIEW — hard gates green, in zone'],
            ['NEAR', counts.near, 'Near entry band — prepare, not full ready'],
            ['WATCH', counts.watch, 'Wait / held / stale / missing plan'],
            ['ALL', counts.all, 'Full queue'],
          ] as const).map(([id, n, tip]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={lane === id}
              data-testid={`reentry-lane-${id.toLowerCase()}`}
              title={tip}
              onClick={() => onLane(id)}
              style={chip(lane === id)}
            >
              {id} <b>{n}</b>
            </button>
          ))}
        </div>
        {onRefresh && (
          <button type="button" onClick={onRefresh} style={chip(false)} data-testid="reentry-command-refresh">
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        )}
        {build && (
          <span title="UI build / source_commit" style={{ fontSize: 10, color: 'var(--text3)', fontFamily: 'monospace' }}>
            {build}
          </span>
        )}
      </div>
      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text3)', lineHeight: 1.45 }}>
        <b style={{ color: 'var(--text2)' }}>NOW</b> = in zone + hard gates pass.
        {' '}<b style={{ color: 'var(--text2)' }}>NEAR</b> = within ~3% of zone or soft setup.
        {' '}<b style={{ color: 'var(--text2)' }}>WATCH</b> = wait / held / stale / missing plan.
        Expand a row for gate scorecard (PASS / WAIT / UNAVAILABLE).
      </div>
    </div>
  )
}
