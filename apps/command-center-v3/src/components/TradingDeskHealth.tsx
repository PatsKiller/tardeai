/**
 * Trading desk health strip — WP-T2 enterprise packaging.
 * Paper pending and broker queue are always separate labels (never mixed).
 * Colors: CSS variables only (design-token guard).
 */
import { useEffect, useState, type CSSProperties } from 'react'

export interface TradingDeskHealthProps {
  openCount: number
  paperPending: number | null
  brokerQueue: number | null
  readinessLevel?: string | null
  readinessPct?: number | null
  liveVia2faAllowed?: boolean | null
  alpacaStatus?: string | null
  pureSchwabTabs?: boolean
  onRefresh?: () => void
  refreshing?: boolean
}

interface BuildMeta {
  ui_version?: string
  source_commit?: string
  built_at?: string
  release_notes?: string
}

export default function TradingDeskHealth(props: TradingDeskHealthProps) {
  const {
    openCount, paperPending, brokerQueue, readinessLevel, readinessPct,
    liveVia2faAllowed, alpacaStatus, pureSchwabTabs, onRefresh, refreshing,
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

  const sha = meta?.source_commit ? meta.source_commit.slice(0, 12) : null
  const uiVer = meta?.ui_version || (metaErr ? 'build unknown' : '…')
  const liveLabel = liveVia2faAllowed === true
    ? '2FA LIVE ON'
    : liveVia2faAllowed === false
      ? 'AUTO LIVE BLOCKED'
      : '2FA state —'
  const liveTone = liveVia2faAllowed === true ? 'var(--text1)' : 'var(--text1)'

  const hardReload = () => {
    try { sessionStorage.removeItem('cc_v3_build') } catch { /* */ }
    const u = new URL(window.location.href)
    u.searchParams.set('_cc_reload', String(Date.now()))
    window.location.replace(u.pathname + u.search + u.hash)
  }

  const chip = (extra?: CSSProperties): CSSProperties => ({
    fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 4, whiteSpace: 'nowrap',
    color: 'var(--text1)', background: 'var(--bg2)', border: '1px solid var(--border)',
    ...extra,
  })

  const fmt = (n: number | null) => (n == null ? '—' : String(n))
  const ready = readinessLevel ? readinessLevel.replace(/_/g, ' ') : '—'

  return (
    <div
      data-testid="trading-desk-health"
      style={{
        display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
        marginBottom: 12, padding: '8px 12px',
        background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8,
      }}
    >
      <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--text2)', letterSpacing: 0.3 }}>DESK</span>
      <span
        title="Automated / open-trade intelligence count (not holdings lots)."
        style={chip()}
        data-testid="desk-health-open"
      >
        {openCount} open
      </span>
      {!pureSchwabTabs && (
        <>
          <span
            title="Paper validation pipeline PENDING + APPROVED_FOR_PAPER_TEST. Not the Path B broker queue."
            style={chip()}
            data-testid="desk-health-paper"
          >
            paper pending {fmt(paperPending)}
          </span>
          <span
            title="Path B broker operator queue (active entries). Never mixed with paper pending."
            style={chip()}
            data-testid="desk-health-broker-queue"
          >
            broker queue {fmt(brokerQueue)}
          </span>
        </>
      )}
      {pureSchwabTabs && (
        <span title="Schwab program surface — execution only via 2FA pilot paths." style={chip()}>
          Schwab program · READ-ONLY default
        </span>
      )}
      <span
        title="Paper-trade validation readiness tier (sample maturity). Caps are advisory until gates pass."
        style={chip()}
        data-testid="desk-health-readiness"
      >
        readiness {ready}
        {readinessPct != null ? ` · ${Math.round(readinessPct)}%` : ''}
      </span>
      <span
        title={liveVia2faAllowed
          ? 'Operator live via 2FA is allowed. Each order still requires approval.'
          : 'Unattended auto-live is blocked. Live capital only via per-order 2FA.'}
        style={{ ...chip(), color: liveTone }}
        data-testid="desk-health-2fa"
      >
        {liveLabel}
      </span>
      {alpacaStatus && (
        <span title="Automated account (Alpaca) status" style={chip({ color: 'var(--text3)' })}>
          auto acct {alpacaStatus}
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
        style={chip({ color: 'var(--text3)' })}
      >
        {sha ? `${uiVer} · ${sha}` : uiVer}
      </span>
      {onRefresh && (
        <button
          type="button"
          data-testid="desk-health-refresh"
          onClick={onRefresh}
          style={{
            fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 4, cursor: 'pointer',
            border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
          }}
        >
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      )}
      <button
        type="button"
        data-testid="desk-health-reload-ui"
        onClick={hardReload}
        title="Hard-reload the SPA after deploy."
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
