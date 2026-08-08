import { useEffect, useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { hubTitle, hubSubtitle, hubPanel } from '../lib/terminalHubChrome'
import { useTerminalUi } from '../lib/terminalUi'

// ── Types ──────────────────────────────────────────────────────────────────────────────
interface RemediationEvent {
  id?: string
  timestamp?: string
  at?: string
  agent?: string
  layer?: number | string
  component?: string
  action?: string
  severity?: string
  old_state?: string
  new_state?: string
  success?: boolean
  detail?: string
  resolution?: string
  message?: string
  actor?: string
}

interface RemediationData {
  remediations?: RemediationEvent[]
  stats?: {
    total_fixes_24h?: number
    success_rate?: number
    total_events?: number
    by_severity?: Record<string, number>
    by_agent?: Record<string, number>
  }
  status?: string
  captured_at?: string
}

// ── Severity colors ────────────────────────────────────────────────────────────────────
const SEV_PILL: Record<string, { bg: string; fg: string }> = {
  P0: { bg: 'rgba(239,68,68,0.12)', fg: 'var(--red)' },
  critical: { bg: 'rgba(239,68,68,0.12)', fg: 'var(--red)' },
  P1: { bg: 'rgba(249,115,22,0.12)', fg: 'var(--amber)' },
  high: { bg: 'rgba(249,115,22,0.12)', fg: 'var(--amber)' },
  P2: { bg: 'rgba(245,158,11,0.12)', fg: 'var(--amber)' },
  medium: { bg: 'rgba(245,158,11,0.12)', fg: 'var(--amber)' },
  P3: { bg: 'rgba(59,130,246,0.12)', fg: 'var(--accent)' },
  low: { bg: 'rgba(59,130,246,0.12)', fg: 'var(--accent)' },
}

const SUCCESS_ICON = '✓'
const FAIL_ICON = '✗'

// ── Helpers ─────────────────────────────────────────────────────────────────────────────
function fmtWhen(s?: string): string {
  if (!s) return '—'
  try { return new Date(s).toLocaleString() } catch { return s }
}

function fmtElapsed(ts?: string): string {
  if (!ts) return ''
  try {
    const then = new Date(ts).getTime()
    const now = Date.now()
    const diffMin = Math.round((now - then) / 60000)
    if (diffMin < 1) return 'just now'
    if (diffMin < 60) return `${diffMin}m ago`
    const diffH = Math.round(diffMin / 60)
    if (diffH < 24) return `${diffH}h ago`
    const diffD = Math.round(diffH / 24)
    return `${diffD}d ago`
  } catch {
    return ''
  }
}

// ── Component ───────────────────────────────────────────────────────────────────────────
export default function RemediationDashboard() {
  const [terminalUi] = useTerminalUi()
  const { data, loading, error } = useApi<RemediationData>(
    '/api/v2/health/remediation',
    60_000
  )

  const remediations = useMemo(() => data?.remediations || [], [data])
  const stats = useMemo(() => data?.stats || {}, [data])

  // ── Loading / Error ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{ padding: 20, color: 'var(--text3)', fontSize: 11 }}>
        Loading remediation log…
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 20 }}>
        <div style={{ color: 'var(--red)', fontSize: 11 }}>Error: {error}</div>
        <div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 6 }}>
          The remediation API may not be available yet. This dashboard will populate once
          the Health Inspector agent begins reporting via{' '}
          <code style={{ color: 'var(--accent)' }}>/api/v2/health/remediation</code>.
        </div>
      </div>
    )
  }

  // ── Empty state ──────────────────────────────────────────────────────────────────────
  if (remediations.length === 0) {
    return (
      <div
        style={{
          ...hubPanel(terminalUi),
          padding: '32px 24px',
          textAlign: 'center',
          marginTop: 12,
        }}
      >
        <div style={{ fontSize: 32, marginBottom: 12 }}>🟢</div>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--green)' }}>
          No issues detected — all systems healthy
        </div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>
          The remediation log is empty. Events will appear here as the Health Inspector
          agent detects and fixes issues.
        </div>
      </div>
    )
  }

  // ── Summary bar ──────────────────────────────────────────────────────────────────────
  const total24h = stats.total_fixes_24h ?? 0
  const successRate = stats.success_rate ?? 0

  return (
    <div style={{ marginTop: 4 }}>
      {/* Summary stats bar */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
          gap: 8,
          marginBottom: 14,
        }}
      >
        <div
          style={{
            padding: '10px 14px',
            background: 'var(--bg1)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
          }}
        >
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--green)' }}>{total24h}</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', marginTop: 2 }}>
            issues fixed in last 24h
          </div>
        </div>
        <div
          style={{
            padding: '10px 14px',
            background: 'var(--bg1)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
          }}
        >
          <div
            style={{
              fontSize: 20,
              fontWeight: 800,
              color: successRate >= 80 ? 'var(--green)' : successRate >= 50 ? 'var(--amber)' : 'var(--red)',
            }}
          >
            {successRate}%
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', marginTop: 2 }}>
            success rate
          </div>
        </div>
        {Object.entries(stats.by_severity || {}).map(([sev, count]) => (
          <div
            key={sev}
            style={{
              padding: '10px 14px',
              background: 'var(--bg1)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
            }}
          >
            <div
              style={{
                fontSize: 20,
                fontWeight: 800,
                color: (SEV_PILL[sev.toUpperCase()] || SEV_PILL.low).fg,
              }}
            >
              {count}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', marginTop: 2 }}>
              {sev} severity
            </div>
          </div>
        ))}
      </div>

      {/* Column headers */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '140px 110px 1fr 72px 72px 60px',
          gap: 8,
          padding: '4px 10px',
          marginBottom: 4,
          fontSize: 10,
          fontWeight: 700,
          color: 'var(--text2)',
          textTransform: 'uppercase',
          letterSpacing: '.4px',
        }}
      >
        <span>When</span>
        <span>Agent</span>
        <span>Detail</span>
        <span>Severity</span>
        <span>Outcome</span>
        <span style={{ textAlign: 'right' }}>Status</span>
      </div>

      {/* Remediation timeline */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {remediations.map((evt, i) => {
          const sevKey = ((evt.severity || 'P3')).toUpperCase()
          const pill = SEV_PILL[sevKey] || SEV_PILL.low
          const agent = evt.agent || evt.actor || 'health-inspector'
          const layer = evt.layer != null ? `L${evt.layer}` : 'L1'
          const ts = evt.timestamp || evt.at || ''
          const success = evt.success !== false
          const action = evt.action || evt.resolution || 'remediated'

          return (
            <div
              key={evt.id || i}
              style={{
                display: 'grid',
                gridTemplateColumns: '140px 110px 1fr 72px 72px 60px',
                gap: 8,
                padding: '6px 10px',
                background: 'var(--bg1)',
                border: '1px solid var(--border)',
                borderRadius: 3,
                fontSize: 10,
                alignItems: 'center',
                borderLeft: `3px solid ${pill.fg}`,
              }}
            >
              {/* When */}
              <div>
                <div style={{ color: 'var(--text1)', fontWeight: 600, fontSize: 10 }}>
                  {fmtElapsed(ts)}
                </div>
                <div style={{ color: 'var(--text3)', fontSize: 10 }} title={fmtWhen(ts)}>
                  {fmtWhen(ts)}
                </div>
              </div>

              {/* Agent */}
              <div>
                <span style={{ color: 'var(--text1)', fontWeight: 600 }}>{agent}</span>
                <span
                  style={{
                    marginLeft: 4,
                    fontSize: 10,
                    fontWeight: 800,
                    background: 'var(--accent-dim)',
                    color: 'var(--accent)',
                    padding: '1px 5px',
                    borderRadius: 4,
                    textTransform: 'uppercase',
                  }}
                >
                  {layer}
                </span>
              </div>

              {/* Detail */}
              <div>
                <div
                  style={{
                    color: 'var(--text0)',
                    fontWeight: 500,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    maxWidth: 360,
                  }}
                  title={evt.message || evt.detail || evt.component}
                >
                  {evt.message || evt.detail || evt.component || action}
                </div>
                {(evt.old_state || evt.new_state) && (
                  <div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 1 }}>
                    {evt.old_state && (
                      <span style={{ color: 'var(--red)' }} title="Previous state">
                        {evt.old_state}
                      </span>
                    )}
                    {evt.old_state && evt.new_state && (
                      <span style={{ margin: '0 3px', color: 'var(--text3)' }}>→</span>
                    )}
                    {evt.new_state && (
                      <span style={{ color: 'var(--green)' }} title="New state">
                        {evt.new_state}
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Severity pill */}
              <div>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 800,
                    textTransform: 'uppercase',
                    background: pill.bg,
                    color: pill.fg,
                    padding: '1px 7px',
                    borderRadius: 4,
                  }}
                >
                  {sevKey}
                </span>
              </div>

              {/* Outcome */}
              <div style={{ fontSize: 10, color: 'var(--text2)' }}>
                {action}
              </div>

              {/* Success/Fail */}
              <div
                style={{
                  textAlign: 'right',
                  fontSize: 14,
                  fontWeight: 800,
                  color: success ? 'var(--green)' : 'var(--red)',
                }}
                title={success ? 'Success' : 'Failed'}
              >
                {success ? SUCCESS_ICON : FAIL_ICON}
              </div>
            </div>
          )
        })}
      </div>

      {/* Footer with last captured time */}
      {data?.captured_at && (
        <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text3)' }}>
          Last updated: {fmtWhen(data.captured_at)} · Auto-refreshes every 60s
        </div>
      )}
    </div>
  )
}
