/**
 * Alerts Center modal (2026-09-29) — global inbox for Entry / Telegram / Setups.
 * Advisory only: no order / 2FA / broker controls. Fan-in logic lives in alertsCenter.ts.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import {
  filterAlerts,
  fanInAlerts,
  shortcuts,
  type AlertRow,
  type KindFilter,
} from '../lib/alertsCenter'
import { BB, T, TYPE } from '../lib/watchTokens'
import { RADIUS, SHADOW } from '../lib/designTokens'

const FILTERS: Array<{ id: KindFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'entry', label: 'Entry' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'setups', label: 'Setups' },
]

function fmtWhen(s?: string | null) {
  if (!s) return '—'
  try { return new Date(s).toLocaleString() } catch { return String(s) }
}

export default function AlertsCenterModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const searchRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<KindFilter>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const packets = useApi<any>('/api/v2/buy-ready/packets', 60_000, { enabled: open })
  const events = useApi<any>('/api/v2/communications/events?limit=250', 60_000, { enabled: open })
  const tradeAi = useApi<any>('/api/v2/trade-ai/summary', 120_000, { enabled: open })

  useEffect(() => {
    if (!open) return
    const t = window.setTimeout(() => searchRef.current?.focus(), 30)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      if (e.key === '/' && document.activeElement !== searchRef.current) {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => { window.clearTimeout(t); window.removeEventListener('keydown', onKey) }
  }, [open, onClose])

  const loading = open && (packets.loading || events.loading || tradeAi.loading)
  const err = [packets.error, events.error, tradeAi.error].filter(Boolean).map(String)

  const rows = useMemo(() => {
    if (!open) return [] as AlertRow[]
    return fanInAlerts({
      packets: packets.data,
      events: events.data,
      tradeAiSummary: tradeAi.data,
    })
  }, [open, packets.data, events.data, tradeAi.data])

  const visible = useMemo(() => filterAlerts(rows, { query, kind }), [rows, query, kind])
  const selected = visible.find(r => r.id === selectedId) || visible[0] || null

  useEffect(() => {
    if (!selectedId && visible[0]) setSelectedId(visible[0].id)
    if (selectedId && visible.length && !visible.some(r => r.id === selectedId)) {
      setSelectedId(visible[0]?.id ?? null)
    }
  }, [visible, selectedId])

  if (!open) return null

  const go = (href: string) => {
    onClose()
    if (href.startsWith('/v3/')) navigate(href.slice(3) || '/')
    else navigate(href)
  }

  return (
    <div
      data-testid="alerts-center-modal"
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
    >
      <div
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-label="Alerts Center"
        style={{
          background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: RADIUS.lg,
          width: 'min(960px, 96vw)', height: 'min(640px, 92vh)', display: 'flex', flexDirection: 'column',
          boxShadow: SHADOW[3],
        }}
      >
        <header style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontWeight: 800, fontSize: 13, letterSpacing: '.4px' }}>⚑ ALERTS CENTER</div>
          <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>Entry · Telegram · Setups · advisory only</div>
          <input
            ref={searchRef}
            data-testid="alerts-center-search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search symbols or titles  (/ focuses · Esc closes)"
            style={{
              marginLeft: 'auto', width: 280, maxWidth: '40vw', background: 'var(--bg2)', color: 'var(--text0)',
              border: '1px solid var(--border)', borderRadius: RADIUS.sm, padding: '6px 10px', fontSize: 12,
            }}
          />
          <button type="button" onClick={onClose} style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text2)', borderRadius: RADIUS.sm, padding: '4px 10px', cursor: 'pointer', fontSize: 11 }}>Close</button>
        </header>

        <div style={{ display: 'flex', gap: 6, padding: '8px 14px', borderBottom: '1px solid var(--border)' }}>
          {FILTERS.map(f => (
            <button
              key={f.id}
              type="button"
              data-testid={`alerts-filter-${f.id}`}
              onClick={() => setKind(f.id)}
              style={{
                background: kind === f.id ? 'var(--bg3, var(--bg2))' : 'transparent',
                color: kind === f.id ? 'var(--text0)' : 'var(--text3)',
                border: `1px solid ${kind === f.id ? 'var(--text3)' : 'var(--border)'}`,
                borderRadius: 999, padding: '3px 10px', fontSize: 11, cursor: 'pointer', fontWeight: 700,
              }}
            >{f.label}</button>
          ))}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            {shortcuts().map(s => (
              <button key={s.href} type="button" onClick={() => go(s.href)}
                style={{ background: 'transparent', border: 0, color: BB.amber, fontSize: TYPE.xs, cursor: 'pointer', textDecoration: 'underline' }}>
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: 'minmax(240px, 1.1fr) minmax(280px, 1.2fr)' }}>
          <div style={{ overflowY: 'auto', borderRight: '1px solid var(--border)' }}>
            {loading && <div style={{ padding: 14, fontSize: 12, color: 'var(--text3)' }}>Loading alerts…</div>}
            {!loading && err.length > 0 && (
              <div role="alert" style={{ padding: 14, fontSize: 11, color: BB.red }}>
                Partial load: {err.join(' · ')}
              </div>
            )}
            {!loading && visible.length === 0 && (
              <div style={{ padding: 14, fontSize: 12, color: 'var(--text2)' }}>
                No alerts in this filter. Entry packets live under Re-Entry; SETUPS is the scalp latest-run tally (not the entry-alert lane).
              </div>
            )}
            {visible.map(r => {
              const active = selected?.id === r.id
              return (
                <button
                  key={r.id}
                  type="button"
                  data-testid="alerts-center-row"
                  onClick={() => setSelectedId(r.id)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
                    background: active ? 'var(--bg2)' : 'transparent',
                    border: 0, borderBottom: '1px solid var(--border)',
                    padding: '10px 12px', color: 'var(--text0)',
                  }}
                >
                  <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                    <span style={{ fontSize: TYPE.xs, fontWeight: 800, color: 'var(--text3)', letterSpacing: '.4px' }}>{r.kind.toUpperCase()}</span>
                    {r.state && <span style={{ fontSize: TYPE.xs, color: BB.amber }}>{String(r.state).replace(/_/g, ' ')}</span>}
                    <span style={{ marginLeft: 'auto', fontSize: TYPE.xs, color: 'var(--text3)' }}>{fmtWhen(r.when)}</span>
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 700, marginTop: 2 }}>{r.title}</div>
                  {r.subtitle && <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.subtitle}</div>}
                </button>
              )
            })}
          </div>

          <div style={{ overflowY: 'auto', padding: 14 }}>
            {!selected && <div style={{ fontSize: 12, color: 'var(--text3)' }}>Select an alert.</div>}
            {selected && (
              <>
                <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: 'var(--text3)', letterSpacing: '.5px' }}>{selected.kind.toUpperCase()}</div>
                <div style={{ fontSize: 16, fontWeight: 800, marginTop: 4 }}>{selected.title}</div>
                {selected.subtitle && <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 6 }}>{selected.subtitle}</div>}
                <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 8 }}>When · {fmtWhen(selected.when)}</div>
                {selected.symbols.length > 0 && (
                  <div style={{ fontSize: 11, marginTop: 8 }}>
                    Symbols · {selected.symbols.map(s => (
                      <code key={s} style={{ marginRight: 6, fontFamily: 'var(--mono)' }}>{s}</code>
                    ))}
                  </div>
                )}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 16 }}>
                  <button type="button" data-testid="alerts-primary-link" onClick={() => go(selected.href)}
                    style={{ background: T.link, color: 'var(--text0)', border: 0, borderRadius: RADIUS.sm, padding: '8px 12px', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
                    Open primary surface →
                  </button>
                  {selected.dossierHref && (
                    <button type="button" onClick={() => go(selected.dossierHref!)}
                      style={{ background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: RADIUS.sm, padding: '8px 12px', fontSize: 12, cursor: 'pointer' }}>
                      Symbol dossier
                    </button>
                  )}
                </div>
                <div style={{ marginTop: 18, fontSize: TYPE.xs, color: 'var(--text3)', lineHeight: 1.5 }}>
                  READ_ONLY_ADVISORY. SETUPS counts are the scalp latest-run taxonomy — they are not entry alerts.
                  Chrome words (ALERT / ENTRY / READY / WATCH) never open a dossier.
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
