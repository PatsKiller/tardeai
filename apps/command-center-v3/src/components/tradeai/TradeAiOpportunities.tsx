/** Trade AI — Opportunities (operator-approved Gate 3 design Main.dc.html, 2026-10-22).
 *
 *  Run line → six filter tiles → filter chips + Table/Cards toggle → float-first table (catalyst · grade ·
 *  validation on one line, click-to-filter float / RVOL / sector, column sort) or cards → AI analysis panel
 *  with the Level 2 entry / exit signals → Shared Momentum drawer (collapsed).
 *
 *  Reads the existing endpoints only: /api/v2/trade-ai/scanner (passed in by the hub),
 *  /api/v2/trade-ai/candidates (Shared Momentum) and /api/v3/active-trader/alerts (served L2 signals).
 *  Gate 2 fields (catalyst type, grade, validation, action score, AI checks) show "—" with a tooltip until
 *  the CIO prospect record exists. Awareness only: no order, approval or 2FA control lives here.
 */
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../../lib/designTokens'
import {
  applyFilters, buildTiles, chgText, filterChips, floatBand, floatText, GATE2_TIP, l2Brief, l2View, latestAlertFor,
  NO_FILTERS, rvolText, sortOpportunities, stars, toOpportunity, volText,
  type Decision, type Filters, type L2Chip, type Opportunity, type SortKey,
} from '../../lib/tradeAiOpportunities'
import { tradeAiSurfaceFreshness } from '../../lib/surfaceFreshness'
import { latestRunPhrase, payloadRunAge } from '../../lib/scanRunAge'
import { classifyRunHealth, runHealthChipColor, runHealthReasonCodes } from '../../lib/runHealth'
import SharedMomentumCandidates from './SharedMomentumCandidates'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }
const mono: CSSProperties = { fontFamily: FONT.mono, fontVariantNumeric: 'tabular-nums' }
const caps: CSSProperties = { fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2] }
const COLS = '72px 70px 56px 56px 60px minmax(0, 1fr) 56px 112px'
const DEC_TONE: Record<Decision, Tone> = { GO: 'success', WAIT: 'warning', MANUAL: 'ai', AVOID: 'danger', OTHER: 'neutral' }
const DEC_LABEL: Record<Decision, string> = { GO: 'GO', WAIT: 'WAIT', MANUAL: 'MANUAL', AVOID: 'AVOID', OTHER: '—' }
const tc = (t: Tone) => (t === 'neutral' ? TOKENS.text[2] : toneVars(t).color)

function pill(d: Decision): CSSProperties {
  return { display: 'inline-block', fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.05em', padding: '2px 6px', borderRadius: RADIUS.sm,
    color: TOKENS.bg[0], background: d === 'OTHER' ? TOKENS.text[3] : toneVars(DEC_TONE[d]).color }
}

function Gate2({ children, inline }: { children?: ReactNode; inline?: boolean }) {
  return <span title={GATE2_TIP} data-gate2="true" style={{ color: TOKENS.text[3], cursor: 'help', borderBottom: inline ? `1px dotted ${TOKENS.text[3]}` : undefined }}>{children ?? '—'}</span>
}

const DEC_TIP = 'Scanner decision. MANUAL = the scanner routed it to manual review (Entry Desk only) — not a validated setup. '
  + 'Ready / not ready is the shared 5-fact verdict below (the same one the Active Trader alert prints as "Ready: YES/NO").'

/** The catalyst as the SHARED verdict states it: a headline is the catalyst only when source-verified. */
function CatalystBadge({ r }: { r: Opportunity }) {
  const v = r.catalystVerdict
  if (v.status === 'VERIFIED') return null
  const tone: Tone = v.status === 'HERMES_FOUND' ? 'warning' : v.status === 'UNVERIFIED_HEADLINE' ? 'warning' : 'neutral'
  return (
    <span data-testid="ta-catalyst-verdict" data-status={v.status} title={`${v.label}${v.reason ? ` — ${v.reason}` : ''}${v.served ? '' : ' (shared verdict not served for this row; read from the scan flag)'}`}
      style={{ flex: '0 0 auto', fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.04em', textTransform: 'uppercase', padding: '1px 5px', borderRadius: RADIUS.sm,
        color: tc(tone), border: `1px solid ${tone === 'neutral' ? TOKENS.border : toneVars(tone).border}`, cursor: 'help' }}>
      {v.status === 'UNVERIFIED_HEADLINE' ? 'unverified' : v.status === 'HERMES_FOUND' ? 'Hermes only' : v.status === 'NONE_FOUND' ? 'none found' : 'not checked'}
    </span>
  )
}

function catalystText(r: Opportunity): string {
  return r.catalystVerdict.text ?? (r.catalystVerdict.status === 'NONE_FOUND' ? 'No catalyst found (scan + Hermes)' : 'No catalyst found by the scan')
}

function Chip({ c }: { c: L2Chip }) {
  const lit = c.on === true
  const tone: Tone = c.on == null ? 'neutral' : lit ? (c.warn ? 'danger' : 'success') : 'neutral'
  const v = toneVars(tone)
  return (
    <div title={c.tip} data-testid={`l2-${c.key}`} data-on={String(c.on)}
      style={{ display: 'flex', justifyContent: 'space-between', gap: 6, alignItems: 'center', padding: '5px 8px', borderRadius: RADIUS.sm, minWidth: 0,
        background: lit ? v.bg : TOKENS.bg[2], border: `1px solid ${lit ? v.border : TOKENS.borderSubtle}` }}>
      <span style={{ fontSize: TYPE.sm, color: TOKENS.text[1], whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.on == null ? '○' : lit ? '●' : '○'} {c.label}</span>
      <span style={{ ...mono, fontSize: TYPE.sm, color: c.on == null ? TOKENS.text[3] : lit ? v.color : TOKENS.text[2] }}>{c.value}</span>
    </div>
  )
}

export default function TradeAiOpportunities({ tradeAi, error, loading, classic }: { tradeAi: any; error?: unknown; loading?: boolean; classic?: ReactNode }) {
  const [f, setF] = useState<Filters>(NO_FILTERS)
  const [sort, setSort] = useState<SortKey>('score')
  const [view, setView] = useState<'table' | 'cards'>('table')
  const [sel, setSel] = useState<string | null>(null)
  const [drawer, setDrawer] = useState<{ momentum: boolean; classic: boolean }>({ momentum: false, classic: false })
  // Ticks the run-age chip between scanner refreshes so "4 min ago" does not freeze.
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000)
    return () => window.clearInterval(id)
  }, [])
  const { data: alerts } = useApi<any>('/api/v3/active-trader/alerts?limit=300', 60_000, { enabled: !!tradeAi })
  const { data: candidates } = useApi<any>('/api/v2/trade-ai/candidates', 120_000, { enabled: !!tradeAi && !drawer.momentum })

  const all = useMemo(() => (Array.isArray(tradeAi?.tickers) ? tradeAi.tickers : []).map(toOpportunity) as Opportunity[], [tradeAi])
  const rows = useMemo(() => sortOpportunities(applyFilters(all, f), sort), [all, f, sort])
  const tiles = useMemo(() => buildTiles(all, f), [all, f])
  const chips = filterChips(f)
  const hasGate2 = all.some(r => r.catalystGrade != null || r.act != null)
  const selected = all.find(r => r.sym === sel) ?? rows[0] ?? null
  const patch = (p: Partial<Filters>) => setF(prev => ({ ...prev, ...p }))

  if (!tradeAi) {
    return (
      <div style={{ ...panel, padding: 16, borderColor: error ? toneVars('danger').border : TOKENS.border }} data-testid="trade-ai-opportunities">
        <div style={{ fontSize: TYPE.md, fontWeight: 700, color: TOKENS.text[0], marginBottom: 6 }}>Opportunities</div>
        <div role={error ? 'alert' : undefined} style={{ fontSize: TYPE.base, color: error ? toneVars('danger').color : TOKENS.text[2] }}>
          {error ? 'Scanner data temporarily unavailable — /api/v2/trade-ai/scanner did not respond (auto-retrying every 60 s). This is an API or data-availability issue, not an empty scan.'
            : loading ? 'Loading the latest scanner run…' : 'The scanner returned an empty payload.'}
        </div>
      </div>
    )
  }

  const summary = tradeAi?.setup_run_summary ?? {}
  const fresh = tradeAiSurfaceFreshness(tradeAi)
  // Same run-health facts the header strip renders (one classifier, lib/runHealth): the chip below carries
  // data-run-* so e2e/run_health_agreement.spec.ts can prove the header and this page state the same run.
  const health = String(tradeAi?.run_health_status || 'UNKNOWN')
  const healthTier = classifyRunHealth(tradeAi?.run_health_status)
  const healthCodes = runHealthReasonCodes(tradeAi)
  const healthFloor = Number(tradeAi?.expected_min_symbols)
  const scannedN = tradeAi?.current_run_scanned ?? tradeAi?.latest_run_symbols_scanned ?? tradeAi?.ticker_count
  const scanned = summary.scanned_count ?? scannedN
  // Slot 0700 is re-run through the morning; the page used to print "7:00 AM scan" over data
  // from the 08:52 attempt. Lead with the run's finished time (ET) and age instead.
  const slot = summary.run_label || tradeAi?.latest_run_label || tradeAi?.run_label
  const age = payloadRunAge({ ...tradeAi, latest_run_timestamp: tradeAi?.latest_run_timestamp ?? summary.run_timestamp }, slot, now)
  const ageColor = age.tone === 'bad' ? toneVars('danger').color : age.tone === 'warn' ? toneVars('warning').color : TOKENS.text[1]
  const latestPhrase = latestRunPhrase(summary)
  const l2For = (sym: string) => l2View(latestAlertFor(alerts, sym))
  const l2Short = (sym: string) => l2Brief(latestAlertFor(alerts, sym))
  const cands: any[] = Array.isArray(candidates?.candidates) ? candidates.candidates : []
  const conflicts = cands.filter(c => (c?.conflicts ?? []).length > 0).length
  const gaps = Object.values(candidates?.source_metadata ?? {}).filter((m: any) => m?.stale || (m?.status && m.status !== 'OK' && m.status !== 'ok')).length

  const sortBtn = (k: SortKey, label: string, enabled = true): ReactNode => (
    <button type="button" disabled={!enabled} onClick={() => setSort(k)} title={enabled ? `Sort by ${label}` : GATE2_TIP} data-testid={`ta-sort-${k}`}
      style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: enabled ? 'pointer' : 'help', font: 'inherit', letterSpacing: 'inherit', textTransform: 'inherit',
        color: sort === k ? TOKENS.text[0] : TOKENS.text[2], minHeight: 28, opacity: enabled ? 1 : 0.7 }}>
      {label} {sort === k ? '▾' : ''}
    </button>
  )

  const catalystLine = (r: Opportunity) => (
    <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', fontSize: TYPE.sm }}>
      <span style={{ fontSize: TYPE.xs, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em', color: TOKENS.text[1], background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: '1px 5px' }}>
        {r.catalystType ?? <Gate2>type —</Gate2>}
      </span>
      <span aria-label={r.catalystGrade != null ? `Catalyst grade ${r.catalystGrade} of 5` : 'No catalyst grade yet'}
        style={{ letterSpacing: 1, color: r.catalystGrade != null ? toneVars('warning').color : TOKENS.text[3] }}>
        {r.catalystGrade != null ? stars(r.catalystGrade) : <Gate2>★ —</Gate2>}
      </span>
      <span style={{ color: r.validation ? tc(r.validationOk ? 'success' : 'danger') : TOKENS.text[3] }}>{r.validation ?? <Gate2>validation —</Gate2>}</span>
    </span>
  )

  return (
    <div data-testid="trade-ai-opportunities" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: TYPE.lg + 4, fontWeight: 700, color: TOKENS.text[0] }}>Opportunities</h2>
          <div data-testid="ta-run-line" style={{ fontSize: TYPE.md - 1, color: TOKENS.text[2], display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 6, rowGap: 2 }}>
            <span data-testid="ta-run-age" data-run-age-min={age.ageMin != null ? String(age.ageMin) : ''} data-run-age-tone={age.tone} data-run-age-source={age.source} title={age.tip}
              style={{ color: ageColor, fontWeight: 800, fontSize: TYPE.md + 1 }}>
              {age.tone === 'bad' ? '▲ ' : ''}{age.source === 'scan' ? 'Data: ' : 'Latest run '}{age.label}
            </span>
            <span>· {summary.run_date ?? tradeAi?.run_date ?? '—'}{age.slotLabel ? ` · ${age.slotLabel}` : ''}</span>
            <span>·{' '}
            <span data-testid="trade-ai-run-health-chip" data-run-id={tradeAi?.run_id ?? ''}
              data-run-scanned={scannedN != null ? String(scannedN) : ''}
              data-run-floor={healthFloor && isFinite(healthFloor) ? String(healthFloor) : ''}
              data-run-health={healthTier} data-run-integrity={summary.count_integrity ?? ''}
              title={healthCodes.length ? healthCodes.join(', ') : health}
              style={{ color: runHealthChipColor(healthTier), fontWeight: 700 }}>{health}</span></span>
            {fresh.stale && <span data-testid="trade-ai-stale-session" style={{ color: toneVars('warning').color, fontWeight: 700 }}>· STALE SESSION</span>}
          </div>
          <div data-testid="ta-population-line" style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}
            title="The header SETUPS · LATEST RUN tile counts the latest run. The tiles below count today's whole universe. The two differ by design.">
            <span data-testid="ta-latest-run-tally">{latestPhrase ?? `latest run: ${scanned ?? '—'} scanned`}</span>
            {' '}· <span data-testid="ta-universe-count">universe: {all.length} rows today (all runs) — the tiles below count this</span>
            {' '}· awareness only, verdicts never grant approval
          </div>
        </div>
      </div>

      <div role="group" aria-label="Opportunity filters" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
        {tiles.map(t => (
          <button key={t.key} type="button" data-testid={`ta-tile-${t.key}`} aria-pressed={t.active} disabled={t.disabled} title={t.tip}
            onClick={() => patch(t.patch(t.active))}
            style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start', textAlign: 'left', cursor: t.disabled ? 'help' : 'pointer', borderRadius: RADIUS.md,
              padding: '12px 14px', minHeight: 88, color: TOKENS.text[0], fontFamily: 'inherit',
              background: t.active ? toneVars('info').bg : TOKENS.bg[1], border: `1px solid ${t.active ? tc(t.tone) : TOKENS.border}`, opacity: t.disabled ? 0.75 : 1 }}>
            <span style={{ ...mono, fontSize: TYPE.xl + 2, fontWeight: 600, color: t.value == null ? TOKENS.text[3] : tc(t.tone) }}>{t.value == null ? '—' : t.value}</span>
            <span style={{ fontSize: TYPE.base, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[1] }}>{t.label}</span>
            <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{t.hint}</span>
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, minHeight: 36 }}>
        <span style={{ fontSize: TYPE.base, color: TOKENS.text[2], fontWeight: 700 }}>Filters</span>
        {chips.length === 0 && <span style={{ fontSize: TYPE.base, color: TOKENS.text[3] }}>none — click any tile, float, RVOL or sector to filter</span>}
        {chips.map(c => (
          <button key={c.label} type="button" onClick={() => patch(c.clear)} aria-label={`Remove filter ${c.label}`} data-testid="ta-filter-chip"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: toneVars('info').bg, border: `1px solid ${toneVars('info').border}`, color: TOKENS.text[0],
              borderRadius: RADIUS.pill, padding: '6px 12px', fontSize: TYPE.base, cursor: 'pointer', minHeight: 32, fontFamily: 'inherit' }}>
            {c.label}<span aria-hidden="true" style={{ color: toneVars('info').color }}>✕</span>
          </button>
        ))}
        {chips.length > 0 && <button type="button" onClick={() => setF(NO_FILTERS)} style={{ background: 'none', border: 'none', color: TOKENS.info, fontSize: TYPE.base, cursor: 'pointer', padding: '6px 4px', fontFamily: 'inherit' }}>Clear all</button>}
        <span style={{ flex: 1 }} />
        <div role="group" aria-label="View" style={{ display: 'inline-flex', border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, overflow: 'hidden' }}>
          {(['table', 'cards'] as const).map(v => (
            <button key={v} type="button" aria-pressed={view === v} data-testid={`ta-view-${v}`} onClick={() => setView(v)}
              style={{ background: view === v ? toneVars('info').bg : 'transparent', color: view === v ? TOKENS.text[0] : TOKENS.text[2], border: 'none', padding: '8px 14px',
                fontSize: TYPE.md - 1, fontWeight: 700, cursor: 'pointer', minHeight: 36, fontFamily: 'inherit' }}>{v === 'table' ? 'Table' : 'Cards'}</button>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' }}>
        <div style={{ flex: '999 1 680px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {view === 'table' ? (
            <div style={{ ...panel, overflowX: 'auto' }}>
              <div style={{ minWidth: 720 }}>
                <div style={{ display: 'grid', gridTemplateColumns: COLS, gap: 8, padding: '8px 12px', borderBottom: `1px solid ${TOKENS.border}`, ...caps, alignItems: 'center' }}>
                  <span>Symbol</span>{sortBtn('float', 'Float')}<span>Vol</span>{sortBtn('rvol', 'RVOL')}{sortBtn('chg', 'Chg')}
                  {sortBtn('grade', 'Catalyst · grade · validation', hasGate2)}{sortBtn('act', 'Act', hasGate2)}
                  <span>{sortBtn('score', 'Decision · L2')}</span>
                </div>
                {rows.length === 0 && <div style={{ padding: '24px 14px', color: TOKENS.text[2] }}>No rows match these filters.</div>}
                {rows.map(r => {
                  const isSel = selected?.sym === r.sym
                  const band = floatBand(r.float)
                  return (
                    <div key={r.sym} data-testid="ta-row" data-symbol={r.sym}
                      style={{ display: 'grid', gridTemplateColumns: COLS, gap: 8, padding: '6px 12px', borderBottom: `1px solid ${TOKENS.borderSubtle}`, alignItems: 'center',
                        background: isSel ? toneVars('info').bg : undefined, borderLeft: `3px solid ${isSel ? toneVars('info').color : 'transparent'}` }}>
                      <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                        <button type="button" onClick={() => setSel(r.sym)} aria-label={`Show analysis for ${r.sym}`}
                          style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', color: TOKENS.text[0], ...mono, fontWeight: 700, fontSize: TYPE.md - 1, minHeight: 24 }}>{r.sym}</button>
                        {r.sector && <button type="button" onClick={() => patch({ sector: r.sector })} title="Filter to this sector"
                          style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', fontSize: TYPE.xs, color: TOKENS.text[2], whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontFamily: 'inherit' }}>{r.sector}</button>}
                      </span>
                      <button type="button" onClick={() => band && patch({ floatMax: band })} title={band ? `Filter to float < ${band}M` : 'No float band'}
                        style={{ background: r.float != null && r.float < 5 ? toneVars('info').bg : 'none', border: 'none', borderRadius: RADIUS.sm, padding: '3px 5px', textAlign: 'left',
                          cursor: band ? 'pointer' : 'default', ...mono, fontWeight: 600, fontSize: TYPE.base, minHeight: 28, color: r.float == null ? TOKENS.text[3] : r.float < 5 ? toneVars('info').color : r.float < 20 ? TOKENS.text[0] : TOKENS.text[2] }}>{floatText(r.float)}</button>
                      <span style={{ ...mono, fontSize: TYPE.base, color: TOKENS.text[1] }}>{volText(r.volume)}</span>
                      <button type="button" onClick={() => patch({ rvolMin: 10 })} title="Filter RVOL ≥ 10×"
                        style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', ...mono, fontSize: TYPE.base, minHeight: 28, color: (r.rvol ?? 0) >= 10 ? toneVars('info').color : TOKENS.text[1] }}>{rvolText(r.rvol)}</button>
                      <span style={{ ...mono, fontSize: TYPE.base, color: r.chg == null ? TOKENS.text[3] : r.chg > 0 ? toneVars('success').color : r.chg < 0 ? toneVars('danger').color : TOKENS.text[2] }}>{chgText(r.chg)}</span>
                      <button type="button" onClick={() => setSel(r.sym)}
                        style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', color: TOKENS.text[0], display: 'flex', flexDirection: 'column', gap: 3, minHeight: 32, minWidth: 0, fontFamily: 'inherit' }}>
                        <span style={{ display: 'flex', gap: 6, alignItems: 'center', minWidth: 0, maxWidth: '100%' }}>
                          <CatalystBadge r={r} />
                          <span title={`${catalystText(r)}${r.catalystVerdict.reason ? `\n${r.catalystVerdict.label} — ${r.catalystVerdict.reason}` : ''}`} style={{ fontSize: TYPE.base, lineHeight: 1.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0, color: r.catalystVerdict.status === 'VERIFIED' ? TOKENS.text[0] : TOKENS.text[2], fontStyle: r.catalystVerdict.status === 'UNVERIFIED_HEADLINE' ? 'italic' : undefined }}>{catalystText(r)}</span>
                        </span>
                        {catalystLine(r)}
                      </button>
                      <span style={{ ...mono, fontWeight: 600, fontSize: TYPE.md - 1 }}>{r.act != null ? r.act : <Gate2 />}</span>
                      <span style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start', minWidth: 0 }}>
                        <span style={pill(r.decision)} title={`Scanner decision ${r.decisionRaw}${r.score != null ? ` · score ${r.score}` : ''}${r.setupGrade ? ` · setup grade ${r.setupGrade}` : ''}\n${DEC_TIP}${r.readiness ? `\n${r.readiness.summary}` : ''}`}>{DEC_LABEL[r.decision]}</span>
                        {r.readiness && <span data-testid="ta-ready" data-ready={r.readiness.status} title={r.readiness.summary} style={{ fontSize: TYPE.xs, fontWeight: 700, color: r.readiness.status === 'READY' ? tc('success') : TOKENS.text[2] }}>{r.readiness.status === 'READY' ? 'ready' : `not ready · ${r.readiness.passed ?? '—'}/${r.readiness.required}`}</span>}
                        <span data-testid="ta-l2-brief" style={{ fontSize: TYPE.xs, color: TOKENS.text[2], whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 108 }} title={l2Short(r.sym).tip}>{l2Short(r.sym).text}</span>
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }} data-testid="ta-cards">
              {rows.length === 0 && <div style={{ color: TOKENS.text[2] }}>No rows match these filters.</div>}
              {rows.map(r => (
                <div key={r.sym} data-testid="ta-card" style={{ ...panel, borderColor: selected?.sym === r.sym ? toneVars('info').color : TOKENS.border, padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span style={{ ...mono, fontWeight: 700, fontSize: TYPE.lg + 2 }}>{r.sym}</span>
                      <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{r.sector ?? '—'}</span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                      <span style={pill(r.decision)}>{DEC_LABEL[r.decision]}</span>
                      <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }} title={l2Short(r.sym).tip}>{l2Short(r.sym).text}</span>
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
                    {([['Float', floatText(r.float)], ['Vol', volText(r.volume)], ['RVOL', rvolText(r.rvol)]] as const).map(([k, v]) => (
                      <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}><span style={caps}>{k}</span><span style={{ ...mono, fontSize: TYPE.md + 2, fontWeight: 600 }}>{v}</span></div>
                    ))}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}><CatalystBadge r={r} /><span style={{ fontSize: TYPE.md, lineHeight: 1.4, color: r.catalystVerdict.status === 'VERIFIED' ? TOKENS.text[0] : TOKENS.text[2] }}>{catalystText(r)}</span></span>
                    {catalystLine(r)}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, fontSize: TYPE.base }}>
                    <span style={{ color: TOKENS.text[2] }}>Scanner score {r.score ?? '—'}{r.setupGrade ? ` · grade ${r.setupGrade}` : ''}</span>
                    <span style={mono}>Act <b>{r.act ?? <Gate2 />}</b></span>
                  </div>
                  <button type="button" onClick={() => setSel(r.sym)} style={{ background: toneVars('info').bg, border: `1px solid ${toneVars('info').border}`, color: TOKENS.text[0], borderRadius: RADIUS.sm, padding: 10, fontSize: TYPE.md - 1, cursor: 'pointer', minHeight: 44, fontFamily: 'inherit' }}>Open AI analysis</button>
                </div>
              ))}
            </div>
          )}

          <div style={panel} data-testid="ta-momentum-drawer">
            <button type="button" aria-expanded={drawer.momentum} onClick={() => setDrawer(d => ({ ...d, momentum: !d.momentum }))}
              style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, background: 'none', border: 'none', color: TOKENS.text[0], padding: 14, cursor: 'pointer', fontSize: TYPE.md, minHeight: 48, textAlign: 'left', fontFamily: 'inherit' }}>
              <span><b>Shared Momentum</b> <span style={{ color: TOKENS.text[2] }}>· {candidates ? `${candidates.candidate_count ?? cands.length} candidates · ${conflicts} conflict${conflicts === 1 ? '' : 's'}${gaps ? ` · ${gaps} source gap${gaps === 1 ? '' : 's'}` : ''}` : 'Trade AI and Active Trader on one record'}</span></span>
              <span aria-hidden="true" style={{ color: TOKENS.info }}>{drawer.momentum ? 'Hide ▴' : 'Show ▾'}</span>
            </button>
            {drawer.momentum && <div style={{ borderTop: `1px solid ${TOKENS.border}`, padding: 14 }}><SharedMomentumCandidates /></div>}
          </div>

          {classic != null && (
            <div style={panel} data-testid="ta-classic-drawer">
              <button type="button" aria-expanded={drawer.classic} onClick={() => setDrawer(d => ({ ...d, classic: !d.classic }))}
                style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, background: 'none', border: 'none', color: TOKENS.text[0], padding: 14, cursor: 'pointer', fontSize: TYPE.md, minHeight: 48, textAlign: 'left', fontFamily: 'inherit' }}>
                <span><b>Scanner tools</b> <span style={{ color: TOKENS.text[2] }}>· run health, run history, sector mix, Thinkorswim copy, Warrior audit</span></span>
                <span aria-hidden="true" style={{ color: TOKENS.info }}>{drawer.classic ? 'Hide ▴' : 'Show ▾'}</span>
              </button>
              {drawer.classic && <div style={{ borderTop: `1px solid ${TOKENS.border}`, padding: 14 }}>{classic}</div>}
            </div>
          )}
        </div>

        <aside aria-label="Catalyst analysis" data-testid="ta-analysis" style={{ ...panel, flex: '1 1 320px', maxWidth: 440, minWidth: 0, padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {!selected && <div style={{ color: TOKENS.text[2], fontSize: TYPE.md - 1 }}>Click a symbol or catalyst to see the AI analysis.</div>}
          {selected && (() => {
            const r = selected
            const l2 = l2For(r.sym)
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ ...mono, fontWeight: 700, fontSize: TYPE.xl - 2 }}>{r.sym}</span>
                  <span style={pill(r.decision)}>{DEC_LABEL[r.decision]}</span>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <CatalystBadge r={r} />
                  <span style={{ fontSize: TYPE.md + 1, lineHeight: 1.4, fontWeight: 600, color: r.catalystVerdict.status === 'VERIFIED' ? TOKENS.text[0] : TOKENS.text[2] }}>{catalystText(r)}</span>
                </div>
                {r.catalystVerdict.reason && <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2], lineHeight: 1.4 }} data-testid="ta-catalyst-reason">{r.catalystVerdict.label} — {r.catalystVerdict.reason}</div>}
                {catalystLine(r)}
                <div data-testid="ta-readiness" data-ready={r.readiness?.status ?? 'UNKNOWN'} style={{ background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={caps}>Driven by · ready? <span style={{ textTransform: 'none', letterSpacing: 0, fontWeight: 500 }}>(same verdict as the Active Trader alert)</span></span>
                  {!r.readiness && <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>Not served for this row — the shared 5-fact verdict is attached to GO / WAIT / manual-review rows.</span>}
                  {r.readiness && (
                    <>
                      {r.readiness.drivenBy.map(d => (
                        <div key={d.id} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, fontSize: TYPE.base }}>
                          <span style={{ color: TOKENS.text[1] }}>{d.label} <span style={{ ...mono, color: TOKENS.text[0] }}>{d.valueText}</span> <span style={{ color: TOKENS.text[3] }}>({d.rule})</span></span>
                          <span style={{ fontWeight: 800, color: d.status === 'PASSED' ? tc('success') : d.status === 'FAILED' ? tc('danger') : TOKENS.text[3] }}>{d.status === 'PASSED' ? '✓' : d.status === 'FAILED' ? '✗' : '?'}</span>
                        </div>
                      ))}
                      <span style={{ fontSize: TYPE.md - 1, fontWeight: 700, color: r.readiness.status === 'READY' ? tc('success') : tc('warning') }}>
                        {r.readiness.status === 'READY' ? 'Ready' : 'Not ready'} — {r.readiness.passed ?? '—'}/{r.readiness.required} source facts
                      </span>
                      {r.readiness.missing.map(m => <span key={m} style={{ fontSize: TYPE.base, color: TOKENS.text[1], lineHeight: 1.4 }}>Missing: {m}</span>)}
                      {r.readiness.blockers.length > 0 && <span style={{ fontSize: TYPE.base, color: TOKENS.text[1] }}>Active Trader veto: {r.readiness.blockers.map(b => b.replace(/_/g, ' ').toLowerCase()).join(', ')}</span>}
                    </>
                  )}
                </div>
                <div style={{ background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }} data-testid="ta-verdict">
                  <span style={caps}>AI verdict · confidence <Gate2 inline /></span>
                  <span style={{ fontSize: TYPE.md, lineHeight: 1.5, color: TOKENS.text[2] }}><Gate2 inline>Not computed yet — arrives with the CIO prospect record (Gate 2).</Gate2></span>
                  {r.critic && (
                    <span style={{ fontSize: TYPE.base, color: TOKENS.text[1], lineHeight: 1.45 }} data-testid="ta-critic">
                      Scanner critic (existing): <b>{r.critic.verdict}</b>{r.critic.confidence != null ? ` · confidence ${r.critic.confidence}` : ''}{r.critic.reasoning ? ` — ${r.critic.reasoning}` : ''}
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <span style={caps}>Checks</span>
                  {['Real event (primary source found)?', 'Material to valuation?', 'Promotional language?', 'Recycled / old news?', 'Type historically moves traders?'].map(q => (
                    <div key={q} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 10, fontSize: TYPE.md - 1, paddingBottom: 6, borderBottom: `1px solid ${TOKENS.borderSubtle}` }}>
                      <span style={{ color: TOKENS.text[1] }}>{q}</span><Gate2 />
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: TYPE.base, color: TOKENS.text[1] }} data-testid="ta-scanner-facts">
                  <span style={caps}>Scanner facts</span>
                  <span>Score {r.score ?? '—'}{r.setupGrade ? ` · setup grade ${r.setupGrade}` : ''} · decision {r.decisionRaw}</span>
                  <span>Catalyst: {r.catalystVerdict.label}{r.catalystConfidence != null ? ` · scan confidence ${r.catalystConfidence}` : ''}{r.catalystSource ? ` · ${r.catalystSource}` : ''}</span>
                  {r.pill && <span>{r.pill}{r.subtitle ? ` — ${r.subtitle}` : ''}</span>}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, borderTop: `1px solid ${TOKENS.border}`, paddingTop: 12 }} data-testid="ta-l2">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
                    <span style={caps}>Level 2 · tape</span>
                    <span style={{ fontSize: TYPE.sm, color: l2.stale ? toneVars('warning').color : TOKENS.text[2] }}>{l2.feed}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span data-testid="ta-l2-state" title="The Active Trader decision for this symbol (its veto can come from VWAP, gap, volume or tape, not only the book)" style={{ fontSize: TYPE.md - 1, fontWeight: 800, color: l2.watched ? toneVars('warning').color : TOKENS.text[2] }}>{l2.watched ? `AT ${l2.state.toLowerCase()}` : l2.state}</span>
                    <span style={{ fontSize: TYPE.base, color: TOKENS.text[1] }}>{l2.summary}</span>
                  </div>
                  <span style={{ ...caps, color: TOKENS.text[3] }}>Entry signals</span>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 6 }}>{l2.entry.map(c => <Chip key={c.key} c={c} />)}</div>
                  <span style={{ ...caps, color: TOKENS.text[3] }}>Exit / warning signals</span>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 6 }}>{l2.exit.map(c => <Chip key={c.key} c={c} />)}</div>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: TYPE.base }}>
                  <Link to={`/watch/intelligence/${encodeURIComponent(r.sym)}`} style={{ color: TOKENS.info }}>Dossier →</Link>
                  {r.decision === 'MANUAL' && <Link to={`/trading?tab=Proposals&section=path-a&symbol=${encodeURIComponent(r.sym)}`} style={{ color: TOKENS.info }}>Entry Desk (Path A) →</Link>}
                </div>
                <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2], lineHeight: 1.45 }}>
                  Catalyst type, grade, validation, the action score and the checks arrive with the CIO prospect record (Gate 2). The decision is the scanner's, as served; it never grants approval.
                </div>
              </div>
            )
          })()}
        </aside>
      </div>
    </div>
  )
}
