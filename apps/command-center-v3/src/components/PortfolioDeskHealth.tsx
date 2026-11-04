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
  onExportCsv?: () => void
  onOpenStopAudit?: () => void
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
    onExportCsv, onOpenStopAudit,
  } = props
  const [meta, setMeta] = useState<BuildMeta | null>(null)
  const [metaErr, setMetaErr] = useState(false)
  const [showBuild, setShowBuild] = useState(false)

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
  // "3.14+mw1ddvr8" → "3.14": the per-build stamp is a cache-buster, not an operator fact.
  const baseVersion = meta?.ui_version ? String(meta.ui_version).split('+')[0] : null

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
        // FQ-050: the stamp used to be cut at 42 characters, so a phone read "Prices 19:30 ET · Finviz
        // after-hours · tec…" with no way to see the rest. It now wraps in full; the raw source keys
        // are operator words (lib/pricingStamp.priceSourceLabel) and the whole line is the title.
        <span
          data-testid="desk-health-price-stamp"
          title={priceStamp}
          style={{ ...chip(MUTED), maxWidth: '100%', whiteSpace: 'normal', overflowWrap: 'anywhere', lineHeight: 1.35 }}
        >
          {priceStamp}
        </span>
      )}
      <span style={{ flex: 1, minWidth: 8 }} />
      <button
        type="button"
        data-testid="desk-health-build"
        aria-expanded={showBuild}
        onClick={() => setShowBuild(v => !v)}
        title={[
          meta?.ui_version && `UI ${meta.ui_version}`,
          sha && `source_commit ${meta?.source_commit}`,
          meta?.built_at && `built ${meta.built_at}`,
          meta?.release_notes,
          'Click to show the build identity. Reload UI if it does not match the expected deploy.',
        ].filter(Boolean).join('\n')}
        style={{ ...chip(PURPLE), color: PURPLE, cursor: 'pointer' }}
      >
        {/* FQ-050: the face was "3.14+mw1ddvr8 · 1f1ba5832a06" — a version stamp plus a commit hash.
            The face is now the release version; the hashes are one tap away. */}
        {baseVersion ? `Build ${baseVersion}` : uiVer}
      </button>
      {showBuild && (
        <div
          data-testid="desk-health-build-details"
          style={{ flexBasis: '100%', fontSize: 10, color: MUTED, fontFamily: 'ui-monospace, monospace', lineHeight: 1.5, overflowWrap: 'anywhere' }}
        >
          <div>UI version: {meta?.ui_version || 'unavailable'}</div>
          <div>Source commit: {sha ? `${meta?.source_commit}` : 'unavailable'}</div>
          {meta?.built_at && <div>Built: {meta.built_at}</div>}
          {metaErr && <div>Build identity could not be read.</div>}
        </div>
      )}
      {onExportCsv && (
        <button
          type="button"
          data-testid="desk-health-export-csv"
          onClick={onExportCsv}
          title="Download filtered holdings as CSV (client-side; no broker write)."
          style={{
            fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 4, cursor: 'pointer',
            border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
          }}
        >
          Export CSV
        </button>
      )}
      {onOpenStopAudit && (
        <button
          type="button"
          data-testid="desk-health-stop-audit"
          onClick={onOpenStopAudit}
          title="Open Stop Management desk (audit / re-entry watch surfaces live there)."
          style={{
            fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 4, cursor: 'pointer',
            border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
          }}
        >
          Stop audit
        </button>
      )}
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
