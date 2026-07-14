import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BB } from '../lib/holdingsTerminalTokens'
import { hubPanel, hubStrip } from '../lib/terminalHubChrome'
import RedeployEventModal, { type RedeployEventDetail } from './RedeployEventModal'

const TIER_COLOR: Record<string, string> = { major: BB.amber, moderate: BB.blue, minor: BB.text3 }
const GRID = '72px 56px 108px 92px 1fr 88px 52px 72px'

const fmtDate = (s?: string) => {
  if (!s) return '—'
  return String(s).slice(5).replace('-', '/') || String(s).slice(0, 10)
}

export default function RedeployPanel() {
  const { data, loading, error, refetch } = useApi<any>('/api/v2/deploy/events?status=open&days=14&material_only=true', 60_000)
  const { data: dismissedData, refetch: refetchDismissed } = useApi<any>('/api/v2/deploy/events?status=dismissed&days=14&material_only=false&limit=20', 60_000)
  const [busy, setBusy] = useState<'detect' | 'recompute' | null>(null)
  const [msg, setMsg] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [modalEvent, setModalEvent] = useState<RedeployEventDetail | null>(null)
  const [showAll, setShowAll] = useState(false)

  const events: RedeployEventDetail[] = data?.events ?? []
  const dismissed: RedeployEventDetail[] = dismissedData?.events ?? []
  const selected = useMemo(
    () => events.find(e => e.id === selectedId) ?? events[0] ?? null,
    [events, selectedId],
  )

  const { data: allData, refetch: refetchAll } = useApi<any>(
    '/api/v2/deploy/events?status=open&days=14&material_only=false',
    60_000,
    { enabled: showAll },
  )
  const displayEvents: RedeployEventDetail[] = showAll ? (allData?.events ?? []) : events

  function refreshAll() {
    refetch?.()
    refetchDismissed?.()
    refetchAll?.()
  }

  async function run(action: 'detect' | 'recompute') {
    setBusy(action)
    setMsg('')
    try {
      const path = action === 'detect' ? '/api/v2/deploy/detect' : '/api/v2/deploy/recompute'
      const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const j = await r.json()
      setMsg(j?.ok ? `${action} ✓` : `ERR ${j?.error || 'failed'}`)
      refreshAll()
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
      setMsg(j?.ok ? `DISMISSED #${id}` : `ERR ${j?.error}`)
      if (modalEvent?.id === id) setModalEvent(null)
      refreshAll()
    } catch {
      setMsg('ERR dismiss failed')
    }
  }

  async function restore(id: number) {
    try {
      const r = await fetch('/api/v2/deploy/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, recompute: true }),
      })
      const j = await r.json()
      setMsg(j?.ok ? `RESTORED ${j.symbol ?? id}` : `ERR ${j?.error}`)
      refreshAll()
    } catch {
      setMsg('ERR restore failed')
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

  function openModal(ev: RedeployEventDetail) {
    setSelectedId(ev.id)
    setModalEvent(ev)
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
      <div style={hubStrip(true)}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center' }}>
          <span style={{ color: BB.amber, fontWeight: 800, letterSpacing: '.08em' }}>REDEPLOY DESK</span>
          <span style={{ color: BB.text3 }}>ADVISORY · NO BROKER</span>
          <span style={{ color: BB.text2 }}>
            {displayEvents.length} open · click row or OPEN to expand
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

      {dismissed.length > 0 && (
        <div style={{ ...panelStyle(), borderLeft: `3px solid ${BB.text3}` }}>
          <div style={{ fontSize: BB.fontXs, color: BB.text3, marginBottom: 6, letterSpacing: '.06em' }}>DISMISSED (restore if accidental)</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {dismissed.slice(0, 8).map(ev => (
              <button
                key={ev.id}
                onClick={() => void restore(ev.id)}
                style={{ ...btn(false), color: BB.amber, fontSize: BB.fontXs }}
                title={`Restore ${ev.symbol} sale — reopens queue`}
              >
                RESTORE {ev.symbol} {fmt$(Number(ev.proceeds_usd ?? 0), 0)}
              </button>
            ))}
          </div>
        </div>
      )}

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

      <div style={{ ...panelStyle(), padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: GRID, gap: 8, padding: '6px 10px', borderBottom: `1px solid ${BB.border}`, fontSize: BB.fontXs, color: BB.text3, letterSpacing: '.05em' }}>
          <span>DATE</span><span>SOLD</span><span>ACCOUNT</span><span>PROCEEDS</span><span>REDUCED SLEEVE</span><span>TOP PICK</span><span>OPEN</span><span>DISMISS</span>
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
              onDoubleClick={() => openModal(ev)}
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
                onClick={e => { e.stopPropagation(); openModal(ev) }}
                style={{ ...btn(false), fontSize: 8, padding: '2px 6px', color: BB.amber }}
              >OPEN</button>
              <button
                onClick={e => { e.stopPropagation(); void dismiss(ev.id) }}
                style={{ ...btn(false), fontSize: 8, padding: '2px 6px', color: BB.text3 }}
              >DISMISS</button>
            </div>
          )
        })}
      </div>

      {selected && !modalEvent && (
        <div style={{ ...panelStyle(), borderLeft: `3px solid ${TIER_COLOR[selected.tier ?? 'moderate'] ?? BB.amber}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{ color: BB.text2, fontSize: BB.fontXs }}>Preview — double-click row or OPEN for full modal</span>
            <button onClick={() => openModal(selected)} style={{ ...btn(false), color: BB.amber, fontSize: 8 }}>EXPAND</button>
          </div>
          <PreviewRow event={selected} onPropose={proposeTarget} />
        </div>
      )}

      {modalEvent && (
        <RedeployEventModal
          event={modalEvent}
          onClose={() => setModalEvent(null)}
          onDismiss={id => void dismiss(id)}
          onPropose={proposeTarget}
        />
      )}
    </div>
  )
}

function PreviewRow({ event, onPropose }: { event: RedeployEventDetail; onPropose: (s: string, sl: string, r: string) => void }) {
  const top = event.redeploy_plan?.[0]
  if (!top) return <div style={{ color: BB.text3, fontSize: BB.fontXs }}>No targets</div>
  return (
    <div style={{ fontSize: BB.fontXs, color: BB.text2 }}>
      <b style={{ color: BB.green }}>{top.symbol}</b> score {top.score} — {top.rationale}
      <button onClick={() => onPropose(top.symbol, top.sleeve || 'Redeploy', top.rationale || '')} style={{ ...btn(false), marginLeft: 10, fontSize: 8, color: BB.green }}>PROPOSE</button>
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