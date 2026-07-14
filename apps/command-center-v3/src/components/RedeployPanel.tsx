import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BB } from '../lib/holdingsTerminalTokens'
import { hubPanel, hubStrip, hubFilterSelect } from '../lib/terminalHubChrome'

type DeployTarget = {
  symbol: string
  score: number
  sleeve?: string
  rationale?: string
  review_amount_range?: { low?: number; high?: number }
  evidence?: Record<string, unknown>
}

type DeployEvent = {
  id: number
  symbol: string
  account: string
  sold_at: string
  proceeds_usd?: number
  proxy_symbol?: string
  proxy_sleeve?: string
  tier?: string
  redeploy_plan?: DeployTarget[]
  lookthrough_delta?: { theme?: string; delta_pct?: number }[]
  metadata?: {
    sale_context?: { tier?: string; reduced_themes?: string[]; proceeds_usd?: number }
    advisory_note?: string
    sleeve_gaps?: { theme?: string; gap_pct?: number; gap_usd?: number }[]
    market_context?: {
      geopolitical?: { posture?: string; catalyst_count?: number }
      regime_posture?: string
    }
  }
}

const TIER_COLOR: Record<string, string> = { major: BB.amber, moderate: BB.blue, minor: BB.text3 }
const GRID = '72px 56px 108px 92px 1fr 88px 72px'

const fmtDate = (s?: string) => {
  if (!s) return '—'
  return String(s).slice(5).replace('-', '/') || String(s).slice(0, 10)
}

export default function RedeployPanel() {
  const { data, loading, error, refetch } = useApi<any>('/api/v2/deploy/events?status=open&days=14&material_only=true', 60_000)
  const [busy, setBusy] = useState<'detect' | 'recompute' | null>(null)
  const [msg, setMsg] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [showAll, setShowAll] = useState(false)

  const events: DeployEvent[] = data?.events ?? []
  const selected = useMemo(
    () => events.find(e => e.id === selectedId) ?? events[0] ?? null,
    [events, selectedId],
  )

  const { data: allData } = useApi<any>(
    '/api/v2/deploy/events?status=open&days=14&material_only=false',
    60_000,
    { enabled: showAll },
  )
  const displayEvents: DeployEvent[] = showAll ? (allData?.events ?? []) : events

  async function run(action: 'detect' | 'recompute') {
    setBusy(action)
    setMsg('')
    try {
      const path = action === 'detect' ? '/api/v2/deploy/detect' : '/api/v2/deploy/recompute'
      const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const j = await r.json()
      setMsg(j?.ok ? `${action} ✓` : `ERR ${j?.error || 'failed'}`)
      refetch?.()
    } catch {
      setMsg('ERR request failed')
    }
    setBusy(null)
  }

  async function dismiss(id: number) {
    try {
      const r = await fetch('/api/v2/deploy/dismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, reason: 'operator_dismissed' }),
      })
      const j = await r.json()
      setMsg(j?.ok ? `dismissed #${id}` : `ERR ${j?.error}`)
      refetch?.()
    } catch {
      setMsg('ERR dismiss failed')
    }
  }

  async function proposeTarget(symbol: string, sleeve: string, rationale: string) {
    const r = await fetch('/api/v2/rotation/propose-etf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, direction: 'long', instrument_type: 'etf', sleeve, rationale }),
    })
    const j = await r.json()
    setMsg(j?.ok ? `${symbol} → review queue` : `ERR ${j?.error}`)
  }

  const gaps = data?.portfolio_gaps ?? selected?.metadata?.sleeve_gaps ?? []
  const geo = data?.market_context?.geopolitical ?? selected?.metadata?.market_context?.geopolitical
  const regime = data?.market_context?.regime_posture ?? selected?.metadata?.market_context?.regime_posture

  if (loading && !data) {
    return <div style={panelStyle()}>LOADING REDEPLOY QUEUE…</div>
  }
  if (error && !data) {
    return <div style={{ ...panelStyle(), color: BB.red }}>API ERR — {error}</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontFamily: BB.mono, fontSize: BB.fontSm }}>
      {/* Context strip */}
      <div style={hubStrip(true)}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center' }}>
          <span style={{ color: BB.amber, fontWeight: 800, letterSpacing: '.08em' }}>REDEPLOY DESK</span>
          <span style={{ color: BB.text3 }}>ADVISORY · NO BROKER</span>
          <span style={{ color: BB.text2 }}>
            {displayEvents.length} event{displayEvents.length === 1 ? '' : 's'}
            {!showAll && (allData?.count != null || data?.minor_hidden) ? ' · minors hidden' : ''}
          </span>
          {data?.material_proceeds_usd > 0 && (
            <span style={{ color: BB.green }}>material proceeds {fmt$(data.material_proceeds_usd, 0)}</span>
          )}
          {regime && <span style={{ color: BB.text2 }}>REGIME {String(regime).toUpperCase()}</span>}
          {geo?.posture && geo.posture !== 'neutral' && (
            <span style={{ color: BB.amberAlt }}>GEO {String(geo.posture).toUpperCase()}</span>
          )}
          <span style={{ flex: 1 }} />
          <button disabled={!!busy} onClick={() => void run('detect')} style={btn(busy === 'detect')}>DETECT</button>
          <button disabled={!!busy} onClick={() => void run('recompute')} style={btn(busy === 'recompute')}>RECOMPUTE</button>
          <label style={{ display: 'flex', alignItems: 'center', gap: 5, color: BB.text3, fontSize: BB.fontXs, cursor: 'pointer' }}>
            <input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} />
            SHOW MINORS
          </label>
        </div>
        {msg && <div style={{ marginTop: 4, fontSize: BB.fontXs, color: /ERR/.test(msg) ? BB.red : BB.green }}>{msg}</div>}
      </div>

      {/* Portfolio gaps — shown once, not per event */}
      {gaps.length > 0 && (
        <div style={panelStyle()}>
          <div style={{ fontSize: BB.fontXs, color: BB.text3, marginBottom: 4, letterSpacing: '.06em' }}>PORTFOLIO UNDERWEIGHT (context — not auto-applied to every sale)</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {gaps.slice(0, 5).map((g: { theme?: string; gap_pct?: number; gap_usd?: number }) => (
              <span key={g.theme} style={{ color: BB.text1, fontSize: BB.fontXs }}>
                {g.theme} <b style={{ color: BB.amber }}>-{g.gap_pct}%</b>
                <span style={{ color: BB.text3 }}> ≈{fmt$(g.gap_usd ?? 0, 0)}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Event queue table */}
      <div style={{ ...panelStyle(), padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: GRID, gap: 8, padding: '6px 10px', borderBottom: `1px solid ${BB.border}`, fontSize: BB.fontXs, color: BB.text3, letterSpacing: '.05em' }}>
          <span>DATE</span><span>SOLD</span><span>ACCOUNT</span><span>PROCEEDS</span><span>REDUCED SLEEVE</span><span>TOP PICK</span><span />
        </div>
        {displayEvents.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: BB.text3, fontSize: BB.fontXs }}>
            No material redeploy events in 14d — run DETECT after broker sync
          </div>
        ) : displayEvents.map(ev => {
          const tier = ev.tier ?? ev.metadata?.sale_context?.tier ?? 'moderate'
          const reduced = ev.metadata?.sale_context?.reduced_themes
            ?? (ev.lookthrough_delta ?? []).map(d => d.theme).filter(Boolean)
          const top = ev.redeploy_plan?.[0]
          const active = selected?.id === ev.id
          return (
            <div
              key={ev.id}
              onClick={() => setSelectedId(ev.id)}
              style={{
                display: 'grid', gridTemplateColumns: GRID, gap: 8, padding: '7px 10px', alignItems: 'center',
                borderBottom: `1px solid ${BB.borderSubtle}`, cursor: 'pointer',
                background: active ? BB.bgRowFocus : 'transparent',
              }}
            >
              <span style={{ color: BB.text3, fontSize: BB.fontXs }}>{fmtDate(ev.sold_at)}</span>
              <span style={{ color: TIER_COLOR[tier] ?? BB.text0, fontWeight: 800 }}>{ev.symbol}</span>
              <span style={{ color: BB.text2, fontSize: BB.fontXs, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {(ev.account ?? '').replace(/_/g, ' ').replace('schwab ', 'S·').replace('fidelity ', 'F·')}
              </span>
              <span style={{ color: BB.text0, fontWeight: 700 }}>{fmt$(Number(ev.proceeds_usd ?? 0), 0)}</span>
              <span style={{ color: BB.text2, fontSize: BB.fontXs }} title={reduced.join(', ')}>
                {reduced[0] ?? '—'}{reduced.length > 1 ? ` +${reduced.length - 1}` : ''}
              </span>
              <span style={{ color: top ? BB.green : BB.text3, fontWeight: 700 }}>
                {top ? `${top.symbol} ${top.score}` : tier === 'minor' ? 'CASH' : '—'}
              </span>
              <button
                onClick={e => { e.stopPropagation(); void dismiss(ev.id) }}
                style={{ ...btn(false), fontSize: 8, padding: '2px 6px', color: BB.text3 }}
              >DSM</button>
            </div>
          )
        })}
      </div>

      {/* Detail pane — single selected event */}
      {selected && (
        <div style={{ ...panelStyle(), borderLeft: `3px solid ${TIER_COLOR[selected.tier ?? 'moderate'] ?? BB.amber}` }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 10, alignItems: 'baseline' }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: BB.text0 }}>
              {selected.symbol}
            </span>
            <span style={{ color: BB.text3, fontSize: BB.fontXs }}>
              {fmtDate(selected.sold_at)} · {(selected.account ?? '').replace(/_/g, ' ')} · {fmt$(Number(selected.proceeds_usd ?? 0), 0)}
            </span>
            {selected.proxy_symbol && (
              <span style={{ color: BB.text2, fontSize: BB.fontXs }}>
                freed {selected.metadata?.sale_context?.reduced_themes?.[0] ?? 'exposure'} via proxy {selected.proxy_symbol}
              </span>
            )}
            <span style={{ color: TIER_COLOR[selected.tier ?? 'moderate'], fontSize: BB.fontXs, fontWeight: 800 }}>
              {(selected.tier ?? 'moderate').toUpperCase()}
            </span>
          </div>

          {selected.metadata?.advisory_note && (
            <div style={{ color: BB.text3, fontSize: BB.fontXs, marginBottom: 10, fontStyle: 'italic' }}>
              {selected.metadata.advisory_note}
            </div>
          )}

          {(selected.redeploy_plan ?? []).length === 0 ? (
            <div style={{ color: BB.text3, fontSize: BB.fontXs }}>No redeploy targets — hold cash or dismiss</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: BB.fontXs }}>
              <thead>
                <tr style={{ color: BB.text3, textAlign: 'left', borderBottom: `1px solid ${BB.border}` }}>
                  <th style={{ padding: '4px 6px' }}>SYM</th>
                  <th style={{ padding: '4px 6px' }}>SCORE</th>
                  <th style={{ padding: '4px 6px' }}>SLEEVE</th>
                  <th style={{ padding: '4px 6px' }}>REVIEW $</th>
                  <th style={{ padding: '4px 6px' }}>WHY (this sale)</th>
                  <th style={{ padding: '4px 6px' }} />
                </tr>
              </thead>
              <tbody>
                {(selected.redeploy_plan ?? []).map((t, i) => {
                  const lo = t.review_amount_range?.low
                  const hi = t.review_amount_range?.high
                  const fills = t.evidence?.fills_sale_gap
                  return (
                    <tr key={t.symbol} style={{ borderBottom: `1px solid ${BB.borderSubtle}`, background: i === 0 ? BB.greenDim : 'transparent' }}>
                      <td style={{ padding: '6px', color: i === 0 ? BB.green : BB.text0, fontWeight: 800 }}>{t.symbol}</td>
                      <td style={{ padding: '6px', color: BB.blue }}>{t.score}</td>
                      <td style={{ padding: '6px', color: BB.text2 }}>{t.sleeve}</td>
                      <td style={{ padding: '6px', color: BB.text1 }}>
                        {lo != null && hi != null ? `${fmt$(lo, 0)}–${fmt$(hi, 0)}` : '—'}
                      </td>
                      <td style={{ padding: '6px', color: BB.text2, lineHeight: 1.35, maxWidth: 420 }}>
                        {fills ? <span style={{ color: BB.green, marginRight: 6 }}>▸ REPLACES</span> : null}
                        {t.rationale}
                      </td>
                      <td style={{ padding: '6px' }}>
                        <button
                          onClick={() => void proposeTarget(t.symbol, t.sleeve || 'Redeploy', t.rationale || '')}
                          style={{ ...btn(false), fontSize: 8, color: BB.green }}
                        >PROPOSE</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

function panelStyle(): React.CSSProperties {
  return hubPanel(true)
}

function btn(active: boolean): React.CSSProperties {
  return {
    fontSize: 9,
    fontWeight: 800,
    padding: '3px 10px',
    borderRadius: 2,
    border: `1px solid ${active ? BB.amber : BB.border}`,
    background: active ? BB.amberDim : BB.bgRow,
    color: active ? BB.amber : BB.text2,
    cursor: active ? 'default' : 'pointer',
    letterSpacing: '.06em',
    fontFamily: BB.mono,
  }
}