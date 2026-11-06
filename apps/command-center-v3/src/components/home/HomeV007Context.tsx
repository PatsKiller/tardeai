// Home v008 — "Your names today" (operator-approved mockup home/v008 HomeTodaysContextActionable, 2026-11-06).
//
// Self-fetching so the existing card props (and marketRisk.ts) are untouched: it reads the same
// GET /api/v2/market-risk/latest (the `home_v007` block plus the sibling reentry/book/protect fields) and the recovery
// read for case links. Three groups, each opening with its takeaway: today's stop-outs, held names in stressed groups,
// older exits on watch (collapsed). The per-symbol provenance, the grouped gaps and the raw score/hedge/budget lines
// live in the collapsed Diagnostics disclosure. Facts and links only — no size, order, stop level or buy/sell word.
import { useId, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS, TYPE, numStyle, toneVars } from '../../lib/designTokens'
import {
  categoryLine, conflictLine, groupGaps, headlineLine, hedgeLine, marketStanceLine, namesSource, namesToday, nextEventLine, parseHomeV007,
  provenanceText, referenceLine, signedPct1, stateText, volumeLine, type HeldRow, type HomeV007, type NamesToday, type OlderRow, type StoppedRow, type SymbolContext,
} from '../../lib/homeV007'
import { offersBudgetDecision } from '../../lib/budgetIntent'
import { fmtAsOf } from '../../lib/asOfDisplay'
import { recoveryProjection } from '../../lib/recoveryCases'
import { prefillAsk } from '../../lib/askCioPresentation'
import BudgetIntentControl from './BudgetIntentControl'
import { EXPLAIN_CSS, Explain, GlossaryProvider } from './MarketRiskActions'

const PATH = '/api/v2/market-risk/latest'
const RECOVERY_PATH = '/api/v2/recovery'
const card: React.CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 12, display: 'grid', gap: 8 }
const h4: React.CSSProperties = { margin: 0, fontSize: TYPE.sm, fontWeight: 800, color: TOKENS.text[0] }
const dim: React.CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[3] }
const small: React.CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[1] }

const money = (v: number | null) => (v == null ? null : `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`)
/** A measured amount in its OWN unit: a share of the book is a percentage, never a dollar figure. */
const amount = (v: number | null, unit: string | null): string | null =>
  v == null ? null : unit === '%' ? `${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}%` : money(v)
const pct = (v: number | null) => (v == null ? null : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

const provenance = provenanceText

function SymbolBlock({ s }: { s: SymbolContext }) {
  const q = s.quote
  const qState = stateText(q)
  return <div data-testid={`v7-symbol-${s.symbol}`} style={{ display: 'grid', gap: 3, padding: '6px 0', borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
      <b style={{ color: TOKENS.text[0] }}>{s.symbol}</b>
      {qState
        ? <span data-testid={`v7-quote-${s.symbol}`} style={{ color: toneVars('warning').color, fontWeight: 600 }}>
            <>price {qState}{provenance(q)}</>
          </span>
        : <span data-testid={`v7-quote-${s.symbol}`} style={small}>
            <b style={{ color: TOKENS.text[0] }}>{money(q.price) ?? 'price unknown'}</b>
            {q.session ? ` · ${q.session}` : ''}{q.asOf ? ` · fetched ${fmtAsOf(q.asOf) ?? q.asOf}` : ''}{q.source ? ` · ${q.source}` : ''}{q.basis ? ` · ${q.basis}` : ''}{q.asOf ? ' · trade time unverified' : ''}{q.stale || (q.ageSeconds != null && q.ageSeconds >= 900) ? ' · stale' : ''}{q.ageSeconds != null && q.ageSeconds >= 300 ? ` · ${Math.round(q.ageSeconds / 60)}m old` : ''}
          </span>}
    </div>
    {(() => { const line = conflictLine(q); return line ? <div style={dim} data-testid={`v7-conflict-${s.symbol}`}>{line}</div> : null })()}
    {stateText(s.dayChange) ? <div style={dim}>day change {stateText(s.dayChange)}{provenance(s.dayChange)}</div>
      : <div style={dim}>today {money(s.dayChange.usd) ?? ''}{s.dayChange.pct != null ? ` (${pct(s.dayChange.pct)})` : ''}{s.dayChange.referenceDate ? ` vs ${s.dayChange.referenceDate} close` : ''}{provenance(s.dayChange)}</div>}
    {stateText(s.sinceExit) ? <div style={dim}>since exit {stateText(s.sinceExit)}{provenance(s.sinceExit)}</div>
      : <div style={dim}>since exit {money(s.sinceExit.usd) ?? ''}{s.sinceExit.pct != null ? ` (${pct(s.sinceExit.pct)})` : ''}{s.sinceExit.exitDate ? ` · exited ${s.sinceExit.exitDate}` : ''}{provenance(s.sinceExit)}</div>}
    {stateText(s.referencesFact) ? <div style={dim} data-testid={`v7-references-${s.symbol}`}>to trigger {stateText(s.referencesFact)}{provenance(s.referencesFact)}</div> : null}
    {s.references.map((r, i) => <div key={i} style={dim} data-testid={`v7-reference-${s.symbol}-${i}`}>{referenceLine(r)}</div>)}
    {s.headlines.length ? <div style={dim}>headlines: {s.headlines.map(headlineLine).join(' · ')}</div> : null}
    {(() => { const line = nextEventLine(s.nextEvent); return line ? <div style={dim} data-testid={`v7-next-event-${s.symbol}`}>{line}</div> : null })()}
    {stateText(s.cio) ? <div style={dim}>CIO stance {stateText(s.cio)}{provenance(s.cio)}</div>
      : <div style={dim}>CIO stance <b>{s.cio.stance}</b>{s.cio.conviction != null ? ` · conviction ${s.cio.conviction}` : ''}{provenance(s.cio)}</div>}
    {(() => { const line = marketStanceLine(s.marketStance); return line ? <div style={dim} data-testid={`v7-stance-${s.symbol}`}>{line}</div> : null })()}
    <div style={dim} data-testid={`v7-volume-${s.symbol}`}>{volumeLine(s.volume)}</div>
  </div>
}

/** The raw score / hedge / budget lines (they repeat the header), now one tap away inside Diagnostics. */
function RawLines({ v7, refetch }: { v7: HomeV007; refetch: () => void }) {
  return <>
    {/* The score is a measurement: it shows its own clock, and the row exists even when no category was returned
        (an empty category list is a fact about the payload, not a reason to hide the score). */}
    {v7.risk.score != null || v7.risk.categories.length || v7.risk.nextEvaluation?.at ? <div style={dim} data-testid="v7-risk">
      risk score {v7.risk.score ?? 'unknown'}{v7.risk.scoreAsOf ? ` · ${fmtAsOf(v7.risk.scoreAsOf) ?? v7.risk.scoreAsOf}` : v7.risk.score != null ? ' · clock not recorded' : ''}{v7.risk.categories.length ? ` · ${v7.risk.categories.map(c => `${categoryLine(c)}${provenance(c)}`).join(' · ')}` : ' · no category returned'}
      {v7.risk.nextEvaluation?.at ? ` · next evaluation ${fmtAsOf(v7.risk.nextEvaluation.at) ?? v7.risk.nextEvaluation.at} (${v7.risk.nextEvaluation.basis ?? 'declared'})` : ''}
    </div> : null}
    {v7.hedge.triggers.length ? <div style={dim}>hedge: {v7.hedge.triggers.map(hedgeLine).join(' · ')}{v7.hedge.inverse.length ? ` · inverse today: ${v7.hedge.inverse.map(i => `${i.symbol} ${i.dayPct == null ? 'unknown' : pct(i.dayPct)}`).join(' · ')}` : ''}</div> : null}
    {v7.budgets.map(b => <div key={b.key} style={dim} data-testid={`v7-budget-${b.key}`}>
      budget {b.label}: {b.state === 'measured'
        // The producer states the unit on every risk-budget row ("%" for a share of the book). Rendering a percent
        // budget through money() printed "52% of 35%" as "$52 of $35" — a wrong number, not a formatting quibble.
        ? <>{amount(b.current, b.unit) ?? 'unknown'} of {amount(b.budget, b.unit) ?? 'unknown'}{b.breach ? ' · breach' : ''}{b.clearsWhen ? ` · clears ${b.clearsWhen}` : ''}{provenance(b)}</>
        : <>{b.state === 'not_applicable' ? 'not applicable' : 'unknown'}{b.reason ? ` — ${b.reason}` : ''}{b.remediation ? ` · ${b.remediation}` : ''}</>}
      {b.decision.active
        ? ` · intentional${b.decision.intentionalUntil ? ` until ${fmtAsOf(b.decision.intentionalUntil) ?? b.decision.intentionalUntil}` : ''}${b.decision.actor ? ` · ${b.decision.actor}` : ''}${b.decision.receipt ? ` · receipt ${b.decision.receipt.slice(0, 8)}` : ''}${b.breach ? ' · breach still stands' : ''}${b.decision.history ? ` · ${b.decision.history} earlier` : ''}`
        : b.operatorDecision === 'unavailable'
          ? ` · intentional decision ${b.decisionRemediation ?? 'not available yet'}`
          : ' · intentional decision available to the operator'}
      {/* The clock and source are already in `provenance`; this adds the two binding hashes without repeating them. */}
      {b.sourceSha || b.presentationSha
        ? ` · src ${b.sourceSha ? b.sourceSha.slice(0, 8) : 'none'}${b.presentationSha ? ` · presentation ${b.presentationSha.slice(0, 8)}` : ''}`
        : ''}
      {offersBudgetDecision(b) ? <BudgetIntentControl row={b} onRecorded={refetch} /> : null}
    </div>)}
    {v7.decisionHistory.complete === false ? <div style={dim} data-testid="v7-decision-history-partial">decision history is incomplete{typeof v7.decisionHistory.count === 'number' ? ` · ${v7.decisionHistory.count} in the ledger` : ''} — earlier decisions may be missing</div> : null}
  </>
}

/** Collapsed by default, last in the card: grouped gaps, read errors, the raw score/hedge/budget lines and the full
 *  provenance per symbol. Every fact the card used to print inline is here, one tap away. */
function Diagnostics({ v7, id, refetch }: { v7: HomeV007; id?: string; refetch?: () => void }) {
  const groups = groupGaps(v7.gaps)
  const n = v7.gaps.length
  return <details className="mr-sec" data-testid="v7-diagnostics" id={id}>
    <summary><span role="heading" aria-level={3}>Diagnostics ({n} gap{n === 1 ? '' : 's'})</span>
      <span className="mr-sec-one">{groups.length} reason{groups.length === 1 ? '' : 's'}{v7.readErrors.length ? ` · ${v7.readErrors.length} read error${v7.readErrors.length === 1 ? '' : 's'}` : ''}{v7.symbols.length ? ' · per-symbol provenance' : ''}</span></summary>
    <div className="mr-sec-body" style={{ display: 'grid', gap: 6 }}>
      {groups.map((g, i) => <div key={i} data-testid="v7-gap-group" data-count={g.count} style={dim}>
        <span style={{ color: TOKENS.text[1] }}>{g.text}</span>{g.remediation ? <> · <i>{g.remediation}</i></> : null}
      </div>)}
      {v7.readErrors.map((e, i) => <div key={i} style={dim}>read error {e.member} · {e.code}</div>)}
      {refetch ? <RawLines v7={v7} refetch={refetch} /> : null}
      {v7.symbols.length ? <div style={{ ...dim, marginTop: 4 }}>Per-symbol provenance (clock and source of every fact):</div> : null}
      {v7.symbols.map(s => <SymbolBlock key={s.symbol} s={s} />)}
    </div>
  </details>
}

// ── v008 rows ──
const grp: CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '2px 10px', padding: '10px 0 4px', borderTop: `1px solid ${TOKENS.border}`, fontSize: TYPE.sm, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2] }
const take: CSSProperties = { color: TOKENS.text[0], letterSpacing: 0, textTransform: 'none', fontWeight: 600 }
const rowS: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 6, padding: '10px 0', borderTop: `1px solid ${TOKENS.borderSubtle}`, minWidth: 0 }
const l1: CSSProperties = { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', minWidth: 0 }
const symS: CSSProperties = { ...numStyle, fontWeight: 700, fontSize: TYPE.md + 1, color: TOKENS.text[0] }
const acctS: CSSProperties = { fontSize: TYPE.base, color: TOKENS.text[2], minWidth: 0, overflowWrap: 'anywhere' }
const factsS: CSSProperties = { ...numStyle, fontSize: TYPE.base, color: TOKENS.text[1], display: 'flex', flexWrap: 'wrap', gap: '4px 12px' }
const whyS: CSSProperties = { fontSize: TYPE.base, color: TOKENS.text[2], lineHeight: 1.45, overflowWrap: 'anywhere' }
const actsS: CSSProperties = { display: 'flex', gap: 8, flexWrap: 'wrap' }
const btnBase: CSSProperties = { minHeight: 44, display: 'inline-flex', alignItems: 'center', padding: '8px 12px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.info, fontWeight: 600, fontSize: TYPE.md - 1, textDecoration: 'none', cursor: 'pointer', fontFamily: 'inherit' }
const btnPri: CSSProperties = { ...btnBase, background: TOKENS.info, borderColor: TOKENS.info, color: TOKENS.bg[0] }
const pillS = (tone: 'success' | 'danger' | 'warning' | 'neutral'): CSSProperties => ({ marginLeft: 'auto', fontSize: TYPE.sm, fontWeight: 700, padding: '2px 8px', borderRadius: RADIUS.pill, border: '1px solid currentColor', color: tone === 'neutral' ? TOKENS.text[2] : toneVars(tone).color, whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', gap: 4 })
const signed = (v: number | null) => <i style={{ fontStyle: 'normal', color: v == null ? TOKENS.text[3] : v < 0 ? toneVars('danger').color : toneVars('success').color }}>{signedPct1(v)}</i>
const usd = (v: number | null) => (v == null ? null : `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`)

function AskButton({ symbol, text }: { symbol: string; text: string }) {
  return <button type="button" data-testid={`v8-ask-${symbol}`} style={btnBase} onClick={() => prefillAsk(text)}>Ask CIO about {symbol}</button>
}

/** NO PRICE carries its reason behind a tap-friendly (i) sheet — the same Explain primitive as the market-risk card. */
function NoPricePill({ r }: { r: StoppedRow }) {
  const term = `v8_no_price_${r.symbol}`
  return <span style={pillS('neutral')} data-testid={`v8-pill-${r.symbol}`} title={r.noPriceWhy ?? undefined}>
    NO PRICE
    <GlossaryProvider terms={{ [term]: { label: `Why no price for ${r.symbol}`, text: r.noPriceWhy ?? 'no current quote was measured' } }}><Explain term={term} /></GlossaryProvider>
  </span>
}

function StoppedRowView({ r }: { r: StoppedRow }) {
  return <div style={rowS} data-testid={`v8-stopped-${r.symbol}`} data-status={r.status}>
    <div style={l1}><span style={symS}>{r.symbol}</span><span style={acctS}>{r.account}</span>
      {r.status === 'no_price' ? <NoPricePill r={r} /> : <span style={pillS(r.status === 'above' ? 'success' : 'danger')} data-testid={`v8-pill-${r.symbol}`}>{r.pill}</span>}
    </div>
    <div style={factsS}>
      {r.exitPrice != null ? <span>exit {usd(r.exitPrice)}</span> : null}
      {r.price != null ? <span>now {usd(r.price)}</span> : null}
      {r.dayPct != null ? <span>today {signed(r.dayPct)}</span> : null}
      {r.event ? <span>{r.event}</span> : null}
    </div>
    {r.why ? <div style={whyS}>{r.why}</div> : null}
    <div style={actsS}>
      {r.caseTo ? <Link to={r.caseTo} style={btnPri} data-testid={`v8-case-${r.symbol}`}>Open re-entry case</Link> : null}
      <AskButton symbol={r.symbol} text={r.askText} />
    </div>
  </div>
}

function HeldRowView({ h }: { h: HeldRow }) {
  return <div style={rowS} data-testid={`v8-held-${h.symbol}`}>
    <div style={l1}><span style={symS}>{h.symbol}</span><span style={acctS}>{h.accountText}</span><span style={pillS('warning')}>{h.pill}</span></div>
    <div style={factsS}>
      {h.price != null ? <span>{usd(h.price)}</span> : <span style={{ color: TOKENS.text[3] }}>price unavailable</span>}
      {h.dayPct != null ? <span>today {signed(h.dayPct)}</span> : null}
      {h.event ? <span>{h.event}</span> : null}
    </div>
    {h.stopFacts.length ? <div style={whyS}>{h.stopFacts.join(' · ')}</div> : null}
    <div style={actsS}>
      <Link to={h.reviewTo} style={btnPri} data-testid={`v8-review-${h.symbol}`}>Review stop{h.stopFacts.length > 1 ? 's' : ''}</Link>
      <AskButton symbol={h.symbol} text={h.askText} />
    </div>
  </div>
}

function OlderRows({ rows }: { rows: OlderRow[] }) {
  return <div style={{ display: 'grid', gridTemplateColumns: 'auto minmax(0,1fr) auto', gap: '4px 10px', ...numStyle, fontSize: TYPE.base, padding: '8px 12px 12px' }}>
    {rows.map(o => <div key={o.symbol} data-testid={`v8-older-${o.symbol}`} style={{ display: 'contents' }}>
      <span style={{ color: TOKENS.text[0], fontWeight: 600 }}>{o.symbol}</span>
      <span style={{ color: TOKENS.text[1], minWidth: 0 }}>{o.vsExitPct != null ? `${signedPct1(o.vsExitPct)} vs exit` : 'no price'}{o.dayPct != null ? ` · today ${signedPct1(o.dayPct)}` : ''}</span>
      <span style={{ color: o.flagged ? toneVars('warning').color : TOKENS.text[3], fontFamily: 'inherit', textAlign: 'right' }}>{o.flagged ? o.flag : ''}</span>
    </div>)}
  </div>
}

function NamesBody({ n, diagId }: { n: NamesToday; diagId: string }) {
  const openDiagnostics = () => {
    const el = typeof document !== 'undefined' ? document.getElementById(diagId) as HTMLDetailsElement | null : null
    if (el) { el.open = true; el.scrollIntoView?.({ block: 'start', behavior: 'smooth' }) }
  }
  return <>
    {n.stopped.length ? <section data-testid="v8-stopped" aria-label={n.stoppedHeading}>
      <div style={grp}><span>{n.stoppedHeading}</span><b style={take} data-testid="v8-stopped-takeaway">{n.stoppedTakeaway}</b></div>
      {n.stopped.map(r => <StoppedRowView key={r.symbol} r={r} />)}
    </section> : null}
    {n.held.length || n.tiny.length ? <section data-testid="v8-held" aria-label="You hold, in stressed groups">
      <div style={grp}><span>You hold · in stressed groups</span>{n.held.length ? <b style={take}>{n.heldTakeaway}</b> : null}</div>
      {n.held.map(h => <HeldRowView key={h.symbol} h={h} />)}
      {n.tiny.length ? <div style={{ ...dim, padding: '8px 0' }} data-testid="v8-tiny">+ {n.tiny.map(t => `${t.symbol} $${Math.round(t.usd)}`).join(' · ')}: leftover positions under $100, no action.</div> : null}
    </section> : null}
    {n.older.length ? <details className="mr-sec" data-testid="v8-older">
      <summary><span role="heading" aria-level={3}>Older exits on watch ({n.older.length})</span>{n.olderTakeaway ? <span className="mr-sec-one">{n.olderTakeaway}</span> : null}</summary>
      <OlderRows rows={n.older} />
    </details> : null}
    {!n.total ? <div style={small} data-testid="v8-empty">No stop-outs, stressed holdings or exits on watch right now.</div> : null}
    {n.cioGap ? <div data-testid="v8-cio-gap" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0 8px', padding: '6px 10px', borderRadius: RADIUS.md, background: TOKENS.bg[2], fontSize: TYPE.base, color: TOKENS.text[1] }}>
      <span><b style={{ color: toneVars('warning').color }}>Data gap:</b> CIO view missing for {n.cioGap.missing} of {n.cioGap.total} name{n.cioGap.total === 1 ? '' : 's'}.{n.cioGap.reason ? ` Cause: ${n.cioGap.reason}.` : ''}</span>
      <button type="button" onClick={openDiagnostics} data-testid="v8-cio-gap-details" style={{ ...btnBase, background: 'transparent', border: 0, padding: '0 4px' }}>Details in Diagnostics</button>
    </div> : null}
  </>
}

export default function HomeV007Context() {
  // Background priority: Home already fetches this same endpoint for the card model, so this read yields to the
  // page's own requests instead of competing with them for the three shared slots (see useApi's fan-out note).
  const api = useApi<{ home_v007?: unknown }>(PATH, 60_000, { priority: 'background' })
  const rec = useApi<unknown>(RECOVERY_PATH, 120_000, { priority: 'background' })
  const diagId = useId()
  const v7 = parseHomeV007(api.data?.home_v007)
  if (!v7.present) return null
  // The producer's stated failure is not an empty success. It carries a reason, a remediation and the gaps that
  // explain it; the card says so and renders no symbol body over it.
  if (v7.unavailable) {
    return <section data-testid="home-v007-unavailable" style={card}>
      <h4 style={h4}>Your names today is unavailable</h4>
      <div style={{ ...small, color: toneVars('warning').color }} data-testid="v7-unavailable-reason">
        {v7.blockReason ?? 'the producer marked the block unavailable without a stated reason'}
      </div>
      {v7.blockRemediation ? <div style={dim} data-testid="v7-unavailable-remediation">{v7.blockRemediation}</div> : null}
      <Diagnostics v7={v7} />
    </section>
  }
  const proj = recoveryProjection(rec.data, rec.error)
  const cases = proj.cases.map(c => ({ key: c.key, symbol: c.symbol, account: c.account, settled: c.settled }))
  const names = namesToday(v7, namesSource(api.data), cases, new Date())
  return <section data-testid="home-v007" style={card}>
    <style>{EXPLAIN_CSS}</style>
    <div>
      <h4 style={{ ...h4, fontSize: TYPE.md + 1 }}>Your names today</h4>
      <div style={{ ...dim, fontSize: TYPE.base, marginTop: 2 }}>What changed for things you hold or just sold, grouped by the decision in front of you. Facts and links only. Nothing here is a size, an order or a stop level.</div>
    </div>
    <NamesBody n={names} diagId={diagId} />
    <Diagnostics v7={v7} id={diagId} refetch={() => api.refetch()} />
  </section>
}
