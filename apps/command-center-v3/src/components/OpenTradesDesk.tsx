/** Open Trades — protect first (operator-approved Gate 3 design OpenTrades.dc.html, 2026-10-22).
 *
 *  Headline → freshness chips → protect-first strip (no working stop, largest exposure first) →
 *  filters → one position table (PAPER badged) + detail panel (stop history, actions) → drawers
 *  (broker reconciliation — moved from the retired Broker Recon tab — write-offs, small positions,
 *  protection advisory, excluded rows, how this page works).
 *
 *  HARD BOUNDARY: this view never builds, sizes or sends an order. "Arm stop (2FA)…" opens the
 *  existing PositionDecisionCardV4 for the selected position, whose Stage 2c protective-stop ARM +
 *  per-order 2FA flow is rendered unchanged. "Snooze 1 week" calls the same advisory stop-alert snooze
 *  route the card's "Ignore 1 week" uses; it never touches the broker stop.
 */
import { accountName } from '../lib/accountLabels'
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import {
  ageText, buildDeskModel, DESK_FILTERS, filterRows, money, price, sharesText, sortRows, stopHistory,
  type DeskFilter, type DeskRow, type SortKey, type StopState,
} from '../lib/openTradesDesk'
import { summarizeReconByBroker } from '../lib/brokerReconSummary'
import { downloadOpenTradesCsv } from '../lib/exportOpenTradesCsv'
import { formatReviewStamp } from '../lib/stopReviewTooltip'
import type { DrillContext } from './DetailDrawer'
import PositionDecisionCardV4 from './PositionDecisionCardV4'
import ProtectionPanel from './ProtectionPanel'
import { useProAnalystMap } from './ProAnalystPill'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }
const mono: CSSProperties = { fontFamily: FONT.mono, fontVariantNumeric: 'tabular-nums' }
const caps: CSSProperties = { fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2] }
const COLS = '60px minmax(118px, 1.1fr) 72px 74px 86px 88px 96px minmax(118px, 1fr) 80px'
const STOP_TONE: Record<StopState, Tone> = { none: 'danger', near: 'warning', ok: 'success', na: 'neutral' }
const toneColor = (t: Tone) => (t === 'neutral' ? TOKENS.text[2] : toneVars(t).color)

const ET_FMT = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
function etTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : `${ET_FMT.format(d)} ET`
}

function chip(t: Tone): CSSProperties {
  const v = toneVars(t)
  return { fontSize: TYPE.base, borderRadius: RADIUS.pill, padding: '5px 10px', border: `1px solid ${v.border}`, background: v.bg, color: TOKENS.text[0] }
}

function btn(kind: 'danger' | 'info' | 'plain'): CSSProperties {
  const v = toneVars(kind === 'danger' ? 'danger' : 'info')
  return {
    whiteSpace: 'nowrap', fontSize: TYPE.base, fontWeight: 700, padding: '6px 10px', borderRadius: RADIUS.sm, minHeight: 32,
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontFamily: 'inherit',
    background: kind === 'plain' ? 'transparent' : v.bg, border: `1px solid ${v.border}`, color: kind === 'plain' ? TOKENS.text[1] : v.color,
    textDecoration: 'none',
  }
}

function Drawer({ id, title, summary, open, onToggle, children }: { id: string; title: string; summary: ReactNode; open: boolean; onToggle: () => void; children: ReactNode }) {
  return (
    <div style={panel} data-testid={`ot-drawer-${id}`} id={`ot-drawer-${id}`}>
      <button type="button" onClick={onToggle} aria-expanded={open}
        style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, background: 'none', border: 'none', color: TOKENS.text[0], padding: '12px 16px', cursor: 'pointer', fontSize: TYPE.md, minHeight: 46, textAlign: 'left', fontFamily: 'inherit' }}>
        <span><b>{title}</b> <span style={{ color: TOKENS.text[2] }}>· {summary}</span></span>
        <span aria-hidden="true" style={{ color: TOKENS.info, whiteSpace: 'nowrap' }}>{open ? 'Hide ▴' : 'Show ▾'}</span>
      </button>
      {open && <div style={{ borderTop: `1px solid ${TOKENS.border}`, padding: '12px 16px', fontSize: TYPE.base, lineHeight: 1.6, color: TOKENS.text[1] }}>{children}</div>}
    </div>
  )
}

function PaperBadge() {
  return <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.04em', color: TOKENS.bg[0], background: toneVars('ai').color, borderRadius: RADIUS.sm, padding: '1px 5px' }}>PAPER</span>
}

function MarkCell({ r }: { r: DeskRow }) {
  const move = r.todayPct
  return (
    <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 1 }}
      title={`${r.quoteSource ?? 'source unknown'} · as of ${etTime(r.markAsOf)}${r.markStale ? ' · stale: the day move is hidden' : ''}`}>
      <span style={mono}>{price(r.mark)}</span>
      <span style={{ fontSize: TYPE.xs, color: r.markStale ? toneVars('warning').color : TOKENS.text[2] }}>
        {r.markStale ? `stale · ${ageText(r.markAgeHours)}` : `${move == null ? '' : `${move > 0 ? '+' : ''}${move.toFixed(1)}% · `}${ageText(r.markAgeHours)}`}
      </span>
    </span>
  )
}

export default function OpenTradesDesk({ onDrill, focusSymbol, initialDrawer }: { onDrill: (c: DrillContext) => void; focusSymbol?: string; initialDrawer?: string | null }) {
  const { data, loading, error } = useApi<any>('/api/v2/open-trades/intelligence', 60_000)
  const model = useMemo(() => buildDeskModel(data), [data])
  const summary = data?.summary ?? {}
  const [filter, setFilter] = useState<DeskFilter>('all')
  const [account, setAccount] = useState('all')
  const [sort, setSort] = useState<SortKey>('value')
  const [selId, setSelId] = useState<string | null>(null)
  const [cardOpen, setCardOpen] = useState(false)
  const [drawers, setDrawers] = useState<Record<string, boolean>>(() => (initialDrawer ? { [initialDrawer]: true } : {}))
  const [snooze, setSnooze] = useState<{ busy: boolean; msg: string }>({ busy: false, msg: '' })
  const cardRef = useRef<HTMLDivElement | null>(null)
  const focus = (focusSymbol || '').toUpperCase()

  const everyRow = useMemo(() => [...model.rows, ...model.small, ...model.writeOffs], [model])
  const selected = everyRow.find(r => r.id === selId) ?? null

  // Deep link (?symbol=XXX from a Reports stop action / triage chip): select it and open its stop controls.
  useEffect(() => {
    if (!focus || !everyRow.length) return
    const hit = everyRow.find(r => r.sym.toUpperCase() === focus)
    if (hit) { setSelId(hit.id); setCardOpen(true) }
  }, [focus, everyRow.length]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (initialDrawer) setDrawers(d => ({ ...d, [initialDrawer]: true })) }, [initialDrawer])
  useEffect(() => {
    if (initialDrawer && data) document.getElementById(`ot-drawer-${initialDrawer}`)?.scrollIntoView?.({ block: 'start' })
  }, [initialDrawer, !!data]) // eslint-disable-line react-hooks/exhaustive-deps

  const { data: recon } = useApi<any>('/api/v2/broker-reconciliation', 120_000, { enabled: !!drawers.recon })
  const { data: llmCov } = useApi<any>('/api/v2/portfolio/llm-coverage', 300_000, { enabled: cardOpen })
  const { data: scards } = useApi<any>('/api/v2/symbol-cards', 300_000, { enabled: cardOpen })
  const paMap = useProAnalystMap()

  const shown = useMemo(() => sortRows(filterRows(model.rows, filter, account), sort), [model.rows, filter, account, sort])
  const toggle = (k: string) => setDrawers(d => ({ ...d, [k]: !d[k] }))
  const select = (r: DeskRow) => { setSelId(r.id); setSnooze({ busy: false, msg: '' }) }
  const armStop = (r: DeskRow) => {
    select(r); setCardOpen(true)
    window.setTimeout(() => cardRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 60)
  }
  const doSnooze = async (r: DeskRow) => {
    setSnooze({ busy: true, msg: '' })
    try {
      const res = await fetch('/api/v2/holdings/stop-snooze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: r.sym, days: 7 }) }).then(x => x.json())
      setSnooze({ busy: false, msg: res?.ok ? `Stop alert for ${r.sym} snoozed until ${String(res.snoozed_until).slice(0, 10)}. The broker stop (if any) is unchanged.` : `Snooze failed: ${res?.error ?? 'unknown error'}` })
    } catch {
      setSnooze({ busy: false, msg: 'Snooze failed — retry.' })
    }
  }

  if (loading && !data) return <div style={{ ...panel, padding: 16, color: TOKENS.text[2] }}>Loading open positions…</div>
  if (error && !data) return <div role="alert" style={{ ...panel, padding: 16, color: toneVars('danger').color }}>Position intelligence unavailable: {String(error)}. Nothing here is reported as protected.</div>

  const h = model.headline
  const counts = Object.fromEntries(DESK_FILTERS.map(f => [f.key, filterRows(model.rows, f.key, account).length])) as Record<DeskFilter, number>
  const staleN = Number(summary.stale_price_count ?? 0)
  const freshness: Array<{ k: string; v: string; tone: Tone; tip: string }> = [
    { k: 'Marks', v: `repriced ${etTime(summary.last_price_update)}${staleN ? ` · ${staleN} stale` : ''}`, tone: staleN ? 'warning' : 'success',
      tip: `Each row shows its own price time. Oldest mark ${etTime(summary.oldest_price_update)}; a mark older than ${summary.price_stale_after_hours ?? 18} h is stale and its day move is hidden.` },
    { k: 'Stops', v: `broker snapshot ${formatReviewStamp(summary.broker_stops_fetched_at) ?? '—'}`, tone: summary.broker_stops_fetched_at ? 'success' : 'warning',
      tip: 'Working stop orders read from the broker (Schwab, Alpaca paper). "No working stop" means the broker had no open stop order for those shares at this time.' },
    { k: 'Cost basis', v: h.basisPending ? `${h.basisPending} pending` : 'all positions priced', tone: h.basisPending ? 'warning' : 'success',
      tip: 'Unrealized = shares × mark − cost basis. A position without a broker cost basis shows "pending", never zero.' },
  ]

  return (
    <div data-testid="open-trades-desk" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: TYPE.lg + 4, fontWeight: 700, color: TOKENS.text[0] }}>Open trades</h2>
          <div data-testid="ot-headline" style={{ fontSize: TYPE.md - 1, color: TOKENS.text[1] }}>
            {h.positions} positions across {h.accounts} accounts · unrealized{' '}
            <b style={{ color: (h.unrealized ?? 0) >= 0 ? toneVars('success').color : toneVars('danger').color }}>{money(h.unrealized, { signed: true })}</b>
            {h.writeOffCount ? ` excluding ${h.writeOffCount} write-off${h.writeOffCount > 1 ? 's' : ''}` : ''}
            {h.basisPending ? ` (${h.basisPending} without cost basis)` : ''}
            {' · '}
            <b style={{ color: h.unprotectedCount ? toneVars('danger').color : TOKENS.text[1] }}>
              {h.unprotectedCount
                ? `${h.unprotectedCount} position${h.unprotectedCount > 1 ? 's' : ''} (${money(h.unprotectedValue)}) have no working stop`
                : 'every stoppable position has a working stop'}
            </b>
          </div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          <button type="button" data-testid="open-trades-export-csv" disabled={!shown.length} onClick={() => downloadOpenTradesCsv(shown.map(r => r.raw))}
            title="Download the positions shown as CSV (client-side; no broker call)" style={{ ...btn('plain'), opacity: shown.length ? 1 : 0.5 }}>Export CSV ({shown.length})</button>
          <Link to={selected ? `/journal?symbol=${encodeURIComponent(selected.sym)}` : '/journal'} data-testid="open-trades-journal-link" style={btn('plain')}>Journal</Link>
          <Link to={`/portfolio?tab=${encodeURIComponent('Stop Management')}${selected ? `&symbol=${encodeURIComponent(selected.sym)}` : ''}`} data-testid="open-trades-stop-desk-link" style={btn('plain')}>Stop Management</Link>
        </div>
      </div>

      <div role="group" aria-label="Data freshness" data-testid="ot-freshness" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {freshness.map(f => <span key={f.k} style={chip(f.tone)} title={f.tip}><b>{f.k}</b> {f.v}</span>)}
      </div>

      {model.protect.length > 0 && (
        <section aria-label="Protect first" data-testid="ot-protect-first"
          style={{ background: toneVars('danger').bg, border: `1px solid ${toneVars('danger').border}`, borderRadius: RADIUS.md, padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
            <h3 style={{ margin: 0, fontSize: TYPE.md + 2, color: TOKENS.text[0] }}>Protect first · no working stop</h3>
            <span style={{ fontSize: TYPE.base, color: TOKENS.text[1] }}>largest dollar exposure first · placing a stop is your action, with 2FA</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
            {model.protect.slice(0, 8).map(p => (
              <div key={p.id} data-testid="ot-protect-card" style={{ background: TOKENS.bg[1], border: `1px solid ${toneVars('danger').border}`, borderRadius: RADIUS.sm, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ ...mono, fontWeight: 700, fontSize: TYPE.md + 1 }}>{p.sym}</span>
                  <span style={{ ...mono, fontSize: TYPE.md - 1 }}>{money(p.value)}</span>
                </div>
                <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{p.accountLabel} · {sharesText(p.shares)} sh{p.paper ? ' · PAPER' : ''}</span>
                <span style={{ fontSize: TYPE.base, color: toneVars('warning').color }}>{stopHistory(p.raw)[0]}</span>
                <button type="button" onClick={() => armStop(p)} style={{ ...btn('danger'), marginTop: 4, minHeight: 36 }}>Set a stop…</button>
              </div>
            ))}
          </div>
        </section>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <div role="group" aria-label="Filter positions" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {DESK_FILTERS.map(f => (
            <button key={f.key} type="button" aria-pressed={filter === f.key} data-testid={`ot-filter-${f.key}`} onClick={() => setFilter(f.key)}
              style={{ borderRadius: RADIUS.pill, padding: '6px 12px', fontSize: TYPE.base, fontWeight: 600, cursor: 'pointer', minHeight: 32, fontFamily: 'inherit',
                background: filter === f.key ? toneVars('info').bg : 'transparent', border: `1px solid ${filter === f.key ? toneVars('info').color : TOKENS.border}`, color: filter === f.key ? TOKENS.text[0] : TOKENS.text[1] }}>
              {f.label} <span style={{ ...mono, opacity: 0.85 }}>{counts[f.key]}</span>
            </button>
          ))}
        </div>
        <span style={{ flex: 1 }} />
        <label style={{ fontSize: TYPE.base, color: TOKENS.text[2], display: 'inline-flex', gap: 6, alignItems: 'center' }}>Account
          <select value={account} onChange={e => setAccount(e.target.value)} data-testid="ot-account"
            style={{ fontSize: TYPE.base, padding: '5px 8px', background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, color: TOKENS.text[0] }}>
            <option value="all">All accounts</option>
            {model.accounts.map(a => <option key={a} value={a}>{summary.account_labels?.[a] ?? a}</option>)}
          </select>
        </label>
        <label style={{ fontSize: TYPE.base, color: TOKENS.text[2], display: 'inline-flex', gap: 6, alignItems: 'center' }}>Sort
          <select value={sort} onChange={e => setSort(e.target.value as SortKey)} data-testid="ot-sort"
            style={{ fontSize: TYPE.base, padding: '5px 8px', background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, color: TOKENS.text[0] }}>
            <option value="value">Value</option><option value="stop">Stop status</option><option value="pl">Unrealized (worst first)</option><option value="sym">Symbol</option>
          </select>
        </label>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' }}>
        <section aria-label="Positions" style={{ ...panel, flex: '999 1 700px', minWidth: 0, overflowX: 'auto' }}>
          <div style={{ minWidth: 840 }}>
            <div style={{ display: 'grid', gridTemplateColumns: COLS, gap: 8, padding: '8px 14px', borderBottom: `1px solid ${TOKENS.border}`, ...caps }}>
              <span>Symbol</span><span>Account</span><span style={{ textAlign: 'right' }}>Shares</span><span style={{ textAlign: 'right' }}>Avg cost</span>
              <span style={{ textAlign: 'right' }}>Mark</span><span style={{ textAlign: 'right' }}>Value</span><span style={{ textAlign: 'right' }}>Unrealized</span><span>Stop</span><span />
            </div>
            {shown.length === 0 && <div style={{ padding: '20px 14px', color: TOKENS.text[2] }}>No positions match this filter.</div>}
            {shown.map(r => {
              const sel = selected?.id === r.id
              return (
                <div key={r.id} data-testid="ot-row" data-symbol={r.sym}
                  style={{ display: 'grid', gridTemplateColumns: COLS, gap: 8, padding: '6px 14px', alignItems: 'center', borderBottom: `1px solid ${TOKENS.borderSubtle}`,
                    background: sel ? toneVars('info').bg : undefined, borderLeft: `3px solid ${sel ? toneVars('info').color : 'transparent'}` }}>
                  <button type="button" onClick={() => select(r)} aria-label={`Show details for ${r.sym}`}
                    style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', color: TOKENS.text[0], ...mono, fontWeight: 700, fontSize: TYPE.md - 1, minHeight: 32 }}>{r.sym}</button>
                  <span style={{ fontSize: TYPE.base, display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 }}>
                    <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={r.account}>{r.accountLabel}</span>
                    {r.paper && <PaperBadge />}
                  </span>
                  <span style={{ ...mono, fontSize: TYPE.base, textAlign: 'right' }}>{sharesText(r.shares)}</span>
                  <span style={{ ...mono, fontSize: TYPE.base, textAlign: 'right', color: r.avgCost == null ? toneVars('warning').color : TOKENS.text[0] }}>{r.avgCost == null ? 'pending' : price(r.avgCost)}</span>
                  <span style={{ fontSize: TYPE.base, textAlign: 'right' }}><MarkCell r={r} /></span>
                  <span style={{ ...mono, fontSize: TYPE.base, textAlign: 'right' }}>{money(r.value)}</span>
                  <span style={{ ...mono, fontSize: TYPE.base, textAlign: 'right', color: r.pl == null ? TOKENS.text[2] : r.pl < 0 ? toneVars('danger').color : toneVars('success').color }}>{r.pl == null ? 'basis pending' : money(r.pl, { signed: true })}</span>
                  <span style={{ fontSize: TYPE.base, color: toneColor(STOP_TONE[r.stopState]) }}>{r.stopText}</span>
                  <button type="button" onClick={() => (r.stopState === 'none' ? armStop(r) : select(r))} style={r.stopState === 'none' ? btn('danger') : btn('info')}>
                    {r.stopState === 'none' ? 'Set stop' : r.stopState === 'near' ? 'Review' : 'Details'}
                  </button>
                </div>
              )
            })}
            {model.small.length > 0 && (
              <div style={{ padding: '10px 14px', fontSize: TYPE.base, color: TOKENS.text[2] }}>
                + {model.small.length} small positions under {money(Number(summary.small_position_usd ?? 500))} each · in the{' '}
                <button type="button" onClick={() => toggle('small')} style={{ background: 'none', border: 'none', padding: 0, color: TOKENS.info, cursor: 'pointer', fontSize: TYPE.base, fontFamily: 'inherit' }}>Small positions</button> drawer
              </div>
            )}
          </div>
        </section>

        <aside aria-label="Position detail" data-testid="ot-detail" style={{ ...panel, flex: '1 1 320px', maxWidth: 440, minWidth: 0, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {!selected && <div style={{ color: TOKENS.text[2], fontSize: TYPE.md - 1 }}>Click a position to see its stop history and what you can do.</div>}
          {selected && (() => {
            const r = selected
            const tiles: Array<[string, string]> = [
              ['Shares', sharesText(r.shares, true)], ['Avg cost', r.avgCost == null ? 'pending' : price(r.avgCost)],
              ['Mark', `${price(r.mark)} · ${ageText(r.markAgeHours)}`], ['Value', money(r.value)],
              ['Unrealized', r.pl == null ? 'basis pending' : money(r.pl, { signed: true })], ['Stop', r.stopText.split(' · ')[0]],
            ]
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <span style={{ ...mono, fontWeight: 700, fontSize: TYPE.lg + 2, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  {r.sym} <span style={{ fontFamily: FONT.sans, fontWeight: 500, fontSize: TYPE.md - 1, color: TOKENS.text[1] }}>· {r.accountLabel}</span>{r.paper && <PaperBadge />}
                </span>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
                  {tiles.map(([k, v]) => (
                    <div key={k} style={{ background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: 8, display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                      <span style={caps}>{k}</span><span style={{ ...mono, fontSize: TYPE.md - 1, fontWeight: 600, overflowWrap: 'anywhere' }}>{v}</span>
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }} data-testid="ot-stop-history">
                  <span style={caps}>Stop history</span>
                  {stopHistory(r.raw).map((line, i) => <span key={i} style={{ fontSize: TYPE.base, color: TOKENS.text[1] }}>{line}</span>)}
                </div>
                <div style={{ fontSize: TYPE.md - 1, lineHeight: 1.5, background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: 10 }}>
                  {r.raw?.decision_reason || r.raw?.operator_decision || 'No advisory note for this position.'}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  <button type="button" data-testid="ot-arm-stop" onClick={() => armStop(r)} style={btn('danger')}
                    title="Opens this position's stop controls (Stage 2c protective stop). Nothing is sent until you confirm the order and enter the 2FA code.">Arm stop (2FA)…</button>
                  <Link to={`/trading?tab=Options&symbol=${encodeURIComponent(r.sym)}`} style={btn('info')} title={`Opens the Options desk filtered to ${r.sym}, where protective put ideas for it are listed`}>Protective put ideas</Link>
                  <button type="button" data-testid="ot-snooze" disabled={snooze.busy} onClick={() => doSnooze(r)} style={btn('info')}
                    title="Snoozes this position's stop ALERT for 7 days. Advisory only: it does not place, change or cancel any broker stop.">{snooze.busy ? '…' : 'Snooze 1 week'}</button>
                </div>
                {snooze.msg && <span role="status" style={{ fontSize: TYPE.base, color: TOKENS.text[1] }}>{snooze.msg}</span>}
                <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>Arming a stop sends nothing until you enter the 2FA code. The system never places or moves a stop on its own.</span>
              </div>
            )
          })()}
        </aside>
      </div>

      {selected && cardOpen && (
        <section ref={cardRef} aria-label={`Stop controls for ${selected.sym}`} data-testid="ot-stop-controls" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0, fontSize: TYPE.md + 1, color: TOKENS.text[0] }}>Stop controls · {selected.sym} · {selected.accountLabel}</h3>
            <button type="button" onClick={() => setCardOpen(false)} style={btn('plain')}>Close</button>
          </div>
          <div style={{ maxWidth: 980 }}>
            <PositionDecisionCardV4
              p={selected.raw} paMap={paMap} expanded onToggle={() => setCardOpen(false)} onDrill={onDrill}
              llmCov={(llmCov as any)?.coverage?.[selected.sym.toUpperCase()]}
              protectionRec={(llmCov as any)?.protection?.[selected.sym.toUpperCase()]}
              symCard={(scards as any)?.cards?.[selected.sym.toUpperCase()]}
              onAction={(a: string, pos: any) => onDrill({ title: `${pos.symbol} — ${a}`, subtitle: `${pos.operator_decision} · read-only review`, endpoint: '/api/v2/open-trades/intelligence', rows: [pos], subjectType: 'position', subjectKey: pos.symbol } as any)}
            />
          </div>
        </section>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <ReconDrawer open={!!drawers.recon} onToggle={() => toggle('recon')} recon={recon} onDrill={onDrill} />
        <Drawer id="writeoffs" title="Write-offs" open={!!drawers.writeoffs} onToggle={() => toggle('writeoffs')}
          summary={model.writeOffs.length ? `${model.writeOffs.map(w => w.sym).join(', ')} · ${money(h.writeOffPnl, { signed: true })} · excluded from totals` : 'none'}>
          {model.writeOffs.length === 0 ? 'No worthless or delisted positions.' : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {model.writeOffs.map(w => (
                <div key={w.id} data-testid="ot-writeoff-row">
                  <b style={mono}>{w.sym}</b> · {w.accountLabel} · {sharesText(w.shares)} sh · last mark {price(w.mark)} ({etTime(w.markAsOf)}) · basis {money(w.raw?.cost_basis)} · {money(w.raw?.write_off_pnl ?? w.pl, { signed: true })}
                </div>
              ))}
              <span style={{ color: TOKENS.text[2] }}>Shown here so a worthless or delisted holding does not distort the headline P/L. Confirm the write-off on your broker statement.</span>
            </div>
          )}
        </Drawer>
        <Drawer id="small" title="Small positions" open={!!drawers.small} onToggle={() => toggle('small')}
          summary={`${model.small.length} under ${money(Number(summary.small_position_usd ?? 500))} each`}>
          {model.small.length === 0 ? 'None.' : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}>
              {model.small.map(s => (
                <button key={s.id} type="button" onClick={() => select(s)} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: TOKENS.text[1], fontSize: TYPE.base, fontFamily: 'inherit' }}>
                  <b style={mono}>{s.sym}</b> {s.accountLabel} · {sharesText(s.shares)} sh · {money(s.value)}{s.pl != null ? ` (${money(s.pl, { signed: true })})` : ''}
                </button>
              ))}
              <span style={{ flexBasis: '100%', color: TOKENS.text[2] }}>Fractional shares (mostly dividend reinvestment); too small for stop orders, so they never raise "large gain unprotected".</span>
            </div>
          )}
        </Drawer>
        <Drawer id="protection" title="Protection advisory" open={!!drawers.protection} onToggle={() => toggle('protection')} summary="ATM adjustment proposals · paper account only">
          {drawers.protection && <ProtectionPanel onDrill={onDrill} />}
        </Drawer>
        {(summary.excluded_stale_trade_rows > 0 || summary.excluded_zero_share_rows > 0) && (
          <Drawer id="excluded" title="Excluded rows" open={!!drawers.excluded} onToggle={() => toggle('excluded')}
            summary={`stale trade rows ${summary.excluded_stale_trade_rows ?? 0} · zero-share ${summary.excluded_zero_share_rows ?? 0} · non-ticker ${summary.excluded_non_ticker_rows ?? 0}`}>
            <div style={{ maxHeight: 220, overflow: 'auto' }}>
              {(data?.excluded_items ?? []).slice(0, 60).map((e: any, i: number) => (
                <div key={i} style={{ fontSize: TYPE.sm }}><span style={{ color: TOKENS.text[2] }}>{e.account ? accountName(e.account, e.account_label) : '—'}</span> · <b>{e.symbol ?? '—'}</b> · {e.reason}<span style={{ color: TOKENS.text[2] }}> · {e.source}</span></div>
              ))}
            </div>
          </Drawer>
        )}
        <Drawer id="help" title="How this page works" open={!!drawers.help} onToggle={() => toggle('help')} summary="what each column means">
          Shares come from the broker read. Mark is the latest price with its own time (hover it for the source); a mark older than {summary.price_stale_after_hours ?? 18} hours is marked stale and its day move is hidden.
          Unrealized = shares × mark − cost basis. "No working stop" means the broker has no open stop order for these shares right now; funds that cannot take a stop order and fractional positions show "n/a".
          Arming a stop needs your 2FA code; nothing is placed automatically. Live Schwab account orders and order history:{' '}
          <Link to="/trading?tab=Schwab+Accounts" style={{ color: TOKENS.info }}>Schwab account monitor</Link>.
        </Drawer>
      </div>
    </div>
  )
}

function ReconDrawer({ open, onToggle, recon, onDrill }: { open: boolean; onToggle: () => void; recon: any; onDrill: (c: DrillContext) => void }) {
  const r = recon?.data ?? recon ?? {}
  const runs: any[] = r.runs ?? []
  const latest = runs[0] ?? {}
  const items: any[] = (r.items ?? []).filter((it: any) => latest.id == null || it.run_id == null || it.run_id === latest.id)
  const venues = summarizeReconByBroker(runs, items)
  const breaks = Number(latest.unmatched_broker_orders ?? 0) + Number(latest.unmatched_local_trades ?? 0)
  const summaryText = !recon ? 'open to load the latest run' : `${items.length || breaks} break${(items.length || breaks) === 1 ? '' : 's'} on the paper account · ${latest.started_at ? new Date(latest.started_at).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}`
  const byIssue = items.reduce((m: Record<string, number>, it: any) => { const k = String(it.issue_code || it.reconciliation_state || 'other'); m[k] = (m[k] || 0) + 1; return m }, {})
  return (
    <Drawer id="recon" title="Broker reconciliation (moved from the Broker Recon tab)" open={open} onToggle={onToggle} summary={summaryText}>
      {!recon ? 'Loading reconciliation…' : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }} data-testid="ot-recon">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <span style={chip('neutral')}><b>Orders seen</b> {latest.orders_seen ?? '—'}</span>
            <span style={chip('neutral')}><b>Matched</b> {latest.trades_matched ?? '—'}</span>
            <span style={chip(Number(latest.unmatched_broker_orders) > 0 ? 'warning' : 'neutral')}><b>Unmatched broker</b> {latest.unmatched_broker_orders ?? 0}</span>
            <span style={chip(Number(latest.unmatched_local_trades) > 0 ? 'warning' : 'neutral')}><b>Unmatched local</b> {latest.unmatched_local_trades ?? 0}</span>
            {Object.entries(byIssue).map(([k, n]) => <span key={k} style={chip('warning')}><b>{k.replace(/_/g, ' ').toLowerCase()}</b> {n as number}</span>)}
          </div>
          {venues.map(v => (
            <div key={v.broker} style={{ fontSize: TYPE.base }}>
              <b>{v.broker}</b> <PaperBadge /> · {v.status.toUpperCase()} · {v.next_action}
            </div>
          ))}
          <div style={{ maxHeight: 260, overflow: 'auto' }}>
            {items.length === 0 ? <div>No unmatched items — the broker and our books agree for the latest run.</div> : items.slice(0, 40).map((it: any, i: number) => (
              <button key={it.id ?? i} type="button" onClick={() => onDrill({ title: it.symbol ?? 'Reconciliation item', subtitle: it.reconciliation_state, endpoint: '/api/v2/broker-reconciliation', rows: [it] })}
                style={{ display: 'grid', gridTemplateColumns: '80px 1fr 1fr', gap: 8, width: '100%', textAlign: 'left', background: 'none', border: 'none', borderBottom: `1px solid ${TOKENS.borderSubtle}`, padding: '5px 0', cursor: 'pointer', color: TOKENS.text[1], fontSize: TYPE.base, fontFamily: 'inherit' }}>
                <span style={{ ...mono, fontWeight: 700, color: TOKENS.text[0] }}>{it.symbol ?? '—'}</span>
                <span>{String(it.reconciliation_state ?? '').replace(/_/g, ' ').toLowerCase()}</span>
                <span style={{ color: TOKENS.text[2] }}>{it.paper_trade_id ? `paper trade #${it.paper_trade_id}` : it.severity ?? ''}</span>
              </button>
            ))}
          </div>
          <span style={{ color: TOKENS.text[2] }}>Source: /api/v2/broker-reconciliation — the latest run on the paper account (tradeai_automated). No real-money account is reconciled here.</span>
        </div>
      )}
    </Drawer>
  )
}
