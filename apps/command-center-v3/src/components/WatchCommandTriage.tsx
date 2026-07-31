/**
 * Minimalist NOW strip for Watch MAIN — quality-first plan 2026-07-31.
 * Strip only; Card v4 stays locked. CTAs write lane/now into the parent.
 */
import type { CSSProperties } from 'react'
import { BB, TYPE } from '../lib/watchTokens'

export type WatchLane = 'main' | 'research' | 'coverage' | 'legacy_hermes'
export type WatchNow = 'all' | 'GO' | 'WAIT' | 'NOGO'

type Quality = {
  sample_n?: number
  main_n?: number
  main_cap?: number
  main_go?: number
  main_wait?: number
  main_nogo?: number
  actionable_n?: number
  actionable_pct?: number
  no_setup_n?: number
  no_setup_pct?: number
  by_lane?: Record<string, number>
  by_now?: Record<string, number>
}

type Weights = {
  locked?: boolean
  profile?: string
  analyst_weight?: number
  setup_quality_weight?: number
}

type Props = {
  lane: WatchLane
  now: WatchNow
  quality?: Quality | null
  weights?: Weights | null
  universeCount?: number | null
  onLane: (lane: WatchLane) => void
  onNow: (now: WatchNow) => void
}

const chip = (active: boolean, color: string): CSSProperties => ({
  fontSize: TYPE.sm,
  fontWeight: 800,
  padding: '4px 10px',
  borderRadius: 999,
  cursor: 'pointer',
  border: `1px solid ${active ? color : BB.border}`,
  background: active ? `${color}18` : 'transparent',
  color: active ? color : BB.text2,
})

const cta: CSSProperties = {
  fontSize: TYPE.sm,
  fontWeight: 800,
  padding: '6px 12px',
  borderRadius: 4,
  cursor: 'pointer',
  border: `1px solid ${BB.green}66`,
  background: `${BB.green}14`,
  color: BB.green,
}

export default function WatchCommandTriage({
  lane, now, quality, weights, universeCount, onLane, onNow,
}: Props) {
  const go = quality?.main_go ?? quality?.by_now?.GO ?? 0
  const wait = quality?.main_wait ?? quality?.by_now?.WAIT ?? 0
  const nogo = quality?.main_nogo ?? quality?.by_now?.NOGO ?? 0
  const mainN = quality?.main_n ?? (go + wait + nogo)
  const cap = quality?.main_cap ?? 60
  const researchN = quality?.by_lane?.research
  const coverageN = quality?.by_lane?.coverage
  const analystW = weights?.analyst_weight
  const setupW = weights?.setup_quality_weight
  const locked = weights?.locked

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        margin: '8px 0 12px',
        padding: '10px 12px',
        background: 'var(--bg1)',
        border: '1px solid var(--border)',
        borderRadius: 4,
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text0 }}>
          MAIN {mainN}/{cap}
        </span>
        <button type="button" style={chip(lane === 'main' && now === 'GO', BB.green)} onClick={() => { onLane('main'); onNow('GO') }}>
          {go} GO
        </button>
        <button type="button" style={chip(lane === 'main' && now === 'WAIT', BB.amber)} onClick={() => { onLane('main'); onNow('WAIT') }}>
          {wait} WAIT
        </button>
        <button type="button" style={chip(lane === 'main' && now === 'NOGO', BB.red)} onClick={() => { onLane('main'); onNow('NOGO') }}>
          {nogo} NOGO
        </button>
        <span style={{ color: BB.text3, fontSize: TYPE.sm }}>·</span>
        <button type="button" style={chip(lane === 'research', BB.text2)} onClick={() => { onLane('research'); onNow('all') }}>
          RESEARCH{researchN != null ? ` ${researchN}` : ''}
        </button>
        <button type="button" style={chip(lane === 'coverage', BB.amber)} onClick={() => { onLane('coverage'); onNow('all') }}>
          COVERAGE{coverageN != null ? ` ${coverageN}` : ''}
        </button>
        <button type="button" style={chip(lane === 'legacy_hermes', BB.text3)} onClick={() => { onLane('legacy_hermes'); onNow('all') }}>
          Legacy top-200
        </button>
        {universeCount != null && (
          <span style={{ color: BB.text3, fontSize: TYPE.sm }} title="Full non-removed universe">
            universe {universeCount.toLocaleString()}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', fontSize: TYPE.sm, color: BB.text2 }}>
        <span>
          Quality: actionable {quality?.actionable_n ?? '—'}
          {quality?.actionable_pct != null ? ` (${quality.actionable_pct}%)` : ''}
          {' · '}
          no-setup {quality?.no_setup_n ?? '—'}
          {quality?.no_setup_pct != null ? ` (${quality.no_setup_pct}%)` : ''}
        </span>
        {weights && (
          <span
            title={locked ? 'Main score profile locked — outcome graft cannot rewrite' : 'Weights unlocked'}
            style={{ color: locked ? BB.green : BB.amber }}
          >
            rank profile {weights.profile || '—'}
            {setupW != null && ` · setup ${Math.round(setupW * 100)}%`}
            {analystW != null && ` · analyst ${Math.round(analystW * 100)}%`}
            {locked ? ' · LOCKED' : ''}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        <button type="button" style={cta} onClick={() => { onLane('main'); onNow('GO') }}>
          Review GO →
        </button>
        <button
          type="button"
          style={{ ...cta, borderColor: `${BB.amber}66`, background: `${BB.amber}14`, color: BB.amber }}
          onClick={() => { onLane('main'); onNow('WAIT') }}
        >
          Fix WAIT →
        </button>
        <button
          type="button"
          style={{ ...cta, borderColor: `${BB.red}66`, background: `${BB.red}12`, color: BB.red }}
          onClick={() => { onLane('main'); onNow('NOGO') }}
        >
          Cull no-setup →
        </button>
        <button
          type="button"
          style={{ ...cta, borderColor: 'var(--border)', background: 'transparent', color: BB.text2 }}
          onClick={() => { onLane('coverage'); onNow('all') }}
        >
          Coverage only →
        </button>
        {lane !== 'main' || now !== 'all' ? (
          <button
            type="button"
            style={{ ...cta, borderColor: 'var(--border)', background: 'transparent', color: BB.text3 }}
            onClick={() => { onLane('main'); onNow('all') }}
          >
            Reset MAIN
          </button>
        ) : null}
      </div>
    </div>
  )
}
