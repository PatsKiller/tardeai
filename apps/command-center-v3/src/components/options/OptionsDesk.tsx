/** Options desk (2026-10-22) — the operator-approved Gate 3 layout.
 *
 *  Truth header → data-freshness chips → 7-step lifecycle row → one idea table (accounts merged)
 *  + detail panel → your plans → collapsed drawers. Every term and number carries a glossary
 *  tooltip (src/lib/optionsGlossary.ts).
 *
 *  HARD BOUNDARY: this view never POSTs to an order, preflight, 2FA or broker route. Its next-step
 *  controls only call the hub's existing flows: the Strategy Proposal review modal, the existing
 *  quote-validation route, and the read-only chain drill.
 */
import { useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { FONT, RADIUS, TOKENS, TYPE, toneVars } from '../../lib/designTokens'
import { HOW_THIS_PAGE_WORKS } from '../../lib/optionsGlossary'
import {
  buildIdeas, buildPlans, freshnessChips, laneCounts, LANES, planIdeas, strategyGlossaryKey, truthSentence,
  type Idea, type LaneKey, type NextStep, type Tone,
} from '../../lib/optionsDeskModel'
import ManualExecutionLog from '../ManualExecutionLog'
import { ControlTip, Missing, Term } from './GlossaryTip'

type Any = Record<string, any>

export type OptionsDeskProps = {
  proposals: Any | null
  proposalsError?: string | null
  loading?: boolean
  execStatus: Any | null
  intentFeed: Any | null
  openPositions: Any | null
  validation: Any | null
  liveEligible: number
  onReview: (proposalId: string) => void
  onStage: (source: { directive_id?: number | string; play?: string; contract_guid?: string }) => void
  onValidate: (proposalId: string) => Promise<string>
  onChain: (proposalId: string) => void
  onNewPlan: () => void
  onOpenView: (view: 'Proposals' | 'All coverage' | 'Lifecycle' | 'Open Options') => void
}

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }
const mono: CSSProperties = { fontFamily: FONT.mono, fontVariantNumeric: 'tabular-nums' }
const caps: CSSProperties = { fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2] }
const COLS = '72px 160px minmax(0, 1fr) 104px 200px 140px'
const LANE_TONE: Record<LaneKey, Tone> = { scan: 'neutral', research: 'warning', data: 'warning', plan: 'info', you: 'danger', place: 'success', open: 'info' }
const MARK_TONE: Record<string, Tone> = { '✓': 'success', '✗': 'danger', '○': 'neutral' }
const toneColor = (t: Tone) => (t === 'neutral' ? TOKENS.text[2] : toneVars(t).color)

function chipStyle(t: Tone): CSSProperties {
  const v = toneVars(t)
  return { fontSize: TYPE.base, borderRadius: RADIUS.pill, padding: '5px 10px', border: `1px solid ${v.border}`, background: v.bg, color: TOKENS.text[0] }
}

function btn(primary: boolean, danger = false): CSSProperties {
  const v = toneVars(danger ? 'danger' : 'info')
  return {
    whiteSpace: 'nowrap', fontSize: TYPE.base, fontWeight: 700, padding: '8px 10px', borderRadius: RADIUS.sm, minHeight: 36,
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontFamily: 'inherit',
    background: primary ? v.bg : 'transparent', border: `1px solid ${v.border}`, color: primary ? v.color : TOKENS.text[1],
  }
}

function NextControl({ step, onReview, onStage, onValidate, onChain, danger }: {
  step: NextStep; danger: boolean
  onReview: OptionsDeskProps['onReview']; onStage: OptionsDeskProps['onStage']; onValidate: OptionsDeskProps['onValidate']; onChain: OptionsDeskProps['onChain']
}) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  if (step.kind === 'none') {
    return <button type="button" disabled aria-disabled="true" title={step.reason} style={{ ...btn(false), cursor: 'not-allowed', opacity: 0.55 }}>No step here</button>
  }
  const run = async () => {
    if (step.kind === 'review') onReview(step.proposalId)
    else if (step.kind === 'stage') onStage(step.source)
    else if (step.kind === 'chain') onChain(step.proposalId)
    else if (step.kind === 'validate') {
      setBusy(true); setMsg(null)
      try { setMsg(await onValidate(step.proposalId)) } finally { setBusy(false) }
    }
  }
  const what = step.kind === 'review' ? 'Opens the existing strategy review. Nothing is placed from it without your preflight and per-order 2FA.'
    : step.kind === 'stage' ? 'Opens the existing strategy review to pick an account and size for this plan match. Nothing is placed.'
      : step.kind === 'chain' ? 'Opens the read-only option chain so you can pick a more liquid strike or expiry.'
        : 'Re-reads this exact contract from the live chain (read-only market data) and recomputes the economics. No order is sent.'
  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
      <button type="button" onClick={e => { e.stopPropagation(); void run() }} disabled={busy} title={what}
        data-testid="options-desk-next-step" style={btn(true, danger)}>
        {busy ? 'Working…' : step.label}
      </button>
      {msg && <span role="status" style={{ fontSize: TYPE.xs, color: TOKENS.text[2], maxWidth: 160 }}>{msg}</span>}
    </span>
  )
}

function Drawer({ title, summary, children, testId }: { title: string; summary: ReactNode; children: ReactNode; testId: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={panel} data-testid={testId}>
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
        style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, background: 'none', border: 'none',
          color: TOKENS.text[0], padding: '12px 16px', cursor: 'pointer', fontSize: TYPE.md, minHeight: 46, textAlign: 'left', fontFamily: 'inherit' }}>
        <span><b>{title}</b> <span style={{ color: TOKENS.text[2] }}>· {summary}</span></span>
        <span aria-hidden="true" style={{ color: TOKENS.info, whiteSpace: 'nowrap' }}>{open ? 'Hide ▴' : 'Show ▾'}</span>
      </button>
      {open && <div style={{ borderTop: `1px solid ${TOKENS.border}`, padding: '12px 16px', fontSize: TYPE.base, lineHeight: 1.6, color: TOKENS.text[1] }}>{children}</div>}
    </div>
  )
}

export default function OptionsDesk(props: OptionsDeskProps) {
  const { proposals, execStatus, intentFeed, openPositions, validation, liveEligible } = props
  const [lane, setLane] = useState<LaneKey | null>(null)
  const [selId, setSelId] = useState<string | null>(null)
  const [help, setHelp] = useState(false)
  const [fStrategy, setFStrategy] = useState('')
  const [fSymbol, setFSymbol] = useState('')
  const [fTier, setFTier] = useState('')

  const p = proposals && typeof proposals === 'object' ? (proposals.data && !Array.isArray(proposals.data) ? proposals.data : proposals) : null
  const raw: Any[] = Array.isArray(p?.proposals) ? p.proposals : []
  const now = useMemo(() => new Date(), [proposals])
  const ideas = useMemo(() => buildIdeas(raw, now), [raw, now])
  const plans = useMemo(() => buildPlans(intentFeed, ideas, now), [intentFeed, ideas, now])
  const allRows = useMemo(() => [...ideas, ...planIdeas(plans)], [ideas, plans])
  const counts = useMemo(() => laneCounts(proposals, ideas, intentFeed, openPositions), [proposals, ideas, intentFeed, openPositions])
  const chips = useMemo(() => freshnessChips(proposals, raw, now), [proposals, raw, now])
  const truth = truthSentence(proposals, execStatus, liveEligible)

  const filtered = allRows.filter(i => (!lane || i.lane === lane)
    && (!fStrategy || i.strategy === fStrategy) && (!fTier || i.tier === fTier)
    && (!fSymbol || i.symbol.includes(fSymbol.trim().toUpperCase())))
  const sel: Idea | undefined = allRows.find(i => i.id === selId) || filtered.find(i => i.lane === 'you') || filtered[0]
  const laneMeta = lane ? LANES.find(l => l.key === lane) : null
  const filtersOn = !!(fStrategy || fSymbol || fTier)

  const income = (p?.income_screen?.reasons || {}) as Record<string, { count: number; symbols: string[] }>
  const dropped = Array.isArray(p?.entry_directional_dropped) ? p.entry_directional_dropped as Array<{ symbol: string; reason: string }> : []
  const REASON: Record<string, string> = {
    NO_EXECUTABLE_CREDIT: 'no executable credit', NO_LIQUID_CONTRACT: 'no liquid contract', PREMIUM_BELOW_FLOOR: 'premium below floor',
    PRICE_BELOW_FLOOR: 'stock price below floor', NO_CHAIN: 'no listed chain', IV_UNKNOWN: 'IV unknown', THESIS_ABANDONED: 'archived (thesis not completed in time)',
  }
  const notBuilt = Object.entries(income).map(([k, v]) => `${v.count} ${REASON[k] || k.toLowerCase().replace(/_/g, ' ')} (${(v.symbols || []).join(', ')})`)
  if (dropped.length) notBuilt.push(`${dropped.length} entry ideas below the edge floor or without data (${dropped.map(d => d.symbol).join(', ')})`)
  const pathB: Any[] = Array.isArray(validation?.desk_path_b_strategies) ? validation.desk_path_b_strategies.filter((s: Any) => s?.ok)
    : Array.isArray(validation?.data?.desk_path_b_strategies) ? validation.data.desk_path_b_strategies.filter((s: Any) => s?.ok) : []

  return (
    <div data-testid="options-desk" style={{ display: 'flex', flexDirection: 'column', gap: 14, color: TOKENS.text[0], fontSize: TYPE.md }}>
      {/* 1 · Truth header */}
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 900 }}>
          <div style={{ fontSize: TYPE.base, color: TOKENS.text[1] }} data-testid="options-desk-truth">
            <Term k="exec.state">Execution</Term>: {truth} Every idea moves left to right.
          </div>
        </div>
        <button type="button" onClick={() => setHelp(h => !h)} aria-expanded={help} aria-controls="options-desk-help" style={btn(false)}>
          How this page works {help ? '▴' : '▾'}
        </button>
      </div>
      {help && (
        <section id="options-desk-help" aria-label="How this page works" style={{ ...panel, padding: '12px 16px', fontSize: TYPE.base, lineHeight: 1.6, color: TOKENS.text[1] }}>
          <h3 style={{ margin: '0 0 6px', fontSize: TYPE.md, color: TOKENS.text[0] }}>How this page works</h3>
          <p style={{ margin: '0 0 8px' }}><b>The lifecycle.</b> {HOW_THIS_PAGE_WORKS.lifecycle.join(' ')}</p>
          <p style={{ margin: '0 0 8px' }}><b>How to read an idea.</b> {HOW_THIS_PAGE_WORKS.readIdea}</p>
          <p style={{ margin: '0 0 8px' }}><b>The checklist.</b> {HOW_THIS_PAGE_WORKS.checklist}</p>
          <p style={{ margin: 0 }}><b>What the system never does on its own.</b> {HOW_THIS_PAGE_WORKS.never}</p>
          <p style={{ margin: '8px 0 0', color: TOKENS.text[2] }}>Every underlined term and number has a definition: hover it, tap it, or tab to it with the keyboard. A "—" means the server did not send that value; the page never estimates it.</p>
        </section>
      )}

      {/* 2 · Data freshness */}
      <div role="group" aria-label="Data freshness" data-testid="options-desk-freshness" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {chips.map(c => (
          <span key={c.key} style={chipStyle(c.tone)} data-testid={`options-desk-chip-${c.key}`}>
            <Term k={c.glossaryKey} extra={c.detail}><b>{c.label}</b>&nbsp;<span data-testid={`options-desk-chip-${c.key}-value`}>{c.value}</span></Term>
          </span>
        ))}
      </div>

      {/* 3 · Lifecycle row */}
      <div role="group" aria-label="Lifecycle" data-testid="options-desk-lifecycle"
        style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {LANES.map(l => {
          const c = counts.find(x => x.key === l.key)
          const on = lane === l.key
          const t = toneVars(LANE_TONE[l.key])
          return (
            <ControlTip key={l.key} k={l.glossaryKey} style={{ flex: '1 1 140px', minWidth: 0 }} extra={c ? `Count: ${c.n ?? '—'} (${c.note}). Click to show only this step.` : undefined}>
              {d => (
                <button type="button" {...d} onClick={() => setLane(on ? null : l.key)} aria-pressed={on} data-testid={`options-desk-lane-${l.key}`}
                  style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-start', textAlign: 'left', cursor: 'pointer',
                    borderRadius: RADIUS.md, padding: '10px 12px', minHeight: 96, color: TOKENS.text[0], fontFamily: 'inherit',
                    background: on ? TOKENS.bg[2] : TOKENS.bg[1], border: `1px solid ${on ? t.color : TOKENS.border}` }}>
                  <span style={caps}>Step {l.step}</span>
                  <span style={{ ...mono, fontSize: TYPE.xl, fontWeight: 600, color: c?.n ? toneColor(LANE_TONE[l.key]) : TOKENS.text[3] }}>
                    {c?.n == null ? '—' : c.n.toLocaleString('en-US')}
                  </span>
                  <span style={{ fontSize: TYPE.base, fontWeight: 600 }}>{l.name}</span>
                  <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{l.owner}</span>
                </button>
              )}
            </ControlTip>
          )
        })}
      </div>

      {props.proposalsError && (
        <div role="alert" style={{ ...panel, padding: '10px 14px', borderLeft: `4px solid ${TOKENS.danger}`, color: TOKENS.danger, fontSize: TYPE.base }}>
          Options data unavailable: {props.proposalsError}. Nothing below is current.
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' }}>
        <div style={{ flex: '999 1 680px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* 4 · One idea table */}
          <section aria-label="Ideas" data-testid="options-desk-ideas" style={panel}>
            <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, padding: '12px 16px', borderBottom: `1px solid ${TOKENS.border}` }}>
              <h2 style={{ margin: 0, fontSize: TYPE.md + 2 }}>
                {laneMeta ? `${laneMeta.name} · ${filtered.length}` : `All ideas in flight · ${filtered.length}`}{filtersOn ? ' (filtered)' : ''}
              </h2>
              <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>
                one row per idea · <Term k="concept.merged">accounts merged</Term> · click a row for the full picture
              </span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <div role="table" aria-label="Options ideas" style={{ minWidth: 760 }}>
                <div role="row" style={{ display: 'grid', gridTemplateColumns: COLS, gap: 10, padding: '8px 16px', ...caps, borderBottom: `1px solid ${TOKENS.borderSubtle}` }}>
                  <span role="columnheader">Symbol</span>
                  <span role="columnheader">Strategy</span>
                  <span role="columnheader">What it does</span>
                  <span role="columnheader"><Term k="term.total_cost">Cost</Term></span>
                  <span role="columnheader">Stuck on</span>
                  <span role="columnheader">Next step</span>
                </div>
                {props.loading && !raw.length && <div style={{ padding: '18px 16px', color: TOKENS.text[2] }}>Loading ideas…</div>}
                {!props.loading && filtered.length === 0 && (
                  <div style={{ padding: '18px 16px', color: TOKENS.text[2] }} data-testid="options-desk-empty">
                    {lane === 'scan' ? 'Found names are inventory, not ideas yet. Open "Scan coverage" below to see which were evaluated and why others were not built.'
                      : lane === 'open' ? 'Open positions are managed in the Lifecycle view.'
                        : laneMeta ? `Nothing in "${laneMeta.name}" right now.` : 'No ideas in flight. This is not a completed market search; see Scan coverage.'}
                    {lane === 'open' && <> <button type="button" onClick={() => props.onOpenView('Lifecycle')} style={btn(false)}>Open Lifecycle view</button></>}
                  </div>
                )}
                {filtered.map(i => {
                  const on = sel?.id === i.id
                  return (
                    <div role="row" key={i.id} data-testid="options-desk-row" data-lane={i.lane} onClick={() => setSelId(i.id)}
                      style={{ display: 'grid', gridTemplateColumns: COLS, gap: 10, padding: '8px 16px', alignItems: 'center', cursor: 'pointer',
                        borderBottom: `1px solid ${TOKENS.borderSubtle}`, background: on ? TOKENS.bg[2] : 'transparent',
                        borderLeft: `3px solid ${on ? TOKENS.info : 'transparent'}` }}>
                      <span role="cell">
                        <button type="button" onClick={e => { e.stopPropagation(); setSelId(i.id) }} aria-pressed={on} aria-label={`Show ${i.symbol} ${i.strategyLabel} details`}
                          style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', color: TOKENS.text[0], ...mono, fontWeight: 600, fontSize: TYPE.md, minHeight: 36 }}>
                          {i.symbol}
                        </button>
                      </span>
                      <span role="cell" style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: TYPE.base }}>
                        <Term k={strategyGlossaryKey(i.strategy)}>
                          <span style={{ fontWeight: 600 }}>{i.strategyLabel}</span>
                        </Term>
                        <span style={{ ...mono, fontSize: TYPE.sm, color: TOKENS.text[2] }}>{i.contract}</span>
                      </span>
                      <span role="cell" style={{ fontSize: TYPE.base, color: TOKENS.text[1], lineHeight: 1.35 }}>{i.does}</span>
                      <span role="cell" style={{ ...mono, fontSize: TYPE.base }}>{i.costValue == null ? <Missing k="term.total_cost" /> : i.cost}</span>
                      <span role="cell" style={{ fontSize: TYPE.base, lineHeight: 1.35, color: toneColor(LANE_TONE[i.lane]) }}>
                        <Term k={i.stuckKey}>{i.stuck}</Term>
                      </span>
                      <span role="cell" onClick={e => e.stopPropagation()}>
                        <NextControl step={i.next} danger={i.lane === 'you'} onReview={props.onReview} onStage={props.onStage} onValidate={props.onValidate} onChain={props.onChain} />
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          </section>

          {/* 6 · Your plans */}
          <section aria-label="Your plans" data-testid="options-desk-plans" style={{ ...panel, padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
              <h2 style={{ margin: 0, fontSize: TYPE.md + 2 }}><Term k="concept.standing_plan">Your plans</Term></h2>
              <button type="button" onClick={props.onNewPlan} style={btn(false)}>New plan ›</button>
            </div>
            {!plans.length && <div style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>No standing plans{intentFeed ? '' : ' (plans not provided by this server version)'}.</div>}
            {plans.map(pl => (
              <div key={pl.symbol} style={{ border: `1px solid ${TOKENS.borderSubtle}`, borderRadius: RADIUS.md, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px', alignItems: 'baseline' }}>
                  <span style={{ ...mono, fontWeight: 600, fontSize: TYPE.md + 2 }}>{pl.symbol}</span>
                  <span style={{ fontSize: TYPE.base + 1 }}>{pl.goal}</span>
                  <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{pl.facts}</span>
                  {pl.badges.map(b => <span key={b} style={chipStyle('neutral')}><Term k="concept.watch_only">{b}</Term></span>)}
                </div>
                {pl.warnings.map(w => (
                  <div key={w} role="note" style={{ fontSize: TYPE.base, color: TOKENS.warning }}>
                    ⚠ <Term k="concept.plan_conflict">{w}</Term>
                  </div>
                ))}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
                  {pl.best.map(b => (
                    <div key={b.kind} style={{ background: TOKENS.bg[2], borderRadius: RADIUS.md, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <span style={caps}><Term k={b.glossaryKey}>{b.kind}</Term></span>
                      <span style={{ ...mono, fontSize: TYPE.base + 1 }}>{b.contract}</span>
                      <span style={{ fontSize: TYPE.base, color: TOKENS.text[1] }}>{b.note}</span>
                      {b.cta.kind === 'stage'
                        ? <button type="button" onClick={() => props.onStage((b.cta as Extract<NextStep, { kind: 'stage' }>).source)} style={{ ...btn(false), alignSelf: 'flex-start' }}
                          title="Opens the existing strategy review to pick an account and size. Nothing is placed.">{b.cta.label}</button>
                        : <span style={{ fontSize: TYPE.sm, color: TOKENS.text[3] }}>Nothing to stage</span>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </section>

          {/* 7 · Drawers */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Drawer testId="options-desk-drawer-coverage" title="Scan coverage and why ideas were not built"
              summary={notBuilt.length ? `${notBuilt.length} reason group${notBuilt.length === 1 ? '' : 's'}` : 'no not-built reasons served'}>
              <div>{notBuilt.length ? <>Not built: {notBuilt.join(' · ')}.</> : 'No not-built reasons were served.'}</div>
              <div>Scan status <b>{p?.scan_status || '—'}</b>. {p?.scan_capacity?.status ? <>Expanded {p.scan_capacity.refresh_interval_minutes}-minute scan: {String(p.scan_capacity.status).toLowerCase()} (needs about {p.scan_capacity.minimum_chain_requests_per_minute} chain requests a minute; provider capacity {p.scan_capacity.provider_capacity_verified ? 'verified' : 'unverified'}).</> : null}</div>
              {p?.market_session && String(p.market_session).toUpperCase() !== 'REGULAR' && <div>Chains were read during the {String(p.market_session).toLowerCase().replace(/_/g, ' ')} session.</div>}
              <button type="button" onClick={() => props.onOpenView('All coverage')} style={{ ...btn(false), marginTop: 8 }}>Open the full coverage list</button>
            </Drawer>
            <Drawer testId="options-desk-drawer-ledger" title="Desk Path B paper ledger"
              summary={pathB.length ? pathB.map(s => s.progress_label ? String(s.progress_label).replace(/^desk Path B · /, '') : '—')[0] + ' per strategy · lab only' : 'not provided by this server version'}>
              <div><Term k="concept.desk_path_b">What this is</Term>: paper results never unlock live trading.</div>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {pathB.map(s => <li key={s.strategy_id}>{String(s.display_name || s.strategy_id).replace(/_/g, ' ')}: {s.progress_label ?? '—'}</li>)}
              </ul>
            </Drawer>
            <Drawer testId="options-desk-drawer-log" title="Manual execution log" summary="trades you placed yourself">
              <div style={{ marginBottom: 8 }}><Term k="concept.manual_log">Why record them</Term>: so open positions and P/L stay accurate.</div>
              <ManualExecutionLog mode="option" borderColor="var(--ai-color)" />
            </Drawer>
            <Drawer testId="options-desk-drawer-filters" title="Advanced filters" summary={filtersOn ? 'filters active' : 'strategy, symbol, tier'}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
                <label>Symbol <input value={fSymbol} onChange={e => setFSymbol(e.target.value)} aria-label="Filter ideas by symbol" style={{ width: 80 }} /></label>
                <label>Strategy{' '}
                  <select value={fStrategy} onChange={e => setFStrategy(e.target.value)} aria-label="Filter ideas by strategy">
                    <option value="">All</option>
                    {[...new Set(allRows.map(i => i.strategy))].map(s => <option key={s} value={s}>{allRows.find(i => i.strategy === s)?.strategyLabel}</option>)}
                  </select>
                </label>
                <label><Term k="term.tier">Tier</Term>{' '}
                  <select value={fTier} onChange={e => setFTier(e.target.value)} aria-label="Filter ideas by tier">
                    <option value="">All</option><option value="A">A</option><option value="B">B</option><option value="C">C</option>
                  </select>
                </label>
                <button type="button" onClick={() => { setFStrategy(''); setFSymbol(''); setFTier('') }} style={btn(false)}>Clear</button>
                <button type="button" onClick={() => props.onOpenView('Proposals')} style={btn(false)}>Classic cards with every filter (POP, edge, sleeve, status) ›</button>
              </div>
              <div style={{ marginTop: 6, color: TOKENS.text[2] }}>The lifecycle row above is the main filter. These narrow the table further.</div>
            </Drawer>
          </div>
        </div>

        {/* 5 · Detail side panel */}
        <aside aria-label="Idea detail" data-testid="options-desk-detail" style={{ ...panel, flex: '1 1 320px', maxWidth: 460, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {!sel && <div style={{ color: TOKENS.text[2], fontSize: TYPE.base + 1 }}>Click an idea to see what it does, what it costs, and exactly what is left before it can be placed.</div>}
          {sel && (
            <>
              <div style={{ ...mono, fontWeight: 600, fontSize: TYPE.lg + 2 }}>{sel.symbol} · {sel.strategyLabel}</div>
              <div style={{ ...mono, fontSize: TYPE.base + 1, color: TOKENS.text[1] }}>{sel.contract} · {sel.accounts}</div>
              <div style={{ fontSize: TYPE.md, lineHeight: 1.5 }}>{sel.plain}</div>
              {sel.econ.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
                  {sel.econ.map(e => (
                    <div key={e.label} style={{ background: TOKENS.bg[2], borderRadius: RADIUS.md, padding: 8, display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span style={caps}><Term k={e.glossaryKey} extra={e.note}>{e.label}</Term></span>
                      <span style={{ ...mono, fontSize: TYPE.base + 1, fontWeight: 600 }}>{e.value === '—' ? <Missing k={e.glossaryKey} /> : e.value}</span>
                      {e.note && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>{e.note}</span>}
                    </div>
                  ))}
                </div>
              )}
              {sel.quoteTimes && <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}><Term k="fresh.stock_quotes">Quote times</Term>: {sel.quoteTimes}</div>}
              {sel.strategy === 'protective_put' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={caps}><Term k="concept.scenario">If the stock falls by expiry</Term></span>
                  {sel.scenarios.length ? (
                    <div role="table" aria-label="If the stock falls by expiry" style={{ display: 'grid', gridTemplateColumns: '60px 1fr 1fr 1fr', gap: '4px 10px', ...mono, fontSize: TYPE.base }}>
                      <span role="columnheader" style={{ color: TOKENS.text[3] }}>move</span>
                      <span role="columnheader" style={{ color: TOKENS.text[3] }}>stock only</span>
                      <span role="columnheader" style={{ color: TOKENS.text[3] }}>with this</span>
                      <span role="columnheader" style={{ color: TOKENS.text[3] }}>saved</span>
                      {sel.scenarios.map(s => (
                        <span key={s.move} role="row" style={{ display: 'contents' }}>
                          <span role="cell">{s.move}</span>
                          <span role="cell" style={{ color: TOKENS.danger }}>{s.stockOnly}</span>
                          <span role="cell">{s.withThis}</span>
                          <span role="cell" style={{ color: TOKENS.success }}>{s.saved}</span>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>{sel.scenarioNote}</span>
                </div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} data-testid="options-desk-checklist">
                <span style={caps}><Term k="concept.checklist">Checklist to place it</Term></span>
                {sel.checks.map((c, n) => (
                  <div key={`${c.text}-${n}`} style={{ display: 'grid', gridTemplateColumns: '18px 1fr', gap: 8, fontSize: TYPE.base + 1 }}>
                    <span aria-label={c.mark === '✓' ? 'done' : c.mark === '✗' ? 'failing' : 'not yet'} style={{ color: toneColor(MARK_TONE[c.mark]) }}>{c.mark}</span>
                    <span style={{ color: TOKENS.text[1] }}><Term k={c.glossaryKey}>{c.text}</Term></span>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: TYPE.base, color: TOKENS.text[2], lineHeight: 1.45 }} data-testid="options-desk-model">
                <Term k="concept.aegis_review">Model review (Aegis)</Term>: {sel.model}. A model vote is advice, not a decision.
              </div>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
