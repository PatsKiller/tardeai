/** TradeInView — every trade's journey: where it came from, what happened while you held it, why it ended, and
 *  when to get back in (operator directive 2026-10-22; Gate 3 mockup design: one table, a detail panel, drawers).
 *
 *  Reads ONE projection: GET /api/v3/data-broker/trade-journeys (+ /{trade_id} for the price band) —
 *  scripts/lib/data_broker/trade_journey.py, TradeJourneys@v1. The CIO prospect record when its store is live; an
 *  interim adapter until then, labelled on the page. The server decides origin, exit cause, facts and re-entry
 *  conditions; this page renders them.
 *
 *  The one action reuses an existing operator flow: Set alert → ReEntryAlertArmModal (POST /api/v2/watch/alerts,
 *  advisory notification). Nothing here sizes, places, moves or cancels an order. */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle, numStyle, toneVars, type Tone } from '../lib/designTokens'
import {
  API_LIST, EXIT_TONE, FILTERS, TIMELINE_LABEL, TOOLTIPS, alertIntel, apiDetail, chartGeom, drawers,
  etShort, exitText, filterJourneys, originBadge, pct, plText, plTone, px, spreadLabels, stopSegments, timelineTone, unwrap,
  unwrapDetail, type Chart, type FilterId, type Journey, type JourneysPayload,
} from '../lib/tradeJourneyModel'
import { serverNumber, tradeLink } from '../lib/tradeInViewModel'
import '../components/tradeinview/TradeInViewLayout.css'
import ReEntryAlertArmModal from '../components/reentry/ReEntryAlertArmModal'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, minWidth: 0 }
const label: CSSProperties = { fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2] }
const GRID = '90px 200px 110px 110px 150px minmax(0, 1fr)'

function Chip({ tone, children, tip, testId, size = 'md' }: { tone: Tone; children: ReactNode; tip?: string; testId?: string; size?: 'sm' | 'md' }) {
  return (
    <span title={tip} data-testid={testId} style={{ ...chipStyle(tone, 'soft', size), ...(size === 'md' ? { fontSize: TYPE.base, padding: '5px 10px' } : {}), cursor: tip ? 'help' : undefined }}>
      {children}
    </span>
  )
}

function Row({ j, selected, onSelect }: { j: Journey; selected: boolean; onSelect: () => void }) {
  const ob = originBadge(j.origin)
  const exitTone = EXIT_TONE[j.exit_cause.kind]
  const end = j.status === 'closed' ? j.exit : j.mark
  return (
    <div className="tradeinview-journey-row" data-testid="tj-row" data-trade-id={j.trade_id} data-symbol={j.symbol} data-status={j.status} data-origin={j.origin.kind}
      style={{ display: 'grid', gridTemplateColumns: GRID, gap: 12, padding: '12px 16px', alignItems: 'start',
        borderBottom: `1px solid ${TOKENS.borderSubtle}`, background: selected ? TOKENS.bg[2] : undefined,
        borderLeft: `3px solid ${selected ? TOKENS.info : 'transparent'}` }}>
      <span className="tradeinview-mobile-symbol" style={{ fontFamily: FONT.mono, fontWeight: 700, fontSize: TYPE.md }}>{j.symbol}</span>
      <button className="tradeinview-open-journey" data-testid="tj-open-journey" type="button" onClick={onSelect} aria-pressed={selected} title={`Open the ${j.symbol} journey`}
        style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', color: TOKENS.text[0], fontFamily: FONT.mono, fontWeight: 700, fontSize: TYPE.md, minHeight: 36 }}>
        <span className="tradeinview-desktop-symbol">{j.symbol}</span><span className="tradeinview-mobile-action">Journey →</span>
      </button>
      <span style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
        <span title={`${j.origin.label}\n\n${TOOLTIPS.origin}`} data-testid="tj-origin" style={{ ...chipStyle(ob.tone, 'soft', 'sm'), alignSelf: 'flex-start', cursor: 'help', maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }}>{ob.text}</span>
        <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2], whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{j.account_label || 'Unlabelled account'}</span>
      </span>
      <span data-label="Entry" style={{ ...numStyle, fontSize: TYPE.base, textAlign: 'right' }} title={`Entry fill · ${j.entry.source ?? 'source unknown'}`}>
        {px(j.entry.price_ref)}<span style={{ display: 'block', color: TOKENS.text[3], fontSize: TYPE.sm }}>{j.entry.at ? etShort(j.entry.at).slice(0, 5) : '—'}</span>
      </span>
      <span data-label={j.status === 'closed' ? 'Exit' : 'Mark'} style={{ ...numStyle, fontSize: TYPE.base, textAlign: 'right' }} title={j.status === 'closed' ? 'Exit fill' : 'Latest mark'}>
        {px(end?.price_ref ?? null)}<span style={{ display: 'block', color: TOKENS.text[3], fontSize: TYPE.sm }}>{j.status === 'closed' ? (end?.at ? etShort(end.at).slice(0, 5) : '—') : 'mark'}</span>
      </span>
      <span data-label="P/L" style={{ ...numStyle, fontSize: TYPE.base, textAlign: 'right', color: toneVars(plTone(j.pl.amount ?? j.pl.pct)).color }} title={TOOLTIPS.pl}>{plText(j)}</span>
      <span style={{ fontSize: TYPE.base, color: toneVars(exitTone).color, lineHeight: 1.3 }} title={`${j.exit_cause.detail}\n\n${TOOLTIPS.exit}`} data-testid="tj-exit">
        <span style={{ ...chipStyle(exitTone, 'soft', 'sm') }}>{exitText(j)}</span>
        <span style={{ display: 'block', color: TOKENS.text[2], fontSize: TYPE.sm, marginTop: 4 }}>{j.exit_cause.detail}</span>
      </span>
    </div>
  )
}

function PriceBand({ c }: { c: Chart }) {
  const g = chartGeom(c, 520, 220)
  if (!g) return <span style={{ fontSize: TYPE.base, color: TOKENS.text[3] }}>No daily bars for this symbol through the data broker.</span>
  const m = c.marks
  const lastStop = m.stops.length ? m.stops[m.stops.length - 1].level_ref : null
  const ly = spreadLabels(([['laststop', lastStop], ['entry', m.entry_ref], ['exit', m.exit_ref]] as [string, number | null][])
    .filter(([, v]) => v != null).map(([key, v]) => ({ key, y: g.y(v as number) + 3 })), 11, g.pad.t + 6, g.h - g.pad.b)
  const hline = (v: number | null, tone: Tone, text: string, dash: string | undefined, key: string) => v == null ? null : (
    <g key={key}>
      <line x1={g.pad.l} x2={g.w - g.pad.r} y1={g.y(v)} y2={g.y(v)} style={{ stroke: toneVars(tone).color, strokeWidth: 1, strokeDasharray: dash }} />
      <text x={g.w - g.pad.r + 4} y={ly[key] ?? g.y(v) + 3} style={{ fill: toneVars(tone).color, fontSize: 10, fontFamily: 'var(--font-mono)' }}>{text}</text>
    </g>
  )
  const bw = Math.max(2, Math.min(9, (g.w - g.pad.l - g.pad.r) / g.bars.length * 0.6))
  const ex = g.xOf(m.entry_at), xx = g.xOf(m.exit_at)
  return (
    <svg data-testid="tj-chart" role="img" aria-label="Price band: daily bars with entry, stops, exit and the re-entry zone"
      viewBox={`0 0 ${g.w} ${g.h}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
      {m.zone_low_ref != null && m.zone_high_ref != null && (
        <rect x={g.pad.l} width={g.w - g.pad.l - g.pad.r} y={g.y(Math.max(m.zone_low_ref, m.zone_high_ref))}
          height={Math.abs(g.y(m.zone_low_ref) - g.y(m.zone_high_ref))} style={{ fill: toneVars('success').bg, stroke: toneVars('success').border }}>
          <title>{`Re-entry zone ${px(m.zone_low_ref)}–${px(m.zone_high_ref)} (reference)`}</title>
        </rect>
      )}
      {ex != null && xx != null && <rect x={ex} width={Math.max(1, xx - ex)} y={g.pad.t} height={g.h - g.pad.t - g.pad.b} style={{ fill: toneVars('info').bg }}><title>Held</title></rect>}
      {c.kind !== 'candles' && (
        <polyline points={g.bars.filter(b => b.c != null).map(b => `${b.x},${g.y(b.c as number)}`).join(' ')}
          style={{ fill: 'none', stroke: TOKENS.text[1], strokeWidth: 1.5 }} />
      )}
      {g.bars.map(b => (
        <g key={b.time}>
          {b.h != null && b.l != null && <line x1={b.x} x2={b.x} y1={g.y(b.h)} y2={g.y(b.l)} style={{ stroke: TOKENS.text[3], strokeWidth: 1 }} />}
          {b.o != null && b.c != null
            ? <rect x={b.x - bw / 2} width={bw} y={g.y(Math.max(b.o, b.c))} height={Math.max(1, Math.abs(g.y(b.o) - g.y(b.c)))}
                style={{ fill: b.c >= b.o ? toneVars('success').color : toneVars('danger').color }}><title>{`${b.time} O ${px(b.o)} H ${px(b.h)} L ${px(b.l)} C ${px(b.c)}`}</title></rect>
            : b.c != null && <circle cx={b.x} cy={g.y(b.c)} r={1.6} style={{ fill: TOKENS.text[1] }}><title>{`${b.time} close ${px(b.c)}`}</title></circle>}
        </g>
      ))}
      {stopSegments(g, m).map((sg, i) => (
        <line key={`s${i}`} data-testid="tj-chart-stop" x1={sg.x1} x2={sg.x2} y1={sg.y} y2={sg.y}
          style={{ stroke: toneVars('warning').color, strokeWidth: 2 }}>
          <title>{`Stop ${px(sg.level)}${sg.timed ? '' : ' (order only — time not recorded)'}`}</title>
        </line>
      ))}
      {hline(lastStop, 'warning', `stop ${lastStop?.toFixed(2)}`, '3 3', 'laststop')}
      {hline(m.entry_ref, 'info', `in ${m.entry_ref?.toFixed(2)}`, undefined, 'entry')}
      {hline(m.exit_ref, 'danger', `out ${m.exit_ref?.toFixed(2)}`, undefined, 'exit')}
      {m.high_ref != null && <circle cx={g.xOf(m.high_at) ?? 0} cy={g.y(m.high_ref)} r={3} style={{ fill: toneVars('success').color }}><title>{`High while held ${px(m.high_ref)} · ${m.high_at}`}</title></circle>}
      {m.low_ref != null && <circle cx={g.xOf(m.low_at) ?? 0} cy={g.y(m.low_ref)} r={3} style={{ fill: toneVars('danger').color }}><title>{`Low while held ${px(m.low_ref)} · ${m.low_at}`}</title></circle>}
      <text x={g.pad.l} y={g.h - 6} style={{ fill: TOKENS.text[3], fontSize: 10 }}>{g.bars[0].time}</text>
      <text x={g.w - g.pad.r} y={g.h - 6} textAnchor="end" style={{ fill: TOKENS.text[3], fontSize: 10 }}>{g.bars[g.bars.length - 1].time}</text>
    </svg>
  )
}

function Detail({ j: initial, onAlert }: { j: Journey; onAlert: (j: Journey) => void }) {
  const detail = useApi<any>(apiDetail(initial.trade_id))
  const full = unwrapDetail(detail.data)
  const j = full?.trade_id === initial.trade_id ? full : initial
  const chart = j.chart ?? null
  const ob = originBadge(j.origin)
  const re = j.re_entry
  const tiles: [string, string, string][] = [
    ['Entry', `${px(j.entry.price_ref)} · ${etShort(j.entry.at).slice(0, 5)}${j.entry.at_basis ? ' ≈' : ''}`, `Entry fill · ${j.entry.source ?? '—'}${j.entry.at_basis ? ` · date ${j.entry.at_basis}` : ''}`],
    [j.status === 'closed' ? 'Exit' : 'Mark', j.status === 'closed' ? `${px(j.exit?.price_ref)} · ${etShort(j.exit?.at).slice(0, 5)}` : px(j.mark?.price_ref), j.status === 'closed' ? 'Exit fill' : 'Latest mark'],
    ['P/L', plText(j), TOOLTIPS.pl],
    ['Held', j.hold_days == null ? '—' : `${j.hold_days} d`, 'Days from the entry fill to the exit (or now).'],
    ['Conviction', `${j.origin.conviction_at_entry == null ? '—' : Math.round(j.origin.conviction_at_entry)} → ${j.conviction_now == null ? '—' : Math.round(j.conviction_now)}`, TOOLTIPS.conviction],
    ['Shares', j.fill_qty == null ? '—' : String(j.fill_qty), 'Shares in the trade.'],
  ]
  return (
    <div data-testid="tj-detail" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {full && full.trade_id !== initial.trade_id && <div role="status" className="tradeinview-gap">Detail update could not be matched to this trade — showing its recorded list facts.</div>}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: FONT.mono, fontWeight: 700, fontSize: TYPE.lg + 2 }}>{j.symbol} · {j.account_label || 'Unlabelled account'}</span>
        <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{j.company ?? ''}</span>
      </div>

      {j.exit_cause.kind === 'stop_likely_filled' && <section data-testid="tj-awaiting-fill" style={{ background: toneVars('info').bg, border: `1px solid ${toneVars('info').border}`, borderRadius: RADIUS.md, padding: 10 }}>
        <b style={{ color: TOKENS.info, fontSize: TYPE.md }}>Awaiting fill confirmation</b>
        <div style={{ fontSize: TYPE.base, marginTop: 4 }}>{j.exit_cause.detail}</div>
      </section>}
      {j.reconciliation_facts?.length ? <section aria-label="Reconciliation evidence" data-testid="tj-conflicts">
        <div className="tradeinview-reconciliation">
          {j.reconciliation_facts.map(f => <div key={f.key} style={{ background: TOKENS.bg[2], borderRadius: RADIUS.md, padding: 8 }} title={f.source || 'Source unavailable'}>
            <span style={{ ...label, display: 'block' }}>{f.label}</span>
            <span style={{ fontSize: TYPE.base }}>{f.value == null ? f.missing_reason || 'Evidence unavailable' : String(f.value)}</span>
            <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2], display: 'block' }}>{f.at ? etShort(f.at) : 'Time unavailable'}</span>
          </div>)}
        </div>
        {j.conflicts.length > 0 && <details style={{ marginTop: 8, fontSize: TYPE.base }}><summary>Source disagreement details</summary>
          {j.conflicts.map((c, i) => <div key={i} style={{ padding: '6px 0' }}><b>{c.summary}</b><div>{String(c.a.value)} · {c.a.source || 'Source unavailable'} · {c.a.at ? etShort(c.a.at) : 'Time unavailable'}</div><div>{String(c.b.value)} · {c.b.source || 'Source unavailable'} · {c.b.at ? etShort(c.b.at) : 'Time unavailable'}</div></div>)}
        </details>}
      </section> : <section data-testid="tj-conflicts" className="tradeinview-gap" style={{ fontSize: TYPE.base }}>
        Reconciliation evidence unavailable — the server has not supplied the Holdings / Stop vs mark / Fills ledger facts.
        {j.conflicts.map((c, i) => <div key={i}>{c.summary} · {String(c.a.value)} ({c.a.source || 'source unknown'}) vs {String(c.b.value)} ({c.b.source || 'source unknown'})</div>)}
      </section>}
      <div className="tradeinview-controls">
        <Link data-testid="tj-replay" to={tradeLink('replay', { trade_id: j.trade_id })} style={{ ...chipStyle('info', 'soft', 'md'), padding: 10 }}>Replay this trade</Link>
        <Link data-testid="tj-history" to={tradeLink('history', { symbol: j.symbol })} style={{ ...chipStyle('neutral', 'outline', 'md'), padding: 10 }}>All {j.symbol} history</Link>
      </div>

      <section aria-label="Origin" data-testid="tj-origin-card" title={TOOLTIPS.origin}
        style={{ border: `1px solid ${toneVars(ob.tone).border}`, background: toneVars(ob.tone).bg, borderRadius: RADIUS.md, padding: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={label}>Where it came from</span>
        <span style={{ fontSize: TYPE.md, fontWeight: 700, color: toneVars(ob.tone).color }}>{j.origin.label}</span>
        {j.origin.evidence.map((e, i) => <span key={i} style={{ fontSize: TYPE.sm, color: TOKENS.text[2], fontFamily: FONT.mono }}>{e.source}: {e.detail}</span>)}
        {j.origin.surface_href && <Link to={j.origin.surface_href.replace(/^\/v3/, '')} style={{ fontSize: TYPE.sm, color: TOKENS.info }}>Open {j.origin.surface}</Link>}
      </section>

      <div className="tradeinview-detail-tiles" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
        {tiles.map(([k, v, tip]) => (
          <div key={k} title={tip} style={{ background: TOKENS.bg[2], borderRadius: RADIUS.md, padding: 8, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ ...label, fontSize: TYPE.xs }}>{k}</span>
            <span style={{ ...numStyle, fontSize: TYPE.base + 1, fontWeight: 600 }}>{v}</span>
          </div>
        ))}
      </div>

      <section aria-label="Price band" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span style={label} title={TOOLTIPS.chart}>Price band {chart ? `· ${chart.kind} · ${chart.source}` : ''}</span>
        {chart ? <PriceBand c={chart} /> : <span style={{ fontSize: TYPE.base, color: TOKENS.text[3] }}>{detail.loading ? 'Loading daily bars…' : 'No daily bars for this symbol through the data broker.'}</span>}
      </section>

      <section aria-label="Timeline" data-testid="tj-timeline" style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        <span style={{ ...label, marginBottom: 6 }} title={TOOLTIPS.timeline}>Timeline (ET)</span>
        {j.timeline.map((e, i) => {
          const t = toneVars(timelineTone(e))
          return (
            <div key={i} data-testid="tj-event" data-kind={e.kind} title={[e.detail, e.source ? `source: ${e.source}` : null].filter(Boolean).join('\n')}
              style={{ display: 'grid', gridTemplateColumns: '82px 70px 1fr', gap: 8, padding: '4px 0', borderLeft: `2px solid ${t.border}`, paddingLeft: 8, fontSize: TYPE.base }}>
              <span style={{ ...numStyle, color: TOKENS.text[2] }} title={e.at ? undefined : 'Time not recorded — the order is known, the time is not'}>{e.at ? etShort(e.at) : 'time n/r'}</span>
              <span style={{ color: t.color, fontWeight: 700 }}>{TIMELINE_LABEL[e.kind]}</span>
              <span style={{ color: TOKENS.text[1], lineHeight: 1.35 }}>
                {e.label}{e.unconfirmed && <span style={{ color: TOKENS.info }}> · unconfirmed</span>}
                {e.kind === 'exit_fill' && e.detail && <span style={{ display: 'block', color: TOKENS.text[2], fontSize: TYPE.sm }}>{e.detail}</span>}
              </span>
            </div>
          )
        })}
      </section>


      <section aria-label="Review" data-testid="tj-review" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span style={label} title={TOOLTIPS.review}>{j.status === 'closed' ? 'Post-exit review — facts' : 'Review so far — facts'}</span>
        {j.review.facts.map(f => (
          <div key={f.key} title={`source: ${f.source}`} style={{ display: 'grid', gridTemplateColumns: '150px 1fr', gap: 8, fontSize: TYPE.base }}>
            <span style={{ color: TOKENS.text[2] }}>{f.label}</span>
            <span style={{ ...numStyle, color: f.tone === 'neutral' ? TOKENS.text[0] : toneVars(f.tone).color }}>{f.value}</span>
          </div>
        ))}
        {j.review.advisory && (
          <div data-testid="tj-advisory" title={`${j.review.advisory.source}${j.review.advisory.generated_at ? ' · ' + j.review.advisory.generated_at : ''}`}
            style={{ marginTop: 4, border: `1px dashed ${toneVars('ai').border}`, borderRadius: RADIUS.md, padding: 8, fontSize: TYPE.base, lineHeight: 1.5 }}>
            <span style={{ ...chipStyle('ai', 'soft', 'sm'), marginRight: 6 }}>ADVISORY · {j.review.advisory.model ?? 'model'}</span>
            <span style={{ color: TOKENS.text[1] }}>{j.review.advisory.text}</span>
            <span style={{ display: 'block', color: TOKENS.text[3], fontSize: TYPE.sm, marginTop: 4 }}>{j.review.advisory.label}</span>
          </div>
        )}
      </section>

      <section aria-label="Re-entry" data-testid="tj-reentry" title={TOOLTIPS.reentry}
        style={{ border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={label}>When to get back in</span>
          <span style={{ fontSize: TYPE.sm, color: re.stale ? TOKENS.warning : TOKENS.text[3] }}>desk {re.desk_as_of ? etShort(re.desk_as_of) : '—'}{re.stale ? ' · stale' : ''}</span>
        </div>
        <span style={{ fontSize: TYPE.base + 1, lineHeight: 1.45 }}>{re.summary ?? '—'}</span>
        {(re.zone_low_ref != null || re.reclaim_ref != null) && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 6 }}>
            {([['Zone', re.zone_low_ref != null ? `${px(re.zone_low_ref)}–${px(re.zone_high_ref)}` : '—'],
              ['Invalidation', px(re.invalidation_ref)], ['Target', px(re.target_ref)], ['Reclaim exit', px(re.reclaim_ref)],
              ['Price now', px(re.price_ref)], ['Distance', re.distance_pct == null ? '—' : pct(re.distance_pct, 1)]] as [string, string][]).map(([k, v]) => (
              <div key={k} style={{ background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: 6 }}>
                <span style={{ ...label, display: 'block' }}>{k}</span><span style={{ ...numStyle, fontSize: TYPE.base }}>{v}</span>
              </div>
            ))}
          </div>
        )}
        {re.conditions.length > 0 && (
          <div data-testid="tj-conditions" style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{serverNumber(re.conditions_met)} of {serverNumber(re.conditions_required)} conditions met{re.conditions_met == null || re.conditions_required == null ? ' · server counts unavailable' : ''}</span>
            {re.conditions.map(c => (
              <span key={c.id} title={c.detail ?? undefined} style={{ fontSize: TYPE.base, color: c.met === true ? TOKENS.success : c.met === false ? TOKENS.text[2] : TOKENS.text[3] }}>
                {c.met === true ? '✓' : c.met === false ? '○' : '?'} {c.label}{c.detail ? <span style={{ color: TOKENS.text[3] }}> — {c.detail}</span> : null}
              </span>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <button type="button" data-testid="tj-set-alert" disabled={!alertIntel(re)} onClick={() => onAlert(j)} title={TOOLTIPS.setAlert}
            style={{ fontSize: TYPE.base, fontWeight: 700, padding: '8px 12px', borderRadius: RADIUS.md, minHeight: 36, cursor: alertIntel(re) ? 'pointer' : 'not-allowed', background: toneVars('info').bg, border: `1px solid ${toneVars('info').border}`, color: toneVars('info').color }}>
            Set alert…
          </button>
          {re.watch_href && <Link to={re.watch_href.replace(/^\/v3/, '')} style={{ fontSize: TYPE.base, fontWeight: 700, padding: '8px 12px', borderRadius: RADIUS.md, background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, color: TOKENS.text[1] }}>Open in Watch</Link>}
        </div>
        <span style={{ fontSize: TYPE.sm, color: TOKENS.text[3] }}>{re.source}. Levels are references for your decision, never orders.</span>
      </section>
    </div>
  )
}

export default function TradeJourney({ payload, loading, error, embedded = false }: { payload?: JourneysPayload | null; loading?: boolean; error?: string | null; embedded?: boolean } = {}) {
  const [params, setParams] = useSearchParams()
  const location = useLocation(), navigate = useNavigate()
  const [phone, setPhone] = useState(() => window.matchMedia('(max-width: 820px)').matches)
  const detailSheet = useRef<HTMLElement>(null)
  useEffect(() => {
    const media = window.matchMedia('(max-width: 820px)')
    const update = () => setPhone(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  const api = useApi<any>(API_LIST, 60_000, { enabled: payload === undefined })
  const p: JourneysPayload | null = useMemo(() => payload === undefined ? unwrap(api.data) : payload, [api.data, payload])
  const filter = (FILTERS.find(f => f.id === params.get('filter'))?.id ?? 'all') as FilterId
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [alertFor, setAlertFor] = useState<Journey | null>(null)
  const [alertMsg, setAlertMsg] = useState('')
  const rows = useMemo(() => (p ? filterJourneys(p.journeys, filter) : []), [p, filter])
  const counts: Record<string, number | undefined> | null = p ? { ...p.counts, attention: p.counts.awaiting_fill, mine: p.counts.operator } : null

  // URL identity also closes the phone sheet on browser Back; no hidden local selection can reopen it.
  const deepSym = (params.get('symbol') || '').trim().toUpperCase()
  const requestedTrade = params.get('trade')
  const detailRequested = Boolean(requestedTrade || deepSym)
  const sel = (requestedTrade ? p?.journeys.find(j => j.trade_id === requestedTrade)
    : deepSym ? p?.journeys.find(j => j.symbol === deepSym) : phone ? null : p?.journeys[0]) ?? null
  const closeDetail = () => {
    if (location.state?.tradeJourneyReturn) { navigate(-1); return }
    const next = new URLSearchParams(params)
    next.delete('trade'); next.delete('symbol')
    setParams(next, { replace: true })
  }
  const closeRef = useRef(closeDetail)
  closeRef.current = closeDetail
  const hasPayload = Boolean(p), hasAlert = Boolean(alertFor)
  useEffect(() => {
    if (!phone || !detailRequested || !hasPayload || hasAlert || !detailSheet.current) return
    const sheet = detailSheet.current, before = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'; sheet.focus()
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeRef.current(); return }
      if (event.key !== 'Tab') return
      const controls = [...sheet.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),summary,[tabindex="0"]')].filter(node => node.getClientRects().length)
      const first = controls[0], last = controls[controls.length - 1]
      if (!first) { event.preventDefault(); sheet.focus() }
      else if (event.shiftKey && (document.activeElement === sheet || document.activeElement === first)) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && (document.activeElement === sheet || document.activeElement === last)) { event.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', key, true)
    return () => {
      window.removeEventListener('keydown', key, true); document.body.style.overflow = overflow
      if (before?.isConnected && (sheet.contains(document.activeElement) || document.activeElement === document.body)) before.focus()
    }
  }, [phone, detailRequested, requestedTrade, deepSym, hasPayload, hasAlert])

  const setFilter = (id: FilterId) => {
    const next = new URLSearchParams(params)
    if (id === 'all') next.delete('filter'); else next.set('filter', id)
    setParams(next, { replace: true })
  }
  const select = (j: Journey) => {
    const next = new URLSearchParams(params)
    next.set('trade', j.trade_id); next.delete('symbol')
    setParams(next, { replace: !phone, state: phone ? { ...location.state, tradeJourneyReturn: true } : location.state })
  }

  if (!p) {
    return (
      <div className="tradeinview" data-testid="trade-journey" style={{ padding: 16, color: TOKENS.text[2], fontSize: TYPE.base }}>
        {(loading ?? api.loading) ? 'Loading trade journeys…' : `Trade journeys unavailable${(error ?? api.error) ? ` — ${error ?? api.error}` : ''}.`}
      </div>
    )
  }
  const c = p.counts
  return (
    <div className="tradeinview" data-testid="trade-journey" style={{ display: 'flex', flexDirection: 'column', gap: 14, fontFamily: FONT.sans, color: TOKENS.text[0] }}>
      {!embedded && <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {!embedded && <h1 style={{ margin: 0, fontSize: TYPE.xl - 2, fontWeight: 700 }}>TradeInView · trade journeys</h1>}
          <div style={{ fontSize: TYPE.base + 1, color: TOKENS.text[1] }}>
            {serverNumber(c.open)} open · {serverNumber(c.closed)} closed in {p.window_days == null ? 'an unknown number of' : p.window_days} days · <b style={{ color: toneVars('ai').color }}>{serverNumber(c.internal)} from internal</b> · {serverNumber(c.operator)} your picks · {serverNumber(c.unknown)} origin unknown
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {p.interim && (
            <span data-testid="tj-interim" title={TOOLTIPS.interim}
              style={{ fontFamily: FONT.mono, fontSize: TYPE.sm, color: TOKENS.text[2], border: `1px dashed ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '3px 7px', cursor: 'help' }}>
              {p.source_label}
            </span>
          )}
          <Link to="/journal?view=classic" data-testid="tj-classic" title="The previous TradeInView journal: analytics, tagging, costs, import."
            style={{ fontSize: TYPE.base, color: TOKENS.info }}>Classic journal →</Link>
        </div>
      </div>}

      <div role="group" aria-label="Data freshness" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {(p.freshness_chips || []).map(ch => (
          <Chip key={ch.key} tone={ch.tone} tip={`${ch.tip}${ch.at ? `\nas of ${ch.at}` : ''}${ch.source ? `\nsource: ${ch.source}` : ''}`} testId={`tj-chip-${ch.key}`}><b>{ch.label}</b>&nbsp;{ch.value ?? ch.missing_reason ?? 'Sync evidence unavailable'}{ch.at && ch.source_label ? <span data-testid={`tj-chip-${ch.key}-source`}>&nbsp;· {ch.source_label}</span> : null}</Chip>
        ))}
        {!p.freshness_chips && <span className="tradeinview-gap" style={{ fontSize: TYPE.base }}>Freshness receipt fields unavailable — sync times are not inferred from fill or stop observations.</span>}
      </div>

      <div role="group" aria-label="Filter" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {FILTERS.map(f => (
          <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)} title={f.tip} data-testid={`tj-filter-${f.id}`}
            style={{ borderRadius: RADIUS.pill, padding: '6px 12px', fontSize: TYPE.base, fontWeight: 600, cursor: 'pointer', minHeight: 32,
              background: filter === f.id ? TOKENS.bg[3] : 'transparent', border: `1px solid ${filter === f.id ? TOKENS.info : TOKENS.border}`,
              color: filter === f.id ? TOKENS.text[0] : TOKENS.text[2] }}>
            {f.label} <span style={{ fontFamily: FONT.mono, opacity: 0.85 }}>{serverNumber(counts?.[f.id])}</span>
          </button>
        ))}
      </div>

      <div className="tradeinview-journey-layout">
        <div style={{ flex: '999 1 600px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <section aria-label="Trades" className="tradeinview-journey-table" style={panel}>
            <div style={{ minWidth: 660 }}>
              <div className="tradeinview-journey-head" style={{ display: 'grid', gridTemplateColumns: GRID, gap: 12, padding: '10px 16px', borderBottom: `1px solid ${TOKENS.border}`, ...label }}>
                <span>Symbol</span><span title={TOOLTIPS.origin}>Origin · account</span><span style={{ textAlign: 'right' }}>Entry</span>
                <span style={{ textAlign: 'right' }}>Exit / mark</span><span style={{ textAlign: 'right' }} title={TOOLTIPS.pl}>P/L</span>
                <span title={TOOLTIPS.exit}>Status</span>
              </div>
              {rows.length === 0 && <div style={{ padding: 16, fontSize: TYPE.base, color: TOKENS.text[2] }}>No trades in this filter.</div>}
              {rows.map(j => <Row key={j.trade_id} j={j} selected={sel?.trade_id === j.trade_id} onSelect={() => select(j)} />)}
            </div>
          </section>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {drawers(p).map(d => (
              <div key={d.id} data-testid={`tj-drawer-${d.id}`} style={panel}>
                <button type="button" aria-expanded={!!open[d.id]} onClick={() => setOpen({ ...open, [d.id]: !open[d.id] })}
                  style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, background: 'none', border: 'none', color: TOKENS.text[0], padding: '12px 16px', cursor: 'pointer', fontSize: TYPE.md, minHeight: 46, textAlign: 'left' }}>
                  <span><b>{d.title}</b> <span style={{ color: TOKENS.text[2] }}>· {d.summary}</span></span>
                  <span aria-hidden="true" style={{ color: TOKENS.info, whiteSpace: 'nowrap' }}>{open[d.id] ? 'Hide ▴' : 'Show ▾'}</span>
                </button>
                {open[d.id] && <div data-testid={`tj-drawer-${d.id}-body`} style={{ borderTop: `1px solid ${TOKENS.border}`, padding: '12px 16px', fontSize: TYPE.base + 1, lineHeight: 1.6, color: TOKENS.text[1], whiteSpace: 'pre-line' }}>{d.body}</div>}
              </div>
            ))}
          </div>
        </div>
        <aside ref={detailSheet} tabIndex={-1} className={`tradeinview-journey-detail${detailRequested ? ' is-open' : ''}`} data-testid="tj-detail-sheet" role={phone && detailRequested ? 'dialog' : undefined} aria-modal={phone && detailRequested || undefined} aria-label="Trade journey" style={{ ...panel, borderRadius: phone ? 0 : RADIUS.lg, padding: 16 }}>
          <div className="tradeinview-journey-back"><button type="button" data-testid="tj-detail-back" onClick={closeDetail} style={{ border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.text[0], borderRadius: RADIUS.md, padding: '8px 12px', fontSize: TYPE.base }}>Back</button><strong>Trade journey</strong></div>
          <div className="tradeinview-journey-detail-scroll">
          {sel ? <Detail key={sel.trade_id} j={sel} onAlert={setAlertFor} />
            : <div style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>{detailRequested ? 'Selected trade unavailable in this recorded journey window.' : 'Click a trade to see where it came from, what happened, why it ended and when to get back in.'}</div>}
          {alertMsg && <div data-testid="tj-alert-armed" style={{ color: TOKENS.success, fontSize: TYPE.base, marginTop: 8 }}>{alertMsg}</div>}
          </div>
        </aside>
      </div>

      {alertFor && alertIntel(alertFor.re_entry) && (
        <ReEntryAlertArmModal
          symbol={alertFor.symbol}
          intel={alertIntel(alertFor.re_entry)!}
          noteTag="tradeinview-reentry"
          onClose={() => setAlertFor(null)}
          onArmed={summary => { setAlertMsg(`${alertFor.symbol}: armed ${summary}`); setAlertFor(null) }}
        />
      )}
    </div>
  )
}

