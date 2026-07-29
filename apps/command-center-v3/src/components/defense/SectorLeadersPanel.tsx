/** Sector Leaders panel (SL-S1) — flag-gated host for SectorLeadersCard.
 *
 * Renders unless localStorage SECTOR_LEADERS_V1 === 'off' (default ON since
 * 2026-07-29, operator request — it shipped dark earlier the same day). The existing
 * RESEARCH WATCH tile (components/rotation/ActionableSectorDecisionBoard.tsx)
 * is untouched and continues to render either way, so the operator can compare
 * the two on live data before anything is retired.
 *
 * Read-only: one GET, no mutation path.
 */
import { useEffect, useState } from 'react'
import { BB, DASH, numStyle } from '../../lib/watchTokens'
import { sectorLeadersEnabled } from '../../lib/sectorLeaders'
import type { SLSector, SLStripRow } from '../../lib/sectorLeaders'
import SectorLeadersCard from './SectorLeadersCard'

const HORIZONS: Array<{ key: string; label: string }> = [
  { key: 'W', label: '1 week' },
  { key: 'M', label: '1 month' },
  { key: 'Q', label: '1 quarter' },
]

export default function SectorLeadersPanel() {
  const enabled = sectorLeadersEnabled()
  const [horizon, setHorizon] = useState('M')
  const [selected, setSelected] = useState<string | null>(null)
  const [strip, setStrip] = useState<SLStripRow[]>([])
  const [sector, setSector] = useState<SLSector | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!enabled) return
    let dead = false
    setLoading(true)
    const qs = new URLSearchParams({ horizon })
    if (selected) qs.set('sector', selected)
    fetch(`/api/v2/defense/sector-leaders?${qs}`)
      .then(r => r.json())
      .then((j) => {
        if (dead) return
        const d = j?.data ?? j
        if (!d?.ok) { setErr('endpoint returned an error'); return }
        setErr(null)
        setStrip(d.sectors || [])
        setSector(d.sector || null)
        if (!selected && d.sectors?.length) setSelected(d.sectors[0].key)
      })
      .catch(() => { if (!dead) setErr('could not reach the sector-leaders endpoint') })
      .finally(() => { if (!dead) setLoading(false) })
    return () => { dead = true }
  }, [enabled, horizon, selected])

  if (!enabled) return null

  const btn = (active: boolean) => ({
    border: `1px solid ${active ? BB.amber : BB.border}`,
    background: active ? BB.amberDim : 'transparent',
    color: active ? BB.amber : BB.text2,
    borderRadius: 6, padding: '4px 10px', fontSize: DASH.data,
    cursor: 'pointer', font: 'inherit' as const,
  })

  return (
    <section style={{ marginTop: 18 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: DASH.panel, color: BB.text0 }}>Sector Leaders</h2>
        <span style={{ fontSize: DASH.data, color: BB.text3 }}>
          sector → confirming industry → names · behind SECTOR_LEADERS_V1, default on — set it to 'off' to hide
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          {HORIZONS.map(h => (
            <button key={h.key} type="button" style={btn(horizon === h.key)} onClick={() => setHorizon(h.key)}>
              {h.label}
            </button>
          ))}
        </div>
      </div>

      {/* Rank beside weight for the whole board — the inversion is legible with
          no sizing policy at all. */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
        {strip.map(s => (
          <button
            key={s.key}
            type="button"
            onClick={() => setSelected(s.key)}
            style={{
              border: `1px solid ${selected === s.key ? BB.amber : BB.border}`,
              background: selected === s.key ? BB.amberDim : BB.bgPanel,
              color: BB.text2, borderRadius: 6, padding: '5px 9px',
              fontSize: DASH.data, cursor: 'pointer', font: 'inherit', textAlign: 'left',
            }}
            title={`${s.name} · ${s.state || 'unknown'} · as of ${s.as_of || 'unknown'}`}
          >
            <span style={{ color: BB.text3 }}>#{s.rank ?? '?'}</span>{' '}
            <span style={{ color: BB.text1 }}>{s.etf}</span>{' '}
            <span style={{ ...numStyle, color: BB.text3 }}>
              {s.book_weight_pct == null
                ? <em style={{ color: BB.text3 }}>unknown</em>
                : `${s.book_weight_pct}%`}
            </span>
          </button>
        ))}
      </div>

      {err && (
        <div style={{ padding: '10px 14px', border: `1px solid ${BB.border}`, borderRadius: 8,
                      background: BB.redDim, color: BB.red, fontSize: DASH.data }}>{err}</div>
      )}
      {!err && loading && !sector && (
        <div style={{ padding: '10px 14px', color: BB.text3, fontSize: DASH.data }}>loading…</div>
      )}
      {!err && sector && <SectorLeadersCard sector={sector} />}
    </section>
  )
}
