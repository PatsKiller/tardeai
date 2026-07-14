import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { useTerminalUi } from '../lib/terminalUi'
import { hubPanel } from '../lib/terminalHubChrome'

const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const PURPLE = '#a855f7'

type DeployTarget = {
  symbol: string
  score: number
  sleeve?: string
  rationale?: string
  review_amount_range?: { low?: number; high?: number }
  evidence?: Record<string, unknown>
  market_context?: Record<string, unknown>
}

type DeployEvent = {
  id: number
  symbol: string
  account: string
  sold_at: string
  proceeds_usd?: number
  proxy_symbol?: string
  proxy_sleeve?: string
  status: string
  redeploy_plan?: DeployTarget[]
  lookthrough_delta?: { theme?: string; delta_pct?: number; note?: string }[]
  metadata?: {
    market_context?: {
      geopolitical?: { posture?: string; catalyst_count?: number; active_themes?: string[] }
      regime?: { label?: string }
      regime_posture?: string
    }
    sleeve_gaps?: { theme?: string; gap_pct?: number; gap_usd?: number }[]
    methodology?: string
  }
}

const fmtDate = (s?: string) => {
  if (!s) return '—'
  const d = new Date(`${String(s).slice(0, 10)}T12:00:00`)
  return isNaN(+d) ? String(s).slice(0, 10) : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

const daysSince = (s?: string) => {
  if (!s) return null
  const sold = new Date(`${String(s).slice(0, 10)}T12:00:00`)
  if (isNaN(+sold)) return null
  return Math.round((Date.now() - sold.getTime()) / 864e5)
}

const postureColor = (p?: string) => p === 'elevated' ? AMBER : p === 'moderate' ? BLUE : 'var(--text3)'

export default function RedeployPanel() {
  const [terminalUi] = useTerminalUi()
  const panel = terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
  const { data, loading, error, refetch } = useApi<any>('/api/v2/deploy/events?status=open&days=365', 60_000)
  const [busy, setBusy] = useState<'detect' | 'recompute' | null>(null)
  const [msg, setMsg] = useState('')
  const [dismissBusy, setDismissBusy] = useState<number | null>(null)

  const events: DeployEvent[] = data?.events ?? []
  const recent = useMemo(() => events.filter(e => (daysSince(e.sold_at) ?? 999) < 14), [events])
  const market = data?.market_context ?? events[0]?.metadata?.market_context

  async function run(action: 'detect' | 'recompute') {
    setBusy(action)
    setMsg('')
    try {
      const path = action === 'detect' ? '/api/v2/deploy/detect' : '/api/v2/deploy/recompute'
      const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const j = await r.json()
      setMsg(j?.ok ? `${action} complete ✓` : `error: ${j?.error || 'failed'}`)
      refetch?.()
    } catch {
      setMsg('request failed')
    }
    setBusy(null)
  }

  async function dismiss(id: number) {
    setDismissBusy(id)
    try {
      const r = await fetch('/api/v2/deploy/dismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, reason: 'operator_dismissed' }),
      })
      const j = await r.json()
      setMsg(j?.ok ? `event #${id} dismissed` : `dismiss failed: ${j?.error || 'error'}`)
      refetch?.()
    } catch {
      setMsg('dismiss request failed')
    }
    setDismissBusy(null)
  }

  async function proposeTarget(symbol: string, sleeve: string, rationale: string) {
    try {
      const r = await fetch('/api/v2/rotation/propose-etf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, direction: 'long', instrument_type: 'etf', sleeve, rationale }),
      })
      const j = await r.json()
      setMsg(j?.ok ? `${symbol} proposed for review ✓` : `propose failed: ${j?.error || 'error'}`)
    } catch {
      setMsg('propose request failed')
    }
  }

  if (loading && !data) {
    return <div style={{ ...panel, color: 'var(--text3)', fontSize: 12 }}>Loading redeploy events…</div>
  }
  if (error && !data) {
    return <div style={{ ...panel, color: AMBER, fontSize: 12 }}>Redeploy API unavailable: {error}</div>
  }

  const geo = market?.geopolitical

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ ...panel, borderLeft: `4px solid ${GREEN}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>
              Post-sale Redeploy
              <span style={{ fontSize: 9, color: AMBER, fontWeight: 600, marginLeft: 8 }}>advisory only · no broker action</span>
            </div>
            <div style={{ fontSize: 10.5, color: 'var(--text3)', marginTop: 4, lineHeight: 1.45 }}>
              Detects broker sells, scores redeploy targets from sleeve gaps, Hermes, CIO view, sentiment, regime, and geopolitical posture.
              {recent.length > 0 && <span style={{ color: GREEN }}> {recent.length} sale{recent.length === 1 ? '' : 's'} in the last 14 days.</span>}
            </div>
          </div>
          <button disabled={!!busy} onClick={() => void run('detect')} style={btnStyle(busy === 'detect')}>
            {busy === 'detect' ? '⟳ Detecting…' : '⟳ Detect sells'}
          </button>
          <button disabled={!!busy} onClick={() => void run('recompute')} style={btnStyle(busy === 'recompute')}>
            {busy === 'recompute' ? '⟳ Recomputing…' : '⟳ Recompute plans'}
          </button>
        </div>
        {msg && <div style={{ fontSize: 10, color: /error|failed/.test(msg) ? '#ef4444' : GREEN }}>{msg}</div>}
        {(geo || market?.regime) && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
            {market?.regime_posture && (
              <Chip label={`Regime ${market.regime_posture}`} color={market.regime_posture === 'risk_off' ? '#ef4444' : GREEN} />
            )}
            {geo?.posture && geo.posture !== 'neutral' && (
              <Chip label={`Geopolitical ${geo.posture}`} color={postureColor(geo.posture)} sub={geo.catalyst_count ? `${geo.catalyst_count} catalysts` : undefined} />
            )}
            {(geo?.active_themes ?? []).slice(0, 2).map((theme: string) => (
              <Chip key={theme} label={theme} color={PURPLE} />
            ))}
          </div>
        )}
        {data?.methodology && (
          <div style={{ fontSize: 9, color: 'var(--text4)', marginTop: 8 }}>{data.methodology}</div>
        )}
      </div>

      {events.length === 0 ? (
        <div style={{ ...panel, color: 'var(--text3)', fontSize: 12, textAlign: 'center', padding: 28 }}>
          No open redeploy events. Run broker sync, then <b>Detect sells</b>, or check dismissed historical backfill (&gt;90d auto-dismissed).
        </div>
      ) : events.map(ev => (
        <div key={ev.id} style={{ ...panel, borderTop: `2px solid ${(daysSince(ev.sold_at) ?? 999) < 14 ? GREEN : 'var(--border)'}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)' }}>
                Sold {ev.symbol}
                <span style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 500, marginLeft: 8 }}>
                  {fmtDate(ev.sold_at)}{(daysSince(ev.sold_at) ?? 0) < 14 ? ' · recent' : ''}
                </span>
              </div>
              <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 3 }}>
                {ev.account?.replace(/_/g, ' ')} · proceeds {fmt$(ev.proceeds_usd ?? 0, 0)}
                {ev.proxy_symbol && <span> · proxy {ev.proxy_symbol} ({ev.proxy_sleeve || 'sleeve'})</span>}
              </div>
            </div>
            <button
              disabled={dismissBusy === ev.id}
              onClick={() => void dismiss(ev.id)}
              style={{ ...btnStyle(false), color: 'var(--text3)', borderColor: 'var(--border)' }}
            >
              {dismissBusy === ev.id ? '…' : 'Dismiss'}
            </button>
          </div>

          {(ev.lookthrough_delta ?? []).length > 0 && (
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>
              Look-through impact: {(ev.lookthrough_delta ?? []).map(d => `${d.theme} ${d.delta_pct}%`).join(' · ')}
            </div>
          )}

          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Redeploy targets</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(ev.redeploy_plan ?? []).length === 0 ? (
              <div style={{ fontSize: 10, color: 'var(--text3)' }}>No targets scored — run Recompute plans.</div>
            ) : (ev.redeploy_plan ?? []).map((t, i) => {
              const range = t.review_amount_range
              const evd = t.evidence ?? {}
              return (
                <div key={`${ev.id}-${t.symbol}`} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 800, fontSize: 13, color: i === 0 ? GREEN : 'var(--text0)' }}>#{i + 1} {t.symbol}</span>
                    <span style={{ fontSize: 11, fontWeight: 700, color: BLUE }}>score {t.score}</span>
                    {t.sleeve && <span style={{ fontSize: 9.5, color: 'var(--text3)' }}>{t.sleeve}</span>}
                    {range?.low != null && range?.high != null && (
                      <span style={{ fontSize: 9.5, color: PURPLE }}>review {fmt$(range.low, 0)}–{fmt$(range.high, 0)}</span>
                    )}
                    <span style={{ flex: 1 }} />
                    <button
                      onClick={() => void proposeTarget(t.symbol, t.sleeve || 'Redeploy', t.rationale || `Redeploy after ${ev.symbol} sale`)}
                      style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 6, border: '1px solid #22c55e66', background: 'rgba(34,197,94,.12)', color: '#86efac', cursor: 'pointer' }}
                    >
                      + propose
                    </button>
                  </div>
                  {t.rationale && <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 6, lineHeight: 1.45 }}>{t.rationale}</div>}
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6 }}>
                    {evd.geopolitical_alignment != null ? <Chip label={String(evd.geopolitical_alignment)} color={AMBER} /> : null}
                    {evd.regime_alignment != null ? <Chip label={String(evd.regime_alignment)} color={BLUE} /> : null}
                    {evd.sleeve_gap_pct != null ? <Chip label={`gap ${evd.sleeve_gap_pct}%`} color={GREEN} /> : null}
                    {evd.hermes_rank != null ? <Chip label={`Hermes #${evd.hermes_rank}`} color={PURPLE} /> : null}
                    {evd.cio_view != null ? <Chip label={`CIO ${String(evd.cio_view)}`} color={BLUE} /> : null}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

function btnStyle(active: boolean): React.CSSProperties {
  return {
    fontSize: 10, fontWeight: 700, padding: '5px 12px', borderRadius: 6, cursor: active ? 'default' : 'pointer',
    border: '1px solid var(--border)', background: active ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
    color: active ? BLUE : 'var(--text2)', whiteSpace: 'nowrap',
  }
}

function Chip({ label, color, sub }: { label: string; color: string; sub?: string }) {
  return (
    <span style={{ fontSize: 8.5, fontWeight: 800, padding: '2px 7px', borderRadius: 4, background: `${color}1a`, color, border: `1px solid ${color}44` }}>
      {label}{sub ? ` · ${sub}` : ''}
    </span>
  )
}