/**
 * Portfolio desk health strip — enterprise provenance + stop-truth SLA at a glance.
 * Colors: CSS variables only (design-token guard).
 */
import { useEffect, useState, type CSSProperties } from 'react'

export interface PortfolioDeskHealthProps {
  holdingsCount: number
  viewTotalLabel: string
  brokerStopReadOk: string[]
  unverifiedAccounts: string[]
  liveStopsDegraded: boolean
  brokerStopsFetchedAt: string | null
  placementCount: number
  verificationCount: number
  priceStamp?: string | null
}

interface BuildMeta {
  ui_version?: string
  source_commit?: string
  built_at?: string
  release_notes?: string
}

const BLUE = 'var(--text1)'
const GREEN = 'var(--text1)'
const AMBER = 'var(--text1)'
const MUTED = 'var(--text3)'
const PURPLE = 'var(--text1)'

export default function PortfolioDeskHealth(props: PortfolioDeskHealthProps) {
  const {
    holdingsCount, viewTotalLabel, brokerStopReadOk, unverifiedAccounts,
    liveStopsDegraded, brokerStopsFetchedAt, placementCount, verificationCount, priceStamp,
  } = props
  const [meta, setMeta] = useState<BuildMeta | null>(null)
  const [metaErr, setMetaErr] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetch('/v3/build-meta.json', { cache: 'no-store' })
      .then(r => r.json())
      .then((j: BuildMeta) => { if (!cancelled) setMeta(j) })
      .catch(() => { if (!cancelled) setMetaErr(true) })
    return () => { cancelled = true }
  }, [])

  const readOkN = brokerStopReadOk?.length ?? 0
  const unverN = unverifiedAccounts?.length ?? 0
  const stopsTone = liveStopsDegraded || unverN > 0 ? AMBER : readOkN > 0 ? GREEN : MUTED
  const stopsLabel = liveStopsDegraded
    ? 'Broker stops: DEGRADED / UNVERIFIABLE'
    : readOkN > 0
      ? `Broker stops: OK ${readOkN} acct${readOkN === 1 ? '' : 's'}${unverN ? ` · ${unverN} unverified` : ''}`
      : 'Broker stops: not verified yet'
  const fetchLabel = brokerStopsFetchedAt
    ? `fetched ${String(brokerStopsFetchedAt).replace('T', ' ').slice(0, 19)}`
    : 'fetch time unknown'
  const sha = meta?.source_commit ? meta.source_commit.slice(0, 12) : null
  const uiVer = meta?.ui_version || (metaErr ? 'build unknown' : '…')

  const hardReload = () => {
    try {
      sessionStorage.removeItem('cc_v3_build')
    } catch { /* */ }
    const u = new URL(window.location.href)
    u.searchParams.set('_cc_reload', String(Date.now()))
    window.location.replace(u.pathname + u.search + u.hash)
  }

  const chip = (color: string): CSSProperties => ({
    fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 4, whiteSpace: 'nowrap',
    color, background: 'var(--bg2)', border: '1px solid var(--border)', cursor: 'help',
  })

  return (
    <div
      data-testid="portfolio-desk-health"
      style={{
        display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
        marginBottom: 12, padding: '8px 12px',
        background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8,
      }}
    >
      <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--text2)', letterSpacing: 0.3 }}>DESK</span>
      <span title="Filtered book size" style={chip(BLUE)}>
        {holdingsCount} lots · {viewTotalLabel}
      </span>
      <span
        data-testid="desk-health-stops"
        title={`${stopsLabel}. ${fetchLabel}. Unverified accounts never count as permission to place stops.`}
        style={{ ...chip(stopsTone), color: stopsTone }}
      >
        {stopsLabel}
      </span>
      {placementCount > 0 && (
        <span data-testid="desk-health-placement" style={{ ...chip(AMBER), color: AMBER }}>
          {placementCount} need placement
        </span>
      )}
      {verificationCount > 0 && (
        <span data-testid="desk-health-verify" style={{ ...chip(AMBER), color: AMBER }}>
          {verificationCount} verification required
        </span>
      )}
      {priceStamp && (
        <span title={priceStamp} style={{ ...chip(MUTED), maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {priceStamp.slice(0, 42)}{priceStamp.length > 42 ? '…' : ''}
        </span>
      )}
      <span style={{ flex: 1, minWidth: 8 }} />
      <span
        data-testid="desk-health-build"
        title={[
          meta?.ui_version && `UI ${meta.ui_version}`,
          sha && `source_commit ${meta?.source_commit}`,
          meta?.built_at && `built ${meta.built_at}`,
          meta?.release_notes,
          'Click Reload UI if this chip does not match the expected deploy.',
        ].filter(Boolean).join('\n')}
        style={{ ...chip(PURPLE), color: PURPLE }}
      >
        {sha ? `${uiVer} · ${sha}` : uiVer}
      </span>
      <button
        type="button"
        data-testid="desk-health-reload-ui"
        onClick={hardReload}
        title="Hard-reload the SPA (clears build session marker). Use when the UI looks stale after deploy."
        style={{
          fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 4, cursor: 'pointer',
          border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
        }}
      >
        Reload UI
      </button>
    </div>
  )
}
