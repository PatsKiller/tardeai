import { useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BB, T, TYPE } from '../../../lib/watchTokens'
import { RADIUS } from '../../../lib/designTokens'
import {
  clockET, defenseLines, GAP, GLOSSARY, ladder, money, pct, readinessTone, scorePosition, signed, sourceSummaryText,
  sourceTone, tierTone, type DefenseProjection, type Tone,
} from '../../../lib/defenseEngine'

/**
 * Design defense/v001: the engine view on the v3 Defense desk. Every sentence and number comes from
 * DefenseProjection@v1 (GET /api/v2/defense/engine); this file only lays it out. Read-only: no request
 * but GET, no order control, no size, no level. Rows open route-backed full-screen sheets (?detail=engine:<id>).
 */
export const TONE: Record<Tone, string> = { good: BB.green, warn: BB.amber, bad: BB.red, info: T.link, muted: BB.text2 }
const card: CSSProperties = { background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: RADIUS.lg, padding: 14, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }
const h3: CSSProperties = { margin: 0, fontSize: TYPE.md, color: BB.text0 }
const small: CSSProperties = { fontSize: TYPE.base, color: BB.text3, overflowWrap: 'anywhere' }
const mono: CSSProperties = { fontFamily: 'var(--font-mono)' }
const rowBtn: CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, minHeight: 56, width: '100%', padding: '8px 0', border: 'none', borderTop: `1px solid ${BB.border}`, background: 'transparent', color: BB.text1, font: 'inherit', textAlign: 'left', cursor: 'pointer', boxSizing: 'border-box' }

/** A dotted term: tap on a phone, hover or focus on desktop, shows a one-line definition. */
export function Term({ k, children }: { k: string; children?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const def = GLOSSARY[k]
  if (!def) return <>{children ?? k}</>
  return <span style={{ position: 'relative', display: 'inline' }} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
    <button type="button" aria-expanded={open} aria-label={`${k}: definition`} onClick={e => { e.stopPropagation(); setOpen(o => !o) }}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      style={{ background: 'none', border: 'none', padding: 0, font: 'inherit', color: 'inherit', borderBottom: `1px dotted ${BB.text3}`, cursor: 'help', minHeight: 0 }}>
      {children ?? k}
    </button>
    {open && <span role="tooltip" style={{ position: 'absolute', left: 0, top: '1.6em', zIndex: 20, width: 'min(280px, 80vw)', background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: RADIUS.md, padding: '8px 10px', fontSize: TYPE.base, color: BB.text1, lineHeight: 1.4 }}>{def}</span>}
  </span>
}

function Stamp({ asOf, why }: { asOf?: string | null; why?: string | null }) {
  return <span style={{ ...small, color: why ? BB.amber : BB.text3 }}>{why ? `${why}` : asOf ? `as of ${clockET(asOf)}` : GAP}</span>
}

function Chip({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: RADIUS.md, border: `1px solid ${TONE[tone]}`, color: TONE[tone], fontSize: TYPE.base, fontWeight: 600, ...mono }}>{children}</span>
}

function Hero({ p, onOpen }: { p: DefenseProjection; onOpen: (k: string) => void }) {
  const t = p.tier ?? {}, tone = tierTone(t.tier)
  return <section aria-label="Defense headline" data-testid="defense-engine-hero" style={{ ...card, borderLeft: `3px solid ${TONE[tone]}` }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <button type="button" onClick={() => onOpen('tier')} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', minHeight: 44 }} aria-label="Open the tier ladder">
        <Chip tone={tone}><Term k="tier">{t.tier ?? 'TIER ' + GAP}</Term> · {t.score != null ? Number(t.score).toFixed(1) : GAP}</Chip>
      </button>
      {t.shock?.label && <span style={small}>{t.shock.label}</span>}
      {t.confirming?.n != null && <span style={small}>{t.confirming.n} of {t.confirming.of} categories confirming</span>}
    </div>
    <h2 style={{ margin: 0, fontSize: TYPE.lg, color: BB.text0, lineHeight: 1.3 }}>{p.narrative?.headline ?? 'The defense projection has no headline on file.'}</h2>
    {p.stale_reason && <div role="note" style={{ padding: '8px 10px', borderRadius: RADIUS.md, border: `1px dashed ${BB.amber}`, color: BB.amber, fontSize: TYPE.base }}>{p.stale_reason}</div>}
    <h3 style={{ ...h3, marginTop: 6 }}>Where we stand</h3>
    <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6, color: BB.text1, fontSize: TYPE.md }}>
      {(p.narrative?.where_we_stand ?? []).map((w, i) => <li key={w.field ?? i}>
        {w.text} {w.stale_reason && <span style={{ ...small, color: BB.amber }}>({w.stale_reason})</span>}
      </li>)}
      {!(p.narrative?.where_we_stand ?? []).length && <li style={small}>Nothing on file.</li>}
    </ul>
  </section>
}

function WhatToDo({ p, onOpen }: { p: DefenseProjection; onOpen: (k: string) => void }) {
  const steps = p.narrative?.what_to_do ?? []
  return <section aria-label="What to do about it" data-testid="defense-engine-steps" style={card}>
    <h3 style={h3}>What to do about it</h3>
    {steps.map((s, i) => <button key={s.id} type="button" onClick={() => onOpen(s.sheet)} data-testid={`defense-step-${s.id}`} style={{ ...rowBtn, alignItems: 'flex-start' }}>
      <span style={{ display: 'flex', gap: 10, minWidth: 0 }}>
        <span style={{ ...mono, color: TONE[(s.tone as Tone) in TONE ? (s.tone as Tone) : 'muted'], fontWeight: 700 }}>{i + 1}</span>
        <span style={{ minWidth: 0 }}>
          <span style={{ display: 'block', color: BB.text0, fontWeight: 600 }}>{s.title}</span>
          <span style={{ display: 'block', ...small, color: BB.text2 }}>{s.text}</span>
        </span>
      </span>
      <span aria-hidden style={{ color: T.link }}>›</span>
    </button>)}
    {!steps.length && <p style={small}>No step on file.</p>}
    {p.narrative?.disclaimer && <p style={{ ...small, margin: 0 }}>{p.narrative.disclaimer}</p>}
  </section>
}

export function Ladder({ p }: { p: DefenseProjection }) {
  const t = p.tier ?? {}, pos = scorePosition(t.score)
  return <section aria-label="Tier ladder" data-testid="defense-engine-ladder" style={card}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
      <h3 style={h3}>Tier ladder</h3><Stamp asOf={t.as_of} why={t.stale_reason} />
    </div>
    <div style={{ position: 'relative', height: 10, borderRadius: RADIUS.md, background: BB.bgShift, border: `1px solid ${BB.border}` }}>
      {pos != null && <span aria-label={`score ${pos}`} style={{ position: 'absolute', left: `calc(${pos}% - 2px)`, top: -3, width: 4, height: 14, background: TONE[tierTone(t.tier)], borderRadius: RADIUS.sm }} />}
    </div>
    <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 4 }}>
      {ladder(t).map(s => <li key={s.tier} aria-current={s.current ? 'step' : undefined} style={{ textAlign: 'center', padding: '6px 2px', borderRadius: RADIUS.md, border: `1px solid ${s.current ? TONE[tierTone(s.tier)] : BB.border}`, color: s.current ? TONE[tierTone(s.tier)] : BB.text2, fontSize: TYPE.sm, minWidth: 0 }}>
        <div style={{ fontWeight: s.current ? 700 : 400 }}>{s.tier}</div>
        <div style={{ ...mono, color: BB.text3 }}>{s.min_score != null ? `≥${s.min_score}` : '—'}</div>
      </li>)}
    </ol>
    {t.sessions_recorded?.n != null && <p style={{ ...small, margin: 0 }}>De-escalation clock: {t.sessions_recorded.n} of {t.sessions_recorded.of} sessions recorded{t.held_by_session_rule ? ' · tier held by the session rule' : ''}.</p>}
    {t.deescalates_if && <p style={{ ...small, margin: 0 }}>Steps down if: {t.deescalates_if}</p>}
  </section>
}

function Lines({ p, onOpen }: { p: DefenseProjection; onOpen: (k: string) => void }) {
  return <section aria-label="The defense, line by line" data-testid="defense-engine-lines" style={card}>
    <h3 style={h3}>The defense, line by line</h3>
    {defenseLines(p).map(l => <button key={l.id} type="button" data-testid={`defense-line-${l.id}`} onClick={() => onOpen(l.sheet)} style={rowBtn}>
      <span style={{ minWidth: 0 }}>
        <span style={{ display: 'block', color: BB.text0 }}>{l.label}</span>
        <span style={{ display: 'block', ...small }}>{l.staleReason ?? l.sub}</span>
      </span>
      <span style={{ textAlign: 'right', minWidth: 0, flexShrink: 0, maxWidth: '45%' }}>
        <span style={{ display: 'block', ...mono, color: TONE[l.tone], overflowWrap: 'anywhere' }}>{l.value}</span>
        {l.valueSub && <span style={{ display: 'block', ...small }}>{l.valueSub}</span>}
      </span>
    </button>)}
  </section>
}

export function SourceStrip({ p, onOpen }: { p: DefenseProjection; onOpen: (k: string) => void }) {
  return <button type="button" data-testid="defense-engine-sources" onClick={() => onOpen('sources')} style={{ ...rowBtn, borderTop: 'none', minHeight: 44, flexWrap: 'wrap', justifyContent: 'flex-start' }}>
    <span style={small}>Sources:</span>
    {(p.sources ?? []).map(s => <span key={s.id} title={s.stale_reason ?? undefined} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: TYPE.sm, color: BB.text2 }}>
      <span aria-hidden style={{ width: 8, height: 8, borderRadius: RADIUS.pill, background: TONE[sourceTone(s.state)] }} />{s.label}
    </span>)}
    <span style={{ ...small, marginLeft: 'auto' }}>{sourceSummaryText(p.source_summary, p.sources)} · built {clockET(p.generated_at)}</span>
  </button>
}

/** The engine view: three columns from 980px, one column on a phone. */
export default function DefenseEngineView({ p, onOpen }: { p: DefenseProjection; onOpen: (k: string) => void }) {
  return <div data-testid="defense-engine" style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
    <style>{`.def-engine-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;align-items:start}.def-engine-col{display:flex;flex-direction:column;gap:12px;min-width:0}@media(min-width:980px){.def-engine-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}`}</style>
    <div className="def-engine-grid">
      <div className="def-engine-col"><Hero p={p} onOpen={onOpen} /></div>
      <div className="def-engine-col"><WhatToDo p={p} onOpen={onOpen} /><Ladder p={p} /></div>
      <div className="def-engine-col"><Lines p={p} onOpen={onOpen} /></div>
    </div>
    <SourceStrip p={p} onOpen={onOpen} />
  </div>
}

// ── full-screen sheets ───────────────────────────────────────────────────────

function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return <div style={{ borderTop: `1px solid ${BB.border}`, paddingTop: 8, display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
    <span style={{ color: BB.text2, fontSize: TYPE.md, minWidth: 0 }}>{label}</span>
    <span style={{ ...mono, color: BB.text0, fontSize: TYPE.md, textAlign: 'right', overflowWrap: 'anywhere', minWidth: 0 }}>{children}</span>
  </div>
}
function List({ children }: { children: ReactNode }) {
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{children}</div>
}
function Note({ children }: { children: ReactNode }) {
  return <p style={{ ...small, margin: '8px 0 0' }}>{children}</p>
}

export const SHEET_TITLES: Record<string, string> = {
  tier: 'Tier and ladder', exposure: 'Book in stressed groups', stops: 'Stop coverage', hedge: 'Hedge readiness',
  sector: 'Sector posture', cash: 'Cash alternatives', base: 'What usually happens next', watch: 'Watch next session', sources: 'Sources',
}

export function EngineSheetBody({ p, sheet }: { p: DefenseProjection; sheet: string }) {
  const stamp = (s: { as_of?: string | null; stale_reason?: string | null }) => <Note>{s.stale_reason ? `Gap: ${s.stale_reason}` : `As of ${clockET(s.as_of)}`}</Note>
  switch (sheet) {
    case 'tier': {
      const t = p.tier ?? {}
      return <List><Ladder p={p} />
        <Field label="Score">{t.score != null ? Number(t.score).toFixed(1) : GAP}</Field>
        <Field label="Shock">{t.shock?.label ?? GAP}</Field>
        <Field label="Since">{clockET(t.since)}</Field>
        <Field label="Acknowledged">{t.acknowledged_at ? clockET(t.acknowledged_at) : 'not acknowledged'}</Field>
        {p.playbook?.stage_text && <Note>{p.playbook.stage_text}</Note>}
        {(t.history ?? []).slice(-6).map((h, i) => <Field key={i} label={clockET(h.as_of)}>{h.tier ?? GAP} · {h.score ?? GAP}</Field>)}
        {stamp(t)}</List>
    }
    case 'exposure': {
      const e = p.exposure ?? {}
      return <List>
        <Field label={<Term k="stressed groups">In stressed groups</Term>}>{money(e.stressed_usd)} · {pct(e.stressed_pct_invested, 1)} of invested</Field>
        <Field label="Invested">{money(e.invested_usd)}</Field>
        <Field label="Cash">{money(e.cash_usd)} · {pct(e.cash_pct_book)} of book</Field>
        <Field label="Groups">{(e.stressed_groups ?? []).join(', ') || 'none'}</Field>
        <h3 style={{ ...h3, marginTop: 8 }}>Holdings (<Term k="look-through" />)</h3>
        {(e.rows ?? []).map((r, i) => <Field key={`${r.symbol}-${r.account_label}-${i}`} label={<>{r.symbol} <span style={small}>{r.account_label ?? ''}</span></>}>
          {money(r.usd_exposed)}{r.stop_distance_pct != null ? ` · stop ${pct(r.stop_distance_pct, 1)} away` : ''}{r.stance_label ? <> · <Term k="exit review">{r.stance_label}</Term></> : ''}
        </Field>)}
        {e.residuals?.count ? <Note>{e.residuals.count} smaller holdings carry {money(e.residuals.usd_exposed)} more.</Note> : null}
        {(e.unmapped ?? []).length > 0 && <Note>Not mapped to a group: {(e.unmapped ?? []).map(u => u.symbol).join(', ')}.</Note>}
        {(e.budgets ?? []).map((b, i) => <Field key={i} label={`${b.account_label ?? ''} ${b.budget ?? ''}`}>{b.actual ?? GAP}{b.unit ?? ''} vs {b.limit ?? GAP}{b.unit ?? ''}</Field>)}
        {(e.rotate ?? []).length > 0 && <Note>Holding up: {(e.rotate ?? []).map(r => `${r.label} (${signed(r.rs5)})`).join(', ')}.</Note>}
        {stamp(e)}</List>
    }
    case 'stops': {
      const s = p.stops ?? {}
      return <List>
        <Field label="No broker stop">{s.no_stop?.count ?? GAP} · {money(s.no_stop?.value_usd)}</Field>
        <Field label="Pending">{s.pending?.count ?? GAP} · {money(s.pending?.value_usd)}</Field>
        <Field label="Planned only">{s.planned_only ?? GAP}</Field>
        <Field label="Active">{s.active ?? GAP}</Field>
        {s.hedged_share && <Field label="Hedged">{s.hedged_share}</Field>}
        {s.beta && <Field label="Beta">{s.beta}</Field>}
        <h3 style={{ ...h3, marginTop: 8 }}>Gaps</h3>
        {(s.gaps ?? []).map((g, i) => <Field key={i} label={<>{g.symbol} <span style={small}>{g.account_label ?? ''}</span></>}>{money(g.value_usd)} · {g.state ?? GAP}</Field>)}
        {!(s.gaps ?? []).length && <Note>No gap on file.</Note>}
        {(s.near ?? []).length > 0 && <><h3 style={{ ...h3, marginTop: 8 }}>Within {pct(s.near_threshold_pct)} of the stop</h3>
          {(s.near ?? []).map((n, i) => <Field key={i} label={n.symbol}>{pct(n.distance_pct, 1)}</Field>)}</>}
        <Note>Stops are set at the broker by you. This page shows coverage only.</Note>
        {stamp(s)}</List>
    }
    case 'hedge': {
      const h = p.hedge_readiness ?? {}
      return <List>
        <Field label="Readiness"><span style={{ color: TONE[readinessTone(h.readiness)] }}>{h.readiness ?? 'UNKNOWN'}</span></Field>
        <Field label="Shock class">{h.shock_class ?? GAP}</Field>
        <h3 style={{ ...h3, marginTop: 8 }}><Term k="considered when">Considered when</Term></h3>
        {(h.triggers ?? []).map(t => <Field key={t.id} label={t.label}>{t.met == null ? GAP : t.met ? 'met' : 'not met'}{t.value != null ? ` · ${t.value}${t.unit ?? ''} vs ${t.threshold}${t.unit ?? ''}` : ''}</Field>)}
        <h3 style={{ ...h3, marginTop: 8 }}>Inverse ETF gates (<Term k="daily reset" />)</h3>
        {Object.entries(h.inverse_triggers ?? {}).map(([bench, v]) => <Field key={bench} label={`${bench} → ${v.inverse ?? GAP}`}>{v.trigger == null ? GAP : v.trigger ? 'thesis on' : 'thesis off'}</Field>)}
        {(h.inverse_lane ?? []).map((l, i) => <Field key={i} label={`${l.inverse} (${l.name ?? l.bench})`}>{l.thesis_label ?? l.thesis_state ?? GAP}</Field>)}
        {h.put_protection && <Field label={<Term k="protective put">Put protection</Term>}>QQQ IV {h.put_protection.qqq_atm_iv ?? GAP} · {h.put_protection.structures ?? GAP} structures{h.put_protection.lifecycle?.stale_reason ? ` · ${h.put_protection.lifecycle.stale_reason}` : ''}</Field>}
        <Note>No size, no order. Any hedge is your decision at the broker.</Note>
        {stamp(h)}</List>
    }
    case 'sector': {
      const s = p.sector_posture ?? {}
      return <List>
        <Field label="Measured">{s.sectors_measured ?? GAP} · {s.sectors_hit ?? GAP} hit</Field>
        {(s.engine ?? []).map(r => <Field key={r.key} label={r.label}><span style={{ color: r.state === 'STRESS' ? BB.red : r.state === 'WEAKENING' || r.state === 'WEAK' ? BB.amber : BB.text1 }}>{r.state ?? GAP}</span> · {signed(r.rs5)}{r.check_data ? ' · check data' : ''}</Field>)}
        {(s.disagreements ?? []).length > 0 && <Note>Desk and engine disagree on: {(s.disagreements ?? []).map(d => d.label).join(', ')}.</Note>}
        <Link to="/watch?tab=sectors" style={{ display: 'flex', alignItems: 'center', minHeight: 44, color: T.link }}>Sector momentum on Watch ›</Link>
        {stamp(s)}</List>
    }
    case 'cash': {
      const c = p.cash_alternatives ?? {}
      return <List>
        <Field label="Cash">{money(c.cash_usd)} · {pct(c.cash_pct_book)} of book</Field>
        <Field label="Yields">{c.yields_on_file ? 'on file' : GAP}</Field>
        {(c.vehicles ?? []).map(v => <Field key={v.symbol} label={`${v.symbol} ${v.name ?? ''}`}>{v.yield_pct != null ? pct(v.yield_pct, 2) : GAP}</Field>)}
        {stamp(c)}</List>
    }
    case 'base': {
      const b = p.base_rates ?? {}
      return <List>
        {(b.rows ?? []).map(r => <Field key={r.label} label={r.label}>median {pct(r.median_pct, 1)} · 10th pct {pct(r.p10_pct, 1)} · lower in {pct(r.lower_pct)} (n={r.n ?? GAP})</Field>)}
        {b.further_drop_pct != null && <Field label="A further drop followed">{pct(b.further_drop_pct)}</Field>}
        {(b.notes ?? []).map((n, i) => <Note key={n.id ?? i}>{n.text}</Note>)}
        <Note>{b.caveat ?? 'History, not a forecast.'}</Note>
        {stamp(b)}</List>
    }
    case 'watch': {
      const w = p.watch_next ?? {}
      return <List>{(w.items ?? []).map((it, i) => <Field key={i} label={it.kind ?? 'item'}>{it.text}</Field>)}
        {!(w.items ?? []).length && <Note>Nothing on file.</Note>}{stamp(w)}</List>
    }
    case 'sources':
      return <List>{(p.sources ?? []).map(s => <Field key={s.id} label={<><span aria-hidden style={{ display: 'inline-block', width: 8, height: 8, borderRadius: RADIUS.pill, background: TONE[sourceTone(s.state)], marginRight: 6 }} />{s.label}</>}>
        {s.state.replace('_', ' ')} · {clockET(s.as_of)}{s.stale_reason ? ` · ${s.stale_reason}` : ''}{s.lane_ids?.length ? ` · ${s.lane_ids.join(', ')}` : ''}
      </Field>)}
        {p.served && <Note>Served from {p.served.served_from ?? GAP}{p.served.stale ? ` · stale: ${p.served.fallback_reason ?? GAP}` : ''}.</Note>}
      </List>
    default:
      return <p>This sheet is not in the defense projection.</p>
  }
}
